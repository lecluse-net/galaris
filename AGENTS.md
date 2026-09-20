# Galaris — guide des agents de développement

Galaris est une plateforme auto-hébergée qui orchestre des agents IA autonomes, leurs
tâches, outils, objectifs, espaces de travail et canaux de messagerie. Ce fichier est le
point d’entrée durable pour tout agent qui modifie le dépôt.

## Commencer par les bonnes sources

En cas de divergence, utiliser cet ordre de confiance :

1. contrats, modèles, implémentation et tests présents dans le dépôt ;
2. `.env.example`, `back/core/settings.py` et déclarations de modules ;
3. `docs/fr/dev/README.md` et les décisions acceptées dans `project/decisions/` ;
4. `docs/fr/architecture/generated/project-map.md`, régénéré depuis le code ;
5. les fichiers de `project/plans/`, qui expriment une intention et dont le statut est indexé dans
   `project/plans/README.md`.

Avant toute intervention :

- lire `git status --short` et préserver les changements sans rapport ;
- ne jamais créer de commit sans une demande explicite de l’utilisateur dans le message courant ;
  une autorisation antérieure ne vaut pas pour les changements suivants ;
- rédiger tous les nouveaux messages de commit exclusivement en anglais, titre et corps compris,
  afin de faciliter les contributions internationales ;
- consulter la cartographie générée, puis les contrats et tests du domaine concerné ;
- utiliser `rg` ou `rg --files` pour localiser les surfaces réelles ;
- vérifier les hypothèses dans le code : un plan ou un exemple historique ne fait pas foi.

## Environnement et commandes

Ne JAMAIS modifier directement des fichiers sur le serveur de production, y compris
pour une correction urgente, un diagnostic ou une restauration. Préparer tous les
changements dans le dépôt de développement. Toute intervention en production exige
une demande explicite de l’utilisateur ; une demande de correction ou la documentation
des commandes de production ne constitue pas cette autorisation. Une demande de
déploiement n’autorise pas l’édition directe de fichiers sur le serveur.

`APP_ENV` est un libellé libre, avec `prod` par défaut. Le seul mode applicatif dérivé
est `is_dev = (APP_ENV == "dev")` : seule la valeur exacte `dev` active le développement.
Toute autre valeur (`prod`, `pp`, `test`, `demo`, inconnue ou vide) applique les comportements
et protections de production. Conserver le libellé `APP_ENV` pour les futures chartes graphiques
propres à chaque environnement. Les adaptations des tests automatisés appartiennent à leur
infrastructure isolée ; `APP_ENV=test` ne désactive aucune protection applicative.

Le développement est entièrement conteneurisé. Ne pas chercher ni lancer Python, Node,
npm, uv, Atlas ou PostgreSQL sur l’hôte.

```bash
APP_ENV=dev make start
make logs-back
make tests
make tests ARGS='app/agent/tests/test_registry.py'
make typecheck
make architecture-check
make project-context        # régénère la cartographie déterministe
make project-context-check  # vérifie qu’elle suit encore le code
make architecture-baseline  # réduit/actualise la dette de couplage après revue du diff
make sync-db                # dev uniquement : schéma/datasets DbAdmin, sans restart
make update                 # dev/prod : images + restart + synchronisation DB + attente de disponibilité
```

- Utiliser les cibles `make` lorsqu’elles existent.
- Le backend et le frontend ont le hot reload : ne pas redémarrer pour une simple édition.
- Les tests backend utilisent une base PostgreSQL éphémère. Ne jamais lancer `pytest` dans
  le conteneur de développement.
- Le schéma `public` est déclaratif et dérivé des modèles SQLAlchemy par `core.dbadmin`, qui
  encapsule Atlas. Il n’y a ni Alembic,
  ni migration manuscrite, ni cible `make migration`. En développement, `make sync-db` applique
  les changements sans redémarrer la stack ; en production, `make update` les applique au
  redémarrage du backend et attend que celui-ci soit sain.
