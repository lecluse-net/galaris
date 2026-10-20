<p align="right"><strong>Français</strong> · <a href="../../en/dev/native-processes.md">English</a></p>

# Profils BPMN natifs et contrats de données

## Propriété des ressources

Le BPMN courant est stocké directement dans `process_definitions.bpmn_xml`.
Process possède ses révisions (`process_definition_revisions`) et autorise ses ressources
avant de déléguer les droits à `app.share`. `process_definition_grants` reste une source
historique de migration, sans écriture métier. Créer, modifier, partager ou restaurer une définition
ne crée ni ne modifie de Document. Les Documents sont du HTML et les Datasets du JSON.
Les lancements figent le BPMN, le graphe et la révision sans référence documentaire.

L'action DbAdmin `app.process.native_definition_storage` transfère les anciennes
définitions, leurs révisions et leurs droits par lots transactionnels. Elle détache
l'ancien FK documentaire et archive les sources uniquement après copie. Un échec
conserve les sources du lot ; le rejeu ne duplique ni historique ni droits. L'ancien
champ nullable `document_id` reste réservé à cette reprise de migration.

## Profil typé v2

Les nouvelles définitions de l'éditeur utilisent `galaris.bpmn/v2`. Les profils sont figés
dans les snapshots : enregistrer ou convertir une définition ne modifie pas un run admis.
La conversion d'une définition v1 est explicite et initialise des listes à configurer.

Le graphe et chaque activité (`task`, `human_task`, `tool_call`, `rest`, `code`, `program`,
`call`) déclarent `inputs` et `outputs`, éventuellement vides. Chaque variable contient
`name`, `type`, `nullable` et un `default` typé facultatif. Noms dupliqués, défauts mal typés
et défauts nuls notnull sont refusés à la sauvegarde. Les valeurs suivent l'enveloppe
`{"type":"int","value":7}` ; types : int, float, string, bool, Agent, File, User, Document,
array et object. Les conteneurs sont récursifs et chaque élément reste typé.
Tous les types représentent `null`. Une omission utilise d'abord le défaut, sinon un null
typé si nullable, sinon produit une erreur. Un null explicite n'utilise jamais le défaut.
False, zéro et vides sont conservés ; les entiers restent dans la plage exacte ±(2^53−1).
Le codec borne taille/profondeur et refuse les clés JSON dupliquées et les conversions implicites.

Le moteur prépare et fige les entrées locales, contrôle les sorties avant intégration,
puis écrit atomiquement le delta fonctionnel dans `process_runs.data`, les liens dans
`process_run_files` et son reçu dans `process_runs.execution_state`.
Les tâches IA remettent leurs résultats
avec `process_activity_complete(output={...}, message="...")` : les valeurs JSON ordinaires
sont converties et validées selon les sorties déclarées, indépendamment du texte final du driver.
Une activité sans sortie peut terminer avec un message naturel. Les anciennes réponses JSON
typées restent acceptées. Les humains répondent par la messagerie. Les écritures
directes des données typées du run sont refusées. Un reçu d'intégration permet la reprise sans réexécution ;
les changements disjoints sont préservés et les conflits d'une variable sont explicites.

`process_activity_question` ouvre une demande au lanceur humain authentifié, dans la
conversation d'origine. L'attente appartient à l'activité ; aucune Task auxiliaire n'est
créée. La Task IA existante est suspendue pour raison `input`, puis reprend avec la réponse.
Le contexte de reprise associe explicitement la question et sa réponse typée. Une nouvelle
formulation pour les mêmes variables restitue la réponse déjà reçue sans créer d'attente ;
une nouvelle `question_key` stable demande volontairement une nouvelle réponse et reste
identique lors des retries. Des variables différentes
permettent de demander d'autres informations dans la même activité.
Les réponses précédentes restent des reçus de l'activité : un réessai d'une ancienne clé
ou une réponse identique ne modifie jamais la question suivante. L'historique local est borné
à 2 Mo et n'est pas transmis aux activités suivantes. Découverte, livraison et retrait
contrôlent l'identité de la question, en plus de celle de la tentative.
Le lanceur du processus porte les échanges humains dans sa conversation d'origine, même
si l'activité est exécutée par un autre agent ; la réponse réveille la Task de cet exécutant.
`conversation_process_respond` reçoit des valeurs JSON ordinaires comme `{"age": 27}` ;
Conversation les valide et les convertit en valeurs typées avant de contrôler les fichiers.
`typed_values: true` permet les enveloppes historiques, notamment pour les objets ; un objet
JSON ordinaire contenant `type` et `value` reste sinon un objet métier.
La réponse et le reçu Messenger sont atomiques, y compris pour les doublons et les réponses
arrivées avant la fin du tour IA. Une pause utilisateur reste prioritaire. Chaque
question est corrélée et idempotente. L'activité termine après la reprise et la remise
des résultats. Le contexte en lecture seule contient aussi les données du run, même sans
entrées locales déclarées. Les couloirs d'acteurs inutilisés ne bloquent pas le lancement.
Les anciennes Tasks d'attente inertes sont retirées lors de l'observation du run ou de la
réponse ; la question et sa référence restent conservées, sans nouvelle exécution.

