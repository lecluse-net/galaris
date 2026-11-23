<p align="right"><strong>Français</strong> · <a href="../../en/dev/native-processes.md">English</a></p>

# Profils BPMN natifs et contrats de données

Les campagnes du Lab conservent leurs entrées synthétiques dans `app.dataset`,
via sa façade publique : `dataset_id`, révision et URI `data://`. Elles ne créent
pas de Document. À l'admission, les droits sont vérifiés et les cas sont figés.
La FK native `lab_process_campaigns.dataset_id` est additive ; l'ancienne FK
nullable `dataset_document_id` préserve les campagnes existantes. Une contrainte
impose exactement une source. Voir la décision
[0225](../../../project/decisions/0225-process-lab-native-datasets.md).

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

Le graphe racine déclare un registre unique `variables`. Les activités et les corps
FOR/WHILE utilisent ce registre et ne déclarent aucune variable locale. Chaque variable contient
`name`, `type`, `nullable` et un `default` typé facultatif. Noms dupliqués, défauts mal typés
et défauts nuls notnull sont refusés à la sauvegarde. Les valeurs suivent l'enveloppe
`{"type":"int","value":7}`. Le codec commun prend en charge les scalaires, `array`, `object`
et les références métier. `Agent`, `User`, `Team`, `Service`, `Connection`, `Model` et `Skill`
portent un identifiant entier positif ; `Topic`, `Conversation` et `VoiceSession` un UUID.
`Task`, `Goal`, `GoalCycle`, `Contact`, `ConversationRound`, `VoiceConversation` et `CodeWorkspace`
emploient leurs URI `galaris://` existantes (`task`, `goal`, `goal_cycle`, `contact`, `text`, `voice`, `code`).
`Process` utilise `galaris://process/<code>`, `ProcessRun` utilise
`galaris://processes/runs/<uuid>` et `Memory` utilise `memory://<uuid>`.
Les conteneurs sont récursifs et chaque élément reste typé. Le sélecteur humain masque
les types techniques demandés ; cette présentation ne change pas le format des références.

`date` contient une date civile valide sous forme de chaîne `AAAA-MM-JJ`, sans heure ni fuseau
(par exemple `{"type":"date","value":"2000-02-29"}` pour une naissance). `datetime` contient
une chaîne `AAAA-MM-JJTHH:mm:ss` avec un suffixe `Z` ou un décalage `±HH:mm` obligatoire ;
les fractions de seconde sont facultatives (1 à 6 chiffres). Les valeurs conservent leur fuseau
et leur représentation, sans conversion implicite. Les dates impossibles et les heures sans
fuseau sont refusées aux mêmes frontières que les autres valeurs typées, y compris les réponses humaines.

Chaque déclaration peut ajouter `label` (200 caractères) et `description` (4 000 caractères)
en texte brut. Ces métadonnées expliquent le sens métier au contrôleur et apparaissent sur
les cartes du run ; `name` reste la clé technique stable. Elles ne modifient pas le codec des valeurs.

Les listes `inputs` et `outputs` des nœuds autorisés référencent des noms de ce registre,
jamais des déclarations. Début et IF n'ont aucune sortie variable ; Fin n'a aucune entrée variable.
Les entrées du processus sont exactement les `inputs` du Début racine, sans liste indépendante
sur le graphe. Les sorties sont déduites des sélections des nœuds Fin racines, sans liste
indépendante. Le run retourne seulement les sorties des Fin effectivement atteintes.
Une liste vide ne transmet aucune variable. Les références inconnues
ou dupliquées sont refusées à la sauvegarde, y compris dans les corps de boucle. Le lancement
accepte uniquement les entrées sélectionnées du processus ; sa sortie expose uniquement ses
sorties sélectionnées et renseignées. Les autres valeurs restent visibles dans les données du run.
Chaque activité reçoit ses entrées sélectionnées et peut modifier uniquement ses sorties
sélectionnées, y compris après post-traitement. Les mappages adaptent les paramètres externes
sans créer de variable locale. Le résultat `decision` d'un IF reste exclusivement technique ;
il ne modifie aucune variable métier, même une variable du registre portant ce nom.
Les sélections du processus et de ses étapes sont figées dans le snapshot de lancement.

