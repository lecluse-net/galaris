# 0178 — Reprise des conversations après interruption du worker

Statut : accepté. Date : 2026-10-12.

## Problème et garantie

Le nombre de claims d'un round ne représente pas son nombre d'erreurs métier. Un arrêt du
backend pendant l'inférence ou la préparation d'une Task ne doit ni consommer les entrées
ni épuiser ce budget. Un checkpoint sûr permet aussi de continuer après un effet confirmé.
Le contrat couvre rechargement de développement, mise à jour et arrêt brutal.

## Décision

Les tentatives interrompues sont terminées en `INTERRUPTED` ; leurs numéros restent monotones.
Seules les tentatives `ERROR` consomment le budget de deux erreurs. L'arrêt propre stoppe les
préparations et générations puis attend jusqu'à vingt secondes les outils engagés et les
notifications. Il annule ensuite le travail restant et attend sa sauvegarde avant de libérer
le bail. Le superviseur accorde trente secondes au scheduler et Docker quatre-vingt-dix
secondes au backend. La récupération d'un bail expiré applique la même décision.

Le round reprend son identité et son checkpoint chiffré. La politique publique du harnais
interne décide si ce checkpoint est sûr ; le contrôleur Conversation n'a pas de reconciler
Console et n'accepte donc pas un simple état `reconcile`. Sans checkpoint, seul un round
n'ayant engagé aucun effet peut repartir. Les anciens tokens ne peuvent plus enregistrer
de checkpoint, publier un résultat ou démarrer un effet. L'admission d'une Task déclare sa
politique idempotente : clés d'action durables et révisions attendues bornent le rejeu.

Une fermeture de transport MCP identifiée par son code protocolaire reste une interruption,
jamais une erreur métier acquittée. Le journal conserve l'appel en attente. À la reprise,
les appels engagés de lecture ou idempotents du dernier lot sont exécutés par les résultats
différés Pydantic AI avant une nouvelle décision du modèle, avec leurs arguments et identités
d'origine. Les résultats achevés du même lot sont conservés. La frontière native revérifie
les droits et la fraîcheur ; ce mécanisme ne remplace aucune autorisation Galaris.
Une annulation provenant de l'action alors que le worker reste actif est une véritable
erreur d'exécution, soumise au budget habituel : un transport durablement défaillant
ne provoque pas une boucle de reprises illimitée.
La politique courante de l'outil est revérifiée avant dispatch : si une mise à jour
le rend non idempotent, l'appel en attente devient incertain et n'est pas rejoué.

La livraison de la réponse finale est marquée `SENDING` avant le transport. Un reçu Messenger
persisté avec la corrélation exacte du round est rattaché sans nouvel envoi. Sans ce reçu,
la livraison devient `UNKNOWN`. Les notifications de fallback ne prennent jamais le bail
d'une exécution active. Les erreurs de récupération expliquent l'incertitude effective,
sans attribuer systématiquement toute expiration à un effet potentiellement commencé.

## Limites et vérification

Une opération externe non idempotente sans reçu ne permet pas de garantir exactement un effet
après destruction du processus. Le système conserve cette incertitude et refuse le rejeu.
Les autorisations, nouveaux messages, suppressions administratives, résultats terminaux et
le budget des véritables erreurs conservent leurs contrats.

Les suites Conversation et Harness couvrent les interruptions successives, la sauvegarde
avant libération, les reçus confirmés, l'admission en préparation, les checkpoints illisibles,
la perte d'autorité et la livraison sans double envoi. Les modèles et transports externes
sont synthétiques ; les transactions et liens utilisent PostgreSQL isolé. La régression
initiale a été reproduite avant correction : une deuxième expiration sans effet abandonnait
le round. Les tests précédents couvraient la perte d'un bail et le retry d'une vraie erreur,
sans distinguer des redémarrages successifs ni vérifier la reprise après effet confirmé.
Une seconde régression échappait à ces tests : FastMCP convertissait une annulation serveur
en fermeture de connexion, conservée comme erreur définitive. La couverture utilise désormais
un vrai serveur et client MCP avec le harnais Pydantic AI : coupure avant ou après effet,
reprise de l'appel idempotent sans nouvelle décision, conservation des résultats du lot
et refus du rejeu non idempotent. Les services métier et leur déduplication restent couverts
par les tests PostgreSQL ; les fixtures MCP et LLM sont entièrement synthétiques.
