# Mise en œuvre de l'audit des tests — hors Lab

L'audit du 7 septembre 2026 est mis en œuvre sur les tests, leur exécution et leur
documentation. Le Lab et les changements applicatifs concomitants sont préservés.
Aucun commit, compte externe ou envoi de message n'a été créé.

Le gain principal est de remplacer les inspections de code censées prouver une interface
par des comportements exécutés. **55 scénarios Chromium** montent les composants réels.
La boucle Node prend **1,86 s** ; le test coûteux de la porte TypeScript conserve sa place
en CI, dans une commande distincte. Les tests backend de refus, de persistance et de
concurrence restent en place.

## Traitement des constats

| Audit | Mise en œuvre |
|---|---|
| A01 | Le choix fermé crée une interaction, reçoit un texte non reconnu, vérifie l'état persistant inchangé et l'absence de résolution, puis accepte une réponse valide. |
| A02 | Migration des oracles frontend vers composants réels, services/modules évalués ou suppression explicite des contraintes accessoires. Les tests exécutables des fichiers mixtes sont conservés. |
| A03 | Suppression des trois doublons exacts dans les tests Params et YAML. |
| A04 | Suppression du faux scénario d'accolades imbriquées déjà couvert comme interpolation ordinaire ; vraie exécution terminée et annulations répétées ; refus MCP exigeant `ToolError` avec `PermissionError`, sans démarrage ni ProcessRun créé. |
| A05 | Le test de récence compare les instants avec fuseau plutôt qu'une représentation imposée en heure de Paris. Il passe dans l'environnement UTC. |
| A06 | `typecheck-gate.check.mjs` reste exécuté par `test:tooling`, la CI et `make quality`, hors collecte Node rapide. |
| A07 | Tests locaux des bridges conservés. Portée documentée : adapter, requêtes, conversion, erreurs et effets locaux ; aucune certification d'un compte distant. |
| A08 | Évaluations déterministes conservées, avec distinction explicite entre contrats/règles et qualité générale d'un modèle. Aucun changement du Lab. |
| A09 | Documentation des savepoints, connexions indépendantes, vrais commits et limites du client ASGI. Fixtures conservées. |
| A10 | Contrats statiques utiles conservés ; plusieurs catalogues et configurations sont désormais évalués au lieu d'être cherchés par regex. Une seule exécution backend complète avec couverture en CI. Seuil de 70 % inchangé. |
| A11 | Squelette manuel vide supprimé ; diagnostics opérateur documentés ; ancien script 3D repris dans trois scénarios collectés et obligatoires en CI, puis retiré. |

## Traçabilité des tests frontend

Le [tableau par définition](2026-09-07-test-suite-evidence/frontend-tests-migration.csv)
contient les **191 définitions d'oracles d'interface** signalées par l'audit, ainsi que
**13 contrats à assouplir**, soit 204 lignes. Il associe chaque définition historique à
son traitement, aux tests du domaine et à la portée réellement reprise.

Il ne s'agit pas de 204 nouveaux tests ni de 204 garanties équivalentes. Les scénarios
sont regroupés lorsqu'ils couvrent un même parcours. Les prescriptions de marge, de
couleur exacte, de commentaire, de classe ou d'ordre interne sont retirées lorsqu'elles
n'apportent pas une garantie fonctionnelle distincte. Les scénarios associés ne prouvent
pas individuellement tous les anciens intitulés. L'ancien inventaire reste la référence
historique, avec son avertissement sur la revue sémantique ciblée.

Deux fichiers mêlaient du hors Lab et du Lab : `agentSelectPresentation.test.mjs` et
`pageHeaderNavigation.test.mjs`. Seules leurs portions hors chantier parallèle ont été
traitées ; leurs contrôles Lab restants, ainsi que le test de retour du journal d'incidents
déplacé en parallèle, sont conservés. Les catalogues Lab encore chargés par des tests
transversaux ne font pas l'objet d'une modification ou d'une certification ici.

| Domaine | Comportements désormais exercés dans le navigateur |
|---|---|
| Accueil et shell | Droits visibles puis révoqués, liens autorisés, thèmes calculés, accueil public mobile/desktop, navigation au clavier, sidebar repliable. |
| Chat | Création avec préférences, archivage/restauration, filtres indépendants, compteurs accessibles, effort de tâche transmis puis réinitialisé, détails processus/documents. |
| Tâches et exécution | Filtres clavier/souris et paramètres HTTP, expansion locale, conservation du défilement, retour en bas, pause sans animation, trace vivante malgré un chargement retardé. |
| Goals et calendrier | Pause/reprise avec révision, actions absentes en lecture seule, onglets et fermeture, grille réelle au clavier/pointeur et restriction aux créneaux permis. |
| Mémoire | Recherche avec types, sélection d'un résultat, autosave avec révision, brouillon préservé lors d'une révision distante, bibliothèque en plusieurs pages, document mobile, tableaux Markdown. |
| LLM et harnais | Tokens/coûts/effort affichés, réponse normalisée, événements filtrés par propriétaire, consentement d'abonnement et révocation, disponibilité/retry et prévention du double restart. |
| Préférences | Thème/langue persistés, diff de prompt, sauvegarde, conservation du personnalisé ou adoption du défaut, révocation des droits. |
| Compétences | Actions à 375, 1023, 1024 et 1440 px, disposition calculée, ouverture/fermeture et aperçu réel du frontmatter. |
| 3D | Géométrie visible dans les trois surfaces, zoom/rotation/déplacement, clavier, souris, plein écran, fermeture de l'aide puis du viewer, backdrop mobile et nettoyage. |
| Voix | Offre WebRTC réelle, candidats ICE, annulation pendant la connexion, suppression d'un appel tardif, mute et libération des pistes sur terminaison distante simulée. |