Une déclaration `Document` accepte `document://<uuid>` ou `data://<uuid>` et peut préciser
son code dans `document_format` (`text`, `data` ou un autre format installé). Une déclaration `File` peut préciser `mime_type`, exact
ou par famille (`image/*`). Les contraintes ne conviennent qu'à leur type respectif.
La validation syntaxique et des défauts intervient à la sauvegarde. Au lancement et avant
les écritures, Process vérifie les métadonnées via File Sharing avec l'identité de l'exécutant,
sans télécharger le contenu. Les références ordinaires ne donnent jamais de droits supplémentaires.
Les défauts s'appliquent une seule fois au lancement. Toutes les entrées sélectionnées par
le Début racine doivent être fournies ou avoir un défaut déclaré, même si elles sont nullables.
Le serveur refuse un lancement incomplet avant de créer un run. Les autres variables sans
valeur restent absentes et pourront être renseignées par une activité. Un null explicite
exige `nullable` et n'utilise jamais le défaut. Une mise à jour omise conserve la valeur courante.
False, zéro et vides sont conservés ; les entiers restent dans la plage exacte ±(2^53−1).
Le codec borne taille/profondeur et refuse les clés JSON dupliquées et les conversions implicites.

En conversation, `conversation_process_prepare` conserve un dossier par processus et participant,
avec un run `waiting` dès que le lancement est demandé, sans activité ni job de démarrage.
Le contrat est figé sur ce run ; la collecte complète puis autorisée démarre ce même identifiant.
L'état opérationnel et les travaux en cours de l'agent indiquent les entrées encore attendues.
Une inférence structurée extrait les réponses et pièces jointes,
réutilise les valeurs acquises et propose les recherches puis les questions manquantes.
Le contrôleur recherche dans Memory et les fichiers autorisés et convertit les formats si nécessaire.
Un null ne remplace pas une information inconnue : hors défaut explicite, l'absence doit être
confirmée par les mots du participant. Annulation et changement de sujet ne lancent rien.
Le dossier complet rejoint l'autorisation de lancement existante ; les relances utilisent
l'historique réel et comptent les occurrences dans le message courant seulement.
Les entrées déjà complètes ou couvertes par défaut peuvent passer directement au lanceur.
Pour un dossier prêt, omettre `input` au lancement réutilise les valeurs typées persistées,
y compris les null imbriqués. Les validations de types et les relectures du même message ne
demandent pas d'inférence supplémentaire ; seuls les cas d'intention ou de périmètre à
réévaluer conservent le contrôle IA. Le service Process calcule lui-même les entrées manquantes
et interdit d'initialiser les variables non sélectionnées par Début depuis cette collecte.

Dans le run en attente, un utilisateur ayant le droit de lancement, le contrôle du processus
et la gestion de son agent lanceur peut compléter chaque entrée sélectionnée directement.
`PATCH /api/processes/internal/runs/{id}/inputs` reçoit `values`, `expected_revision` et
`start` (faux par défaut). Le dépôt d'un fichier utilise
`POST /api/processes/internal/runs/{id}/inputs/{name}/file` avec `upload` et la révision en query.
Les types, MIME et droits des ressources sont validés sans IA ; les fichiers déposés appartiennent
au run. L'enregistrement n'exécute rien. Une action Démarrer explicite libère ce même run complet ;
son rejeu identique ne crée pas de second job. Une révision dépassée renvoie 409 sans écraser
le brouillon. L'agent relit les contributions depuis le run ; une ancienne autorisation IA ne
couvre jamais ces nouvelles valeurs. Ces entrées initiales sont distinctes des activités humaines
en cours d'exécution, dont les réponses restent exclusivement dans Messenger.