- `make clean` supprime les volumes et n’est jamais une étape de diagnostic ordinaire.

Stack de référence : Python 3.14, FastAPI, Pydantic 2, SQLAlchemy 2 async, PostgreSQL 17 et
pgvector ; Vue 3, Quasar 2, Pinia 3, Vue Router 5, vue-i18n 11 et TypeScript ; Pydantic AI,
MCP/FastMCP et Docker Compose.

## Architecture du dépôt

Les deux listes d’activation font foi : `back/modules.py` et `front/modules.ts`.

| Couche | Responsabilité | Règle de dépendance |
|---|---|---|
| `back/core` | Infrastructure réutilisable : DB, API, auth, RBAC, i18n, websocket | Ne dépend jamais de `app` ni de `bridge` |
| `back/app` | Domaines métier Galaris | Consomme les surfaces publiques des autres domaines |
| `back/bridge` | Adaptation de systèmes externes | Traduit les protocoles externes vers les contrats Galaris |
| `front/core` | Shell, API, auth, navigation, i18n | Ne contient pas de logique métier applicative |
| `front/app` | Pages et états des domaines | Modules déclarés et routes basées sur les fichiers |
| `front/bridge` | Configuration et guides des systèmes externes | Contribue aux écrans génériques sans dupliquer les domaines métier |

Une surface inter-module stable est exposée par le package racine ou un module public nommé
`contracts.py`, `facade.py` ou `interface.py`. Éviter les imports vers un service interne ou
un modèle ORM d’un autre domaine. Les imports de composition au bootstrap sont une exception,
pas un précédent pour la logique métier.

### Exécution agentique

- `app.agent` est la façade et le contrat uniques : drivers, registre, dispatcher, planner,
  briefing, résolution du modèle, streaming et application du résultat.
- `app.harness` est l’implémentation concrète Pydantic AI.
- `app.task` possède la persistance, les transitions, leases, tentatives et le scheduler. Il
  fournit un port à `app.agent`; `app.agent` n’importe jamais `app.task`.
- `bridge.hermes` adapte Hermès au contrat `AgentDriver` ; un bridge ne contourne pas la
  façade agentique.
- Un stream produit zéro ou plusieurs événements de message, puis exactement un résultat
  terminal, et aucun événement après celui-ci.

Consulter `docs/fr/architecture/flows/agent-execution.md`,
`docs/fr/architecture/state-machines.md` et le skill `galaris-agent-execution` avant de modifier
ce chemin critique.

### Messagerie et médias

`app.messenger` est le modèle canonique des conversations, messages, capacités, journal
entrant et dispatch. Matrix, Nextcloud Talk, OneBot, Telegram et WhatsApp sont des bridges :
ils convertissent leur protocole, puis appellent la façade canonique. Ne pas réimplémenter le
workflow de tâches dans un bridge.

Les fichiers et médias entrants conservent l’URI du Tool qui les a reçus. Un runtime ne reçoit
qu’une matérialisation temporaire bornée lorsqu’une bibliothèque exige des octets ; ce temporaire
n’est ni durable ni adressable par l’agent. Consulter le skill `galaris-messaging-bridges`
et les flux `messaging.md` et `media-resources.md`.

### Outils et processus

Les outils MCP, connexions, fichiers et exécutions longues traversent les contrats de
`app.tools`, `app.mcp`, `app.connection`, `app.file_share` et `app.process`. n8n reste un
bridge externe. Les callbacks et transitions de processus doivent être idempotents et les
états terminaux immuables. Consulter le skill `galaris-process-tools`.

## Skills du dépôt

Les skills Codex sont versionnés dans `.agents/skills/`. Lire complètement le `SKILL.md`
applicable avant d’agir, puis ne charger que ses références utiles.