Les unités nouvelles exécutent les services Chat, Goal, Contact et Process pour contrôler
les requêtes réelles ; les statuts, autorisations, catégories LLM et contributions sont
évalués. Le worker PWA est exécuté pour vérifier push, badge, suppression pour la conversation
visible et navigation au clic. Le scénario PWA complet vérifie aussi les en-têtes HTTP des
fichiers bootstrap et l'URL du worker sur le serveur de production.

## Environnement et CI

`make tests-front-components` crée un projet Docker propre, copie les sources dans un
répertoire temporaire et démarre Vite avec les dépendances préchargées. Cela évite qu'une
édition concurrente ou une découverte tardive de dépendance recharge une page testée.
Les composants utilisent Vue, Quasar, Pinia, i18n et les services applicatifs. Toute requête
API sans fixture fait échouer le test. Le transport HTTP est simulé ; le réseau Docker est
interne et aucun backend ni compte externe n'est utilisé.

Le job `frontend-components` est requis par `Quality required`. Ses traces, captures et
logs sont archivés en cas d'échec. `make quality` l'inclut. Le scénario 3D précédemment
manuel est donc collecté dans ce job dédié. La porte TypeScript reste obligatoire et
utilise une commande distincte des unités
rapides dans le job statique. Le job backend lance `make tests-coverage` une seule fois
au lieu d'enchaîner la suite complète puis une seconde sélection couverte.

## Résultats exécutés

| Validation | Résultat |
|---|---|
| `make tests-coverage COVERAGE_TEST_ARGS='--ignore=app/lab -q'` | **3 313 réussis, 1 ignoré**, 162 s ; **73,87 %** sur la configuration critique, seuil atteint. |
| `make typecheck` | Pyright et vue-tsc réussis ; **218 unités frontend réussies**, 1,86 s ; contrôle i18n réussi. |
| `make tests-front-tooling` | **1 scénario réussi**, 40,48 s, avec erreurs injectées rejetées. |
| `make tests-front-components` | **55 réussis**, environ 1,1 min hors construction/préparation, zéro retry configuré. |
| E2E ciblés hors fichier Lab | **51 réussis** : 17 scénarios × Chromium/Firefox/WebKit, environ 3,1 min. |
| `make tests-mutations` | Référence valide et **4 mutations backend détectées sur 4**. |
| `make architecture-check` | Cartographie/frontières valides et **27 tests réussis**. |
| Cartographie générée | Régénérée après les changements concomitants, puis vérifiée avec `make project-context-check`. |
| `make lint` | Ruff et ESLint réussis. |
| `make format-check` | Réussi lors du premier passage ; le dernier passage signale uniquement `back/app/lab/run_inference.py`, modifié en parallèle et laissé intact. |

Les E2E ont sélectionné `chat.spec.mjs`, `reliability.spec.mjs`, `session-races.spec.mjs`,
`sanitizer.spec.mjs`, `pwa.spec.mjs` et le nouveau `incident.spec.mjs` du chantier parallèle.
Leurs étapes transversales ne sont pas une revue du Lab. Les répétitions `--repeat-each=3`
de CI n'ont pas été reproduites ici. Les tests d'executors et les qualifications de charge,
restauration et release ne sont pas relancés : ils ne sont pas modifiés par ce chantier.

Les premiers essais de composants ont permis de corriger les fixtures et le banc de test,
notamment les imports par la contribution publique de l'éditeur, la préoptimisation et les
rechargements dus aux éditions concurrentes. Les chiffres ci-dessus décrivent les dernières
exécutions réussies, sans masquer ces corrections sous des retries automatiques.

## Vérifier que les nouveaux tests peuvent échouer utilement

Trois transformations ont été exécutées dans une copie jetable, après validation des huit
scénarios de référence concernés :

| Transformation | Ancien oracle | Nouvel oracle |
|---|---|---|
| `rgb(250, 250, 250)` → `#fafafa` | Échec erroné | Réussite : même couleur calculée. |
| Règle finale `flex-wrap: wrap !important` sur les actions | Réussite erronée | Échec sur le style calculé à 375 px. |
| `v-if="canReadChat"` déplacé dans un commentaire | Réussite erronée | Échec : la carte reste présente après révocation du droit. |

Ces expériences ne modifient pas le code de travail. Elles qualifient trois oracles choisis,
sans constituer un score global de mutation. Les résultats sont conservés dans
[les preuves de validation](2026-09-07-test-suite-evidence/implementation-validation.json).

Les limites générales et commandes sont documentées dans
[Tester les comportements](../../docs/fr/dev/testing.md) et la
[décision 0079](../decisions/0079-behavioral-frontend-test-gates.md).