Pendant une collecte, `file_search` peut rejouer une recherche identique pendant 30 secondes
dans le même message canonique. Les droits et versions des résultats sont revérifiés ;
`refresh=true` force une nouvelle recherche après un changement connu. Un nouveau message
invalide ce contexte. Les conversions PDF/image réutilisent un résultat seulement pour les mêmes
octets source, nom, format, page et destination, avec contrôle vivant de la source et du résultat.
File Sharing garde au plus 200 reçus par agent ; les conversions expirent après 30 jours.

La provenance d'entrée est conservée séparément dans `ProcessRun.input_provenance` et son
journal. Le champ est différé au niveau ORM ; les vues ordinaires des runs, leurs événements,
les dossiers conversationnels et les prompts n'embarquent pas cet audit. Il contient des
références/versions et des empreintes, sans copie des valeurs ou des documents, ni appel IA
supplémentaire. Les métadonnées de fichiers déjà validées et les reçus de conversion sont réutilisés.
Les propositions scalaires gardent leur origine agent/conversation ; aucune source Memory précise
n'est inventée lorsque cette filiation n'est pas établie.

`GET /api/processes/internal/runs/{id}/inputs/provenance?name=...` lit une seule variable.
`history=true` ajoute une page d'historique (`page_size=50`, maximum 500 ; curseur `before`).
L'agent peut aussi utiliser `file_read` sur
`galaris://processes/runs/<uuid>/input-provenance/<nom-encodé>`, sans nouvel outil MCP.
Les lectures exigent les droits du parent et le périmètre de l'agent lanceur. Les sources
indisponibles ou révoquées sont masquées ; l'historique borne les vérifications à 16 références
distinctes par réponse, avec deux secondes maximum par vérification. Les anciens runs ne
reçoivent aucune provenance reconstituée arbitrairement.

Les lancements MCP `process_start` et `conversation_process_start` acceptent des entrées JSON
ordinaires, par exemple `input={"age": 27, "scan": "file://<uuid>"}`. Process les convertit
selon les variables sélectionnées par Début, avant les défauts et les contrôles de fichiers.
Les enveloppes historiques scalaires restent acceptées ; `typed_values: true` sélectionne
explicitement le transport typé, y compris pour les objets. Sans cet indicateur, un objet
contenant `type` et `value` reste un objet métier. L'autorisation conversationnelle fige aussi
cet indicateur. Un refus avant création d'un run peut être suivi d'une demande explicite de
réessai ; la reprise d'un run déjà créé n'autorise pas un nouveau lancement.

Le moteur prépare et fige les entrées locales, contrôle les sorties avant intégration,
puis écrit atomiquement le delta fonctionnel dans `process_runs.data`, les liens dans
`process_run_files` et son reçu dans `process_runs.execution_state`.
Les tâches IA remettent leurs résultats
avec `process_activity_complete(output={...}, message="...")` : les valeurs JSON ordinaires
sont converties et validées selon les variables du processus, indépendamment du texte final du driver.
Un objet vide n'apporte aucune modification. Les anciennes réponses JSON
typées restent acceptées. Les humains répondent par la messagerie. Les écritures
directes des données typées du run sont refusées. Un reçu d'intégration permet la reprise sans réexécution ;
les changements disjoints sont préservés et les conflits d'une variable sont explicites.

Les prompts IA portent un contrat JSON figé avec les noms, types, contraintes et valeurs
typées des seules entrées sélectionnées, ainsi qu'un indicateur explicite pour les valeurs
non initialisées. Les fichiers et documents gardent leurs URI canoniques, y compris dans
les conteneurs ; les paramètres préparés sont ajoutés séparément si un mappage les transforme.
Les sorties attendues indiquent leurs noms exacts, types, nullabilité, sous-type documentaire
et MIME éventuels, sans présenter les défauts comme résultats à produire. Ce contrat est
conservé dans le prompt de la tentative et dans l'objectif de la tâche agentique. Les IF en
LLM simple réutilisent le même prompt préparé, avec seulement un résultat de contrôle booléen
et aucune sortie métier. Sans outils, une URI reste une référence et ne vaut pas lecture du contenu.