| Travail | Skills à utiliser |
|---|---|
| Toute modification | `general` |
| Architecture ou déclaration d’un module | `modules` ; `create-module` pour un CRUD complet |
| Python backend, SQLAlchemy, RBAC | `back-conventions` ; ajouter `database` si le schéma change |
| Migration de données, datasets permanents ou actions sur delta de modèle | `core-dbadmin` avec `database` et `back-conventions` |
| Vue/Quasar | `front-ui-conventions`, `vue-skilld`, `quasar-skilld` |
| Pinia, routes ou traductions | `pinia-skilld`, `vue-router-skilld`, `vue-i18n-skilld` selon les imports |
| Agent, tâche, driver, planner, briefing | `galaris-agent-execution` ; ajouter `building-pydantic-ai-agents` pour le harnais interne |
| Messagerie ou bridge conversationnel | `galaris-messaging-bridges` ; ajouter `onebot-11` pour OneBot |
| MCP, outils, process, n8n, fichiers | `galaris-process-tools` |
| Logfire | le skill `logfire-*` correspondant à instrumentation, requête ou interface |

Créer ou faire évoluer un skill avec le skill système `skill-creator`; ne pas dupliquer ce
skill dans le dépôt. Un skill local contient au minimum `SKILL.md` avec uniquement `name` et
`description` dans son frontmatter. Ajouter `agents/openai.yaml` lorsque sa découverte dans
l’interface mérite un libellé ou un prompt explicite.

## Conventions de code

### Backend

- Pyright est strict sur le code de production : typer les paramètres et retours, et réduire
  les `Any` aux frontières réellement dynamiques.
- Utiliser SQLAlchemy 2 avec `Mapped[T]`, `mapped_column`, requêtes async et la session
  contextuelle fournie par `core.database`.
- Un identifiant primaire est soit un entier auto-incrémenté, soit un UUID. Une colonne dont le
  nom se termine par `_id` est exclusivement une clé étrangère réelle vers l’identifiant primaire
  d’une autre table, avec le même type. Les identifiants fournis par un système externe utilisent
  un nom explicite tel que `external_id` et jamais le suffixe `_id` sur une table qui ne les porte
  pas comme clé primaire.
- La logique métier vit dans des fonctions/services du domaine ; les routers valident,
  autorisent et délèguent.
- Protéger les endpoints avec le mécanisme RBAC existant et tester les refus autant que les
  succès.
- Utiliser Loguru pour les journaux applicatifs ; ne pas laisser de `print` en production.

### Frontend

- La palette **Solaire** est la référence chromatique obligatoire pour toute l’application :
  [valeurs et règles d’usage](docs/fr/dev/palette-solaire.md). Utiliser ses 11 accents et leurs
  fonds clairs/sombres exacts pour les icônes, composants, états et graphiques. Ne pas reprendre
  une couleur historique ou une teinte Quasar approchante comme référence, ni réintroduire les
  couleurs écartées. Toute évolution de la palette doit être portée par cette référence commune.
- Conserver les composants et pages focalisés ; mettre les appels API dans les services et
  l’état partagé dans Pinia.
- Les routes sont dérivées de `pages/`; ne pas maintenir une seconde table de routes.
- Le mode `mobile` correspond exclusivement à une largeur de viewport inférieure à
  1024 px CSS (`$q.screen.lt.md`) ; le mode `desktop` commence à 1024 px, sans tenir compte
  de l’orientation ni du type d’appareil.
- Toute chaîne visible passe par vue-i18n. Les catalogues anglais et français conservent les
  mêmes clés, types et paramètres.
- Respecter les privilèges dans la navigation et dans l’API ; masquer un bouton ne remplace
  jamais l’autorisation backend.
- Toute modale doit pouvoir être fermée en cliquant sur l’arrière-plan. Ne jamais utiliser
  `persistent`, `no-backdrop-dismiss` ou une option équivalente sur un dialogue Quasar.
- Toute liste paginée utilise 50 éléments par défaut et propose exactement
  `[10, 20, 50, 100, 500]`. Pour une pagination serveur, le contrat API doit accepter 500 éléments.

