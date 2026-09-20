<p align="right"><strong>Français</strong> · <a href="../../en/dev/testing.md">English</a></p>

# Tester un comportement et connaître la portée du résultat

Une suite verte signifie que ses scénarios passent avec leurs dépendances et leurs
données. Elle ne garantit pas toutes les interactions possibles. Choisir le test en
fonction de la panne que l'on veut détecter, puis vérifier un effet observable.

## Partir du métier, module par module

Le [catalogue fonctionnel](functional-tests.md) relie les responsabilités métier aux suites
existantes. Ce sont les points de départ d’une modification, pas une certification exhaustive.
Pour chaque évolution, écrire « dans cette situation, cet acteur peut faire cette action et
retrouve ce résultat », avec le refus ou l’effet interdit lorsque pertinent.

Chercher ensuite la preuve existante. Renforcer un scénario ou paramétrer ses variantes avant
d’en créer un autre. Garder les tests de domaine dans leur module et les parcours transversaux
dans `back/tests/` ou `e2e/specs/`; aucun déplacement massif ni framework BDD n’est nécessaire.
Un parcours d’intégration conserve les vrais services, schémas, autorisations et écritures ;
les doubles remplacent les fournisseurs, transports et déclenchements autonomes.

Un petit viewport est une condition d’usage : créer une compétence ou modifier un document
doit fonctionner. Ce n’est pas une raison d’imposer une rangée de boutons, une marge ou une
couleur historique. Vérifier une géométrie seulement lorsqu’elle prouve un usage, comme une
table imprimée sans contenu coupé ou une commande qui reste accessible au défilement.
Les préférences de thème et les styles explicitement enregistrés dans un document restent
des données fonctionnelles ; les pixels des contrôles d’édition ne le sont pas.

Un échec n’autorise pas à recopier le résultat actuel comme nouvelle attente. Expliquer la
garantie, reproduire la panne, puis distinguer défaut du produit, fixture incorrecte et contrat
volontairement modifié. Les nouveaux parcours restent collectés par les commandes et jobs CI
existants. Leur réussite doit être requise avant fusion ; le YAML local ne prouve pas à lui seul
que la protection de branche distante est activée.

## Commandes

Toutes les exécutions utilisent les conteneurs. Les tests backend et les parcours E2E
créent leurs propres bases ; ne pas lancer pytest dans le backend de développement.

| Besoin | Commande | Preuve apportée |
|---|---|---|
| Backend ciblé | `make tests ARGS='app/messenger/tests/test_interactions.py'` | Contrat et persistance des scénarios sélectionnés |
| Compatibilité fournisseurs et admission | `make tests-providers` | Composition SDK → proxy → HTTP simulé, validation des sorties et persistance Task ; obligatoire en CI et dans `make validate` |
| Backend complet et couverture critique | `make tests-coverage` | Suite complète exécutée une fois avec mesure des lignes et branches configurées |
| Typage, unités frontend et catalogues | `make typecheck` | Pyright, vue-tsc, tests Node rapides, cohérence i18n |
| Composants Vue dans Chromium | `make tests-front-components` | DOM réel, événements, styles calculés et requêtes HTTP interceptées explicitement |
| Composants ciblés | `make tests-front-components ARGS='chat.spec.mjs voice.spec.mjs'` | Même environnement, scénarios sélectionnés |
| Efficacité de la porte TypeScript | `make tests-front-tooling` | Des fautes injectées dans des copies sont effectivement rejetées |
| Application complète | `make tests-e2e` | Frontend de production, API, PostgreSQL et WebSocket sur Chromium, Firefox et WebKit |
| Frontières de modules | `make architecture-check` | Cartographie actuelle et contrats statiques |
| Mutations de cycle de vie | `make tests-mutations` | Neuf défauts injectés dans des copies temporaires provoquent un échec métier |
| Collecte navigateur | `make tests-focus-gates` | Les deux configurations acceptent un test ordinaire et rejettent `test.only` |
| Preuves de régression | `make regression-check` | Les tests référencés ont réussi et leurs mutations ont été détectées |