`process_activity_question(variables=["age"])` sélectionne des noms du registre du processus,
sans créer de nouvelles déclarations, et ouvre une demande au lanceur humain authentifié, dans la
conversation d'origine. L'attente appartient à l'activité ; aucune tâche auxiliaire n'est
créée. La tâche IA existante est suspendue pour raison `input`, puis reprend avec la réponse.
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
si l'activité est exécutée par un autre agent ; la réponse réveille la tâche de cet exécutant.
`conversation_process_respond` reçoit des valeurs JSON ordinaires comme `{"age": 27}` ;
Conversation les valide et les convertit en valeurs typées avant de contrôler les fichiers.
`typed_values: true` permet les enveloppes historiques, notamment pour les objets ; un objet
JSON ordinaire contenant `type` et `value` reste sinon un objet métier.
La réponse et le reçu Messenger sont atomiques, y compris pour les doublons et les réponses
arrivées avant la fin du tour IA. Une pause utilisateur reste prioritaire. Chaque
question est corrélée et idempotente. L'activité termine après la reprise et la remise
des résultats. Le contexte en lecture seule contient aussi les données du run.
Les couloirs d'acteurs inutilisés ne bloquent pas le lancement.
Les anciennes tâches d'attente inertes sont retirées lors de l'observation du run ou de la
réponse ; la question et sa référence restent conservées, sans nouvelle exécution.

Après un tour réussi, la finalisation conserve le nettoyage de l'identité et du checkpoint
effectué par la façade Agent. Le rafraîchissement des réponses concurrentes applique les
changements locaux aux données fraîches au lieu de restaurer l'ancien checkpoint.
La réponse humaine déclenche un nouveau tour du harnais sur la même tâche ; un checkpoint
interrompu ou en attente d'autorisation conserve sa politique de reprise et ses reçus.
Après une perte de transport, observer le résultat de l'ancien tour ne signifie pas que
ce tour a lu la réponse reçue entre-temps. Le marqueur d'attente conserve l'identité du
tour qui a posé la question ; sa réconciliation laisse un nouveau tour prêt à utiliser
la réponse. Un résultat explicitement remis après consommation de la réponse peut terminer
dans le même tour. Le retrait asynchrone d'une ancienne demande ne ferme pas la suivante,
même après un échec de transport et un rollback.
À l'admission du tour, la tâche recharge sous son lease les données et la révision courantes
avant d'appliquer ses changements locaux. Une réponse arrivée pendant la préparation du
contexte ne provoque donc pas de conflit de version ; une pause humaine concurrente interdit
le départ du tour.

`config.input_mapping` prépare les noms locaux avec des feuilles `{"$expr":"data.source"}`.
MCP et REST adaptent explicitement les valeurs aux contrats externes. `external_output`
associe la réponse brute (`result`) aux noms déclarés. `external_output_typed: true` indique
explicitement que ce mapping fournit déjà des enveloppes typées ; les objets métier ordinaires
contenant des clés `type` et `value` restent sinon des objets. REST utilise `service_code` et `request`
avec la façade Services existante et l'agent exécutant ; les erreurs HTTP sont conservées.
Les appels d'enfants typés transmettent les entrées locales ; les autres contrats reçoivent
leur JSON ordinaire. Les prédécesseurs activés convergent sans gateway imposée, y compris
après des splits imbriqués ; une branche IF non choisie ne bloque pas la convergence.
Les fichiers conservent leur URI source : aucun transfert automatique n'accompagne le
passage entre tâches. Un lien ne confère aucun droit sur la ressource.

Le profil v2 compile les `intermediateCatchEvent` de type timer ou message,
`eventBasedGateway` et `boundaryEvent` d’erreur. Un timer accepte un délai
de 1 à 31 536 000 secondes, une date ISO 8601 avec fuseau ou une entrée `datetime`.
Un message attend `event_name` et une `correlation_variable` parmi ses entrées
`string`. Les valeurs et l’échéance absolue sont figées dans l’occurrence à son
admission. La passerelle arme au moins deux attentes distinctes simultanément, puis seule
l’attente gagnante se poursuit. Un délai déjà écoulé prime sur un signal reçu ensuite.
Quand toutes les occurrences actives sont en attente d’événement, le prochain passage
du planificateur est fixé à la première échéance ou réactivé par un signal reçu.

