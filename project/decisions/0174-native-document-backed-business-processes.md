# 0174 — Processus métier natifs adossés aux Documents

- Date : 2026-10-11.
- Statut : accepté pour le socle v1 ; qualification en cours.

Le choix de stockage documentaire ci-dessous est remplacé depuis le 2026-10-17 par la
[décision 0197](0197-process-owned-bpmn-storage.md) : BPMN, historique et droits sont
possédés par Process ; les Documents sont exclusivement éditoriaux HTML.

### Décisions binaires et calculs Python purs — 2026-10-16

Les IF configurés ont deux sorties True/False et trois modes dépendant de l'acteur :
IA/code pour un acteur IA, humain imposé pour un acteur humain. L'IA réutilise une Task
durable ; l'humain reçoit les boutons Messenger ; le code doit rendre un booléen exact.
Les tâches partagent le choix de traitement de leur acteur et conservent instructions,
code et déclarations lors d'un changement de mode.

Le port `IsolatedCodeRunner` reçoit maintenant un adapter Monty pour les computations
pures : worker natif neuf, environnement sans secrets, aucun montage, objet hôte,
callback système ou capacité externe. Le Dataset est un snapshot JSON détaché et les
clés Python valides deviennent des paramètres locaux. Le résultat ordinaire retourne
par une frontière JSON bornée, puis le moteur valide les sorties et intègre le delta.
Le worker est fermé avant `stopped=true`. Limites : deux workers, 32 Mo, une seconde de
calcul, trois secondes par requête ; les impressions sont ignorées. Une perte de reçu
autorise uniquement le recalcul pur ; l'intégration conserve sa clé idempotente.