Pour travailler hors Lab : `make tests-coverage COVERAGE_TEST_ARGS='--ignore=app/lab'`.
La configuration de couverture reste celle du dépôt ; sélectionner des tests ne modifie
pas les fichiers mesurés. Pour les E2E, passer explicitement les fichiers souhaités dans
`ARGS`. La CI générale conserve son périmètre complet.

La commande frontend `npm test`, exécutée dans le conteneur, collecte les `*.test.mjs`.
Le test coûteux de l'outillage est un `*.check.mjs`, lancé séparément par la CI et
`make quality`. Les nouveaux scénarios de composants sont des `*.spec.mjs` : leur cible
Make et leur job CI sont obligatoires, ils ne sont pas collectés par Node.

## Choisir la bonne couche

- **Unité** : exécuter la fonction, le module TypeScript complet ou le store réel. Substituer
  les frontières nécessaires, puis vérifier sortie, état, requête et absence d'effet interdit.
- **Intégration DB** : les fixtures `db` et `client` utilisent transaction externe et
  savepoints ; un `commit()` applicatif ne signifie pas un commit indépendant. La fixture
  `committed_database` fournit des connexions indépendantes et de vrais commits pour tester
  verrous, visibilité et concurrence. Conserver ces deux modèles d'isolation.
- **HTTP** : un appel direct de service ne valide pas le RBAC du router. Tester les refus
  aussi bien que les succès. Le client ASGI ordinaire ne remplace pas un démarrage avec
  lifespan et workers, exercé sur les parcours E2E.
- **Composant navigateur** : monter le vrai composant avec Vue, Quasar, Pinia, i18n et les
  services réels. Les fixtures remplacent les réponses HTTP, pas les fonctions testées.
  Une requête API non prévue fait échouer le test. Tester clavier, fermeture, droits,
  chargements retardés, révisions et disposition aux largeurs pertinentes.
- **Contrat statique** : réserver AST, configuration évaluée ou catalogues parsés aux
  exigences effectivement structurelles. Trouver `v-if`, une classe CSS ou un commentaire
  ne démontre pas un comportement à l'écran.

L'environnement de composants est isolé sur un réseau Docker interne, sans backend,
sans port hôte et sans compte externe. Le microphone de test est synthétique. Les événements
Socket.IO de ces tests sont injectés dans les écouteurs enregistrés par l'application :
seuls les E2E valident également le transport réseau. La navigation du banc de composants
utilise un routeur mémoire ; les parcours complets valident le routage de production.

Le script détruit uniquement son projet et ses volumes. Les traces d'échec, captures,
rapports HTML et logs sont conservés sous `artifacts/front-components/<projet>/`.
Le code est copié dans un répertoire temporaire au lancement pour éviter les rechargements
provoqués par des éditions concurrentes. Les dépendances sont installées dans un volume Docker.

## Bridges et qualité IA

Les tests avec `MockTransport`, faux SDK ou réponses enregistrées vérifient le contrat
local : URL, authentification émise, payload, conversion, retries, refus et effets durables.
Ils restent utiles pour WhatsApp, Telegram, Matrix, Talk, OneBot, n8n et les autres adapters.
Ils ne prouvent pas qu'un compte peut se connecter aujourd'hui au service réel, ni qu'un
message est effectivement reçu par un utilisateur distant. Une qualification réelle
exige des comptes dédiés et des preuves de réception. `make qualify-matrix` fournit un premier
parcours réel : deux comptes distincts, une room autorisée, un texte synthétique et un fichier
dont le second compte vérifie les octets. Il ne qualifie pas les autres bridges ni l'admission
d'une Task entrante. Aucun compte réel n'est configuré par la CI générale.

Les évaluations déterministes d'agents et de mémoire protègent le pipeline, les règles,
l'isolation et les formats. Leurs réponses contrôlées ne mesurent pas la pertinence générale
d'un modèle réel. Les évaluations réelles du Lab restent une qualification distincte des
tests déterministes de ses formulaires, autorisations et publications.

## Lire les indicateurs