Utiliser `POST /api/processes/internal/runs/{run_id}/events` ou `process_run_signal`
avec `event_id` (UUID source), `name` et `correlation`. Il faut le droit de
contrôler le run désigné et une unique attente active correspondante. Un signal reçu avant
l’armement n’est pas mis en file. La réception et son reçu de déduplication sont persistés
ensemble sous le verrou du run. La pause laisse les attentes armées se résoudre mais
retient l’admission de leurs successeurs. L’annulation retire les attentes. Galaris
expose ce contrat pour les producteurs d’événements à configurer.

Une activité peut avoir un événement limite d’erreur, en plus de sa continuation normale.
La branche intercepte les erreurs qualifiées par le moteur natif, actuellement les HTTP
`4xx` hors `408`, `425` et `429`, et les échecs confirmés d’un calcul Monty.
`error_code` permet de filtrer le code. L’occurrence source garde l’erreur et
le journal conserve `node.error.caught`. Voir [0307](../../../project/decisions/0307-native-process-events.md).

Les IF configurés possèdent exactement deux sorties : `decision` pour True et une sortie
sans condition pour False. Le menu propose IF Python (`config.mode: code`), IF LLM décisionnel
(`mode: ai`, `ai_mode: llm`) et IF Humain (`mode: human`, avec un acteur humain).
Les tentatives durables exigent un booléen `decision`, sans l'intégrer aux variables du run.
Pour un IF humain, `prompt` fixe la question ou `human_prompt_variable` désigne une entrée
sélectionnée de type `string`. Une activité précédente peut construire cette entrée. Le texte
est figé avant l'envoi des boutons Oui/Non dans Messenger. Les IF agentiques historiques et
les IF historiques sans mode restent exécutables avec leur comportement d'origine.

Pour un IF `mode: ai`, `config.ai_mode` vaut `task` (défaut historique) ou `llm`.
Le sous-mode `llm` utilise `config.llm_profile` avec `model_field: decision_llm_id`.
`profile_id` et `fallback_profile_id` omis ou nuls héritent du profil courant et du profil de
secours par défaut. Le secours utilise sa propre colonne Décision après un échec récupérable.
Les anciens `llm_id` restent exécutables avec leur sélection directe. L'identité de l'inférence
reste liée à l'occurrence et un reçu acquis est réutilisé après reprise. L'annulation attend
l'arrêt de l'inférence. Les appels restent corrélés au run et à la tentative pour les coûts.
Voir [0231](../../../project/decisions/0231-native-if-ai-execution-modes.md).

Les tâches typées proposent quatre traitements : `task` agentique (défaut), `task` avec
`ai_mode: llm`, `code` et `human_task`. Les tâches LLM sélectionnent dans `llm_profile`
un niveau de texte parmi ultra low, low, standard et high, partagé par les deux profils.
Chaque profil fournit le modèle et l'effort de raisonnement de ce niveau. L'inférence durable
applique le secours de profil sur les échecs fournisseur éligibles et conserve un budget
d'une requête logique, sans réessai de sortie. Leur contrat
structuré est `{"output": {...}}` en valeurs JSON ordinaires ; Process le convertit selon
les seules sorties sélectionnées puis applique son intégration atomique habituelle.
Elles exigent un modèle texte et ne créent aucune Task. Code, tâches LLM et IF LLM/code
peuvent référencer tout acteur ou aucun. Les tâches agentiques et humaines conservent
leurs restrictions d'acteur ; déplacer un nœud ne change jamais son type.
Voir [0272](../../../project/decisions/0272-explicit-process-activity-types.md).

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
Les données passent par le snapshot JSON. Le calcul Monty utilise uniquement ses entrées locales.

