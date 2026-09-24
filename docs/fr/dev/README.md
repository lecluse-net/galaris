<p align="right"><strong>Français</strong> · <a href="../../en/dev/README.md">English</a></p>

# Guide développeur

Ce document décrit l’architecture qui existe dans le dépôt. Il sert de contrat de
contribution : lorsqu’une implémentation impose un autre flux, corrigez soit le code soit ce
guide, mais ne créez pas une seconde architecture implicite.

Pour trouver rapidement une surface, utiliser la
[cartographie générée](../architecture/generated/project-map.md). Les
[invariants, flux et machines d’état](../architecture/README.md) complètent ce guide,
et les choix structurels acceptés sont consignés dans
[`project/decisions`](../../../project/decisions/README.md). La cartographie est un index statique ; les
contrats et tests restent l’autorité sur le comportement.

Le [corpus de référence du Lab](lab-reference-corpus.md) fournit des cas reproductibles sur
les contraintes éditoriales et les ressources. Les mesures de chargement frontend et la
lecture des budgets sont décrites dans le [guide d'exploitation](reliability-operations.md).

Le client HTTP frontend n'impose aucun délai maximal aux requêtes API, y compris aux
analyses du Lab, aux transferts de documents et aux opérations de harnais. Une opération
locale lente peut attendre sa réponse ; l'annulation explicite utilise `AbortSignal`, et
une réponse issue d'une ancienne session reste rejetée. Aucun paramètre de délai navigateur
n'est nécessaire. Les limites du serveur, du fournisseur et des proxys sont indépendantes.

## 1. Environnement de développement

Le [catalogue des commandes Make](make-commands.md) recense toutes les cibles du dépôt,
leur rôle et les possibilités de simplification. `make help` liste les commandes de la racine.

`APP_ENV` reste un libellé libre, conservé pour identifier l’environnement et permettre
une future charte graphique dédiée. Sa valeur par défaut est `prod`. Le seul mode
applicatif dérivé est `is_dev = (APP_ENV == "dev")` : `pp`, `test`, `demo` et toute
autre valeur appliquent les mêmes protections et comportements que `prod`.

Avec `APP_ENV=dev` dans `.env`, `make update` reconstruit les images de développement
avec le cache Docker, recrée le backend et le frontend, synchronise la base avant de lancer l’API et
attend que les services soient disponibles. Pour forcer ce mode : `make APP_ENV=dev update`.
Cette commande permet aussi de revenir en dev après avoir utilisé des images de production.
Les services d’infrastructure inchangés restent actifs. Un build échoué conserve les conteneurs
en cours ; après un build réussi, un seul `up --wait` applique les changements et attend la santé
des services. PostgreSQL et TURN ne sont retirés que lorsqu’ils deviennent externes ou désactivés.
En production, la reconstruction réutilise aussi le cache Docker et vérifie les images de base ;
`RELEASE_DIR` reste réservé aux environnements dont `APP_ENV` diffère de `dev`.

`make update` construit et déploie les sources présentes sans récupération Git.
Avec un `.git`, `VERSION=<référence>` récupère et sélectionne un tag exact, sinon une branche
distante. Les changements locaux bloquent uniquement cette sélection explicite.
Le bas du menu affiche la référence Git de construction (tag exact, sinon branche, puis
commit court en HEAD détachée) et un lien « À propos ». Cette page conserve les crédits et
l’accès à la licence ; la page générique de mentions légales a été retirée. La référence
est injectée dans les images par `GALARIS_BUILD_VERSION`, sans réglage utilisateur.
Pour déployer son travail local ou une configuration, utiliser `make update`. `make start` conserve toujours
les sources présentes, y compris lorsqu’il doit reconstruire une installation incomplète.

```bash
make install
# Configurer .env, notamment APP_ENV=dev, APP_HOST et TZ.
make update
make typecheck
make tests
```

Le backend et le frontend utilisent le hot reload en mode `dev`. Ne redémarrez pas toute la
stack après une simple modification Vue ou Python. Après une modification de modèle SQLAlchemy,
de privilège ou de donnée de référence, lancez `make sync-db` : la commande appelle
`core.dbadmin` pour faire converger le schéma `public` et les datasets sans redémarrer. Utilisez
les journaux du service concerné.

Stack principale :

- Python 3.14, FastAPI, Pydantic 2, SQLAlchemy 2 async et asyncpg ;
- Pydantic AI pour le harnais interne ;
- PostgreSQL 17 avec pgvector, schéma déclaratif Atlas ;
- Vue 3, Quasar 2, Pinia 4, Vue Router 5, vue-i18n 11 et TypeScript ;
- MCP/FastMCP pour les outils ;
- Playwright/Chromium dans un sidecar isolé pour le Tool navigateur ;
- Docker Compose pour l’environnement reproductible.

LangGraph et Alembic ne font pas partie de l’architecture.

### Santé et supervision du runtime

Le lifespan enregistre les boucles racines auprès de `core.runtime`. Le superviseur les démarre,
les arrête dans l’ordre inverse et relance une racine terminée avec un backoff borné. Cette couche
ne remplace jamais les leases, transitions ou clés d’idempotence propres aux domaines.

Les trois endpoints ont des contrats distincts :

- `/api/health` conserve la réponse historique ;
- `/api/health/live` vérifie seulement que le processus ASGI répond ;
- `/api/health/ready` vérifie le superviseur, les composants critiques et PostgreSQL, tout en
  signalant les bridges facultatifs comme `degraded`.

Le healthcheck du conteneur backend utilise la readiness locale. Un test synthétique traversant le
frontend doit rester séparé afin qu’une panne du proxy ne falsifie pas la santé du backend.

## 2. Couches et modules

```text
back/
├── core/                 infrastructure réutilisable
│   ├── api, database, authorize, user, params, i18n, websocket
├── app/                  domaines métier Galaris
│   ├── agent/            façade et orchestration agentiques génériques
│   ├── harness/            harnais interne Pydantic AI
│   ├── task/             persistance et ordonnanceur de tâches
│   ├── llm, tools, messenger, memory, process, browser, ...
│   ├── file_share/       URI de ressources, providers et transferts streamés
│   └── audio/            normalisation multimédia et tool MCP de transcription
└── bridge/               intégrations avec des systèmes autonomes
    ├── hermes, n8n, matrix, one_bot, nextcloud
    └── youtube/          validation d’URL et récupération des sous-titres publics

front/
├── core/                 API, auth, RBAC, navigation, i18n, utilitaires
├── app/                  pages et états des domaines métier
└── bridge/               contributions UI des intégrations externes

bridge/
└── harness_manager/      service hôte générique pour instances Compose et fichiers
```

Les modules backend sont déclarés dans `back/modules.py`. Chaque package peut exposer un
`router`, des modèles, des privilèges, un listener, des paramètres ou des locales. Le
bootstrap central charge seulement les éléments déclarés.

Les modules frontend sont déclarés dans `front/modules.ts`. Les pages sont découvertes par
le routage basé sur les fichiers ; la navigation est agrégée depuis les `navigation.ts`.

Le navigateur agentique est décrit dans
[`docs/fr/architecture/flows/browser.md`](../architecture/flows/browser.md). Son conteneur
partage Chromium, mais chaque session possède un contexte isolé et une autorisation liée à
l’agent et à la tâche.

Règles de dépendance :

- `core` ne dépend pas de `app` ;
- un domaine `app` utilise les façades publiques d’un autre domaine, pas ses détails ORM ;
- un `bridge` adapte un système externe aux contrats Galaris ;
- un `front/bridge` expose la configuration et le guide de son `back/bridge`, sans dupliquer
  le workflow métier du domaine ;
- les imports de bootstrap peuvent assembler les modules, mais la logique métier ne doit
  pas s’appuyer sur leur ordre d’import implicite.

Ces règles sont aussi exprimées comme budgets exécutables dans `back/architecture.toml`.
Chaque module actif y déclare ses dépendances `app`/`bridge` autorisées et son fan-out maximal.
`back/architecture-baseline.json` isole la dette historique : imports inter-modules qui ne
passent pas encore par une racine publique, `contracts`, `facade` ou `interface`, ainsi que les
composantes cycliques existantes. `make architecture-check` refuse une nouvelle dépendance non
déclarée, une hausse du budget, un nouvel import privé ou un cycle nouveau ou élargi.

Lorsqu'une dette est supprimée, exécuter `make architecture-baseline`, relire la réduction du
diff puis conserver le budget réduit dans `back/architecture.toml`. Cette cible ne doit jamais
servir à accepter machinalement une régression.

Le frontend possède le même filet progressif dans `front/architecture-baseline.json`. La
cartographie analyse les imports TypeScript/Vue aliasés ou relatifs et publie fan-in, fan-out,
cycles directs et composantes fortement connexes. Une nouvelle dépendance, un nouvel import privé
ou un cycle nouveau/élargi fait échouer `make architecture-check`.

## 3. Architecture agentique

### Responsabilités

`app.agent` est le point d’entrée unique du sous-système agentique. Il contient :

- les contrats indépendants du runtime (`AgentDriver`, `AgentRunRequest`, événements,
  résultats, politiques) ;
- le registre et l’état de disponibilité des drivers ;
- la résolution des modèles et stratégies d’exécution `standard` et `high` ;
- le dispatcher, le planner, le briefing et le workflow commun ;
- la façade publique `run`, `stream`, `cancel`, ainsi que les adaptateurs de tâches ;
- le port vers la persistance durable.

`app.harness` est le harnais interne Pydantic AI : adaptation au contrat `AgentDriver`,
construction de l’agent, toolset, historique, médias, streaming, registre des runs annulables et
checkpoints d’effets. `bridge.hermes` est son pair externe. Le dispatcher, le planner et le briefing restent
dans `app.agent`, car ils préparent un `AgentRunRequest` avant l’entrée dans l’un ou l’autre driver.

`bridge.hermes` contient le client, le driver, la configuration et l'adaptation du runtime
Hermès. Ses routes d’administration peuvent être utilisées par l’IHM Hermès ; une exécution
fonctionnelle ne doit jamais contourner `app.agent`.

Le serveur hôte `harness_manager` est distinct : il gère génériquement les répertoires,
conteneurs Compose, actions bornées et fichiers de n'importe quel harnais. Il ne connaît aucune
API ou CLI Hermès. `bridge.hermes` génère les artefacts Hermès puis consomme ce contrat générique
sous `/instances`, avec une instance et un conteneur distincts pour chaque agent.

Le client de ce contrat vit dans `back/bridge/harness`. Ses coordonnées et son secret partagé
sont des Params communs à tous les harnais, administrables dans Préférences → Harnais.
Le secret est chiffré en base. L’IHM prépare aussi le `.env` du service hôte local ou distant.

Préférences → Harnais distingue **Harnais interne**, **Harnais managés** et **Harnais externes**.
Chaque politique technique se règle dans la configuration du harnais concerné et s’applique
à tous les harnais du même fournisseur. L’onglet interne expose la politique `internal`
et la limite des fichiers binaires envoyés au modèle.
**Tâches et exécution** regroupe l’ordonnancement, les reprises, les budgets globaux, la création
des objectifs, la collaboration et les limites de requêtes modèle et d’appels d’outils par
exécution. Le moteur interne applique ces limites ; les harnais réseau compatibles les
reçoivent et sont responsables de leur application. Les anciens liens vers les onglets
`common` et `advanced` des harnais redirigent vers cette page.
Les blocs Planner et Briefing y listent les harnais dont la politique déclare l’usage
du mécanisme et disparaît si cette liste est vide. L’API expose la politique du provider choisi,
prioritaire sur celle de son transport. Le briefing exige aussi au moins un niveau d’effort
autorisé. Aujourd’hui, seul le harnais interne utilise le Planner ; le Briefing reste masqué.
Le prompt du briefing est un Param (`ai.briefing-system-prompt`) avec défaut canonique et
personnalisation persistée, sans activer le mécanisme. Les évaluations du Lab gardent leur
surcharge explicite. Le Planner conserve son prompt et ses limites de profondeur, nœuds et feuilles.
La conservation automatique des traces d’incidents et
LLM se règle dans Journaux, séparément des purges manuelles. Cette répartition conserve les
clés et valeurs persistées ; elle n’introduit pas de surcharges des limites par harnais.

Les tailles affichées et saisies dans l’interface utilisent des Mo décimaux (1 Mo = 1 000 000
octets), y compris les petites pièces jointes. `core/util/fileSize.ts` centralise le formatage
localisé et les conversions ; les contrats API conservent leurs unités. Un `SettingField`
de taille déclare `sizeUnit` pour convertir aussi ses bornes et son pas. Les réglages historiques
stockés en Mio acceptent les fractions pour saisir des Mo ronds. Les défauts sont décimaux :
20 Mo pour le harnais interne, 4 Mo pour les pièces jointes inline, 1 Mo pour les webhooks,
0,064 Mo pour les données brutes de processus. DbAdmin remplace uniquement les valeurs exactement
égales aux anciens défauts ; les autres valeurs et les remises à zéro explicites sont préservées.
Le manager conserve les unités historiques de son API et de son `.env`, avec des fractions
correspondant à 1 Mo et 512 Mo par défaut. Les avatars sont limités à 5 Mo, les icônes SVG à
0,064 Mo, les aperçus 3D à 32 Mo et les exports à 64 Mo dont 12 Mo de contenu HTML.

Le manager Hermès utilise exclusivement le harness manager et pilote un Compose par agent. Le
répertoire `BASE_DIR/<agent.code>/data` est monté dans `/opt/data` du conteneur
`<agent.code>-agent` ; workspaces, skills, sessions, mémoire et secrets ne sont jamais partagés
avec un autre agent. Les médias passent par le canal de fichiers en flux du manager et non par
`/api/files`, dont la limite de 100 Mio ne fait pas partie du contrat Galaris.

Pour l’exécution, `standard` et `high` utilisent les sessions `/v1/runs` ; `high` conserve son
modèle plus puissant. Le Kanban est désactivé par une constante interne au driver Hermès, non
configurable par le déploiement. Son adaptateur reste isolé sans backend de management en
production ; une réactivation exigerait une nouvelle décision compatible avec l’isolation par
conteneur.

Le manager injecte toujours le proxy OpenAI Galaris et le modèle effectif de l’agent en dernier,
puis retire les clés de fournisseur directes. Hermès ne possède plus de réglage permettant de
contourner ce gateway : tous ses appels LLM restent ainsi corrélés et traçables dans Galaris.
L'URL, le modèle et le port de son API d'exécution restent des données internes générées par le
provisioner ; `/api/hermes/configurations` ne les expose pas aux opérateurs.

Le run direct construit sa trace depuis le stream et la session persistante Hermès. Il ne
reconstruit plus les appels de fonction depuis `LLMCall.tool_calls`. Ce repli reste dans le code
Kanban mais retourne immédiatement tant que la constante interne est désactivée.

Le harness manager, son authentification et son service systemd sont documentés dans
[`docs/fr/components/harness-manager.md`](../components/harness-manager.md). Les particularités
du consommateur Hermès sont documentées dans
[`docs/fr/components/hermes.md`](../components/hermes.md).

`app.task` possède les modèles SQLAlchemy, la machine d’état durable, les leases, tentatives,
reprises, commandes d’administration et le scheduler. Il ne choisit ni le driver, ni le
modèle, ni l’usage du planner ou du briefing.

Ses limites d’ordonnancement, de reprise, de planification, de budget et de collaboration
sont stockées dans `params` et administrées dans **Préférences → Tâches**. Les consommateurs
lisent leur vue typée à la frontière d’une nouvelle action ; une exécution déjà lancée
conserve les bornes capturées à son démarrage.

Les Params déclarés avec le kind `prompt` suivent un contrat analogue aux fichiers de
configuration Debian. Une valeur durable `NULL` suit automatiquement le défaut anglais livré par
Galaris. Les prompts vivent sous `core.params`, jamais dans i18n, et ne sont pas traduits ; seuls
leurs libellés et descriptions d’interface le sont. Une personnalisation mémorise
l’empreinte de ce défaut ; si le bundle livré change,
DbAdmin préserve la valeur et l’IHM propose de garder la personnalisation ou d’adopter le nouveau
défaut après comparaison. Le démarrage reste toujours non interactif.

### Contexte commun, session et mémoire durable

`app.agent.context` compose des providers nommés avant l'entrée dans un driver. Un provider peut
apporter des instructions, un contexte partagé, un historique conversationnel, des candidats
structurés et des métadonnées,
mais ne doit pas modifier la Task. Chaque échec est fail-open et enregistré dans les métadonnées du
run. `app.agent.observers` est un petit bus de projection, pas un gestionnaire du cycle de vie du
runtime : il notifie les changements de profil et les Tasks terminales. Ses observers doivent
inscrire un travail court et idempotent, jamais effectuer une extraction coûteuse sur le chemin de
réponse. La projection Memory des profils d’agent est son consommateur actif principal.

Pour une Task Messenger humaine, les candidats non conversationnels forment une capsule de
continuité strictement liée au contact canonique : Tasks racines récentes, ressources actives de
leurs Working Sets et mémoires scellées au contact. Le Topic, attribué plus tard par Dream, n'est
jamais un filtre de cette capsule. Le compositeur déduplique, classe et borne les extraits, fusionne
les ressources proposées plusieurs fois sous la même URI canonique, puis fige le manifeste sur la
Task racine avant dispatch. Tous les enfants et retries reçoivent les mêmes références ; le Working
Set courant reste dynamique. Une identité non prouvée n'autorise aucun repli vers l'historique
collectif de la room. La vue Task rend le manifeste et sa provenance inspectables sous « Contexte
fourni ».

Exception explicite : lorsqu'une nouvelle Task de conversation a déjà reçu un objectif autonome
construit par l'appel d'admission, cette capsule et l'historique source ne sont pas reconstruits.
Les providers conservent seulement le contexte vivant de la Task, notamment son Working Set, et
les métadonnées serveur du salon et de l'interlocuteur.

`app.messenger.session` projette la session récente depuis le journal canonique. Pour une Task
humaine identifiée, la lecture suit le contact exact à travers les rooms et connexions ; la room
continue de borner le round conversationnel et son routage. Dès qu'une ligne canonique existe, les
historiques locaux des runtimes ne sont plus fusionnés :
ils ne sont que des replis. Le harnais interne remet ce snapshot sous la forme de l'historique natif
Pydantic AI. Hermès reçoit la même conversation canonique, son cache de session restant
non-autoritatif. Les messages de ce snapshot ne sont jamais proposés une seconde fois à la capsule
de continuité. Dans le prompt conversationnel, le rappel durable et la continuité opérationnelle
ou documentaire possèdent respectivement les sections `Long-term memory` et `Continuity context`.
Ces échanges ordinaires ne deviennent pas des souvenirs durables à chaque tour ;
leur promotion explicite reste disponible par les tools mémoire. L'extraction autonome est
effectuée hors du chemin terminal par `app.dream`, une Task historique à la fois.

Une session peut être demandée avec l'UUID canonique de `MessengerRoom` ou son identifiant externe.
La résolution est toujours bornée à la connexion, puis la requête accepte les deux colonnes
canoniques correspondantes. Un UUID local ne doit donc jamais être comparé uniquement au champ
`Message.room_id` externe, sous peine de perdre silencieusement l'historique lors d'une relance.

Le binding Hermès ne réutilise pas la room comme identifiant de transcript. Une clé condensée de
l'adresse complète reste stable dans `X-Hermes-Session-Key`, tandis qu'un `session_id` opaque suit
la lignée de compaction. Le checkpoint conserve à la fois l'origine du run et son tip effectif. Les
bindings historiques sont dédupliqués par agent pendant l'upgrade, puis un scope `room:*` ne peut
être revendiqué que par une seule connexion concrète. La rotation finale compare toujours le
pointeur d'origine du checkpoint : une tâche reprise tardivement ne peut pas faire reculer une
conversation qu'un run plus récent a déjà avancée.

Les appels vocaux temps réel suivent une lignée distincte des Tasks. `app.voice` persiste la
session et chaque tour ; la façade agentique reçoit un `AgentRunRequest(task_id=None)` corrélé par
`run_id` et `voice_turn_id`. Un barge-in termine le tour en `INTERRUPTED` et reporte son objectif
effectif dans le tour suivant. Le nouveau transcript complète donc la demande interrompue au lieu
de la remplacer, et aucune erreur de Task n'est créée pour une interruption normale de dialogue.

Avant de déléguer un nouveau travail substantiel, les contrôleurs texte et voix lisent les Tasks
liées encore actives ou à venir, les pauses humaines âgées d'au plus 24 heures et au plus les
deux Tasks terminales achevées depuis moins d'une heure. Leur projection contient la date locale
de création et `state_since`, fondé sur la dernière mise à jour avec repli sur la création, ainsi
qu'un objectif borné à 250 caractères, la
révision, l'amendabilité et l'état opérationnel. Le
modèle choisit `CREATE_NEW`, `AMEND_CURRENT` ou `AMEND_QUEUED`, ou pose une question si la relation
entre livrables est ambiguë. Le service Task reste l’autorité : il vérifie le scope et la révision,
refuse notamment les plans matérialisés et inscrit chaque amendement accepté dans
`task_amendments`. Les attentes de collègue ou de Process sont projetées comme `WAITING` avec leur
question et leur échéance ; une pause humaine reste `PAUSED`.
Un amendement conserve strictement le même artefact ou la même cible principale et des critères de
réussite substantiellement identiques. Une cible, un dépôt, une ressource, un livrable ou un
résultat vérifiable séparément impose `CREATE_NEW`, même lorsqu'il prolonge le même incident. Le
round expose les `TaskAmendment` qu'il a produits. La reprise d'une Task amendée conserve le journal
anti-rejeu des effets, mais invalide l'ancien historique modèle ; l'empreinte de l'objectif empêche
un checkpoint ou un résultat terminal obsolète d'écraser le nouveau run. Le scheduler clôt cet
ancien attempt comme annulé, sans retry ni erreur sur la Task amendée.

Toute nouvelle racine issue d'une conversation passe ensuite par un appel structuré dédié avec le
modèle `standard` de l'agent. Il produit le libellé et un contexte d'exécution autonome depuis le
tour admis, l'historique canonique, Memory, la continuité, les travaux liés et leurs références. Les
instructions de cette construction viennent du Param Markdown administrable
`ai.task-objective-system-prompt` et suivent le défaut livré lorsqu'aucune personnalisation n'est
enregistrée. Le serveur compose ensuite l'objectif avec deux sections : la demande source citée
sans réécriture et le contexte complémentaire généré. Les messages sources du tour admis et leurs
pièces jointes sont conservés avant le budget conversationnel et les annotations d'affichage ;
le HTML éventuel du message est échappé comme texte. Pour la voix, la demande admise sert de source.
`Task.data._original_demand` conserve cette source seule. Le contexte résout les références aux
échanges antérieurs, conserve les contraintes encore applicables et précise le périmètre de la
Task si le message demande plusieurs résultats indépendants. Les
valeurs envoyées à `conversation_task_submit` restent des indices et ne peuvent effacer une
contrainte source. Le backend conserve seul la connexion, le salon, l'interlocuteur, le Topic, le
contact et les choix `@exec`, `@plan`, `@standard`, `@high`, `@effort` ou `@approve`. Dans le Chat
natif, `conversation_task_submit` n'expose aucun choix d'effort : le dispatcher de Task décide
entre `standard` et `high`. Les directives explicites contournent ce choix conversationnel et
restent persistées comme contraintes de création, notamment `@high`. `@plan` implique la création
d'une Task planifiée et `@effort` implique la création d'une Task avec une surcharge de
raisonnement ; `@task` seul conserve le réglage du profil. Les tags
`@task` et `@effort` sont retirés du texte visible et leur intention
est transportée par les métadonnées serveur. Le parseur conserve `@briefing` pour compatibilité,
mais la politique courante refuse son admission. Il refuse les
URI inventées, contrôle l'idempotence avant cet appel et revérifie la fraîcheur du round avant de
persister directement la `Task`; aucun objet d'objectif intermédiaire n'existe.
Cette Task est ensuite marquée comme portant un objectif autonome. Le dispatcher lit ce `label` et
cet `objective`, tandis que la session Messenger, Memory et la continuité utilisées par l'appel
d'admission sont purgées des prompts aval. Les champs serveur de salon et d'interlocuteur restent
dans `Task.data` et le contexte de messagerie ; les futurs apports du planner, du briefing, du
Working Set et du harnais restent indépendants.

Pour une interaction numérotée, les réponses exactes restent traitées sans modèle. Un texte qui ne
correspond à aucune option est admis comme round conversationnel avec les seules interactions en
attente de sa portée Messenger. Le LLM conversationnel peut les résoudre par
`conversation_choice_resolve`, mais uniquement vers une option persistée. Une intention ambiguë
provoque une question ; une instruction du type « ne fais pas cela, fais plutôt ceci » peut refuser
l'approbation courante puis amender la Task par le chemin durable ci-dessus.

Pour un round textuel humain, le dispatcher retourne `EXEC standard` sans charger de modèle ni
effectuer d'inférence, sur tous les canaux textuels. L'exécuteur décide d'utiliser ses outils ou
d'admettre un travail durable selon la politique d'action. Le contrôleur restitue une réponse
réussie sans juger sa formulation, sa répétition ou l'absence d'appel d'outil. Seule une erreur
d'exécution peut déclencher la reprise bornée du scheduler, sous ses conditions de sécurité des effets.
L'admission persiste la Task avant son accusé de succès. Cette Task conserve le driver de l'agent,
notamment Hermès, alors que le round court reste exécuté par le contrôleur interne. Les libellés
techniques de conversation sont ignorés comme sujets de rappel mémoire et les candidats récents
injectés sont bornés. Pour les pairs IA, le dispatcher conserve le choix `EXEC`/`END` et applique
son fallback déterministe sans retenter une sortie structurée invalide.

Le Param `ai.conversation-action-policy` possède seul l'arbitrage entre réponse directe, petit effet
conversationnel gouverné, Process affecté et Task. Une recherche, lecture, capture, correction ou
suppression Memory explicitement disponible peut ainsi être exécutée dans le round sans créer une
Task. Un Process compatible garde la priorité absolue ; la Task prend en charge les ressources
durables, livraisons, tiers, systèmes externes sans Process et travaux substantiels. Le catalogue
conversationnel des Processes reste une projection de données et ne répète plus cette politique.

Le prompt commun rend une seule frontière de non-fiabilité avant les historiques, souvenirs,
ressources et résultats récupérés. Les prompts conversation et voix déclarent l'identité comme une
parole directe à la première personne, puis rappellent brièvement cette incarnation en fin d'arbre,
avant le suffixe configurable. Ce rappel intentionnel évite les préfixes de personnage et la
narration du rôle sans modifier l'inventaire textuel des outils.
Pour les Tasks, le même constructeur rend nom, genre, poste, personnalité et fiche de poste dans
le socle système commun. Le profil gouverne aussi la rédaction, la mise en forme et l’auteur des
livrables, y compris une préférence explicite de signature lorsqu’elle est pertinente. Internal,
Hermès et les harnais réseau reçoivent ce profil canonique ; une signature modifie le contenu et
ne constitue jamais à elle seule une instruction d’envoi ou de livraison.

Les messages natifs de conversation utilisent une enveloppe compacte
`[horodatage ISO local | auteur]` commune au harnais interne et à Hermès. Les rôles restent natifs,
les pièces jointes restent liées à leur message et les métadonnées canoniques complètes restent
internes au routage et à la trace. Le prompt système rend langue, canal, room, expéditeur courant,
localisation et continuité une seule fois dans `Turn context` ou `Call context` ; le parseur de
sortie continue de retirer les anciennes enveloppes pour assurer la compatibilité des sessions.

Les commandes d'arrêt d'une Task active et de renvoi d'une pièce jointe existante contournent le
modèle : le contrôleur utilise les liens de room et UUID Messenger canoniques, exécute l'effet
idempotent, puis répond depuis son reçu. L'admission refuse de convertir un simple renvoi de
version existante en nouvelle Task de génération. Une erreur d'inférence du dispatcher pour un pair
IA produit `END`; les autres erreurs d'exécution remontent au scheduler. Les narrations précédant un appel
d'outil restent uniquement dans la trace d'audit.

`app.memory` sépare l'identité et la gouvernance du stockage de contenu. PostgreSQL possède les
items avec leur propriétaire direct, grants, révisions, sources, liens, usages, acquisitions
idempotentes et jobs. Il n'existe pas d'espace mémoire intermédiaire. `ResourceStorage` manipule
seulement des octets par identifiant opaque; le provider `native` écrit atomiquement dans le
répertoire fixe `/data/memory`. La recherche applique propriétaire, accès directs, visibilité et validité
dans SQL avant le classement. Le brief automatique classe les mémoires `core` avec les autres
types au lieu de leur réserver une place inconditionnelle. Le classement exige d'abord une preuve
lexicale directe et informative — pas un simple mot conversationnel — ou une proximité sémantique
suffisante, puis combine appartenance thématique,
liens confirmés, provenance, fraîcheur et centralité locale avant d'écarter les quasi-doublons.
Le résultat peut donc contenir de zéro à huit items par défaut, sans appel de LLM. La projection Memory de la fiche Agent est exclue de
ce brief automatique : son identité et sa personnalité proviennent déjà du profil canonique du
prompt système. Elle reste consultable par une recherche Memory explicite.

Le rappel agentique borné utilise toujours l'hybride. Toute recherche `file_search("memory://", ...)`
et `POST /memory/search` fusionnent les candidats FTS avec une recherche cosinus exacte dans la
projection pgvector de `app.memory`. Aucun contrat HTTP, Python ou MCP ne permet de choisir un
mode lexical : il reste uniquement le repli automatique signalé en cas d'indisponibilité. La façade
Python `search_memory(texte, agent_id=..., ...)` renvoie directement une liste d'items classés,
sans score public. La taille du vivier, la longueur sémantique, les poids et la diversité viennent
exclusivement des Params globaux de la section Mémoire. Les chunks sont versionnés par empreinte, modèle et dimension, produits par le worker
après le commit puis remplacés atomiquement. Les ACL et dates restent des filtres SQL antérieurs au
classement. Si l’usage Vectoriel du profil courant, l'index ou le provider n'est pas disponible, le contrat signale
la dégradation et renvoie le résultat lexical. Le brief automatique emprunte le même rappel
hybride ; `/memory/browse` conserve la consultation lexicale paginée. `/memory/recall` est un alias
HTTP déprécié de la recherche classée sans score.

Avec un Topic courant, le rappel fusionne séparément FTS et pgvector dans le dossier, puis FTS et
pgvector dans la portée globale autorisée. L'appartenance au dossier constitue un signal pondéré de
premier rang, configurable par `MEMORY_RECALL_TOPIC_WEIGHT`, sans supprimer la voie globale. Une
proposition positive d'appartenance peut aussi départager des candidats déjà pertinents avec la
décote `MEMORY_RECALL_SUGGESTED_LINK_WEIGHT`, sans devenir un lien canonique. Sans
Topic courant, le moteur présélectionne par le même vecteur le Topic public le plus proche qui
contient au moins une mémoire accessible, puis applique ce prior avec une force proportionnelle à
la similarité. Un contact exact exclut de la voie globale les souvenirs conversationnels d'autres
interlocuteurs. Les projections publiques de Topics restent indexables pour présélectionner les
dossiers mais sont exclues du rappel factuel. Dream
produit aussi des liens `suggested=true` de rattachement, anomalie, fusion ou scission depuis ces
vecteurs ; aucun de ces signaux ne modifie seul un `topic_contains` canonique.

Les documents de travail HTML sont des `MemoryItem` de `node_kind=document` et de type
`working`. Ils sont le support canonique des contenus rédigés et partagés par les agents, même
pour une seule Task. Memory et File Sharing sont des services système obligatoires ; les ACL
des ressources et les restrictions de contexte restent applicables. Voir le [contrat documentaire](editorial-html.md).
Ils restent privés à la création, ne sont ni dédupliqués avec les souvenirs ordinaires, ni ciblés
par Dream, ni oubliés automatiquement pour inactivité. `file_create`, `file_edit`,
`file_read(document://...)` et `file_append(document://...)` maintiennent des révisions
atomiques sans exposer de protocole de patch complexe au modèle. `document_share` pose un grant direct
`read|edit|none` après résolution de l'humain, de l'agent ou de l'équipe cible ; seul le propriétaire administre ces grants et
peut oublier le document. `file_search` assure leur découverte et le brief n'en injecte que des
extraits bornés. Chaque révision conserve l'agent et, lorsqu'elle existe, la Task auteure.
Les pièces jointes sont exposées sous `document://<uuid>/attachments/` : `file_list` les énumère,
`file_read` et les outils spécialisés les consomment, tandis que `file_create`, `file_copy` et
`file_delete` exigent le droit d'écriture sur le document parent. Leur ajout ou suppression ne
crée pas de révision de contenu.

Chaque arbre de Task possède en parallèle un Working Set versionné dans les données de sa racine.
Il centralise les références actives — document principal, documents auxiliaires, ressources
provider, artefact final, destination et reçu de livraison — sans recopier leur contenu. Une
nouvelle ressource de même rôle conserve l'ancienne en état `superseded`. Le provider
`task_working_set` injecte ce registre borné dans chaque étape et dans les reprises
conversationnelles liées. En conversation directe et en audio temps réel, où aucun Working Set
courant n'existe, les providers injectent les documents récemment manipulés par les Tasks et les
traces d'outils des rounds terminés du même agent et du même contact sous leur URI `document://`,
sans élargir la sélection à la room ni extraire une URI depuis du texte libre. Le premier document
créé dans une Task prend le rôle canonique `primary_working_document`; les suivants reçoivent un
rôle de référence distinct.

Les références fichier de ce Working Set et des outils suivent le contrat URI de
`app.file_share` : `console://path`,
`<code-tool>://room-provider/attachment-uuid`, `memory://uuid`, `document://uuid`,
`document://uuid/attachments/attachment-uuid`,
`galaris://task/uuid`, `galaris://process/workflow-id`,
`galaris://skill/skill-code/SKILL.md`, une URL HTTPS publique ou
`<code-tool>://locator`. Le code d'un Tool
portant file-share ou Messenger est son schéma et doit être en minuscules ;
les protocoles (`http`, `https`, `file`, `ssh`, etc.) et les schémas natifs sont réservés.
Messenger et file-share sont des capabilities du même Tool : elles n'ajoutent jamais un schéma
générique. Ainsi une pièce jointe Talk utilise `nextcloud://<room-token>/<file-uuid>` et une pièce
jointe Telegram `telegram://<chat-id>/<file-uuid>`.
Le Tool intégré `file_sharing`, implémenté par `app.file_share`, expose `file_schemes` et toutes les
opérations `file_*` sur les deux runtimes. Cette propriété ne dépend pas du schéma manipulé :
`galaris://` est un provider de projections métier, tandis que le Tool `galaris` conserve ses
actions métier. `file_create` crée et renvoie une URI complète, `file_write` remplace une ressource
existante, et `file_read` renvoie du texte UTF-8 paginé ou un petit binaire en base64 ;
`file_copy` est l'unique primitive de copie persistante streamée. Les outils spécialisés qui
consomment des octets (`image_read`, pièces jointes de `image_generate`, `audio_transcribe`, envoi
Messenger) acceptent ces mêmes URI directement et utilisent `materialize_resource` pour créer un
temporaire borné et automatiquement nettoyé. Ils ne demandent jamais à l'agent une copie locale
préparatoire. Une destination collection conserve le nom renvoyé par les métadonnées source, y
compris lorsque son locator est opaque. `galaris://` projette en lecture seule les Tasks,
rounds de conversation, Goals, cycles de Goal et Processes affectés, avec les ACL de leur domaine.
Sous `galaris://skill/`, une connexion `skill_management` active permet en plus de lire et
modifier les fichiers des skills utilisateurs ; les définitions système restent en lecture seule.
Le Tool intégré `console` déclare son flag `file_share_config` avec le service natif `console` ;
`console://` désigne directement le home SSH et n'est pas dupliqué comme provider externe. Ainsi,
`console://mon_fichier` désigne exactement `~/mon_fichier` et aucune couche ne préfixe son URI par
un segment virtuel `main/`. Lorsqu'elle est disponible, la console est l'unique espace local
annoncé à l'agent et la destination automatique des outils qui autorisent un défaut. Sans console,
aucun fallback local n'existe : `file_list` exige une URI provider, les outils producteurs exigent
une destination writable et les pièces jointes gardent le schéma exact de leur Tool d'origine.
Les chemins relatifs et les anciens schémas locaux implicites sont refusés.

Toutes les fonctions MCP natives traversent le même rendu d'erreur. Un échec expose au runtime une
cause catégorisée, le type technique, une action suivante et une courte référence corrélable ; une
erreur fichier adapte notamment son conseil à `file_create`, aux lectures et aux remplacements. Le
journal serveur reprend cette référence avec le Tool, la catégorie, le type et les seuls
emplacements de code de la pile. Il n'enregistre ni arguments, ni contenu, ni texte arbitraire du
provider. Seules les erreurs métier explicitement déclarées sûres peuvent transmettre leur détail
au modèle ; les autres restent expurgées tout en conservant un diagnostic actionnable.

Les entrées fichier de `process_start` et `process_admin_start` utilisent elles aussi la clé `uri`
et la façade `app.file_share`. Le snapshot du run conserve la référence source et le endpoint
machine matérialise à la demande une copie temporaire bornée pour l'engine. Un workflow peut donc
consommer directement une ressource console, Nextcloud, Mail, Messenger ou HTTPS sans
étape de copie préparatoire.

Pour éviter de transformer un objectif de Goal très long en requête FTS impossible, le brief
utilise une graine bornée : titre du Goal, sinon libellé de Task sans suffixe de cycle, sinon court
extrait de l'objectif. Une politique système commune demande au modèle d'évaluer la pertinence du
rappel pour les travaux `high`, récurrents ou longs, mais de n'appeler `file_search(memory://)` que si le
brief est insuffisant et qu'un contexte durable peut changer le travail. Les tools métier
autoritaires restent obligatoires pour l'état courant.

La trace distingue le brief automatique des appels MCP. Les usages `context`, `search` et `read`
sont séparés, et le résultat d'exécution conserve la requête bornée, les nombres récupéré et
réellement injecté, la troncature et les UUID du brief, jamais son texte. Logfire et `/memory/metrics` exposent seulement
des compteurs et histogrammes à labels bornés; `/memory/retention/preview` estime sans mutation
l'effet d'une durée globale avant son activation.

Les acquisitions admissibles sont appliquées immédiatement et les refus sont automatiques. Leur
journal interne sert à la provenance, à l'idempotence et à la reprise, jamais à constituer une file
de validation humaine. L'interface permet l'audit, la correction et l'oubli.

L'extraction automatique Dream couvre les Tasks réussies, les rounds conversationnels textuels et
les tours Voice transcrits. Elle ne réclame une source que lorsque son `topic_id` est non nul ; les
sources conversationnelles exigent aussi leur contact exact. Les rounds texte et Voice fournissent
au plus cinq messages antérieurs, séparés du tour courant. Le serveur rappelle d'abord des
souvenirs ordinaires autorisés. Seuls les candidats présentant une similarité sémantique forte ou
un recouvrement lexical substantiel peuvent encore être proposés à `LINK`; une proximité de Topic
ne suffit pas. La sortie choisit `CREATE`, `LINK` ou une liste vide équivalente à `IGNORE`.
Elle doit être un objet JSON complet : après une seconde tentative invalide, le reçu passe en
reprise ou en erreur au lieu de réparer silencieusement un fragment. `LINK` ajoute seulement la
nouvelle provenance à un candidat et ne réécrit pas son contenu. Toute cible hors rappel ou non
possédée par l'agent courant est refusée. Les créations et rattachements sont comptés séparément
dans Dream. Une création doit déclarer une
utilité future élevée et un motif de rétention fermé ; recherches, faits publics, résumés de
livrable et détails ponctuels sont exclus. Le prompt est administrable sous
`ai.memory-extraction-system-prompt`. `MEMORY_CAPTURE_ENABLED` contrôle ces trois extracteurs sans
désactiver les autres travaux Dream.

Dream ne réclame qu'une opération par passage et alterne équitablement entre ses mécanismes.
Les quatre mécanismes `memory.attachment_text`, `memory.attachment_document`,
`memory.attachment_image` et `memory.attachment_video` enrichissent les items mémoire vides
des PJ actives, anciennes comme nouvelles. Les paramètres
`DREAM_ATTACHMENT_TEXT_ENABLED`, `DREAM_ATTACHMENT_DOCUMENT_ENABLED`,
`DREAM_ATTACHMENT_IMAGE_ENABLED` et `DREAM_ATTACHMENT_VIDEO_ENABLED` sont tous faux par défaut
et exposés par quatre cases dans les préférences Dream, avec un avertissement sur les coûts
et une recommandation de modèles locaux. Ils partagent les phases de repos et la rotation Dream.
Les services Image et Audio sont injectés par la racine de composition via les ports publics de
Dream. Le décodage audio s'exécute dans un processus borné, arrêté et attendu en cas d'annulation,
avant le nettoyage des temporaires.
Le texte UTF-8/UTF-16, les PDF textuels et les formats DOCX/XLSX/PPTX/ODT/ODS/ODP sont extraits
dans un processus borné puis résumés par le modèle Dream du propriétaire (profil courant pour
un document humain). Les documents sans texte extractible utilisent le modèle documentaire
natif ; les images le modèle de vision ; les vidéos la transcription de leur audio puis le
résumé Dream. Un format refusé par le fournisseur ou une vidéo sans audio reste sans contenu,
avec une erreur et les reprises bornées habituelles. La conversion limite explicitement les
documents à 32 Mio, 500 pages PDF et deux millions de caractères ; l'entrée documentaire native
est limitée à 16 Mio et la vidéo à 1 Go. Aucun dépassement n'est présenté comme un résumé complet.
L'écriture revalide le document, son propriétaire, la PJ active et la révision vide, conserve
une révision HTML et déclenche la réindexation. Un texte ajouté entre-temps n'est jamais écrasé.
Un résultat checkpointé reprend sans nouvelle inférence ; une désactivation empêche son application
jusqu'à réactivation. Les droits de partage et le document parent ne sont pas modifiés.

La rotation conserve toutefois une dépendance stricte entre les deux classements : lorsqu'ils se
présentent dans le même passage, `topic.classify_message` est toujours tenté avant
`topic.classify_task`. Une Task issue d'une conversation ne peut ainsi devancer le Topic de sa
source ; les autres mécanismes conservent leur ordre relatif dans la rotation.
Une extraction Task reste inéligible tant que son reçu de classification Topic est `running` ou
`retry`; les compteurs ne comptent donc pas simultanément les deux étapes du même sujet.
`DREAM_POLL_SECONDS` est une pause de fin à début : elle commence lorsque l'opération courante est
entièrement terminée, puis doit s'écouler avant la suivante. Elle ne constitue pas une fenêtre
périodique dont un appel LLM long consommerait une partie.

`skill.learn_task_outcome` complète l’extraction factuelle avec un apprentissage séparé fondé sur
des preuves observables : tentatives, résultats d’outils, enfants, verdict Goal, correction humaine
et usages Memory. Un filtre sans LLM élimine les signaux faibles, puis la sortie structurée cite ses
preuves avant de créer, renforcer, réviser ou affaiblir une `LearnedSkill`. L’empreinte du matériel
rend le rescan idempotent et autorise une correction tardive distincte. Dream parcourt aussi les
Tasks terminales historiques, de la plus ancienne à la plus récente et une seule par passage ; les
reçus empêchent de compter deux fois le même matériel. Ce mécanisme ne crée aucun `MemoryItem`.

`DREAM_SKILL_LEARNING_MODE` vaut `off`, `observe` ou `learn` et reste `off` par défaut. `observe`
conserve uniquement les diagnostics Dream et `learn` applique la décision checkpointée. Une skill
est d’abord conservée comme candidate non injectable. Elle est promue et injectée en plus des
skills affectées lorsqu'au moins `DREAM_SKILL_MIN_EVIDENCE` Tasks distinctes ont confirmé la même
procédure et qu'elle atteint `DREAM_SKILL_ACTIVATION_SCORE`; le seuil de répétition vaut 3 par
défaut et `DREAM_SKILL_MAX_ACTIVE` borne le nombre de procédures actives. Ces réglages sont
administrés dans `params`, pas dans `.env`.

Lorsqu'un tool Memory écrit pendant une Task, il associe immédiatement l'item créé ou fusionné à
la provenance `task:<uuid>`. Le réconciliateur d'`app.memory` en déduit ensuite les arêtes Topic,
contact, Contact–Topic, Goal et Process ainsi que les scopes conversationnels autoritatifs. Il est
idempotent, n'appelle aucun modèle, traite les nœuds touchés après chaque succès Dream et effectue
un sweep global planifié uniquement à charge nulle. Les déclenchements après Dream et planifié se
règlent avec `MEMORY_LINK_RECONCILIATION_TRIGGER_MODE`; l'intervalle global utilise
`MEMORY_LINK_RECONCILIATION_INTERVAL_HOURS`. La page des préférences Dream expose l'état et le
lancement manuel immédiat, exécuté dans la requête sans attendre la charge nulle. Le réconciliateur
ne possède ni reçu ni jauge Dream. La commande
`make rebuild-memory-links` permet le même traitement global ; `ARGS='--item-id <uuid>'` le borne à
un nœud.

Dans le graphe, l'agent sélectionné reste implicite puisqu'il borne déjà les données accessibles.
Les Topics publics sont en plus limités à ceux qui contiennent une mémoire possédée ou directement
partagée avec cet agent ; un dossier d'un autre agent n'apparaît pas par sa seule visibilité.
Les Topics, contacts et documents ont des formes distinctes ; leurs relations structurelles sont
renforcées et légendées, tandis que les suggestions restent fines et discontinues.

`app.memory.source_projection` adapte les données canoniques `Agent`, `Goal` et `GoalCycle` en
Markdown privé. Les sources conservent leur `memory_item_id`; l'item conserve en retour une identité
de source unique. `app.memory.messenger_contact` projette séparément l'identité minimale des
expéditeurs humains observés en mémoire `social`, avec une clé hashée fondée sur l'agent
propriétaire, le code du bridge et l'identifiant natif exact. Connexion, room et contenu de message
en sont exclus. `memory_contact_identities` rattache ensuite plusieurs adresses Messenger ou une
identité `USER` prouvée au même item canonique. `app.contact` fournit l'administration et la fusion
transactionnelle ; cette opération repointe toutes les portées mémoire et lignées conversationnelles
avant d'oublier le doublon. Ces items `source_managed` ne passent jamais par les mutations publiques, même avec
les droits d'administration. Les observers Agent/Goal ne font qu'inscrire un job durable après le
commit métier. Le worker recharge toujours la dernière version de la source, ce qui rend les jobs
retardés ou réordonnés sans danger. Il conserve une révision seulement lorsque la projection
change, relie un cycle à son Goal par `cycle_of` et oublie les ressources quand la source est
supprimée. Les cycles sont chargés par une requête dédiée, triée par séquence décroissante et
limitée aux 100 plus récents. Cette fenêtre est aussi une rétention de projection : les items plus
anciens sont oubliés par lots bornés et leur pointeur source est remis à `null`, sans supprimer le
cycle canonique. Messenger observe les contacts avant les interactions avec un repli fail-open ;
son journal permet un rejeu idempotent.

La description et le suivi Markdown canoniques d'un Goal ne vivent plus dans ces projections :
chaque Goal référence deux documents Memory privés de travail. Leur contenu est modifiable depuis
les IHM Goal et Documents, mais leur propriétaire, leur titre et leur chemin restent exclusivement
pilotés par le Goal. Le dossier porte le titre expurgé du Goal et les documents portent les
titres `<titre du Goal> — Description` et `<titre du Goal> — Suivi`, actualisés lors du renommage
du Goal. La réconciliation DbAdmin remet aussi les titres existants à ce format.
Ils portent aussi une protection de suppression
indépendante de `source_managed`.
Une édition directe du document révise le Goal et réenfile sa projection déterministe. Le port
`app.goal.document_store` maintient la frontière métier ; son adapter concret est fourni par
`app.memory` au bootstrap.

Le job durable `goal_folder_reconcile` range automatiquement les documents du Goal et les
livrables identifiés par la provenance de ses Tasks dans les dossiers personnels
`Objectifs / <libellé du Goal>`. Il accepte `user_id`, `goal_id`, les deux ou aucun filtre.
Il respecte les accès actuels et tout classement préexistant chez l'utilisateur ; il ne crée
pas de dossier vide. Les événements Goal, document, utilisateur et accès mettent le job en
attente ; DbAdmin enfile le rattrapage global. Aucun parcours ne se fait à l'ouverture de la page.
Un dossier supprimé peut être recréé au prochain passage. Le lancement administratif passe par
`POST /api/memory/goal-folders/reconcile` (`MEMORY_ADMIN`, corps `{}` pour tous, réponse `202`).
Voir la [décision 0107](../../../project/decisions/0107-personal-goal-folders.md).

Dream examine aussi les tours Voice terminés qui possèdent un objectif textuel, puis associe les
nouveaux souvenirs au nœud structurel de leur conversation. Les tours realtime sans transcript
restent à mémorisation explicite. Enfin, `memory.project_process` projette sans LLM les
définitions affectées et les sorties réussies assainies : jamais les entrées ni snapshots bruts,
12 000 caractères maximum et 20 résultats par agent et processus.

Le backfill et les changements de fournisseur utilisent le même chemin que le runtime :

```bash
make rebuild-source-memory
make rebuild-source-memory ARGS='--all'
make rebuild-source-memory ARGS='--recreate --provider native'
make rebuild-messenger-contacts
make rebuild-memory-index
make rebuild-memory-index ARGS='--all'
```

Les trois modes `rebuild-source-memory` traitent respectivement les pointeurs manquants, toutes les
projections sans changer les UUID, puis une recréation avec réécriture des UUID sources. La
commande Messenger rejoue les derniers expéditeurs humains du journal sans dépendre du registre
des bridges. Les deux commandes d'index réparent ou recalculent l'index sémantique pour le modèle
vectoriel sélectionné. La synchronisation du dataset réconcilie automatiquement les projections source, attribue
aux projections publiques de Topic leur clé propriétaire `topic_id`, puis réconcilie les contacts
Messenger et l'index. Les Tasks de Goal sont exclues de la capture terminale générique,
puisque leur résultat appartient à la projection `GoalCycle`.

Le plugin MemoryProvider projeté dans Hermès récupère exactement ce brief déjà calculé pour la Task
active. Il n'expose pas une seconde série de tools : les actions complètes passent par les MCP
`memory_*`, et les écritures natives Hermès deviennent des acquisitions immédiates. Voir le
[flux mémoire](../architecture/flows/memory.md) et
[l'ADR 0010](../../../project/decisions/0010-governed-agent-memory.md).

Le manager sélectionne `memory.provider: galaris`, maintient l'activation explicite
`plugins.enabled: [galaris-memory]` et projette le même provider sous les layouts
`plugins/memory/galaris` et `plugins/galaris`. Le premier est le layout spécialisé actuel ; le
second conserve la compatibilité avec Hermès 0.18, qui découvrait les providers utilisateur à la
racine de `plugins/`. Par défaut, il fixe aussi `memory_enabled=false` et
`user_profile_enabled=false`, puis retire le toolset natif `memory` : `MEMORY.md` et `USER.md` ne
sont donc ni injectés, ni modifiés. Cette couche précède `hermes.default.config` puis
`Agent.hermes_config` ; une valeur explicite globale ou propre à l'agent réactive ainsi la mémoire
fichier, la configuration de l'agent restant prioritaire. Une synchronisation du profil redémarre
Hermès après cette projection.

### Flux d’exécution

```text
Task SQLAlchemy
    │  app.task.agent_adapter
    ▼
AgentTask + app.agent facade
    │
    ├── dispatcher ──► EXEC / PLAN
    ├── politique du driver ──► briefing éventuel
    ├── model_resolver ──► modèle figé pour le run
    ├── DriverSpec ──► stratégie directe figée
    ▼
AgentRunRequest immuable
    │
    ├── InternalHarness ──► Pydantic AI
    ├── HermesAgentDriver  ──► standard : /v1/runs
    │                         high : /v1/runs + modèle high
    └── Codex Harness ──────► App Server ──► gateway Responses Galaris
                              standard : Agent Executor
                              high : Agent Executor high
    ▼
AgentEvent* + un unique ExecutionResult terminal
    │
    ▼
app.agent applique le résultat, app.task le persiste et reprend le workflow
```

La résolution du modèle et du `reasoning_effort` associé à son palier a lieu une fois avant
l’entrée dans le driver. Ces deux valeurs restent indépendantes de l’effort d’exécution de la
Task. Les gateways LLM Hermès et Codex utilisent ce contexte de trace figé ; ils ne doivent pas
recalculer un modèle ou un effort de raisonnement différent au milieu du run. Codex emploie le nom
fournisseur pour les capacités de l'App Server et transmet en parallèle le code stable Galaris au
gateway Responses. La sélection interne de l’adaptateur Kanban appartient exclusivement au driver
Hermès et reste désactivée.

L’échelle canonique est `none`, `low`, `medium`, `high`, `xhigh`, `max`. Une valeur absente signifie
« automatique » et laisse le choix au harness ou au fournisseur. L’ancienne valeur `minimal` est
acceptée uniquement en lecture de données historiques, normalisée en `low`, puis n’est plus émise.
Les bridges et harnesses gérés traduisent cette échelle lorsqu’un runtime emploie des niveaux
différents.

### Contrat de streaming

Un driver émet zéro ou plusieurs événements `message`, puis exactement un événement
`result`. La façade rejette :

- un stream sans résultat terminal ;
- plusieurs résultats terminaux ;
- un événement après le résultat.

Le texte du `result` est autoritaire. Un runtime agentique peut avoir diffusé du texte
provisoire avant un appel d'outil ; son adapter conserve alors ce progrès comme bloc sémantique
`thinking` et remplace le texte terminal par la réponse finale exacte. Pour les Harness réseau,
`galaris.agent-result/v1.result` porte cette réponse autoritaire tandis que les chunks Chat
Completions restent des événements live éphémères. Les fins d'outils et raisonnements publics
utilisent `galaris.agent-message/v1` et ne sont jamais reconstruits depuis le texte final.
Le frontend conserve ces événements live exclusivement comme une liste d'`AIMessage` ; il ne
fabrique pas d'`ExecutionResult` partiel. À la terminaison, seul l'`ExecutionResult` persistant de
la Task ou du round devient la source autoritaire.
La projection live est append-only : un fragment déjà diffusé n'est ni remplacé ni supprimé. Les
révisions divergentes sont conservées dans un nouveau bloc sémantique, notamment pour les
réflexions Codex segmentées par `itemId` et `summaryIndex`. Le `stream_id` optionnel d'un
`AIMessage` rattache les fragments live à ce bloc : le frontend les concatène immédiatement et le
client Harness compacte la trace terminale, sans persister un événement de timeline par delta.

La façade observe les blocs `thinking` et le texte généré de tous les drivers. Si un même motif
raisonné se répète plus de 30 fois consécutives sans activité d'outil, elle ferme immédiatement le
stream et fait échouer le run avec une erreur de dégénérescence explicite, sans retry automatique
de la Task. Le contenu du motif n'est pas recopié dans l'erreur ni dans les journaux du garde-fou.

Un driver déclaré sans streaming utilise automatiquement son résultat non streamé. La
capacité d’annulation est refusée tant que `supports_cancellation` n’est pas explicitement
activée. Les drivers interne et Hermès l’activent. L’interne annule la coroutine du run puis
nettoie console, MCP et sessions browser ; Hermès associe temporairement l’UUID Galaris au
`run_id` direct et appelle `/v1/runs/{id}/stop`. Une ancienne reprise Kanban conserve son
traitement historique : reclaim du worker puis archivage de la carte.

Le harnais interne checkpoint chaque effet MCP avant et après son exécution. Une reprise recharge
l’historique typé Pydantic AI et réutilise les résultats terminés. Un checkpoint arrêté entre les
deux écritures reste non reprenable automatiquement, car l’effet externe peut avoir réussi sans
que son résultat ait été persisté. La livraison Messenger de secours utilise le même journal et,
une fois confirmée, reprend directement sur son résultat terminal.

Après un résultat d'outil réellement réussi, une projection générique inscrit ses références dans
le Working Set. Les erreurs métier des documents, fichiers partagés et livraisons Messenger sont
des erreurs d'outil et non des chaînes ressemblant à un succès. Une production de fichier ne peut
terminer la Task racine sans artefact final ; une origine Messenger exige en plus un reçu. Les
sous-tâches n'émettent jamais automatiquement leur texte terminal dans la conversation, même si
elles peuvent utiliser explicitement un outil Messenger requis par leur étape.

Les outils du harnais interne explicitement déclarés `safe` peuvent s'exécuter en parallèle sous
une limite bornée ; les outils `exclusive` restent des barrières. Chaque appel natif ouvre sa
propre session SQLAlchemy courte. Le journal de checkpoint sérialise seulement ses écritures et
les persiste dans des transactions indépendantes qui rechargent la Task sous verrou. Une erreur et
son rollback ne peuvent donc contaminer ni un autre outil, ni la session du scheduler. Le driver
conserve cette session séquentielle pendant son initialisation, puis le harnais interne libère sa
transaction avant l'exécution du modèle. Chaque branche parallèle remplace explicitement le
contexte par sa propre session courte ; elle n'utilise jamais la session héritée du scheduler.
Trois échecs identiques ou trois succès identiques sans progression interrompent une boucle
d'outil ; la signature de création de document regroupe les brouillons de même titre et rôle même
si leur contenu généré varie. Un arrêt pour succès sans progression déclenche une unique passe de
finalisation bornée depuis l'historique acquis. Lorsqu'un scope sélectionne un outil d'écriture de
fichier ou de document, les outils de lecture et d'inspection nécessaires à sa vérification sont
inclus comme capacités compagnes.

### Politiques statiques

Les aides ne sont pas choisies par `app.task`. Elles sont définies en dur dans le descripteur
du driver :

```python
DriverPipelinePolicy(
    use_planner=True,
    use_briefing=False,
    briefing_efforts=frozenset(),
)
```

Matrice actuelle :

| Driver | Planner | Briefing | `standard` | `high` | Workspace |
|---|---:|---:|---|---|---|
| `internal` | oui | jamais (désactivé pour évaluation) | direct | direct | par agent |
| `hermes` | non | jamais | `/v1/runs` direct | `/v1/runs` direct, modèle `high` | partagé par le runtime |

Le dispatcher filtre les routes selon cette politique et annote sa décision avec le driver,
les routes autorisées et les notes de politique. Les transitions de workflow honorent
ensuite cette décision ; elles ne relancent pas une seconde décision cachée.

### Port de tâches

`app.agent` n’importe jamais `app.task`. Il dépend d’`AgentTaskPort`, enregistré par
`app.task.agent_adapter` au bootstrap. Le port expose seulement les opérations nécessaires :
charger, lister les candidats, créer, amender, lire l’état opérationnel, sauver, changer de phase,
suspendre, reprendre et coordonner les enfants.

SQLAlchemy représente les attributs par `Mapped[T]`, ce qui ne satisfait pas directement le
protocole mutable aux yeux de Pyright. La conversion statique est centralisée dans
`as_agent_task`; ne dispersez pas des `cast()` dans les domaines consommateurs.

### Ajouter un futur driver

Lorsqu’un autre driver sera implémenté :

1. créer son package concret, sans modifier `app.task` ;
2. implémenter `AgentDriver` avec `run`, `stream` et `cancel` ;
3. définir un `AgentDriverSpec` dans le registre : factory, politiques, capacités et
   configuration ;
4. adapter l’entrée `AgentRunRequest` et retourner exclusivement les contrats communs ;
5. ajouter les tests de conformité de stream, politiques, erreurs et disponibilité ;
6. pour un runtime externe optionnel, déclarer son paramètre d’activation dans le spec ; le
   harnais interne reste inconditionnellement disponible.

Un driver ne doit pas importer le modèle ORM `Task`. Une capacité optionnelle utilise un
protocole dédié, par exemple `DriverConfigurationProvider`, pas
un test `if driver == ...` dans la façade.

## 4. Dispatcher, planner et briefing

Le dispatcher de Task construit les couples route/effort exposés par le harnais sélectionné :
`EXEC standard`, `EXEC high`, `BRIEFING` avec un effort accepté et `PLAN high`. Les capacités
du provider précisent celles du driver réseau commun. Après application des contraintes, un
seul choix ne déclenche aucun LLM ; plusieurs choix autorisent une inférence limitée à cette
liste ; aucun choix produit une erreur explicite. Le résultat est toujours persisté. Sans modèle
dispatcher, le premier choix permis est retenu après ces contrôles. `END` reste interdit pour
les Tasks. La règle distingue difficulté et décomposabilité.
`EXEC high` n'est disponible que si le harnais déclare `uses_llm_calls=true` : ses appels
d'exécution passent par le routage de modèles Galaris et son journal `LLMCall`. Un runtime
externe qui utilise sa propre API ou son abonnement reste à EXEC standard ; sans planner ni
briefing, le dispatcher n'appelle donc aucun LLM. Les providers gérés, dont Claude Agent,
imposent actuellement la passerelle Galaris et conservent les deux efforts.
Une opération explicite, bornée, mécanique et simplement vérifiable reste en `EXEC standard`, même
si elle utilise plusieurs outils ou applique une action destructive déjà autorisée : le risque
détermine les garde-fous, pas le niveau d'effort.
Un site, visuel, rapport, document, changement de code ou autre livrable cohérent reste en
`EXEC high` lorsque recherche, production, raffinement, vérification et livraison concourent au
même résultat. `BRIEFING` est un choix distinct de `EXEC high` : il prépare une exécution sans
planifier plusieurs tâches. Il reste désactivé dans le harnais interne. `PLAN`
est réservé à plusieurs unités indépendamment exécutables dont les résultats durables nécessitent
une coordination ; en cas d’ambiguïté, `EXEC high` est préféré. Les échanges conversationnels ne
passent plus par une Task ; leur profil restreint distinct peut encore arbitrer EXEC/END pour éviter
une boucle IA→IA. Ce profil conversationnel impose toujours l’exécution directe `standard` et
désactive planner, briefing et effort `high`. Quand aucun LLM dispatcher n’est configuré, le
service produit une décision d’exécution directe, traçable et déterministe. Pour un humain, cette
décision ne consulte jamais le modèle dispatcher. Les directives explicites `@plan` et `@exec`
suivent le chemin d'admission déterministe sans inférence de routage. Le champ `requires_action`
est absent des contrats courants, y compris pour les Tasks. Sur les Tasks, une directive textuelle
n'est appliquée qu'après résolution des routes exposées par la politique du driver ; elle ne peut
jamais activer un planner absent. Un `forced_route` de création reste au contraire une contrainte
stricte et explicitement incompatible si le driver ne l'expose pas. `@briefing` reste reconnu
pour compatibilité mais est refusé tant qu’aucun driver ne l’expose.

Chaque agent référence un profil LLM personnel ou conserve `profile_id = NULL` pour suivre le
profil courant. Les usages texte partagent quatre niveaux : `ultra-low` pour Dream ; `low` pour le
dispatcher et la conversation rapide ; `standard` pour le briefing, l’exécuteur et le suivi des
Goals ; `high` pour l’exécuteur high, le planner et le Lab IA. Les modèles spécialisés (médias,
transcription et embeddings) conservent leurs colonnes dédiées. Une valeur vide dans un profil
personnel reste vide et ne reprend jamais le profil courant. La sélection du planner couvre aussi
la synthèse finale du plan. Les gateways reconnaissent également les familles Claude
(Haiku/`ultra-low`, Sonnet/`low`, Opus/`standard`, Fable/`high`) et Codex
(Luna/`low`, Terra/`standard`, Sol/`high`) comme alias de ces niveaux ; un code LLM configuré
explicitement garde priorité.
La politique du driver reste prioritaire sur l’activation :
configurer un modèle de briefing ou de planner ne les active pas pour Hermès.

Le dispatcher Task peut utiliser la sélection facultative **Décision** du profil. Ajouter Jev
dans le catalogue OpenRouter, capacité Décision, puis le sélectionner dans les usages du profil.
Une sélection vide conserve le modèle Texte Low. Le réglage de repli autorise un appel texte
après un échec récupérable du modèle spécialisé ; les refus d'accès, budgets épuisés et annulations
ne déclenchent pas ce repli. Aucun SDK ni service supplémentaire n'est requis.
Le Lab Dispatcher propose les deux catégories de candidats et fige le modèle de chaque run.
Ses essais de candidat désactivent le repli ; les traces des tâches exposent le repli en usage
normal. Voir l'[ADR 0127](../../../project/decisions/0127-optional-dispatcher-decision-model.md).

La même sélection **Décision** traite désormais la continuité des topics des messages,
le choix d'un topic existant pour une activité ou Task, et les décisions de rétention mémoire
du Dream : ignorer, rattacher une source à des souvenirs existants ou demander une extraction.
Elle vérifie aussi l'équivalence sémantique avant de rattacher un nouveau souvenir à un doublon
vectoriel. Ce rattachement conserve le contenu existant. Les faits nouveaux, contradictions et
couvertures partielles passent à l'extracteur texte avec la source complète ; les nouveaux titres
de topics restent rédigés par le texte. Décision vide conserve les parcours antérieurs et permet
de travailler avec un seul LLM local.

Le Lab Topics et Extraction mémoire accepte également Jev. Le modèle texte Dream servant aux
rédactions est figé avec le candidat ; le coût inclut leurs appels respectifs. Un candidat texte
est testé seul, même si le profil possède un modèle Décision. Les choix spécialisés n'ajoutent
aucun délai par défaut ; les limites générales des workflows restent applicables. Les gains
des nouveaux parcours doivent être mesurés, notamment lorsque le filtre appelle ensuite une
rédaction. Voir l'[ADR 0129](../../../project/decisions/0129-shared-decision-model-workflows.md).

Avec Décision configuré, le classement des messages entrants textuels commence dès leur
admission autorisée, en parallèle du dispatch. Il n'attend plus le passage à vide de Dream.
Le reçu partagé évite un second classement ; Dream assure le rattrapage en cas d'échec.
Les topics manuels/de room restent prioritaires. Le contexte et les outils mémoire consultent
le topic actualisé lorsqu'il est disponible, sans retarder une réponse pour l'obtenir ni rejouer
une recherche déjà effectuée. Aucun nouveau réglage n'est nécessaire. Voir l'[ADR 0130](../../../project/decisions/0130-live-message-topic-decisions.md).

Le planner produit un brief de mission puis un arbre borné. Toutes les tâches sont
matérialisées durablement, mais une seule feuille est activée à la fois. Les résultats des
étapes précédentes alimentent la suivante ; le parent réalise la synthèse finale. Il construit
cet arbre complet en une seule passe et évalue la décomposition d'après les composants
substantiels et vérifiables du travail. Un fichier ou livrable unique n'est donc pas assimilé à
une feuille unique lorsqu'il exige plusieurs passes cohérentes de construction, de raffinement ou
de validation ; les feuilles concernées modifient alors séquentiellement la même ressource durable.
La consigne Markdown de décomposition est le Param `ai.planner-system-prompt`. Les limites de
taille et l'état du cycle de clarification restent ajoutés par le serveur. Un dataset Planner du
Lab copie la consigne runtime lors de sa création, peut l'éditer indépendamment, puis la fige dans
chaque run afin de rendre les comparaisons reproductibles.
Le planner reçoit tous les noms du catalogue MCP effectif avec des descriptions compactes, plus un
top-k hybride détaillé. Cette recherche est appliquée après les droits et ne remplace jamais le
manifeste exhaustif. La version du catalogue accompagne le plan et les noms choisis sont validés
avant matérialisation. La reprise est idempotente et le scheduler réconcilie un réveil perdu.

Une feuille qui rapporte `BLOCKED:` provoque une unique décision de récupération du planner. Une
alternative n'est insérée que si elle est sûre, autorisée et matériellement différente de l'action
bloquée ; sinon le plan échoue explicitement. Cette reprise ne peut pas boucler et ne peut jamais
affaiblir un contrôle de sécurité. Les échecs des Tasks issues d'une conversation sont notifiés par
leur lien durable après libération du lease ; les anciennes Tasks Messenger sans lien reçoivent un
avis direct.

Dans une feuille planifiée, les outils choisis restent chargés avidement. Les autres outils MCP
autorisés ne sont plus supprimés : Pydantic AI les marque différés et expose `search_tools`, dont
la stratégie utilise la même recherche hybride. L’appel effectif repasse toujours par le toolset
MCP filtré et les contrôles serveur.

Une modification de connexion, de paramètres ou d’autorisation réconcilie automatiquement
l’index des agents concernés. Le bouton **Actualiser les outils** de l’écran Connexions constitue
le rattrapage autoritatif : il crée les connexions internes manquantes, réinterroge tous les
serveurs MCP accessibles, force le recalcul des embeddings et élague les définitions disparues.
Si un agent ou une source distante échoue, l’opération est signalée comme partielle et n’élague
pas l’index. Cette projection reste une optimisation : le catalogue MCP effectif est recalculé
avec les droits courants avant chaque sélection et chaque appel.

Le briefing peut préparer une seule exécution complexe du harnais interne. Il sélectionne uniquement
des ressources réellement disponibles et ne peut ni exécuter, ni envoyer, ni conclure la tâche.
Il est actuellement désactivé dans toutes les politiques de production ; son implémentation, ses
résultats historiques et ses benchmarks restent disponibles pour évaluation. Aucun driver ne reçoit
un ancien résultat de briefing lorsque sa politique ne l’autorise pas.

Ni le plan ni le briefing ne peuvent remplacer l’objectif utilisateur. Les prompts communs
ordonnent à l’agent de poser une question concise lorsqu’une information essentielle manque.

### Lab IA et benchmarks des mécanismes

Les onze traitements du LAB utilisent les contrats typés de `app.lab.contracts` :
une seule variable métier par item, des paramètres exclusivement au niveau du jeu,
et une sortie de référence séparée. Les descripteurs du registre alimentent l’IHM commune
`LabWorkbench.vue`, y compris les paramètres propres aux algorithmes et la prévisualisation.

Le worker commun exécute deux passes persistées : production de toutes les sorties candidates et
contrôles objectifs, puis jugement indépendant. Une nouvelle campagne peut rejuger les sorties
sans rappeler le candidat. Les snapshots figent entrées résolues, profils, consignes et rubriques ;
les empreintes distinguent corpus, contexte, candidat et juge. Les coûts sont séparés.
Un contrôle critique interdit un verdict favorable même avec une bonne note sémantique.
L’échec d’un juge reste inconclusif et réduit la couverture.

Les captures Task, conversation et voix conservent leur provenance. Un dossier incomplet
reste un brouillon. Les captures ne modifient pas les sources métier.

Toute modification doit vérifier le contrat des intrants, les services métier réellement appelés,
l’absence d’effets externes, la rubrique versionnée et les tests des deux passes, des pannes et
des droits. Voir [l’architecture du Lab](../architecture/ai-lab-evaluation.md) et
[l’ADR 0078](../../../project/decisions/0078-lab-variable-and-judgment-campaigns.md).

Depuis un round textuel ou un tour vocal, **Ajouter au Lab** sélectionne le jeu de l’exécuteur
correspondant avant de copier le cas.

Les modales texte et voix proposent également la copie du JSON complet et la suppression du tour.
Les routes de suppression exigent `TASK_EDIT`, refusent les exécutions actives et conservent les
Tasks, ProcessRuns et appels LLM d’audit déjà produits. Les appels LLM sont détachés du tour
supprimé afin que leur journal global demeure exploitable.
Le parcours d’interface se trouve dans le [guide opérateur](../user/lab-ai.md).

## 5. Base de données et synchronisation

Les modèles SQLAlchemy constituent la cible déclarative de tout le schéma `public`.
`core.dbadmin` calcule les transitions puis utilise Atlas en interne ; n’ajoutez pas Alembic,
n’appelez pas Atlas directement et n’écrivez pas de DDL manuel dans un démarrage d’application.
Le cycle complet, les actions conditionnelles et les patrons de transformation sont décrits dans
la documentation dédiée [`core.dbadmin`](dbadmin.md).

Après un changement de modèle :

```bash
make sync-db
git diff -- back/core/authorize/definitions.py front/core/authorize/definitions.ts
```

Une nouvelle colonne `NOT NULL` sans défaut est automatiquement ajoutée nullable, puis resserrée
dès que son backfill est complet. Une évolution destructive d’ENUM exige un mapping total déclaré
par le développeur.

### Actions conditionnelles a-versionnées

DbAdmin ne rejoue pas une suite de migrations numérotées. À chaque synchronisation, il compare la
base présente à la cible SQLAlchemy de la branche courante et produit un `SchemaTransitionSet`.
Une `DbAdminAction` idempotente utilise son prédicat pour décider si ce delta courant la concerne.
Les phases avant/après Atlas, les tables de sauvegarde hors `public`, la reprise et les tests sont
décrits dans la [documentation dédiée à `core.dbadmin`](dbadmin.md).

> **Limite de sécurité actuelle :** une erreur d’action `required=True` produit un verdict fatal,
> mais n’interrompt pas immédiatement l’orchestrateur. La première application Atlas peut donc
> encore retirer une ancienne table ou colonne après l’échec de sa sauvegarde `BEFORE_EXPAND`.
> Tant que l’orchestrateur ne bloque pas Atlas dans ce cas, ne pas utiliser ce patron comme unique
> protection d’une contraction destructive. Une telle évolution doit conserver l’ancien objet
> dans la cible déclarative ou être livrée en plusieurs étapes non destructives.

Toute donnée permanente provient d’une `DbAdminDataSource` enregistrée depuis le fichier
`<module>.dbadmin`. Sa factory produit un ou plusieurs `DbAdminDataset`, chacun avec une clé stable,
une table, une clé naturelle, des lignes statiques ou calculées et des `depends_on` explicites.
DbAdmin compile les sources de tous les modules actifs, refuse les collisions et cycles, puis
applique le merge générique : validation, `INSERT`, mise à jour des colonnes possédées, restauration
`HistoryMixin` et retrait opt-in.

Les fournisseurs de lignes sont évalués juste avant leur dataset. Le dataset des connexions
intégrées peut ainsi résoudre les vrais identifiants des tools et agents après le merge des tools.
Les `column_mergers` couvrent les rares politiques par colonne, par exemple ajouter les nouveaux
paramètres globaux d’un tool sans écraser les valeurs administrateur.

Les privilèges, rôle et grants administrateur, paramètres, profils LLM, tools imposés, connexions
intégrées, skills et matrices d’affectation sont de vrais datasets tabulaires. Les projections
mémoire, contacts Messenger et traitements de compatibilité Hermès sont nommés
`DbAdminReconciler`, car ils reconstruisent un état dérivé et ne constituent pas des datasets. Le
lifespan FastAPI ne resynchronise aucune de ces données.

Pour une transformation métier plus large, contribuer une action DbAdmin idempotente avec
prédicat et postcondition :

1. ajouter la nouvelle table ou colonne ;
2. dual-write si nécessaire ;
3. backfill idempotent avec métriques, sans secrets dans les logs ;
4. vérifier la postcondition et basculer les lectures ;
5. retirer l’ancien objet dans une livraison distincte après preuve de convergence, tant que la
   barrière sur les actions requises documentée ci-dessus n’est pas implémentée.

La migration de configuration Hermès suit ce modèle. Les champs plats historiques ne sont
pas supprimés dans cette version.

Chaque service écrit dans la transaction de son appelant. N’ouvrez pas une nouvelle session
pour contourner une transaction métier, sauf worker explicitement autonome.

## 6. API, services et RBAC

Un module backend suit généralement :

```text
models.py       persistance
schemas.py      entrées/sorties API
service.py      logique métier et transactions
router.py       HTTP et dépendances d’autorisation
privileges.py   constantes RBAC
tests/          tests du domaine
```

Les routeurs restent minces. Ils valident, autorisent, appellent un service et sérialisent la
réponse. Les erreurs HTTP visibles doivent passer par le catalogue i18n lorsqu’elles sont
destinées à l’utilisateur.

Déclarez les privilèges avec des codes stables. `make sync-db` régénère et synchronise les
définitions backend/frontend. Ne renommez pas un code existant comme une simple traduction :
les codes sont des identifiants persistés, les libellés sont traduisibles.

### Packages MCP de management agentique

Les fonctions MCP natives sont découvertes dans le `mcp.py` de chaque module déclaré. Le décorateur
`mcp_tool(tool_code, name=...)` rattache une fonction à un outil intégré ; la connexion active de
l’agent sélectionne ensuite les groupes réellement montés dans son toolset. Les états de fonction
au niveau outil puis connexion affinent cette exposition.

Le prompt de chaque driver reçoit un inventaire compact construit depuis cette même projection
d’autorisation : connexion active, capacité du runtime, état de fonction et éventuel scope de la
tâche. Il ne doit jamais contenir une liste statique de fonctions. `tools_list` applique le même
principe et omet entièrement les groupes et fonctions non autorisés au lieu de les signaler comme
indisponibles.

Le harnais interne expose les noms natifs exacts (`task_get`, `file_read`, `process_start`, etc.)
sans leur ajouter de préfixe `galaris_`. Les noms historiques déjà présents dans une trace ou un
checkpoint sont normalisés à la lecture. Un serveur MCP externe conserve en revanche le code de sa
connexion comme namespace afin d'éviter les collisions entre fournisseurs.

Les lectures Goal en libre-service passent par le Tool `file_sharing`, via `file_list`,
`file_search` et `file_read` sur `galaris://goal/` et `galaris://goal_cycle/`. Les commandes
`goal_update_suivi`, `goal_run_now` et
`goal_ask_referrer` appartiennent au package cœur `galaris`. `app.goal` impose côté serveur que le
Goal appartienne à l'agent appelant. `goal_ask_referrer` exige en plus la tâche courante du Goal et
ne bénéficie jamais d'une élévation administrative.

Les définitions de Process affectées passent également par `galaris://process/`; chaque ressource
est adressée par le même `workflow_id` que `process_get` et `process_start`. Cette projection reste
en lecture seule et sa pagination est exécutée dans la requête SQL.

Les Tasks se découvrent et se lisent complètement par `galaris://task/`. Le package cœur
`galaris` conserve néanmoins `task_get` comme vue opérationnelle compacte : elle projette la
progression, les attentes, la pause et l'amendabilité sans remplacer le snapshot complet de
`file_read`.

Browser, Search, Image et Multimedia sont connectés actifs par défaut. Console
interne est provisionnée automatiquement à la création d'un agent utilisant le
harnais interne et activée après vérification SSH/SFTP. Si l'exécuteur est
indisponible, la connexion reste inactive ; le provisionnement peut être relancé
depuis les connexions. Ces cinq Tools sont autorisés en conversation à leur
première initialisation. Les réglages et restrictions existants sont conservés.

Les packages `goal_management`, `skill_management` et `process_admin` sont déclarés dans
`app.tools.mandatory_tools` avec `default_active=False`. La synchronisation crée donc une connexion
pour chaque agent compatible, mais ne lui accorde aucune fonction par défaut. Une connexion
`goal_management` active élargit les fonctions Goal partagées à tous les propriétaires et expose
uniquement les commandes administratives `goal_create`, `goal_update`, `goal_delete`, `goal_pause`,
`goal_resume` et `goal_complete`. Conservez cette propriété pour toute capacité d'administration
déléguée. Cette connexion active est le témoin d'administration : `app.goal.mcp` la revérifie au
moment de chaque commande administrative, même si la fonction avait déjà été montée dans un
toolset. Sans ce témoin, les fonctions partagées injectent l'identifiant de l'agent appelant jusque
dans la requête du service et répondent comme si tout Goal étranger était inexistant.

Les Tools `galaris`, `conversation`, `memory` et `file_sharing` portent `can_disable=false`.
Cette propriété persistée appartient au logiciel et n'est pas acceptée par les contrats d'écriture.
Leurs connexions sont créées pour tous les agents et convergent vers l'état actif, y compris après
une désactivation historique. Leurs fonctions sont toujours autorisées aux deux niveaux de la
cascade ; les anciens refus sont ignorés. L'API refuse toute modification ou suppression du Tool,
de sa connexion, de ses paramètres et de ses autorisations. L'interface les conserve dans les
trois onglets, en lecture seule, avec une icône de service obligatoire. Les Tools optionnels
conservent leurs activations et restrictions administrées. Les ACL métier, les compatibilités
de harnais et les restrictions de contexte restent appliquées.

Les neuf fonctions de contrôle `conversation_*` appartiennent au Tool `conversation`, avec
`document_show` ; elles restent réservées au contrôleur conversationnel. Le clic sur un Tool
décrit ouvre sa description ; aucun lien n'est présenté pour une description vide. Le catalogue
livré décrit tous les Tools natifs et les bridges de messagerie et de fichiers connus ; la
synchronisation complète les descriptions de bridges vides et actualise les anciens textes courts
standard lorsqu'ils sont restés identiques, sans remplacer les textes personnalisés. Les fiches
utilisent des titres et listes Markdown : rôle, possibilités, cas d'usage illustrés et conditions
d'accès. Le texte source est livré dans `app.tools.descriptions` ; les traductions de l'interface
sont dans le catalogue `front/app/tools/i18n.ts`.

`memory_summarize` synthétise au plus 200 messages et les 32 000 derniers caractères, via le
modèle de l'agent. Il produit des faits, décisions, engagements et questions ouvertes attribués,
stockés en HTML éditorial par l'acquisition Memory. L'ancien argument inopérant `replace_existing`
est supprimé ; les règles normales de déduplication s'appliquent. Une erreur du modèle ne stocke
ni transcription brute ni mémoire partielle.

`galaris_admin` est un quatrième package de management, également inactif par défaut. Il expose
`conversation_round_get` et `voice_turn_get`, deux lectures par UUID primaire destinées à
l’analyse complète des jeux de données conversationnels texte et voix, ainsi que `llm_call` et
`llm_calls` pour inspecter les appels de modèles. Elles incluent les traces
d’exécution et tous les `LLMCall` corrélés. Chaque wrapper revérifie la connexion
`galaris_admin` active au moment de l’appel ; la seule découverte préalable de la fonction ne
constitue pas une autorisation durable.

`app.goal.mcp` adapte le service métier existant sans dupliquer sa persistance :

- création avec propriétaire et référent agent explicites et distincts ;
- liste et inspection bornées au propriétaire, sauf élévation `goal_management` ;
- historique des cycles séparé de la fiche Goal et suivi Markdown modifiable explicitement ;
- mise à jour et commandes pause/reprise/clôture/exécution immédiate protégées par
  `expected_revision` ;
- suppression logique refusée lorsqu’un cycle est inachevé.

Les réponses Goal conservent les champs texte `description` et `tracking_markdown`, résolus depuis
leurs documents canoniques, et exposent aussi `description_document_id` et
`tracking_document_id`. La transition initiale a sauvegardé les anciennes colonnes dans
`galaris_migration.goal_markdown_backup`, créé les documents protégés, puis laissé Atlas supprimer
les colonnes texte et imposer les clés étrangères UUID. Le hook temporaire a été retiré après la
validation de cette contraction en production ; la sauvegarde reste disponible pour audit.

`app.skill.mcp` expose exactement deux lectures : la matrice d’autorisation effective d’un agent et
le seul fichier `SKILL.md` d’un skill central. `skill_read` ne doit jamais devenir un explorateur de
fichiers générique : les scripts, références et assets restent hors de ce contrat de management.

Le wrapper MCP central ouvre exactement une session courte avec `get_db_session` pour chaque appel.
La fonction MCP et tous les services qu'elle appelle réutilisent cette session avec `get_db()` : ils
n'ouvrent jamais de session imbriquée. Les erreurs restent récupérables par le wrapper central, qui
porte seul le commit ou le rollback. Les appels explicitement sûrs peuvent s'exécuter en parallèle,
mais chacun possède alors sa propre session. Les tests doivent vérifier la découverte par code
d’outil, le montage FastMCP, l’inactivité par défaut et le mapping des contrats vers les services.

### Audio, vidéo et fichiers volumineux

`app.audio` expose `audio_transcribe` comme outil MCP natif sous le code intégré `audio`. Son
argument `file` est soit une URI canonique lisible de `app.file_share`, soit une URL HTTPS YouTube,
jamais un contenu binaire dans le schéma du tool. Le contrat MCP reste unique afin que le modèle
n’ait pas à choisir entre plusieurs fonctions selon que la source est un audio, une vidéo ou un
lien. Pour un fichier, le transport est résolu par `app.file_share`, ce qui conserve le même
contrat pour les drivers interne et Hermès. Pour une URL, `app.audio` délègue toute la logique
spécifique à `bridge.youtube`.

La préparation de l’exécuteur applique une règle absolue : les catégories et MIME `audio/*` ou
`video/*`, ainsi que les extensions reconnues comme telles, restent chez leur provider même si le
LLM principal annonce une capacité audio/vidéo. `runtime.Agent._build_file_input_part` répète cette
vérification en défense en profondeur et refuse de construire un `BinaryContent`. Un seuil en
octets ne suffit pas : le fournisseur peut convertir un média relativement petit en beaucoup de
tokens et renvoyer son contenu à chaque tour d’outil.

L'absence de `audio_transcribe` dans le toolset est terminale pour toute demande. L’absence de
modèle STT est terminale uniquement pour un fichier audio ou vidéo ; une URL YouTube sous-titrée
n’appelle pas le STT. Les prompts de pièce jointe interdisent explicitement les
replis par `console_*`, le LLM exécuteur, les lecteurs génériques et les téléchargeurs vidéo :
l'agent doit remonter l'erreur sans contourner le pipeline prévu.

```text
URI source file_share (audio ou vidéo)
        │ materialize_resource vers un fichier temporaire borné
        ▼
PyAV : première piste audio, vidéo ignorée
        │ resample mono 32 kHz + rotation libmp3lame 96 kbit/s toutes les ~10 min
        ▼
MP3 temporaires bornés
        │ STT séquentiel + résumé immédiat de chaque segment
        ▼
verbatim horodaté .txt + réduction hiérarchique → synthèse .summary.md
```

```text
URL HTTPS YouTube
        │ bridge.youtube : hôte allow-listé + extraction de l’identifiant
        ▼
youtube-transcript-api : préférence langue demandée, manuel avant automatique
        │ aucun téléchargement audio/vidéo, aucun STT
        ▼
transcript horodaté .txt
        │ segments texte d’environ 10 min + prompts de synthèse vidéo
        ▼
réduction hiérarchique → synthèse .summary.md
```

`bridge.youtube` est un client pur sans routeur, modèle ni enregistrement au démarrage ; il n’est
donc pas déclaré dans `back/modules.py`. Il accepte uniquement HTTPS, refuse les ports et
identifiants dans l’URL, allow-liste les hôtes YouTube et reconnaît `watch`, `youtu.be`, `shorts`,
`live` et `embed`. La bibliothèque cliente étant synchrone et créant une `requests.Session` non
thread-safe, chaque appel construit sa propre instance dans `asyncio.to_thread`. Ses erreurs sont
réduites à des catégories localisées : URL invalide, sous-titres absents, vidéo indisponible,
accès bloqué et échec temporaire.

La conversion est disque-à-disque et s’exécute avec `asyncio.to_thread` afin de ne pas bloquer la
boucle async. PyAV est déjà fourni par la dépendance `aiortc`; l’implémentation ne lance pas de
processus `ffmpeg`. Les branches OpenAI-compatible et ElevenLabs transmettent le fichier multipart
depuis le disque. L’API OpenRouter imposant un JSON base64, seule cette branche charge le MP3
normalisé en mémoire.

Le format de sortie est volontairement MP3 plutôt qu’Opus : Opus offre un meilleur rapport
qualité/taille, mais MP3 reste le dénominateur le plus largement accepté par les endpoints STT.
Le débit 96 kbit/s mono préserve suffisamment la parole et réduit fortement une source PCM ou
vidéo. Ne présentez toutefois pas cette réduction comme une économie garantie : beaucoup de
fournisseurs facturent à la minute.

Le service doit fermer les conteneurs et supprimer tous les temporaires sur chaque chemin de
sortie. Un média vide, non décodable ou dépourvu de piste audio lève `AudioConversionFailed` ; le
tool transforme ensuite cette exception en erreur opérationnelle localisée. Les tests du module
créent un vrai conteneur vidéo avec piste audio et vérifient que le résultat ne contient plus de
vidéo, utilise une seule piste MP3 mono à 96 kbit/s, et refuse une vidéo silencieuse.

Le découpage s’effectue pendant un unique décodage : les frames rééchantillonnées sont réparties
sur des encodeurs MP3 successifs, sans créer d’abord un MP3 géant et sans conserver l’audio en
mémoire. `summary_service` applique un map-reduce : résumé borné de chaque transcript de segment,
puis regroupements limités à 42 000 caractères jusqu’à ce que la synthèse finale tienne dans une
requête. Le profil `meeting` conserve décisions, responsables et actions ; le profil `video`
préserve idées, affirmations, exemples, réserves et timestamps sans présenter les propos de la
vidéo comme des faits vérifiés. Dans les deux cas, le contenu est marqué comme donnée non fiable et
ne peut pas donner d’instructions au modèle de synthèse. Le transcript complet est écrit au fil de
l’eau et n’est jamais fourni à cette réduction.
Le message de progression passe directement par Messenger sans appeler `note_reply`, afin que la
livraison finale automatique ne soit pas supprimée par le garde anti-doublon.

Les skills différés volumineux ne doivent pas annuler cette économie de contexte. Au-delà de
12 000 caractères, `app.harness.skills` n'injecte qu'un index de titres dans la capability
Pydantic AI. Le tool `skill_<code>_read_file` accepte alors `section` pour lire un seul chapitre
Markdown. En parallèle, le processeur d'historique vide le contenu déjà réinjecté du résultat
typé `load_capability`, tout en conservant l'appel et son identifiant afin que la capability reste
active. Ne retirez pas ces deux protections : les instructions actives sont autrement dupliquées
et refacturées à chaque tour d'outil.

### Processus et n8n

`app.process` possède les définitions, les runs, l’outbox, les callbacks et le registre des
moteurs. `bridge.n8n` adapte l’API et les webhooks n8n au protocole `ProcessEngine` ; il ne
doit pas contenir la logique de persistance métier.

Les six fonctions personnelles `process_*` appartiennent au package socle `galaris` ; il n’existe
plus de connexion `process` à activer. La définition associe explicitement un workflow à un agent,
et les outils de liste, lecture, lancement et suivi filtrent ou revalident systématiquement cet
agent. Les deux drivers ajoutent au prompt un catalogue compact des seuls processus affectés à
l’appelant, y compris lorsqu’il dispose de droits d’administration. Tous sont affichés lorsque
l’agent en possède au plus dix ; au-delà, le modèle vectoriel multilingue configuré sélectionne les
dix plus pertinents pour la demande, sans seuil, avec repli lexical déterministe. Un Process
compatible reste prioritaire sur toute création ou modification de Task.

Le package séparé `process_admin` est auto-connecté **inactif**. Une activation explicite donne à
l’agent administrateur les fonctions de découverte des moteurs, de CRUD des définitions avec un
`agent_id` cible et de gestion des runs de tous les agents. Ces fonctions portent toutes le préfixe
`process_admin_` afin qu’un modèle ne les confonde jamais avec son accès personnel. Le skill système
`galaris` documente les deux surfaces, mais le prompt et la liste réelle des tools restent
l’autorité d’accès.

L’API canonique est `/api/processes/...` et la page frontend est `/process`. L’ancien préfixe
`/api/processus/...` reste un alias caché et déprécié pour ne pas casser les callbacks déjà
déployés. N’utilisez jamais cet alias dans du nouveau code.

La livraison des démarrages est au moins une fois : toute intégration doit honorer
`Idempotency-Key`. Galaris fournit aussi `X-Galaris-Run-Id`, `X-Galaris-Callback-Url` et le
header d’authentification de callback configuré. Le jeton est propre au run et protège aussi
les fichiers liés ; il ne doit pas être remplacé par un secret global exposé dans une URL.
Le corps exact, les callbacks et le gabarit importable sont décrits dans
[`docs/fr/n8n/README.md`](../n8n/README.md).

## 7. Frontend

La [palette Solaire](palette-solaire.md) est la référence chromatique obligatoire pour toute
l’interface : 11 couleurs, chacune avec un accent et deux fonds adaptés aux thèmes clair
et sombre. Ses valeurs exactes et ses règles d’usage font foi pour les changements visuels.

Structure d’un domaine :

```text
front/app/<domain>/
├── components/
├── pages/
├── services/       appels HTTP et types de transport
├── stores/         état Pinia
├── navigation.ts
└── i18n.ts         objets en/fr de mêmes clés
```

Utilisez `<script setup lang="ts">`, des props typées et les composants Quasar. Les stores
Pinia regroupent l’état partagé et les actions ; les services ne contiennent pas d’état UI.
Le routage est basé sur les fichiers : n’ajoutez pas une seconde table de routes manuelle.

Les actions des modales utilisent les dimensions et les formes natives de Quasar : boutons
avec texte standards, boutons d’icône ronds, fermeture d’en-tête `flat round dense`.
Ne pas imposer de hauteur, de `size` ou de variante `dense` aux actions ordinaires.
Ajouter `galaris-dialog-actions` aux `q-card-actions` des modales pour conserver les marges
internes natives des boutons sur mobile. Les popovers, contrôles intégrés aux champs,
filtres, paginations et barres d’édition conservent leurs dispositions spécialisées ;
ne pas leur appliquer une règle générale visant tous les boutons descendants d’une modale.

Tout texte visible passe par `t()` ou `$t()`. Les valeurs purement techniques telles que
`MCP`, un nom de fichier ou un code de modèle restent littérales. Lors d’un changement de
langue, l’attribut HTML `lang` et les requêtes API sont synchronisés par le cœur i18n.

Les préférences `DEFAULT_LANGUAGE` et `LOCALIZATION` sont facultatives et vides par défaut.
Les valeurs déjà enregistrées sont conservées ; « Non renseignée » permet d’effacer la langue
de repli. La langue du profil utilisateur est prioritaire sur celle du contexte et du routage.
L’admission des conversations et des Tasks la conserve pour les traitements en arrière-plan.
Sans utilisateur associé, la langue du contexte est conservée, puis la préférence de repli
s’applique ; sans aucune langue connue, Galaris utilise l’anglais. Aucun lieu n’est inventé
lorsque la localisation est vide.

### PWA et renouvellement de session

`vite-plugin-pwa` génère le manifeste et le service worker depuis `front/vite.config.ts`. Les
icônes normales, maskables et Apple sont versionnées dans `front/public/pwa`. Workbox met en
cache l’interface statique, mais exclut explicitement `/api`, `/socket.io`, `/ws` et
`/openapi.json` du fallback de navigation : aucune donnée métier ne doit être présentée comme
disponible hors connexion. Le service worker utilise le mode `autoUpdate`, y compris dans le
déploiement de développement partagé sans casser le HMR.

Les notifications de Chat utilisent le service worker en mode `injectManifest` et Web Push.
DbAdmin conserve la paire VAPID dans le paramètre interne chiffré `WEB_PUSH_VAPID_KEYS` :
génération unique quand le paramètre est absent, sans reprise des anciennes variables.
La clé privée n’est jamais exposée par les préférences. Le contact `WEB_PUSH_VAPID_SUBJECT`
(`mailto:` ou HTTPS) et le délai `WEB_PUSH_DELAY_SECONDS` (1 à 30 secondes) sont réglables dans
les préférences du Chat, sans redémarrage. Le nouveau délai concerne les notifications suivantes.
La mise à jour retire les quatre anciennes variables du `.env` seulement après vérification
des clés persistées. Une paire persistée invalide bloque le démarrage et n’est jamais remplacée
silencieusement. Le premier passage depuis les anciennes clés exige de désactiver puis réactiver
les notifications sur les appareils ; les mises à jour suivantes conservent la paire interne.

Le navigateur n'autorise l'abonnement que dans un contexte sécurisé (HTTPS, ou localhost en
développement) et après un geste explicite de l'utilisateur. Les endpoints Push et clés propres
à l'appareil sont chiffrés avec `ENCRYPTION_MASTER_KEY`. Une rotation VAPID invalide les
abonnements existants : elle doit donc rester une opération exceptionnelle et annoncée.

Le flux d’authentification navigateur est le suivant :

```text
login
  ├── jeton d’accès court → localStorage
  └── jeton de renouvellement → cookie HttpOnly + ligne hashée en base

démarrage de la PWA ou réponse API 401
  └── POST /api/auth/refresh → rotation atomique → nouveau JWT + nouveau cookie

logout, changement de mot de passe ou désactivation
  └── révocation de la famille ou de toutes les sessions persistantes
```

`front/core/api.ts` centralise le stockage du JWT, active `withCredentials` et sérialise les
renouvellements concurrents dans une promesse unique. Son intercepteur rejoue une requête 401
une seule fois. `authStore.initialize()` tente d’abord le cookie persistant, puis accepte le JWT
historique comme repli pendant la transition des installations existantes. Le rôle présent dans
un ancien JWT signé peut être demandé lors du renouvellement, mais le backend vérifie toujours
que ce rôle appartient encore à l’utilisateur.

Le backend ne conserve jamais le jeton opaque : `refresh_session_service.py` stocke son
condensat, fait la rotation sous verrou SQL et utilise une courte grâce déterministe pour les
rafales concurrentes. Un rejeu tardif révoque la famille. Toute modification de ce contrat doit
conserver les contrôles d’origine, les attributs du cookie et les tests de
`back/core/user/tests/test_refresh_session.py`.

Les mots de passe font au minimum 12 caractères. Un échec de mot de passe ou de second facteur
incrémente un compteur persistant sous verrou SQL ; à partir du cinquième échec, le compte subit un
verrouillage exponentiel borné. Une authentification réussie remet le compteur à zéro.

Le second facteur TOTP est facultatif par utilisateur. La clé TOTP est chiffrée avec
`ENCRYPTION_MASTER_KEY`, un compteur refuse le rejeu d’un code déjà accepté et les codes de
secours sont condensés, consommés sous verrou et affichés une seule fois. Les endpoints de
configuration vivent sous `/api/auth/mfa`; le login JSON accepte `otp_code`. La politique fixe de
verrouillage des connexions protège uniquement le bootstrap et ne peut pas être affaiblie par
l’environnement.

### Observabilité

`core.observability` configure Logfire localement avant les intégrations ; `LOG_LEVEL` reste
lu dans le `.env` dès le démarrage. Après hydratation des paramètres, le token chiffré
`LOGFIRE_TOKEN` active l’export distant. Un listener réagit à son édition dans les préférences
Système : le SDK remplace ses exporteurs sans réinstaller les instrumentations, hors de la
boucle asynchrone de l’API. Un token vide coupe explicitement l’export, même si une ancienne
variable d’environnement ou un fichier de credentials Logfire subsiste. Avec ce token, le backend
centralise les traces FastAPI, les spans SQLAlchemy et HTTPX, les événements Pydantic AI, les
métriques système et les journaux Loguru. Les en-têtes, corps HTTP, contenus de prompts et
contenus binaires ne sont pas collectés. Sans jeton, l’instrumentation reste locale.
`APP_ENV=test` conserve l’instrumentation normale. Seules les compositions de tests
automatisés isolent explicitement la télémétrie et les quotas HTTP, fournissent leurs
propres secrets et demandent `--mode test` à DbAdmin.

`app.incident` complète cette télémétrie par un journal PostgreSQL durable de chaque appel LLM ou
outil en échec. La capture intervient avant le compactage des événements du harnais, conserve les
corrélations de Task, tentative, run, agent, fournisseur, modèle et outil, ainsi que la politique
de retry disponible. Les secrets sont masqués et les octets sont remplacés par leur taille et leur
empreinte. Une limite globale de 8 Mio, signalée dans la fiche, protège la base d’un payload
accidentellement non borné.

Le menu **Préférences → Journal des échecs IA** présente les occurrences et les motifs regroupés.
La routine de maintenance consiste à traiter les motifs `new` et `regression`, documenter le
diagnostic et la cause racine, planifier puis référencer le correctif et son test, et enfin passer
le motif à `resolved`. Une nouvelle occurrence le rouvre automatiquement en `regression`.

## 8. Langue du code et i18n

Le code source est rédigé en anglais : noms, commentaires, docstrings, logs techniques et
messages d’erreur internes. Les identifiants publics et persistés ne sont pas renommés pour
une raison cosmétique. Lorsqu’un retrait ou renommage est réellement nécessaire, il exige une
stratégie explicite de compatibilité ou de révocation des anciens accès.

Les textes visibles ne sont pas « traduits dans le code » :

- frontend : chaque module exporte exactement les mêmes clés `en` et `fr` dans `i18n.ts` ;
- backend : `core.i18n.t()` charge les catalogues de module et reçoit une langue explicite
  pour les workers sans contexte HTTP ;
- prompts contractuels : anglais stable, avec instruction de produire la réponse dans la
  langue détectée ;
- contenu demandé par l’utilisateur : ne jamais le traduire implicitement.

Une traduction française complète est obligatoire pour toute nouvelle clé anglaise. Évitez
les textes construits par concaténation lorsque l’ordre des mots peut changer selon la
langue ; utilisez des paramètres nommés.

## 9. Tests et typage

Voir aussi le [guide d’exploitation de la fiabilité](reliability-operations.md) pour les budgets,
la rétention, les images à promouvoir et les exercices d’upgrade/restauration.
`make lint` bloque les erreurs Python à forte confiance ; `make tests-coverage` mesure les branches
de DbAdmin, du budget et de la machine d’états Task, avec un seuil bloquant de 95 %.

```bash
make typecheck
make tests
make tests ARGS='app/agent/tests/test_registry.py'
make tests-browser
make quality
```

`make typecheck` exécute Pyright strict sur le backend de production, `vue-tsc` sur le
frontend, puis le contrôle de parité des catalogues frontend. Celui-ci vérifie les clés, les
types de valeurs et les paramètres nommés entre l’anglais et le français. Les tests Python
utilisent beaucoup de mocks et monkeypatch dynamiques : ils sont validés par pytest, tandis
que le runtime reste strictement typé.

`make tests` démarre une base PostgreSQL pgvector éphémère, exécute le même DbAdmin que la
production puis lance pytest dans un conteneur one-shot. Son Compose autonome utilise un seul
réseau par défaut, propre au projet de test, puis le supprime systématiquement à la fin de
l'exécution ; il ne charge aucun réseau de la stack applicative.
`back/conftest.py` refuse une base dont
`APP_ENV` n’est pas `test` ou dont le nom n’est pas `test_db`. Les fixtures entourent chaque
test d’une transaction externe avec savepoints et rollback, même si un service appelle
`commit()`. Les tests de `core.i18n` imposent également la parité des clés et placeholders
de tous les catalogues backend anglais/français.

Les configurations CI GitLab et GitHub définissent ces portes pour les demandes de fusion : typage et build de production,
cartographie générée, frontières d’architecture, tests backend avec PostgreSQL éphémère et tests
du sidecar navigateur. Une revue de dépendances bloque les nouvelles vulnérabilités élevées ;
Dependabot suit les verrous Python, npm, Docker et GitHub Actions.
L'activation du runner et des protections du distant GitLab est décrite dans
[le guide de tests](testing.md) ; un YAML présent ne garantit pas leur activation.

Ne lancez pas pytest dans le backend de développement : l’ancien comportement pouvait créer
des tâches et modifier des données réelles.

Tests attendus pour une modification agentique :

- matrice driver × effort × route ;
- transitions durables et reprise après erreur ;
- conformité du stream terminal ;
- absence d’import interdit entre couches (tests AST) ;
- configuration absente/désactivée/inconnue ;
- comportement du driver avec dépendances simulées ;
- test d’intégration DB pour toute persistance nouvelle.

## 10. Workflow de contribution

1. inspecter `git status` et préserver les changements sans rapport ;
2. écrire ou adapter le test qui exprime le contrat ;
3. faire une modification cohérente et limitée à la responsabilité du module ;
4. exécuter les tests ciblés puis `make typecheck` et `make tests` ;
5. vérifier `git diff --check` et relire les changements de schéma/configuration ;
6. documenter tout choix d’architecture ou nouvelle variable.

Tous les nouveaux messages de commit doivent être rédigés exclusivement en anglais,
titre et corps compris, afin de faciliter les contributions internationales.

Format de commit conseillé :

```text
refactor(agent): isolate runtime drivers behind the agent facade
fix(task): keep pytest writes out of the development database
docs: rebuild user, administrator and developer guides
```

Un refactoring ne doit pas changer silencieusement une politique métier. Si le comportement
change, rendez-le explicite dans le contrat, les tests et la documentation.

## 11. Pièges connus

- importer `app.task.models.Task` dans un driver recrée le couplage que la façade élimine ;
- choisir un modèle dans le proxy après le début du run rend les traces incohérentes ;
- faire décider le briefing ou le planner une seconde fois annule le choix du dispatcher ;
- conserver un fallback silencieux pour un code driver inconnu masque une erreur de config ;
- considérer un texte final comme preuve d’une action permet les confirmations hallucinées ;
- persister une fixture de test sur la base de développement crée des tâches parasites ;
- ajouter une chaîne visible en anglais sans clé française casse la promesse i18n ;
- réduire une table au cours de la même version que son backfill empêche un rollback sûr.

Les contrôles de dépendances, secrets, SAST, images et restauration sont décrits dans
[Validation de sécurité](security-validation.md).

Les commandes, couches de test et limites de leurs garanties sont détaillées dans
[Tester les comportements](testing.md), notamment les composants Vue en navigateur,
les fixtures de concurrence et les contrats locaux des bridges.

## Contenus éditoriaux

Le [contrat HTML éditorial](editorial-html.md) décrit les profils, la validation, les révisions,
les médias joints et la migration DbAdmin des contenus riches.