Après un tour réussi, la finalisation conserve le nettoyage de l'identité et du checkpoint
effectué par la façade Agent. Le rafraîchissement des réponses concurrentes applique les
changements locaux aux données fraîches au lieu de restaurer l'ancien checkpoint.
La réponse humaine déclenche un nouveau tour du harnais sur la même Task ; un checkpoint
interrompu ou en attente d'autorisation conserve sa politique de reprise et ses reçus.
Après une perte de transport, observer le résultat de l'ancien tour ne signifie pas que
ce tour a lu la réponse reçue entre-temps. Le marqueur d'attente conserve l'identité du
tour qui a posé la question ; sa réconciliation laisse un nouveau tour prêt à utiliser
la réponse. Un résultat explicitement remis après consommation de la réponse peut terminer
dans le même tour. Le retrait asynchrone d'une ancienne demande ne ferme pas la suivante,
même après un échec de transport et un rollback.
À l'admission du tour, la Task recharge sous son lease les données et la révision courantes
avant d'appliquer ses changements locaux. Une réponse arrivée pendant la préparation du
contexte ne provoque donc pas de conflit de version ; une pause humaine concurrente interdit
le départ du tour.

`config.input_mapping` prépare les noms locaux avec des feuilles `{"$expr":"data.source"}`.
MCP et REST adaptent explicitement les valeurs aux contrats externes. `external_output`
associe la réponse brute (`result`) aux noms déclarés. `external_output_typed: true` indique
explicitement que ce mapping fournit déjà des enveloppes typées ; les objets métier ordinaires
contenant des clés `type` et `value` restent sinon des objets. REST utilise `tool_code` et `request`
avec la façade Tools existante et l'agent exécutant ; les erreurs HTTP sont conservées.
Les appels d'enfants typés transmettent les entrées locales ; les autres contrats reçoivent
leur JSON ordinaire. Les prédécesseurs activés convergent sans gateway imposée, y compris
après des splits imbriqués ; une branche IF non choisie ne bloque pas la convergence.
Les fichiers conservent leur URI source : aucun transfert automatique n'accompagne le
passage entre tâches. Un lien ne confère aucun droit sur la ressource.

Les IF configurés possèdent exactement deux sorties : `decision` pour True et une sortie
sans condition pour False. `config.mode` vaut `ai`, `code` ou `human`. Un acteur IA autorise
IA ou code ; un acteur humain impose humain. Les tentatives durables exigent un booléen
`decision`, sans l'intégrer aux variables du run. Le choix humain passe par les boutons True/False
de Messenger, sans Task IA d'attente. Les IF historiques sans mode conservent leurs expressions.

Les phases `preprocess`, `code` et `postprocess` utilisent `IsolatedCodeRunner`. L'adapter
Monty démarre un worker neuf par invocation : sous-ensemble Python sans montage, réseau,
fonction externe ni objet hôte. Limites : 32 Mo par VM, une seconde d'exécution, trois secondes
par requête et deux workers simultanés. Le worker est fermé avant l'utilisation du résultat.
Les intentions et reçus sont persistés ; seule une computation pure peut être recalculée
après perte de son résultat. L'intégration Process reste idempotente. Une phase absente conserve
son comportement par défaut ; une phase enregistrée vide prépare ou intègre des valeurs vides.

Avec `dataset_code: true`, la tâche reçoit un snapshot JSON détaché des données du run. Les clés
utilisables comme identifiants Python deviennent des paramètres locaux ; toutes les clés restent
accessibles par `dataset["nom"]`. Un IF peut utiliser `return variable_2 != "pas mon projet"` ;
une tâche retourne un dictionnaire de sorties ordinaires, converties et validées avant intégration.
Les données ne sont jamais interpolées dans le code. Ce runner ne fournit ni CPython généraliste,
ni packages tiers, ni capacités MCP/REST. L'exécution arbitraire sur VM/hôte distinct et son broker
de capacités restent hors de ce périmètre.

## Profil historique v1

`app.process.bpmn` compile le XML BPMN MODEL, extensions Galaris et placement BPMN DI,
vers le schéma `galaris.bpmn/v1`. Ce profil est un sous-ensemble exécutable explicite
de BPMN : les autres éléments sont refusés. Un graphe contient `nodes`, `flows` et
ses acteurs ; ses identifiants sont uniques, même dans
les corps imbriqués. Il a un début, au moins une fin, aucun nœud inaccessible ni cycle
brut. Les cycles métier utilisent FOR/WHILE structurés.