<a id="python-capabilities"></a>

### Python isolé et capacités de Services

Le type `python` utilise CPython via un superviseur sur hôte dédié.
Le programme suit la même convention de retour et de variables que `code`. Le mode créé
par l'éditeur fournit aussi `input_files`, la liste des références des pièces jointes.
Le programme peut affecter ou compléter `output_files` avec des objets `{"uri": "..."}`
et continuer à renvoyer ses variables par `return`. Process vérifie les nouvelles URI
avec les droits de l'agent exécutant avant d'ajouter les références au manifeste.
Les variables métier portant un nom réservé (`input_files`, `output_files` ou `call_service`)
restent accessibles par `dataset["nom"]`. Les octets passent par les capacités déclarées
comme `file_read` et `file_create`.

L'éditeur signale
une configuration de runner manquante ou invalide. L'exécution échoue si le runner d'origine est indisponible
au-delà de sa fenêtre de réconciliation. Les phases de préparation et d'intégration utilisent Monty.

Le nœud peut déclarer jusqu'à seize capacités sous `config.capabilities`.

```json
{
  "lookup": {"kind": "mcp", "operation": "process_definition_read"},
  "items": {"kind": "rest", "operation": "synthetic_inventory"}
}
```

`call_service("lookup", {"process_code": "synthetic"})` rend la sortie MCP.
`call_service("items", {"method": "GET", "path": "items"})` rend le statut HTTP,
les en-têtes filtrés et le corps REST. Galaris vérifie les droits de l'agent exécutant
et les autorisations MCP en vigueur. Chaque appel possède une intention et un reçu liés
à l'exécution. Le broker refuse une nouvelle admission à partir de quinze minutes.
Il renvoie le reçu courant à l'identique pour une redélivrance du même appel. Il refuse
la réutilisation d'un identifiant remplacé ou accompagné de paramètres modifiés.
Si un effet externe a été admis et que son reçu manque, l'arrêt du runner conserve le
diagnostic `effect_outcome_unknown` et bloque la reprise en attendant une réconciliation.
Pour une création locale `file://` approuvée, Services peut confirmer la création dans
son journal. Le moteur utilise cette preuve liée à l'appel original pour terminer l'arrêt
et clôturer la Task de contexte sans recréer le fichier. Un appel sans preuve reste en attente.
La réponse MCP est persistée avant la clôture de sa Task de contexte. En cas d'interruption
à cette frontière, le worker poursuit la clôture à partir du reçu.

#### Réconciliation d'une insertion n8n

Pour une capacité REST de Python, réglez `rest_config.effect_receipt` sur `n8n_data_table_insert`
dans le Service, avec une URL de base se terminant par `/api/v1` et l'authentification
par en-tête `X-N8N-API-KEY`. La clé reste dans la Connexion active de l'agent exécutant et
autorise l'insertion et la lecture des lignes. Créez une colonne texte `operation_reference`
dans la Data Table. Le script appelle `POST data-tables/<id>/rows` avec une seule ligne
de valeurs scalaires dans `json_body.data`, sans ajouter cette colonne, d'en-tête ou de
paramètre de requête. Le broker ajoute une référence générée côté serveur et l'enregistre
avant l'envoi avec une empreinte de la requête et de la connexion effective.

Pendant l'arrêt, le worker cherche la référence par `GET` avec la connexion d'origine.
Une seule ligne portant la référence et les valeurs de la requête confirme l'insertion.
Une réponse absente ou contradictoire, ou un changement de clé ou de destination, laisse
le diagnostic actif. Le reçu confirmé clôt l'incertitude après l'arrêt de la sandbox.
Les autres opérations REST conservent le comportement générique. `make qualify-process-n8n`
exerce ce parcours avec une instance jetable de l'[API n8n Data Tables](https://github.com/n8n-io/n8n-docs/blob/main/docs/build/work-with-data/data-tables.md).

#### Déployer le superviseur

