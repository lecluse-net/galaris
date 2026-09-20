<p align="right"><strong>Français</strong> · <a href="../../en/dev/testing-reliability.md">English</a></p>

# Fiabilité du Chat et de l’exécution agentique

La CI `Quality` exécute les tests backend, frontend, typage, build, architecture et
les parcours navigateur Chat. Pour la même validation locale : `make quality`.

## Parcours navigateur

`make tests-e2e` construit le frontend de production, puis démarre une stack
indépendante avec PostgreSQL en mémoire, API, Socket.IO et schedulers réels.
Aucun port hôte, réseau applicatif, secret `.env` ou volume de données existant
n’est utilisé. Le réseau d’exécution n’a pas de sortie Internet. Chaque invocation
a son propre nom de projet et détruit ses conteneurs à la fin.
Le runner partage l’espace réseau du frontend pour utiliser `localhost`, un
contexte sécurisé reconnu par le navigateur, sans polyfill des API cryptographiques.

Le runner Playwright est verrouillé séparément dans `e2e/package-lock.json`.
Les rapports, captures sur échec, traces navigateur et logs de services sont dans
`artifacts/e2e/`, également conservés sept jours en CI. Les relances automatiques
sont désactivées : un échec intermittent reste un échec.
La CI répète chaque parcours trois fois dans la même stack isolée.

Exemples :

```sh
make tests-e2e ARGS='--grep reconnect'
make tests-e2e ARGS='--repeat-each=5'
make tests ARGS='tests/test_conversation_concurrency.py tests/test_driver_conformance.py'
```

Les parcours vérifient la progression avant la fin, le remplacement live/durable
sans doublon ni trou observé dans le DOM, le rechargement, les outils, la reconnexion,
le changement de room, deux onglets, un viewport mobile, une erreur partielle et
la chaîne conversation → Task → livraison du résultat.
Le second onglet et son rechargement doivent retrouver le texte déjà généré avant
que la barrière autorise la fin : cette vérification exerce le snapshot actif HTTP.
Ils vérifient aussi la restauration de session derrière le proxy avec un port
non standard. Les tests unitaires WebSocket protègent la connexion en cours contre
les appels concurrents et couvrent déconnexion, reconnexion et changement de session.
Les service workers sont désactivés dans ces parcours : le cycle de mise à jour
PWA reste à couvrir séparément.
La transition live/durable couvre également les lectures HTTP concurrentes :
les métadonnées sont lues après les messages et une ancienne réponse ne doit pas
effacer un lien durable déjà connu.

La simulation est exclusivement dans `back/tests/e2e_app.py` : contrôleur
conversationnel, génération de l’objectif, résolution du modèle et stream du
harnais interne. Les modèles externes ne sont pas appelés. L’admission, les
transitions, leases, tentatives, autorisations, projections et transports restent
ceux de l’application. Ces tests ne mesurent donc pas la qualité du raisonnement
du modèle ni la compatibilité d’un fournisseur réel. Le serveur de scénarios
refuse de démarrer hors de la base dédiée `db-e2e/test_db` avec `APP_ENV=test`.

`tests/test_codex_provider.py` complète ces parcours au niveau transport : un cas
traverse la vraie génération d’objectif, la sortie structurée Pydantic AI, le SDK,
le proxy Responses et le bridge Codex, avec un fournisseur HTTP simulé exigeant
le streaming. Les cas voisins couvrent le résultat final, le refus fournisseur,
le flux sans événement terminal et le renouvellement d’authentification.
Ils reproduisent aussi un terminal Codex `output: []` après des événements
`response.output_item.done` : les résultats complets sont reconstruits dans leur
ordre natif, sans convertir un fragment inachevé en résultat valide.

## Concurrence et contrats

`committed_database` clone une base modèle figée après la synchronisation DbAdmin
et avant l’exécution de pytest, pour chaque test qui demande cette fixture.
Les workers utilisent des connexions distinctes
et de vrais commits ; aucune transaction de rollback commune ne masque les verrous.
Un rendez-vous asynchrone force le démarrage concurrent, avec un timeout borné.
La base clonée est supprimée après chaque test, même en cas d’échec.

Chaque lancement backend possède également son propre projet Compose. Les tests
couvrent la prise unique d’un round ou d’une Task, l’arrêt brutal d’un processus
après commit et l’expiration du lease avec ou sans effet déjà commencé.
Un ancien propriétaire ne peut plus construire, finaliser ou faire échouer le round
repris par un autre worker. Les tests de Process vérifient également qu'un callback
ou snapshot tardif, même avec le même statut terminal, ne remplace pas son résultat.
Une publication lente doit laisser avancer la génération et converger vers un
snapshot cumulatif sans accumuler une file de fragments.
La conformité partagée est exercée sur les adapters
Internal, Hermès et OpenAI Messages avec leur I/O simulée. Ajouter un driver impose
d’ajouter son cas de conformité. Les partitions exhaustives d’une réponse Unicode
vérifient également l’accumulation frontend et la déduplication ; le reset est
testé avec redelivery d’un ancien fragment.

## Ajouter une protection après un incident

1. Décrire le déclencheur, l’état durable, la séquence d’événements et le résultat attendu.
2. Reproduire l’échec avant de modifier le runtime ; anonymiser toute fixture issue d’un incident.
3. Tester la règle au niveau unité/contrat et ajouter un parcours navigateur si l’erreur était visible.
4. Piloter les étapes par événements ou barrières ; éviter les sleeps arbitraires.
5. Vérifier le résultat après rechargement et les effets durables, pas seulement l’émission d’un événement.

Pour étendre la couverture : ajouter les crashes de processus aux points de commit,
les callbacks externes ambigus, les scénarios plan/enfants, les sessions longues et
des évaluations de fournisseurs réels séparées et budgétées. Un test au port du
contrôleur ne prouve pas ces propriétés à lui seul.