| Nœud | Configuration |
|---|---|
| `task` / `human_task` | `prompt`, acteur facultatif pour l'agent ; accès automatique au pool du run. |
| `if` | Conditions sur les flows, exactement une sortie par défaut sans condition. |
| `parallel` | Compatibilité des passerelles existantes ; non proposé à l'ajout. Les sorties multiples et la convergence des activités expriment le parallélisme du profil v2. |
| `for` | Expression de tableau `items`, `body` séquentiel. |
| `while` | `condition` testée avant chaque passage du `body`. |
| `call` | `process_code` ; données et fichiers actuels copiés vers le run enfant, dernière sauvegarde à l'admission. |
| `tool_call` | Opération MCP déclarée `tool`, arguments `input`, gouvernance commune. |
| `program` | `program_uri` et exécuteur qualifié enregistré par son module propriétaire. |
| `end` | Termine le flux ; sortie égale au JSON courant du run. |

Les arguments des outils peuvent utiliser `{"$expr": "data.amount"}`. Le contexte contient
`input`, `data`, `results`, `files`, puis selon l'activité `output`, `error`, `item`,
`index`. Arithmétique simple, booléens, comparaisons et accès JSON sont autorisés ;
appels, attributs privés, comprehensions et exponentiation sont refusés. Un champ absent
est nul ; même les branches court-circuitées sont validées. `data` est relu dans le
run avant chaque activité et condition. Les anciens schémas, affectations et
formats de résultat sont retirés à la lecture d'une définition, sans effet caché.

Chaque run possède son JSON métier dans `process_runs.data` et ses liens de fichiers dans
`process_run_files`, sans Dataset ni Document. Les données et pièces jointes héritent des
droits du processus. Les tâches v1 peuvent écrire `galaris://processes/runs/<uuid>/data` avec
`expected_revision` et utiliser `galaris://processes/runs/<uuid>/attachments/` pour les fichiers.
Le moteur ne réécrit pas les modifications v1. États et reçus restent séparés des variables.
Les URI canoniques ne contiennent jamais de token ou d'URL de transport.
La première erreur d'exécution interdit toute nouvelle admission et demande l'arrêt
des tâches et Runs enfants actifs. Une fois les arrêts confirmés, le run termine en
`error`. `error_code` est renvoyé dans l'inspection et affiché dans le suivi ; un code
fourni par un moteur enfant est conservé, sinon l'échec d'activité est `node_failed`.
Les anciens `catch`, `retry` et `error_handler` sont ignorés ; les branches réservées
à leurs traitements de secours sont retirées à la lecture des anciennes définitions.
Un effet Tool ambigu n'est pas rejoué. Une écriture sur une révision dépassée échoue ;
la tâche relit puis réapplique sa modification en préservant les autres données.
Un effet ambigu arrête aussi les nouvelles admissions et demande l'arrêt du run,
avec le code `effect_outcome_unknown`. Le debugger refuse reprise/pas avant réconciliation ; l'arrêt
reste incertaine tant que l'arrêt externe n'est pas confirmé.
Les activités Tool ont une Task de contexte non agentique, sous lease et soumise à la
capacité du harnais. Une demande d'autorisation suspend cette Task ; sa décision reprend
la même tentative, tandis qu'un refus connu ferme proprement Task et tentative.

Les routes `/api/processes/internal` exposent définitions, validation, histoire,
restauration, partage, lancement, runs, occurrences, enfants, métriques et debugger.
PROCESS_READ/EDIT/LAUNCH/ADMIN se combinent avec les ACL. Les MCP personnels `galaris`
exposent ces opérations, dont `process_definition_read` pour l'audit.
Les commandes de debugger acceptent `command_key` (UUID) et `expected_revision`.
La projection `operational` de l'inspection est partagée avec `processus_get` : phases,
compteurs d'occurrences, attentes documentées, dernière activité et actions disponibles.
La lecture n'avance pas le moteur et ne déduit aucun blocage d'un simple délai.
Les droits de lecture et d'écriture du processus s'appliquent à ses runs, données et
pièces jointes. Partage et révocation sont immédiats, y compris pour les runs existants.
Aucun nouveau privilège ni grant de run n'est créé. La connexion dédiée `process_admin`
conserve son rôle d'administration. Les filtres précèdent comptage/pagination, enfants
et métriques inclusives. Les snapshots de participants décrivent les affectations sans
constituer une ACL distincte. Voir la [décision 0198](../../../project/decisions/0198-process-run-data-and-files.md).
Leur reçu est enregistré avec la modification ; retransmettre la même commande après
une réponse perdue rend ce reçu sans effectuer un second pas. L'interface conserve
la clé tant que la réponse est incertaine et détecte les commandes concurrentes.