Utiliser une VM Linux dédiée avec Docker et le runtime `runsc`. Autoriser seulement
l'accès entrant TCP 8443 depuis le backend. Garder la VM hors des réseaux de l'API
et de PostgreSQL. Le superviseur utilise le socket Docker local pour créer et
supprimer les sandboxes. Chaque sandbox démarre avec un système de fichiers racine
en lecture seule, un répertoire temporaire borné et une seule interface loopback.
[Configuration gVisor pour Docker](https://gvisor.dev/docs/user_guide/quick_start/docker/) ·
[Réseau Docker none](https://docs.docker.com/engine/network/drivers/none/)

Construire les cibles `sandbox` et `supervisor`, puis publier et provisionner leurs
images par digest sur la VM.

```bash
docker build --target sandbox -t "$SANDBOX_TAG" process-runner
docker build --target supervisor -t "$SUPERVISOR_TAG" process-runner
```

Préparer un répertoire privé contenant `tls.crt`, `tls.key` et `token`. Le backend
doit faire confiance au certificat pour le nom DNS du runner. Utiliser un jeton
dédié aléatoire d'au moins 32 caractères ASCII. Utiliser un superviseur par daemon
Docker et conserver le volume nommé pour préserver les reçus après redémarrage.

```bash
docker run --name process-python-runner --restart unless-stopped \
  --publish "$RUNNER_BIND_IP:8443:8443" \
  --mount type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock \
  --mount "type=bind,src=$RUNNER_TLS_DIRECTORY,dst=/run/runner,readonly" \
  --mount type=volume,src=process-python-state,dst=/var/lib/process-runner \
  --env "PROCESS_PYTHON_IMAGE=$SANDBOX_IMAGE" "$SUPERVISOR_IMAGE"
```

Configurer `PROCESS_PYTHON_RUNNER_URL=https://<runner>:8443` et
`PROCESS_PYTHON_RUNNER_TOKEN` dans le backend. Les limites initiales sont quatre
sandboxes simultanées, 128 Mio de mémoire, un demi-cœur, 8 Mio de stockage temporaire,
quinze minutes et seize appels de capacité par exécution. Linux borne le groupe Docker
à 128 tâches, y compris les threads de gVisor et des hooks OCI. Dans la sandbox, Python
et ses descendants partagent une limite stricte de seize processus et threads.
Si le daemon Docker devient indisponible, le superviseur garde la place de la sandbox
occupée et réessaie le nettoyage avec un intervalle progressif plafonné à 30 secondes.
Le reçu d'arrêt est enregistré après confirmation de la suppression ou de l'absence
du conteneur. Rétablir l'accès au daemon permet au même superviseur de finir le nettoyage.
Qualifier l'ensemble sur la VM avec des processus synthétiques avant de l'activer
pour les utilisateurs.

Exporter les deux paramètres du runner de test dans l'environnement de qualification,
puis lancer `make qualify-process-python`. La commande utilise une base PostgreSQL
éphémère et exerce le transport TLS réel, un aller-retour de fichier avec le broker,
la perte d'un accusé de réception à deux frontières, l'arrêt d'une exécution distincte
des autres et le refus d'un dix-septième processus ou thread dans le script. Les scénarios
du broker vérifient la connexion REST de l'agent affecté, les révocations REST et MCP,
la perte d'une réponse REST après l'effet externe, ainsi que les refus d'expiration
et de rejeu. Le test d'expiration avance l'horloge du broker au seuil de quinze minutes.
L'essai d'endurance soumet 112 petits calculs synthétiques, à quatre en parallèle.
Chaque calcul vérifie son résultat et attend le reçu d'arrêt. La campagne dispose de
dix minutes, puis de soixante secondes pour confirmer l'arrêt des appels restants en cas
d'échec. Elle conserve le débit et les latences médiane et p95, mesurées de la soumission
au reçu d'arrêt, dans `artifacts/process-python-qualification/endurance-*.json`.

#### Worker Process

L'API supervise un processus de travail distinct dans l'image backend. Le worker possède
la progression périodique, l'admission, les effets de services et la réconciliation.
Les slots des appels longs sont indépendants. L'API applique les droits des destinataires
aux événements reçus par un canal Unix privé. La consultation HTTP et MCP lit les données
persistées. Les commandes explicites de contrôle conservent leur autorisation habituelle.

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
Dans une tâche, `file_create` sur cette collection accepte le grant sourcé du run exact,
sans exiger que l'utilisateur nomme à l'avance l'URI de sa sous-collection. Les droits
Process restent vérifiés et un run terminé ne reçoit plus de fichiers. Pour les runs
typés v2, les activités rendent leurs `output_files` au moteur au lieu de publier directement.
Le moteur ne réécrit pas les modifications v1. États et reçus restent séparés des variables.
Les URI canoniques ne contiennent jamais de token ou d'URL de transport.
La première erreur d'exécution non interceptée interdit toute nouvelle admission et demande l'arrêt
des tâches et Runs enfants actifs. Une fois les arrêts confirmés, le run termine en
`error`. `error_code` est renvoyé dans l'inspection et affiché dans le suivi ; un code
fourni par un moteur enfant est conservé, sinon l'échec d'activité est `node_failed`.
Les anciens `catch`, `retry` et `error_handler` sont ignorés ; les branches réservées
à leurs traitements de secours sont retirées à la lecture des anciennes définitions.
Un effet Service ambigu n'est pas rejoué. Une écriture sur une révision dépassée échoue ;
la tâche relit puis réapplique sa modification en préservant les autres données.
Un effet ambigu arrête aussi les nouvelles admissions et demande l'arrêt du run,
avec le code `effect_outcome_unknown`. Le debugger refuse reprise/pas avant réconciliation ; l'arrêt
reste incertaine tant que l'arrêt externe n'est pas confirmé.
Les activités Service ont une tâche de contexte non agentique, sous lease et soumise à la
capacité du harnais. Une demande d'autorisation suspend cette tâche ; sa décision reprend
la même tentative, tandis qu'un refus connu ferme proprement tâche et tentative.

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
Aucun nouveau privilège ni grant de run n'est créé. La connexion dédiée `process`
conserve son rôle d'administration. Les filtres précèdent comptage/pagination, enfants
et métriques inclusives. Les snapshots de participants décrivent les affectations sans
constituer une ACL distincte. Voir la [décision 0198](../../../project/decisions/0198-process-run-data-and-files.md).
Leur reçu est enregistré avec la modification ; retransmettre la même commande après
une réponse perdue rend ce reçu sans effectuer un second pas. L'interface conserve
la clé tant que la réponse est incertaine et détecte les commandes concurrentes.

Les métriques distinguent coût facturé et valeur d'inférence, notamment pour les
abonnements. Elles exposent les totaux directs/inclusifs, par tâche et par occurrence
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
si renseigné, sauf en mode LLM ; `human_task` exige un acteur humain. Le XML conserve ces affectations
et exporte des `laneSet/lane/flowNodeRef` ainsi que `userTask`. Dans le profil typé, les tâches
agentiques restent sur les lignes IA, et les tâches humaines sur les lignes humaines.
Les tâches LLM, Code et IF LLM/code acceptent toute ligne sans conversion implicite.
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
attentes de la portée exacte agent/connexion/Service/room/auteur. `conversation_process_pending`
fournit les contrats complets et la pagination ; `conversation_process_respond` reçoit la
référence choisie et les sorties typées. Les pièces jointes seules restent dans l'historique
avec leur URI source ; les valeurs `File` sont vérifiées par File Sharing, sans téléchargement
ni copie persistante. Une réponse incomplète ou ambiguë appelle une clarification.

L'enregistrement verrouille l'interaction, le Run puis la tentative ; sorties, utilisateur
actif et annulation sont revérifiés. Le résultat et le reçu Messenger sont commités ensemble.
Le même résultat est idempotent ; un résultat différent crée un conflit. Les erreurs de
livraison sont reprises sans abandonner l'attente. Les demandes devenues caduques sont retirées.
