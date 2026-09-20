# ADR 0088 — Paramètres de génération adaptés au fournisseur final

- Statut : Accepted
- Date : 2026-09-12

## Contexte

Un cycle Goal utilisait une température par défaut avec GPT-6 Astra via le provider ChatGPT,
qui la refuse. Le correctif local ne suffisait pas : le Chat interne remplace le constructeur
de requête Pydantic AI et le proxy peut injecter l’effort figé du run après les filtres du SDK.
Une compatibilité OpenAI ne garantit ni les mêmes paramètres ni les mêmes valeurs.

## Décision

Chaque bridge texte enregistre un résolveur `RequestParameterPolicy` dans la façade `app.llm`.
Le proxy applique cette politique après résolution du fournisseur, du modèle et de l’effort,
avant création de la trace et envoi. Chat, Responses, streaming et compaction partagent cette
frontière. Les politiques des auteurs de modèles sont réutilisables par les routeurs, qui
ajoutent les contraintes de leur endpoint. Le domaine commun n’importe aucun bridge.

Les modèles internes Chat et Responses projettent également les restrictions de cette même
politique dans le profil du SDK, avant qu'il construise la requête. Le raisonnement configuré
est visible à cette étape sur les deux protocoles. Si le SDK infère un choix d'outil obligatoire
pour une sortie structurée, il peut utiliser `auto` lorsque le fournisseur interdit ce forçage
avec raisonnement. Le schéma, les validateurs et les limites d'essais sont conservés. Un choix
de forçage explicitement incompatible reste une erreur ; le raisonnement n'est pas désactivé.

Les réglages de génération connus sont autorisés explicitement par protocole. Les contraintes
croisées s’appliquent à l’effort réellement envoyé. Un niveau absent est traduit au niveau
supérieur disponible, plafonné au maximum du fournisseur ; sans effort réglable, le paramètre
est omis. Le niveau `none` utilise le minimum disponible si le modèle ne permet pas de désactiver
le raisonnement. Une requête automatique reste automatique.

Pour un alias non identifié, les contrôles optionnels non établis sont omis. Les messages,
outils et schémas de sortie restent intacts ; une incompatibilité fonctionnelle connue est
refusée explicitement, pas contournée en supprimant un outil. Les plafonds de tokens sont
traduits dans le champ natif en conservant le plus strict. Le transport ChatGPT conserve son
exception existante : son endpoint ne prend pas de plafond `max_output_tokens`.

Aucun nouvel essai payant, changement de modèle ou appel de découverte n’est ajouté au parcours.
Le vocabulaire de champs est fermé : un champ inconnu est refusé avant envoi, y compris après
transformation par un bridge et lors du renouvellement d’authentification. Les extensions
natives doivent être déclarées et testées. Les propriétés des schémas utilisateur restent
libres. Cette politique ne prétend pas valider tout JSON arbitraire contre tous les déploiements.

## Conséquences et preuves

L’effort canonique du run et `llm_calls.reasoning_effort` gardent leur sens de choix Galaris
(ADR 0052) ; ils ne représentent pas nécessairement l’énumération traduite sur le fil.
Les règles de traduction sont documentées dans
[l’audit des providers](../../docs/fr/dev/provider-parameters.md).

`back/tests/test_provider_parameters.py` vérifie les requêtes HTTP sortantes, les deux modes de
streaming et les protocoles utilisés, la conservation du contenu et des budgets, ainsi que
l’idempotence des adaptations. Le catalogue entier des providers texte doit être représenté.
Les scénarios du proxy reproduisent aussi l’injection tardive d’effort. Les tests du modèle
interne couvrent le plafond de tokens et la température xAI autorisée avec raisonnement.

Une fixture indépendante, `back/tests/fixtures/provider_parameters.json`, décrit les exemples
de contrôles et les champs acceptés par les endpoints simulés. L’ajout d’un contrôle sans
exemple fait échouer la suite ; chaque exemple est exécuté sur toute la matrice. Les tests
vérifient que cette vérification détecte aussi une autorisation globale accidentelle. Les
transports HTTP réels sont interdits dans la suite de contrats. Les requêtes construites par
le SDK traversent aussi les vrais proxys sur la matrice de protocoles, modes de sortie et
efforts. Le parcours d'admission conserve une vraie base et vérifie redelivery et échec sans
Task partielle. Une mutation prouve que retirer la projection des restrictions remet le test
en échec. `make tests-providers` produit un rapport JUnit et fait partie des contrôles
obligatoires CI et `make validate`, en plus de la collecte backend complète.

Ces tests utilisent des serveurs HTTP simulés et les contraintes documentées. Ils ne remplacent
pas une qualification sur les comptes et versions de déploiement effectivement utilisés.