Les métriques distinguent coût facturé et valeur d'inférence, notamment pour les
abonnements. Elles exposent les totaux directs/inclusifs, par Task et par occurrence
exacte (boucles et retries compris), la devise USD et la date du calcul. Les descendants
non autorisés sont exclus et le total visible est marqué partiel. Le temps écoulé du
run part de l'admission ; les durées cumulées d'appels LLM restent une mesure séparée,
sans prétendre mesurer les traitements distants non corrélés.

L'initialisation des données du run est idempotente. En v1, les fichiers entrants sont
matérialisés via File Sharing puis publiés dans `core.storage` et liés par
`process_run_files.file_id`. Liens et reçus de copie sont atomiques ; une reprise
réutilise les reçus. Les URI exposées sont `galaris://processes/runs/<uuid>/attachments/<file-uuid>`.
Les références conservent URI d'origine, MIME et SHA-256. En v2, les références externes
conservent leur provider sans copie. Une révocation ou annulation pendant la préparation
n'admet aucune tâche.
Les métadonnées moteur sont réservées au serveur. Les leases et quanta courts ne sont
pas des budgets métier ; il n'y a pas de plafond Process de coût, tokens, durée,
itérations ou profondeur. Les programmes documentaires restent conditionnels à leur
exécuteur. Les runs natifs/enfants sont exclus de la purge automatique externe.

Les reçus d'intégration et de préparation des fichiers sont
propres au run : aucun état d'exécution n'est écrit dans le contenu ou les métadonnées
des variables métier. Les processus internes n'ont jamais été déployés : aucune migration
de reçus ni table de transition n'est conservée.
Voir la [décision 0196](../../../project/decisions/0196-process-run-execution-state.md).

Voir la [décision 0197 sur le stockage BPMN](../../../project/decisions/0197-process-owned-bpmn-storage.md)
et la [décision 0174 sur le socle d'exécution](../../../project/decisions/0174-native-document-backed-business-processes.md)
et le [parcours utilisateur](../user/internal-processes.md).

## Acteurs et activités humaines

`execution_agent_id` est facultatif et nul par défaut. Les tâches utilisent l'agent du
lancement, sauf agent imposé par ce champ ou affectation explicite sur leur acteur (prioritaire).
Les corps de boucle héritent de ce défaut ; chaque processus appelé applique sa propre
définition. Le XML et le snapshot du run conservent ce champ. L'agent lance le processus
depuis le Chat ; les pages Process ne proposent pas de lancement manuel.

`actors` contient des rôles locaux au graphe : `id`, `name`, `kind: agent/human`,
`agent_id` ou `user_id`. `config.actor` référence le rôle. `task` exige un acteur agent
si renseigné ; `human_task` exige un acteur humain. Le XML conserve ces affectations
et exporte des `laneSet/lane/flowNodeRef` ainsi que `userTask`. Dans le profil typé, les tâches
et IF adoptent le traitement humain sur une ligne humaine et IA/code sur une ligne agent.
Les définitions historiques conservent le refus des changements de type incompatibles.
Les anciens graphes sans acteurs restent valides.
L'admission vérifie le périmètre des agents et l'activité des utilisateurs ; le moteur
revérifie ces droits avant un nouvel effet. Les droits de données et fichiers sont ceux du processus parent ; l'affectation ne crée
aucun grant supplémentaire.

Une tentative humaine persiste `human_waiting`, ses instructions, entrées et son utilisateur
affecté avant toute réponse. L'outbox Process appelle un port de messagerie enregistré au
bootstrap. Conversation utilise les interactions canoniques Messenger : conversation de
lancement si son auteur est l'affecté, sinon contact joignable, puis Chat privé comme repli.
L'affectation reste un utilisateur Galaris actif ; une identité externe doit être reliée à
ce compte. Les routes `/human-work` et son formulaire sont retirés.

La demande `process_human_activity` exige une interprétation : le matcher déterministe ne
consomme jamais le prochain message arbitrairement. Le contexte conversationnel expose les
attentes de la portée exacte agent/connexion/Tool/room/auteur. `conversation_process_pending`
fournit les contrats complets et la pagination ; `conversation_process_respond` reçoit la
référence choisie et les sorties typées. Les pièces jointes seules restent dans l'historique
avec leur URI source ; les valeurs `File` sont vérifiées par File Sharing, sans téléchargement
ni copie persistante. Une réponse incomplète ou ambiguë appelle une clarification.

L'enregistrement verrouille l'interaction, le Run puis la tentative ; sorties, utilisateur
actif et annulation sont revérifiés. Le résultat et le reçu Messenger sont commités ensemble.
Le même résultat est idempotent ; un résultat différent crée un conflit. Les erreurs de
livraison sont reprises sans abandonner l'attente. Les demandes devenues caduques sont retirées.