## Tests, documentation et livraison

- Les jeux de test destinés au dépôt doivent être entièrement synthétiques. Ne pas copier
  des conversations, profils, titres de documents ou captures de production puis seulement
  changer les noms. Les audits publics conservent les mesures agrégées et les conclusions
  techniques ; retirer les données individuelles, identifiants réels, commandes capturées
  et chemins propres à une installation. Les diagnostics locaux écrivent hors des sources
  ou sous `artifacts/`, jamais dans un fichier versionné. Conserver les crédits et copyrights.

- Pour une optimisation ou correction transversale (API, chargement différé, cache, session,
  composant partagé), inventorier ses consommateurs et écrire les garanties à préserver avant
  de généraliser le changement. Vérifier un premier parcours complet, puis étendre par groupes
  de consommateurs. Couvrir ouverture, réouverture, données préexistantes, erreurs, réponses
  tardives et changement de contexte lorsque ces états s'appliquent.
- Une correction de stabilisation garde un périmètre limité : séparer les refontes connexes.
  Une suite ciblée verte ne qualifie pas un changement transversal pour publication.
- Sans CI, lancer `make validate` avant publication : la commande teste un instantané isolé
  incluant les changements non committés. Toute édition ultérieure invalide la qualification
  du code courant. Lire `artifacts/validation/*/summary.txt` et les échecs, sans assimiler un
  passage partiel à une validation complète. Aucun commit ni déploiement n'est effectué.
- Partir du métier : formuler d’abord une garantie observable, puis choisir le test le
  plus direct qui la prouve. Consulter le catalogue `docs/fr/dev/functional-tests.md`.
- Un test doit survivre à une réorganisation du code qui préserve cette garantie. Ne pas
  figer une largeur, une couleur, un ordre de boutons ou la présence d’un fragment source
  pour immortaliser une ancienne demande de présentation. Tester l’action utilisable,
  le contenu préservé, les droits et les effets durables. Une dimension n’est une assertion
  que si elle porte un contrat fonctionnel, par exemple l’absence de contenu coupé à l’impression.
- Garder les unités pour les règles pures, les intégrations avec vrais services/DB pour les
  workflows, les composants réels pour les interactions et quelques E2E pour l’assemblage.
  Remplacer les frontières externes, pas les services internes du parcours testé.
- Avant d’ajouter un test, chercher la garantie existante. Renforcer ou paramétrer un scénario
  pertinent plutôt que le dupliquer. Avant d’en supprimer un, consigner la garantie reprise
  ou la contrainte accessoire abandonnée. Ne pas fabriquer un test par fonction ou par module.
- Un test rouge exige un diagnostic : corriger le produit si la garantie est rompue ; ne
  modifier l’attente que si le changement de contrat est volontaire et documenté. Pour un bug,
  vérifier que le scénario reproduit le défaut avant correction.
- Ajouter un test au niveau du contrat modifié : unité pour la logique, intégration DB pour
  la persistance, AST pour une frontière d’architecture.
- Exécuter d’abord les tests ciblés, puis `make typecheck`, `make architecture-check` et les
  suites proportionnées au risque.
- Régénérer `docs/fr/architecture/generated/` et `docs/en/architecture/generated/` avec
  `make project-context`; ne pas éditer leurs
  fichiers à la main.
- Réduire `back/architecture.toml` et `back/architecture-baseline.json` lorsqu’une dépendance,
  un import privé ou un cycle disparaît. Ne jamais augmenter la baseline sans revue explicite.
- Ajouter ou modifier une décision dans `project/decisions/` lorsqu’un choix structurel change.
- Mettre à jour `project/plans/README.md` lorsqu’un plan change de statut. Un plan `design` ou
  `approved` ne décrit pas encore nécessairement le runtime.
- Terminer par `git diff --check` et relire le diff sans écraser les modifications d’autrui.