Cette livraison précise le périmètre du paragraphe ci-dessous : le Python généraliste,
les packages tiers et le broker MCP/REST restent soumis à la qualification d'un runner
sur VM/hôte distinct. Ils ne sont pas exposés par Monty. Les tests utilisent le vrai
interpréteur pour les Dataset, décisions, refus d'accès système, boucle et saturation ;
ils ne constituent pas une qualification de sécurité globale de la plateforme.
Référence : [modèle de sécurité Monty](https://github.com/pydantic/monty/blob/main/docs/security.md).

### Contrats locaux typés — 2026-10-15

Le profil `galaris.bpmn/v2` ajoute des listes input/output à chaque activité et au processus :
nom, type, nullable/notnull, défaut typé facultatif. Le codec commun impose des enveloppes
JSON récursives et distingue les références métier des scalaires de même représentation.
Une omission utilise le défaut, sinon null si nullable, sinon échoue ; un null explicite
n'utilise jamais le défaut. Les définitions v1 et les snapshots déjà admis conservent leur contrat.

Le moteur possède l'intégration des sorties locales ; le Dataset global contient `data`
et `files` et refuse les écritures directes. Memory publie le delta et son reçu dans la
même écriture, en préservant les changements disjoints et en signalant les conflits.
Les fichiers circulent par URI source sans copie automatique. Les tâches IA rendent du
JSON typé et les tâches humaines disposent d'un formulaire construit depuis leurs déclarations.
MCP, REST et les appels enfants partagent les frontières de validation et l'agent exécutant.
Les tâches ordinaires à plusieurs prédécesseurs convergent une seule fois.

Les transformations Python et l'activité `code` utilisent un port d'exécution isolée ;
aucun adapter de production n'est installé. Les tests de protocole emploient un runner
synthétique et ne prouvent pas l'isolation système. La VM/hôte séparé, la sandbox jetable,
le transport authentifié, les limites et l'intermédiaire MCP/REST restent à qualifier avant
activation. Sans runner qualifié, le moteur refuse le code sans repli vers le backend.
Le worker Process dédié et les mesures de charge restent suivis dans le plan.

Galaris ajoute le moteur `galaris` à `app.process`, à côté des moteurs externes.
Les déclarations n8n, leur callback et les contrats existants restent utilisables.
La nouvelle définition métier référence un vrai Document `process`, au format BPMN XML,
et réutilise ses grants, groupes, propriétaire, accès humain et historique.
Il n'existe aucune copie des ACL propre aux processus.

Le code interne est unique et immuable. Un lancement lit exclusivement le contenu courant.
Son XML, son graphe compilé et la révision documentaire sont figés dans le Run pour
l'observation et la reprise ; aucun paramètre de lancement ne sélectionne une version.
Une restauration produit une nouvelle sauvegarde documentaire.

Le profil `galaris.bpmn/v1` accepte Tasks, Tools déclarés, appels, XOR, AND,
FOR séquentiel et WHILE. Les boucles ont des corps structurés ;
les cycles bruts et les éléments BPMN non exécutables par ce moteur sont refusés.
Les appels de processus utilisent des Runs enfants durables, sans récursion Python
ni profondeur métier maximale. L'ordonnanceur Task garde la responsabilité des leases,
des slots de harnais et de l'attente collaborative.

Chaque tentative d'activité possède une intention et une identité persistées avant
l'effet. Les admissions Tasks/Runs se réattachent avec cette identité après interruption.
Une opération Tool sans reçu certain ne se rejoue pas automatiquement. Les Tools passent
par la gouvernance MCP commune et les Connections ; les agents ne reçoivent pas les secrets.
Une API REST doit être une opération déclarée d'un Tool connecté, jamais une URL libre
dans le graphe. L'exécuteur de programmes documentaires possède un port public distinct,
activable seulement par son module qualifié.

Chaque Run possède un Document Dataset privé distinct de la définition. Son objet JSON
est initialisé avec les données du lancement et devient le pool commun modifiable de
toutes ses tâches. La collection de pièces jointes appartient à ce même Dataset. Le moteur
conserve ses états et reçus dans Process et ne réécrit pas le JSON. Le partage du Dataset
reste indépendant : lire une définition n'autorise pas à lire tous ses Runs.
Les processus sans propriétaire actif passent par une politique documentaire transversale
qui réserve leur accès aux administrateurs humains PROCESS_ADMIN.

L'éditeur visuel et l'observateur de Runs consomment les mêmes graphes typés. Les métriques
réutilisent les LLMCalls existants et distinguent coût direct, inclusif, estimé ou indisponible.
L'absence de corrélation est visible et n'est jamais convertie en coût nul.
Pause, pas à pas et points d'arrêt sont persistés ; ils contrôlent les nouvelles admissions.

Le Lab possède les campagnes réelles et les entrées synthétiques. Les cas ont une identité
durable, les campagnes une lease et les résultats conservent les preuves des Runs exécutés.
Les mocks externes restent une seconde phase, conformément à la demande utilisateur.
Il n'y a aucun budget Process v1 de coût, tokens, durée, profondeur ou itérations.
Les limites de parsing/transport et les quanta de scheduling sont des protections techniques.

Les dépendances supplémentaires passent par les ports publics Memory, Task, Tools et Process.
Le fan-out autorisé de Process augmente pour inclure son propriétaire documentaire Memory ;
aucun import privé ni cycle supplémentaire n'est accepté. Revue explicite de la dépendance
frontend `app/process → app/memory` : l'éditeur utilise uniquement l'export public du
composant de partage et ses types, avec les routes Process autorisées injectées. Cette
dépendance intentionnelle réalise le partage documentaire identique demandé et figure
dans le contrat frontend ; elle ne donne aucun accès aux services internes Memory.

### Acteurs nommés et travail humain — 2026-10-12

Les définitions portent des acteurs typés agent/humain et leur affectation ; les activités
référencent ces rôles et le diagramme les représente en lignes. Les affectations et types
survivent au XML et au snapshot de Run. Les tâches humaines sont des `userTask` BPMN,
avec intention et reçu dans les tentatives du domaine Process, sans admission IA.
La boîte d'activités expose le pool commun à l'utilisateur affecté ; la fin d'activité
reste réservée à cet utilisateur et sa réponse est idempotente.
Les agents affectés sont contrôlés dans le périmètre du lanceur et reçoivent un accès
Dataset en écriture via le port Memory contrôlé par les métadonnées moteur, comme les
humains affectés. Les pools des autres Runs restent distincts.

### Pool commun sans contrats de données — 2026-10-13

La demande utilisateur retire les affectations d'entrée/sortie, schémas JSON, formats
de résultat imposés et slots de fichiers requis. Les anciennes déclarations de ces champs
sont ignorées à la lecture, puis disparaissent lors de la prochaine sauvegarde. Les
instructions des tâches indiquent les URI communes. Les conditions et boucles lisent
le JSON courant via `data`. Les révisions documentaires existantes protègent les écritures
concurrentes ; une tâche doit relire après conflit et préserver les modifications reçues.
La sortie du Run est le contenu du Dataset à sa fin. Les appels initialisent un pool
enfant distinct avec les données et fichiers courants du parent, sans recopie automatique
des modifications de l'enfant. Les arguments des opérations Tool restent configurables.

### Arrêt à la première erreur — 2026-10-13

La demande utilisateur retire les traitements d'erreur globaux et locaux ainsi que les
réessais automatiques du moteur Process. À la première erreur d'exécution, aucune
nouvelle activité n'est admise et les tâches/Runs enfants actifs reçoivent une demande
d'arrêt. Après confirmation des arrêts, le run termine en erreur avec son `error_code`.
Les codes des exécuteurs et enfants sont conservés ; l'erreur d'activité générique est
`node_failed`. Le Dataset et ses pièces jointes sont préservés. Un effet externe incertain
renvoie `effect_outcome_unknown` et conserve l'arrêt en cours jusqu'à confirmation.
Les anciennes configurations de secours sont ignorées et leurs branches exclusivement
réservées à la récupération sont retirées à la lecture d'une ancienne définition.