`back/coverage-critical.ini` impose **95 % sur un sous-ensemble agrégé** avec branches.
Ce n'est ni 95 % de toute l'application, ni 95 % minimum par bridge. Neuf mutations
réussies ne sont pas un score global de résistance aux mutations.

Un test plus petit peut être meilleur que dix assertions de texte source. Supprimer une
contrainte de marge, couleur exacte ou commentaire ne doit pas être présenté comme une
nouvelle garantie fonctionnelle. Lors d'un remplacement, consigner le comportement repris
et les assertions abandonnées. Les diagnostics manuels de `back/tests/manual/` restent
des essais opérateur ; leur présence n'apporte aucune garantie de CI.

La [mise en œuvre de l'audit](../../../project/audits/2026-09-07-test-suite-improvements.md)
recense les remplacements, les suppressions et les résultats réellement exécutés.

## Régressions et interruptions

Pour chaque régression produit : décrire la garantie, reproduire avant correction, conserver
le scénario principal et renseigner `regression_test` dans Incident. Les tests trop faibles
suivent le même traitement. `project/regressions.json` relie les cas ayant une mutation permanente
à leur audit et à leur test. `make regression-check` vérifie leurs résultats JUnit et mutations.
Un incident purement externe ne demande ni test artificiel ni fausse référence de correctif.

Les séquences Task et callbacks Process utilisent plusieurs graines fixes et restituent la
graine et l'historique en cas d'échec. `test_crash_recovery.py` tue un processus Python après
un commit de callback ou après l'effet d'un fournisseur simulé, puis redémarre un processus
sur la même base éphémère. Il vérifie résultat, attente, journal et clé d'idempotence.
Le fournisseur simulé possède un registre durable ; cette preuve n'attribue pas l'idempotence
à un fournisseur réel qui ne la propose pas.

Les rapports JUnit backend/navigateur, JSON Playwright, mutations et mesures par domaine sont
conservés en artefacts CI. Comparer les premiers passages, tests ignorés, durées et récidives
Incident. Un second passage vert n'efface pas le premier échec. Les retries navigateur restent
à zéro, avec trois répétitions E2E en CI.

## Couverture par domaine

`make validate` est la commande locale avant publication, sans serveur CI ni stack de
développement démarrée. Elle capture les fichiers suivis et nouveaux non ignorés, y compris les
modifications non committées et les suppressions, dans un clone local isolé. Elle utilise une
configuration de test issue de `.env.example`, jamais le `.env` de déploiement. Aucun commit,
restart applicatif, accès à un compte de messagerie ou appel IA payant n'est effectué.

Elle exécute les contrôles statiques et le build, les tests backend avec couverture, les vrais
composants, les mutations et preuves d'incidents, les executors et les parcours E2E répétés trois
fois sur chaque navigateur. Les étapes indépendantes continuent après un échec pour donner un
bilan complet. Le résultat et les journaux se trouvent dans `artifacts/validation/<run>/` ;
les rapports détaillés et traces sont sous `source/artifacts/`. La copie de code et son archive
sont conservées pour le diagnostic. Prévoir l'espace disque correspondant et supprimer les
anciens dossiers de validation lorsqu'ils ne sont plus utiles.

Un code de sortie non nul interdit de présenter ce passage comme une validation complète.
Si les sources changent pendant les tests, le bilan porte `STALE` et impose un nouveau passage.
Pour contrôler les branches critiques d'un chantier déjà committé, utiliser
`VALIDATION_BASE=<commit avant le chantier> make validate` ; par défaut la comparaison porte
sur les changements locaux contre HEAD. Cette commande ne qualifie pas les comptes externes,
la configuration HTTPS du déploiement, ni une migration depuis une ancienne base : les essais
de livraison, upgrade et restauration restent distincts.

`make tests-coverage` mesure désormais tous les fichiers backend `core`, `app` et `bridge`,
y compris ceux jamais importés par les tests. `artifacts/coverage-full.xml`,
`artifacts/coverage-full.json` et `artifacts/coverage-html/index.html` exposent les lignes et
branches manquantes par domaine. Les tests et runtimes embarqués `default-agent` sont exclus.
`back/coverage-all-domains.json` fixe les premiers planchers de chaque domaine, arrondis au
pourcent inférieur depuis la mesure complète du 12 septembre. Toute baisse sous ces planchers,
absence d'un domaine ou apparition d'un domaine sans plancher fait échouer le contrôle. Ces
planchers se relèvent après revue, jamais automatiquement. Les seuils critiques, plus précis,
continuent à s'appliquer. Le seuil critique de 95 % ne devient pas une prétendue couverture
globale de 95 %. La même exécution produit les deux rapports sans relancer pytest.

`back/coverage-domains.json` impose des planchers séparés de lignes et de branches pour dix
domaines du périmètre critique. Un domaine absent ou un fichier mesuré non affecté fait échouer
le contrôle. `COVERAGE_DIFF_BASE=<commit> make coverage-check` refuse également les branches
critiques modifiées non entièrement couvertes. Le rapport précise le sous-ensemble mesuré.
La commande explicite `check_critical_coverage.py --record` propose des planchers à relire dans
le diff ; elle n'est jamais exécutée en CI. Ne pas les diminuer pour passer un changement sans
expliquer la garantie conservée et la raison de la révision.

## Qualification des modèles et des bridges

`back/lab-qualification.json` impose trois répétitions, une moyenne minimale de 80 par catégorie,
une baisse maximale de cinq points de score ou de taux de réussite et aucun échec en sécurité.
Les catégories nominale, robustesse et sécurité sont exigées. Le corpus figé, les répétitions,
le juge et la version du score doivent correspondre. Un run incomplet, sans budget, sans
jugement exploitable ou dépassant son budget ne qualifie pas le candidat. Le budget Lab reste
un seuil d'admission qu'un appel en cours peut dépasser ; le comparateur refuse alors la preuve.

Installer le corpus versionné avec `scripts/import_lab_reference.py`, puis utiliser
`make qualify-lab` avec `LAB_ACCESS_TOKEN` dans l'environnement et `--base-url <URL>` dans
`ARGS`. Le mode `--start-dataset <uuid> --llm-id <id> --judge-llm-id <id> --max-cost <USD>`
lance explicitement une campagne. `--baseline <uuid> --candidate <uuid>` compare deux campagnes
terminées. Le rapport est `artifacts/lab-qualification.json`. Une note de juge ne prouve pas
une livraison externe ; conserver la revue humaine indépendante pour les erreurs critiques.

Pour Matrix, fournir `MATRIX_QUALIFICATION_SENDER_TOKEN` et `MATRIX_QUALIFICATION_OBSERVER_TOKEN`
par environnement, puis `make qualify-matrix` avec ces arguments dans `ARGS` :
`--homeserver <HTTPS> --sender <compte-test> --observer <second-compte-test>
--send-to-room <room-test> --output /repo/artifacts/matrix-run.json`, sur une seule ligne.
Seuls des comptes et destinations dédiés sont admissibles. Les reçus partiels survivent à une
réponse perdue ; le même fichier de preuve ne peut pas servir à relancer les envois.
La CI générale ne lance jamais ces commandes réelles automatiquement.

## Activation sur GitLab

Le distant `perso/genial` utilise GitLab. `.gitlab-ci.yml` fournit les contrôles de typage/build,
tests, sécurité, restauration et upgrade. Il exige un runner Shell dédié portant le tag
`galaris-quality`, avec Docker Compose, Make, Bash, Git et jq ; Python et Node restent dans
Docker. Une planification GitLab ajoute les essais de charge. La qualification manuelle d'une
release exige l'image précédemment déployée et ne déploie rien. Les workflows GitHub restent
utilisables pour un miroir.

Un Maintainer doit activer `only_allow_merge_if_pipeline_succeeds`, refuser les pipelines
ignorés et réserver les changements de `main` aux fusions validées. Le 11 septembre 2026, la
lecture distante montrait ce premier réglage désactivé et les pushes Maintainer autorisés.
GitLab a validé la syntaxe ; le compte Developer ne peut pas activer ces réglages ni simuler
un pipeline sur `main`. La présence du YAML ne vaut pas activation.
