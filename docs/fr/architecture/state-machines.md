<p align="right"><strong>Français</strong> · <a href="../../en/architecture/state-machines.md">English</a></p>

# Machines d’état durables

Ce document rend les états recherchables, mais les constantes et tests du code restent
l’autorité. Toute modification de matrice doit mettre à jour ce fichier dans le même diff.

## Autorisations d’action

Le journal `tool_action_authorizations` porte les états `pending`, `approved`, `denied`,
`expired`, `invalidated`, `executing`, `completed`, `failed` et `outcome_unknown`.

| Événement | Source | Cible |
|---|---|---|
| Préparation committée, accord requis | absent | `pending` |
| Autorisation mémorisée de harnais correspondante | absent | `approved`, puis claim `executing` |
| Réponse humaine habilitée | `pending` | `approved` ou `denied` |
| Échéance ou perte d’autorité avant effet | `pending` / `approved` | `expired` / `invalidated` |
| Claim atomique après revalidation | `approved` | `executing` |
| Reçu d’effet | `executing` | `completed` / `failed` / `outcome_unknown` |
| Preuve distante tardive | `outcome_unknown` | `completed` / `failed`, sans redispatch |

La première décision valide gagne. Un état réconcilié reste terminal. L’attente produit
`galaris.execution-result/v2` avec `disposition=waiting_for_authorization` et les UUIDs concernés.
Les UUIDs sont sérialisés en chaînes JSON avant la persistance du résultat en JSONB ; leur
identité reste conservée lors du rechargement.
La tentative tâche termine en `WAITING_APPROVAL`, libère son lease et conserve son checkpoint ;
la tâche revient à la phase reprenable `DISPATCH`, avec une raison de pause d’autorisation.
L'accord reste acquis, mais le runtime voit encore l'appel en attente jusqu'à la reprise
d'une tentative après la décision et le transfert de son grant vers ce lease actif.
La récupération des orphelins ignore les tâches suspendues. Une pause humaine
indépendante reste prioritaire au réveil. Les rounds et la voix conservent la même disposition.
Voir [0153](../../../project/decisions/0153-common-action-authorizations.md).

## Inférences LLM

`LLMInference` porte la demande et `LLMInferenceAttempt` chaque tentative. Les états de
l’opération sont `prepared`, `queued`, `running`, `pausing`, `stopping`, `paused`, `stopped`, `completed`,
`failed` et `interrupted`. La tentative reste `running` pendant une demande de pause ou d’arrêt.

| Événement | Source | Cible |
|---|---|---|
| Admission committée | absent | `queued` |
| Préparation committée | absent | `prepared`, aucun worker/provider |
| Démarrage explicite | `prepared` | même tentative `queued` |
| Réclamation avec lease | `queued` | `running` |
| Résultat | `running` | `completed` ou `failed` |
| Pause | `prepared` / `queued` / `running` | `paused` / `pausing`, puis `paused` |
| Arrêt | `prepared` / `queued` / `running` / `pausing` | `stopped` / `stopping`, puis `stopped` |
| Échéance globale épuisée | `queued` / `running` | `failed`, journal partiel conservé |
| Arrêt après suspension | `paused` ou `interrupted` | `stopped`, résultat antérieur conservé |
| Arrêt du worker ou expiration du lease | `running` | `interrupted` ; une pause/un arrêt demandé reste prioritaire |
| Reprise explicite | `paused` ou `interrupted` | nouvelle tentative `queued` |
| Rejeu explicite | tout état | nouvelle inférence `queued`, origine inchangée |

Les commandes sont idempotentes par UUID. Un arrêt demandé ne redevient pas une pause.
Les résultats des tentatives terminées sont immuables ; les écritures d’un lease perdu sont
refusées. Une reprise soumet de nouveau la requête figée, sans reprendre le calcul distant.
Le flux d’une tentative contient les messages committés puis un résultat terminal unique.
Se désabonner de ce flux n’arrête pas l’inférence autonome.

Autorité : `back/app/llm/contracts.py`, `inference_store.py` et `inference_execution.py`.
Voir [0097](../../../project/decisions/0097-durable-inference-lifecycle.md).

## Harness d'agent

États persistés de `AgentHarness.lifecycle_status` : `absent`, `provisioning`, `ready`,
`deprovisioning`, `error`. L'absence de ligne sélectionne le harnais interne.

| Événement | Sources | Cible |
|---|---|---|
| `SELECT_CONTAINERIZED_HARNESS` sans ancien runtime | interne | `absent` |
| `SELECT_CONTAINERIZED_HARNESS` avec ancien runtime | `absent`, `ready`, `error` | `deprovisioning`, puis `absent` après nettoyage |
| `SELECT_REMOTE_CONFIGURATION` | interne, `absent`, `ready`, `error` | `ready` après l'éventuel nettoyage |
| `SELECT_INTERNAL` | `absent`, `ready`, `error` | `deprovisioning`, puis suppression de l'affectation |
| `RESTART` / `UPDATE` | `absent`, `ready`, `error` | `provisioning`, puis `ready` ou `error` |

Une sélection ne provisionne jamais. Le nettoyage, le redémarrage et la mise à jour répondent en
`202` puis s'exécutent en arrière-plan. `restart` et `update` recréent destructivement l'unique
conteneur stable `<agent.code>-agent`; aucune tâche non terminale ne peut chevaucher une transition.

## Tâches

Phases : `CREATE`, `DISPATCH`, `EXEC`, `PLAN`, `SUCCESS`, `ERROR`. `PAUSE` est une
valeur historique PostgreSQL ; la suspension courante utilise `Task.paused` tout en conservant
la phase de reprise.

| Événement | Sources | Cible |
|---|---|---|
| `ROUTE_TO_EXECUTION` | CREATE, DISPATCH | DISPATCH |
| `ROUTE_TO_PLAN` | CREATE, DISPATCH, PLAN | PLAN |
| `START_EXECUTION` | DISPATCH | EXEC |
| `EXECUTION_SUCCEEDED` | EXEC | SUCCESS |
| `EXECUTION_FAILED` | EXEC | ERROR |
| `PLAN_SUCCEEDED` | PLAN | SUCCESS |
| `PLAN_FAILED` | PLAN | ERROR |
| `FAIL` | toute phase active | ERROR |
| `INTERRUPT_EXECUTION` | EXEC | DISPATCH |
| `RECOVER_EXECUTION` | EXEC | DISPATCH |
| `RETRY` | ERROR | DISPATCH |
| `RETRY_PLAN` | ERROR | PLAN |
| `RETRY_CLOSING_ACTION` | SUCCESS | DISPATCH |
| `RETRY_DELIVERY` | SUCCESS, ERROR | DISPATCH |
| `RETRY_ROUTING` | ERROR | CREATE |
| `REVISE` | DISPATCH | CREATE |
| `REASSESS_ORGANIZATION` | PLAN | CREATE |
| `CANCEL` | toute phase active | ERROR |
| `FORCE_TERMINATE` | toute phase active | ERROR |
| `ACTIVATE_PLAN_STEP` | PLAN, DISPATCH | DISPATCH |
| `RESUME_COLLABORATION` | DISPATCH suspendue | DISPATCH |
| `COORDINATION_SUCCEEDED` | CREATE, PAUSE héritée, DISPATCH | SUCCESS |
| `COORDINATION_FAILED` | CREATE, PAUSE héritée, DISPATCH | ERROR |

Actions du scheduler : `CREATE → dispatch`, `DISPATCH → execute`, `PLAN → advance_plan`.
Une tâche suspendue conserve sa phase sans être exécutée.

Une demande d'information appartenant à un domaine suspend la tâche existante avec la raison
`input`, sans enfant technique. À la fin du tour, `INTERRUPT_EXECUTION` conserve un point de
reprise `DISPATCH`. Une réponse reçue pendant `EXEC` est injectée à la finalisation ; une réponse
reçue après libère uniquement `input`. Une pause utilisateur indépendante demeure effective.
Le marqueur conserve le tour qui a posé la question. La réconciliation de ce tour après
perte réseau ne termine pas la tâche si la réponse arrivée depuis n'a pas encore été utilisée :
un nouveau tour `DISPATCH` traite cette réponse, sans renvoyer la question.

Une question d'organisation suspend en `PLAN`. Sa réponse conserve les précisions puis
applique `REASSESS_ORGANIZATION` ; le routage choisit de nouveau avec cette réponse. Sans
réponse à l'échéance, ou sans canal de question, `FAIL` termine la tâche en `ERROR`.

Les collections utilisent les phases existantes : le groupe reste en `PLAN`, sa découverte
puis ses éléments traversent `DISPATCH → EXEC → SUCCESS/ERROR`. Une nouvelle vague est
persistée avant activation. Réessayer un plan entièrement terminal applique `RETRY_PLAN`
aux groupes en erreur et `RETRY` aux feuilles en erreur, puis réactive uniquement le chemin
du curseur. Les succès, inventaires figés et journaux d'effets ne sont pas effacés.

Une clôture finale `run_after_failure=true` peut s'exécuter après un échec sans reprendre
les étapes dépendantes. Le parent reste en `PLAN` pendant cette clôture, conserve sa cause
dans `plan.failure_task_id`, puis termine en `ERROR`. Seule une reprise manuelle réarme
une clôture déjà réussie via `RETRY_CLOSING_ACTION` : le nouveau bilan lit l'état courant,
sans réutiliser le run terminé. Les autres succès et leurs preuves restent conservés.

Pour une exécution interne, le checkpoint d’effet suit `absent → started → completed`.
`completed` autorise la reprise et la restitution du résultat journalisé sans réexécuter l’outil.
Une erreur d’outil observée donne en v4 `started → error_reported`, avec son résultat
structuré et une issue `rejected` ou `unknown`. Elle revient au modèle, qui décide de
poursuivre ou de s’arrêter ; elle ne termine pas le run et ne consomme pas de retry de
correction de schéma. La reprise restitue cette erreur sans réexécuter l’appel.
Un rejet historique prouvé avant effet donne `started → failed` ; une coupure sans réponse
enregistrée donne `started → outcome_unknown`. `ModelRetry` seul n’est pas une preuve de rejet.
Un reçu console v2 autorise `outcome_unknown → completed` par réconciliation sur la même cible.
Sans reçu ni politique rejouable, la tâche échoue avec un diagnostic. Le retry manuel conserve
le journal et les écritures d’une tentative remplacée ou expirée sont rejetées.
Un reçu console peut également résoudre `error_reported → completed`. Voir
[0103](../../../project/decisions/0103-tool-errors-return-to-agent.md).
Si le contrat natif courant corrige explicitement une ancienne classification conservatrice vers
`read` ou `idempotent`, la reprise reclasse cet effet, le ferme comme interrompu et autorise le
modèle à rappeler l'outil. Les outils inconnus et non idempotents ne bénéficient jamais de ce repli.
Une annulation Pydantic AI ou asyncio persiste en plus l'historique du run avec le statut
`interrupted`. Cet historique permet de poursuivre une réponse partielle et de fermer les appels
d'outils incomplets, mais ne rend jamais reprenable un effet non idempotent resté `started`.

Statuts d’une tentative : `CLAIMED`, `SUCCESS`, `ERROR`, `RETRY`, `CANCELLED`,
`WAITING_CHILDREN`.

Une suppression explicite est autoritaire dans toutes les phases. Le service applique d'abord
`FORCE_TERMINATE` aux tâches actives du sous-arbre éligible, annule leur action locale, clôt toute
tentative `CLAIMED`, invalide le lease durable, puis effectue la suppression logique enfants avant
parent. Un worker tardif ne peut donc ni réécrire ni reprendre une tâche supprimée.

Une instruction conversationnelle acceptée sur une tâche non planifiée utilise `REVISE` pour
repasser par le dispatcher. Si la tâche était en `EXEC`, elle est d'abord interrompue vers
`DISPATCH`. Une tâche suspendue sur une coordination conserve au contraire sa phase et sa
corrélation jusqu'au fan-in. Les états opérationnels `QUEUED`, `RUNNING`, `WAITING`, `PAUSED` et
`TERMINAL` sont des projections de lecture, pas de nouvelles phases PostgreSQL.

Pendant des délégations actives, l'amendement accepté reste en attente dans `task_amendments`
(`applied_at` nul) sans interrompre les collègues ni modifier la révision ou le lease du parent.
Le verrou du parent sérialise cette admission avec le fan-in. Après réception de toutes les
contributions, les consignes sont appliquées dans l'ordre d'acceptation et leur horodatage est
fixé dans la même transaction que la reprise du parent et les marqueurs de contributions consommées.
La synthèse utilise donc le nouvel objectif et les résultats existants ; les effets ne sont pas rejoués.
Une pause humaine retarde cette application ; une terminaison l'empêche. Un checkpoint incompatible
conserve la consigne en attente et la suspension, avec un diagnostic. Le plan matérialisé du parent
reste refusé. La file est limitée à 100 consignes, chacune de 8 000 caractères au maximum.

L'amendement conversationnel tolère une révision technique plus récente seulement lorsque
l'empreinte de définition figée par le serveur pour la révision demandée est encore identique
sous verrou. Objectif, plan, forçages, portée ou terminaison modifiés restent conflictuels ;
sans empreinte connue, la révision reste stricte. Le reçu d'amendement préserve l'idempotence.
Tout amendement indisponible retourne `CONFLICT` sans nouvelle tâche implicite, également
pour la soumission vocale générique. Une création indépendante exige le choix explicite
`CREATE_NEW`, qui reste disponible après le conflit.
L'amendabilité vérifie aussi le rebasage du checkpoint auprès du driver, en lecture puis
sous verrou avant interruption. Un lease ou une identité d'exécution sans checkpoint,
ou un checkpoint incompatible, rend l'amendement indisponible sans modifier la tâche.
Deux résultats indépendants dans un même document utilisent `CREATE_NEW` ; le nouvel
objectif conserve seulement son périmètre et demande de relire la ressource au démarrage.
Le plafond existant d'une exécution par agent externe maintient la seconde tâche en file.
Voir le complément du 19 septembre de la décision 0029.

`REPLACE` est une décision explicite distincte. L'arrêt et le successeur suspendu sont
persistés ensemble ; `source_task_id` relie les deux racines. La réconciliation attend la
libération du lease et une preuve d'arrêt de l'exécution capturée. `requested`/`unknown`
ne débloquent pas le successeur, et retirer sa pause ne contourne pas la garde du scheduler.
La confirmation retire seulement la pause de remplacement. Un changement de portée ou
une relance du prédécesseur produit un conflit. Les enfants actifs, Goals et attentes
externes restent hors de ce premier périmètre. La barrière vérifie tout l'arbre descendant,
ses leases résiduels et les preuves fournies par Process au bootstrap : un Process actif ou
logiquement annulé avec `remote_may_continue` reste bloquant, même historisé. Les travaux
indépendants et les Processes terminés sans incertitude restent disponibles.
Voir [0123](../../../project/decisions/0123-explicit-task-replacement.md).

Les heartbeats de tâche et de round renouvellent uniquement un lease encore valide :
un propriétaire expiré ne peut pas redevenir autoritaire en envoyant un heartbeat tardif.

L'outil `conversation_task_stop` relit la tâche sous verrou après contrôle de fraîcheur et
de portée. Si elle est déjà en `SUCCESS` ou `ERROR`, il restitue son état sans nouvelle
transition, modification de révision, de résultat ou de cause de fin. Une tâche active
conserve la commande `CANCEL` existante ; ce comportement ne change pas le contrat HTTP
de révision attendue ni ne prouve l'arrêt physique d'un worker encore en cours de nettoyage.

`conversation_task_retry` conserve la commande de retry existante. La politique de décision
demande d'examiner l'échec avant de choisir : relance explicite de la même tâche ou cause corrigée,
sinon préférence pour `CREATE_NEW` avec le diagnostic et les corrections utiles. Une demande
similaire ne suffit pas à justifier une relance. Cette règle guide le modèle ; elle ne modifie
pas les transitions de la machine d'états ni le retry manuel HTTP.

Autorité : `back/app/task/models.py` et `back/app/task/workflow.py`.

## Conversations textuelles

Une `Room` Messenger est prête lorsqu'elle possède au moins un message entrant sans lien consommé.
L'admission crée ou enrichit un round `FROZEN`; le scheduler le réclame en `CLAIMED`, puis son lease
récupérable passe en `RUNNING`. Tant qu'un round est en traitement pour une room, aucun autre round
de cette room n'est réclamé. Un heartbeat renouvelle le lease avec son token propriétaire pendant
toute l'exécution ; la perte de ce token annule le flux local avant toute récupération concurrente.

| État du round | Transition |
|---|---|
| `CLAIMED` | construction du tour → `RUNNING` |
| `FROZEN`, `CLAIMED`, `RUNNING`, `WAITING_APPROVAL` | commande humaine Pause, après l’outil engagé → `PAUSED` |
| `PAUSED` | Reprendre, checkpoint sûr et aucun successeur en attente → `FROZEN` |
| `PAUSED` ou Pause en cours | nouvel input → `SUPERSEDED`, inputs non consommés transmis au successeur `FROZEN` |
| actif ou `PAUSED` | Stop, après l’outil engagé → `CANCELLED`, aucune réponse livrée |
| `CANCELLED` | Relancer → nouveau round `FROZEN` lié, ancien round inchangé |
| actif ou `PAUSED` | Répondre maintenant → `FROZEN` en mode réponse sans outils, puis tentative normale |
| `RUNNING` sans nouvel input | réponse livrée → `SUCCEEDED` |
| `RUNNING` avec nouvel input, sans effet | garde finale → `SUPERSEDED` |
| `RUNNING` avec nouvel input, après effet | réponse supprimée → `SUCCEEDED` |
| actif, worker interrompu, reprise sûre | arrêt propre → `FROZEN` ; lease expiré → nouvelle tentative `CLAIMED` |
| effet incertain ou budget d'erreurs épuisé | résolution dégradée → `ERROR_RESOLVED` |

Les commandes humaines persistent `control_action` et visent le numéro
de tentative observé. Le polling de préparation et les hooks du modèle les observent entre
les effets ; la garde d’effet refuse toute nouvelle action après la commande. Le lease reste
détenu jusqu’à la sauvegarde du checkpoint. Les pauses humaines terminent leur tentative en
`USER_PAUSED`, les arrêts en `USER_STOPPED`, sans consommer le budget d’erreurs. Relancer
réutilise seulement un checkpoint sûr, dans un nouveau round ; les outils et résultats déjà
acquis restent enregistrés. Répondre maintenant contourne le dispatcher et retire outils,
recherche d’outils et capacités de compétences du run. Ces commandes HTTP exigent `CHAT_SEND`
et l’accès à la room native ; elles ne contrôlent ni la voix ni les travaux de fond.

Un arrêt de worker termine sa tentative en `INTERRUPTED` et ne consomme pas le budget de
deux erreurs réelles. Les numéros de tentative restent monotones. Au shutdown, préparations
et inférences s'interrompent ; un outil déjà engagé dispose de vingt secondes pour terminer
et enregistrer son reçu. L'historique chiffré permet la reprise sans répéter les effets
confirmés. L'expiration après un arrêt brutal utilise la même règle. Un checkpoint corrompu
ou un effet non idempotent non acquitté bloque le rejeu.

La réponse finale passe en livraison `SENDING` avant le transport. La récupération rattache
un reçu Messenger déjà journalisé et termine en `SUCCEEDED`, sans renvoi. Sans reçu, la
livraison devient `UNKNOWN` et nécessite réconciliation ; aucun fallback n'est envoyé.
Le contrôle de notification ne récupère pas le bail d'un round actif.
Voir [0178](../../../project/decisions/0178-conversation-worker-recovery.md).

`SUPERSEDED` ne consomme pas ses liens d'entrée : le prochain round réagrège les mêmes messages
avec les nouveaux. Après effet, les liens du round courant sont consommés et le nouveau message
reste disponible pour son successeur. Les statuts terminaux sont
`SUCCEEDED`, `SUPERSEDED`, `ERROR_RESOLVED` et `CANCELLED`.

Le Chat accepte une projection HTTP seulement pour la sélection et le point de vue qui
l'ont demandée, et si aucune projection plus récente n'a déjà été acceptée. Cette garde
couvre aussi ses erreurs : un ancien refus d'accès ne purge pas une autre conversation ;
un refus courant conserve la purge. Une requête récente échouée n'invalide pas à elle seule
une réponse antérieure encore utile. Purge et changement de point de vue invalident les lectures
en attente. Un trou dans le stream réarme le rattrapage reçu pendant une requête HTTP ;
une nouvelle sélection n'attend pas la requête bloquée d'une ancienne sélection.

Pendant la génération de la réponse texte, le harnais vérifie toutes les 250 ms si un
successeur `FROZEN` a été admis dans la même room, sous le lease courant. Cette lecture
en session courte fonctionne aussi entre workers et ne marque aucun effet. Le signal
annule l'inférence via le token Pydantic AI ; les hooks entre inférences et outils empêchent
le démarrage d'un nouvel appel devenu obsolète. Un outil déjà commencé finit avant cette
interruption. La garde finale conserve les transitions ci-dessus et la trace partielle,
avec `interrupted_by_new_input`, sans publier le brouillon comme réponse durable.
L'annulation administrative, la perte de lease et le mode audio gardent leurs chemins propres.
Si le successeur a disparu à la clôture, un round interrompu sans effet retourne à `FROZEN`
avec ses entrées non consommées ; après effet, il clôture sans publier le brouillon.

Chaque tentative en échec peut enrichir le `ExecutionResult` partiel du round. À la transition
`ERROR_RESOLVED`, l'état de livraison de la réponse de secours est porté par le round et son texte
est dérivé de sa langue ; les
`LLMCall` des tentatives restent consultables séparément.

Les notifications de round et de Process utilisent `PENDING → SENDING → DELIVERED`. Les résultats
terminaux des tâches lancées par une conversation utilisent sur leur lien
`IDLE → SENDING → DELIVERED`, ou `IDLE → SKIPPED` lorsque leur résultat terminal porte déjà la
preuve d'une livraison Messenger réussie. Le worker ne réclame la notification qu'après la
libération du lease de tâche et une dernière tentative durable en `SUCCESS` ou `ERROR`; une
annulation et une erreur encore retryable ne produisent donc aucun message. Un message de
progression distinct ne masque pas le résultat terminal. Une exception de transport après dispatch ou
l’expiration d’un lease `SENDING` produit `UNKNOWN`, jamais un retry aveugle. Le numéro de tentative
Tâche réarme une nouvelle notification après un retry humain ultérieur. L'état du fallback est porté
par le round et celui d'un résultat de tâche ou Process par son lien ; il n'existe plus d'outbox
Conversation distincte. Les liens tâche antérieurs à ce contrat conservent un compteur de tentative
notifiée nul et ne déclenchent aucun message rétroactif.

Un opérateur autorisé peut résoudre `UNKNOWN → DELIVERED` ou `UNKNOWN → SKIPPED` dans le détail
du tour, y compris pour les liens tâche/Process. Cette commande conserve une preuve par tentative,
refuse les baux actifs et les décisions obsolètes ou contradictoires, et ne rejoue aucun envoi
ni transition de tâche/Process. Répéter la même décision avec la même preuve est idempotent.

Autorité : `back/app/conversation/models.py`, `service.py` et `scheduler.py`.

## Envois Mail

Chaque appel `mail_send`, `mail_reply` ou `mail_forward` possède une ligne durable identifiée par
`(connection_id, idempotency_key)`. Le contenu MIME final est persisté avant l’entrée dans un état
qui autorise l’envoi.

| Événement | Source | Cible |
|---|---|---|
| réclamation sans validation humaine | absent | `claimed` |
| réclamation avec validation humaine | absent | `pending_approval` |
| approbation par le USER responsable | `pending_approval` | `submitting` |
| rejet par le USER responsable | `pending_approval` | `rejected` |
| soumission SMTP | `claimed` | `submitting` |
| acceptation SMTP | `submitting` | `sent` |
| rejet SMTP définitif | `submitting` | `error` |
| issue réseau inconnue | `submitting` | `uncertain` |
| Message-ID retrouvé dans Envoyés | `submitting`, `uncertain` | `sent` |
| Message-ID non prouvé | `submitting`, `uncertain` | `uncertain` |

`sent`, `rejected` et `error` sont terminaux. `uncertain` reste un état de sûreté : un rejeu ne
relance jamais SMTP, il tente seulement la réconciliation IMAP. Deux validations concurrentes sont
sérialisées par verrou de ligne ; dès que la première passe en `submitting`, la seconde ne peut plus
approuver le mail.

Autorité : `back/bridge/mail/models.py` et `service.py`.

## Conversations vocales

Une session d'appel utilise `ACTIVE`, puis exactement un état terminal parmi `COMPLETED`,
`CANCELLED` et `ERROR`. Chaque appel possède sa propre session, mais plusieurs sessions successives
peuvent référencer la même room Messenger afin de poursuivre une discussion multimodale unique.

Un tour utilise `RUNNING`, puis exactement un état terminal :

| Événement | Source | Cible | Effet sur l'objectif en attente |
|---|---|---|---|
| réponse complète | RUNNING | COMPLETED | consommé |
| barge-in utilisateur | RUNNING | INTERRUPTED | conservé pour le successeur |
| échec technique | RUNNING | FAILED | conservé pour le successeur |

Les transitions terminales sont idempotentes. Au démarrage d'un tour, son
`effective_objective` devient immédiatement l'objectif durable en attente ; une interruption
ultérieure ne peut donc perdre aucun fragment utilisateur. Un successeur référence le tour
précédent par `source_turn_id`, lequel pointe en retour vers `resolved_by_turn_id`.

Autorité : `back/app/voice/models.py` et `conversation_service.py`.



### Raccrochage forcé administratif

`POST /api/voice/conversations/turns/{id}/force-hangup` exige `VOICE_HISTORY_CONTROL` et la portée de gestion de l’agent. Cette action conserve les messages canoniques, les tours, les tâches et les exécutions de Process. Les verrous sont pris dans l’ordre session puis tours : les tours audio actifs (`FROZEN`, `CLAIMED`, `RUNNING`, `WAITING_APPROVAL`) deviennent `INTERRUPTED` ; leurs leases, checkpoints chiffrés et autorisations en attente sont révoqués. Une session ACTIVE devient CANCELLED. Une session déjà terminale conserve son statut et ses dates, mais ses tours orphelins sont interrompus. Le commit précède l’annulation locale à attente bornée. Le contrôle périodique de l’état durable de la session demande l’arrêt des moteurs classique/realtime, y compris sur un autre worker ; `audio_stopped` (et son alias historique `local_audio_stopped`) acquitte la libération des propriétaires sur tous les workers, via les verrous consultatifs PostgreSQL conservés jusqu’à la fin du nettoyage du transport. Une erreur de fermeture empêche cet acquittement. L’action est idempotente. Elle n’annule pas rétroactivement les effets déjà envoyés avant révocation.

### Suppression différée des tours audio

La suppression révoque d’abord durablement la session et le tour, puis enregistre une demande dans `voice_turn_deletions`. Un nettoyage encore actif ou une erreur de transport conserve le tour et rend la demande explicitement en attente (HTTP 202). Un travail périodique reprend les demandes toutes les deux secondes, y compris après redémarrage, sans dépendre du registre mémoire du worker initial. `GET /api/voice/conversations/turns/{id}/deletion` expose l’état et la dernière erreur ; l’interface suit cette demande jusqu’à son achèvement. La suppression canonique conserve les traces métier liées selon les règles de suppression des conversations.

Le schéma comporte la table de demandes et le champ `voice_sessions.teardown_error` : appliquer le workflow DbAdmin (`make sync-db` en développement, `make update` lors du déploiement) avant activation. La qualification automatisée couvre les propriétaires non coopératifs, un verrou PostgreSQL détenu sur une connexion distincte, la reprise du traitement sans registre local et les erreurs de fermeture. Elle ne remplace pas un essai de bout en bout avec deux processus audio et un redémarrage réel.


## Objectifs

| Objet | États |
|---|---|
| Goal | `ACTIVE`, `PAUSED`, `COMPLETED`, `ERROR` |
| GoalCycle | `RUNNING`, `JUDGING`, `DECIDED`, `ERROR` |
| Verdict | `CONTINUE`, `STOP` |

Un cycle crée une tâche ordinaire, attend son état terminal, passe au jugement puis persiste
un verdict. `CONTINUE` programme le cycle temporel suivant lorsqu'une fréquence existe ; `STOP`
clôt l’objectif. Une pause empêche la création de nouveaux cycles sans effacer l’historique.

Chaque Goal choisit exactement un mode de déclenchement automatique. Le mode temporel exige une
fréquence et peut utiliser la plage globale par défaut ou ajouter une restriction hebdomadaire
propre au Goal. Le mode relationnel désigne un unique Goal parent, sans fréquence ni plage propre.
Chaque cycle parent bouclé dépose de manière idempotente un déclenchement durable pour chacun de ses
enfants directs. Le runner le consomme pour créer un cycle `RELATIONAL` portant l'identifiant du
cycle source ; la cascade vers les niveaux suivants ne se produit qu'une fois leur propre cycle
bouclé. Les relations sont acycliques, et l'API d'arbre expose les descendants à l'interface ainsi
que le parent et le nombre d'enfants dans le détail d'un Goal. Une commande manuelle reste possible
dans les deux modes, sans constituer un troisième mode de configuration.

Un planning hebdomadaire global borne
les nouveaux cycles et relances de tous les Goals. Chaque Goal peut ajouter une restriction
hebdomadaire individuelle, sans jamais réactiver un créneau fermé globalement. Une demande de
cycle manuel est persistée jusqu'à la création de sa tâche et contourne les restrictions horaires
globale et individuelle, mais jamais la pause globale explicite.
Si « Lancer un cycle maintenant » doit d’abord reprendre une évaluation en erreur, la
demande manuelle reste en attente : `CONTINUE` permet de créer une nouvelle tâche sans attendre
le planning, tandis que `STOP` annule cette demande. « Réessayer le suivi » reprend seulement
l’évaluation. Dans les deux cas, la tâche précédente et son résultat sont conservés.
La clôture forcée d’une tâche ignore la révision attendue, rend sa tentative terminale et libère
son lease dans un premier commit. La clôture du cycle, les notifications et le cycle de vie terminal
s’exécutent ensuite dans des transactions distinctes, avec une attente de cinq secondes par
traitement ; leurs erreurs sont journalisées sans faire échouer l’arrêt acquis. Une nouvelle demande
retente la clôture d’un cycle resté ouvert. Cette clôture applique `CONTINUE`, sans attribuer de progrès. Le Goal
reste pausé s’il l’était volontairement ; sinon son suivi est reprogrammé au cycle suivant.
Une reprise explicite de `COMPLETED` conserve les documents, coûts et cycles historiques, efface
`completed_at`, repasse le Goal en `ACTIVE` et rend un nouveau cycle immédiatement éligible selon
la pause, le planning global et sa restriction individuelle.

Autorité : `back/app/goal/models.py`, `goal_service.py` et `runner.py`.

## Dream

| État du reçu | Transition |
|---|---|
| absent | réclamation d'un sujet → `running` |
| `running` | application réussie → `success` |
| `running` | erreur récupérable ou préemption → `retry` |
| `running` | erreur avec budget épuisé → `error` |
| `retry` | nouvelle réclamation → `running` |
| `running` avec lease expiré | réconciliation → `retry` ou `error` |
| `success` | terminal, sauf reprise explicite d'une projection dérivée manquante |

Pour `topic.classify_message` et `topic.classify_task`, une décision de réemploi est
appliquée directement. Une proposition de création suit la politique checkpointée : `forbid`
termine sans affectation, `auto` crée puis affecte, et `propose` persiste une interaction Messenger
`PENDING` avant que le reçu Dream ne devienne `success`. La réponse autorisée fait passer
l'interaction par `PROCESSING`, applique au plus une création ou un réemploi, puis la rend
`RESOLVED`; un rejet la résout sans `topic_id`. Une erreur d'application conserve `PROCESSING` pour
une reprise idempotente après expiration de son lease.

Si une affectation directe déjà réussie (`reuse` ou `create/auto`) disparaît du sujet, le
scheduler peut réclamer à nouveau le reçu `success`, remettre son compteur de tentatives à zéro et
réappliquer son checkpoint sans nouvel appel LLM. Le comptage `pending` inclut uniquement cette
reprise ou un sujet encore sans reçu ; les reçus `error`, les succès sans affectation directe et
les approbations humaines ne sont pas présentés comme du travail réclamable.
Lors d'une synchronisation de base, le reconciler DbAdmin restaure en une passe les cibles encore
actives ; le scheduler conserve la reprise unitaire pour les checkpoints qui ne peuvent pas être
résolus par cette projection directe.

Une tâche créée par un round conversationnel reçoit directement le Topic et le contact persistés
du round dans la transaction de création. La création d'une tâche enfant copie de même la portée de
sa tâche parente ou source. Si le classement d'un message ou d'un tour Voice se termine après la
création de la tâche, ce même passage de classement propage sa portée aux dérivés encore sans Topic ;
aucun mécanisme Dream d'héritage distinct n'est exécuté. L'extraction automatique de souvenirs
attend toujours un `topic_id` non nul : avant cela, elle ne crée ni reçu, ni rappel, ni appel LLM.
Cette dépendance est portée par les prédicats des extracteurs tâche, round texte et tour Voice, pas
par l'ordre de rotation du scheduler. Les sources conversationnelles exigent en plus le contact
exact qui scelle leurs souvenirs ; une identité vocale ambiguë reste volontairement bloquée.

La maintenance des liens n'a pas de machine d'état Dream. Un job durable `link_reconcile` converge
directement depuis les provenances, projections et vecteurs courants. Les jobs ciblés suivent les
opérations Dream réussies ; un job global quotidien n'est admis et exécuté qu'en l'absence de tâche
ou de conversation Voice active. Un report pour charge de premier plan remet le job en `pending`
sans consommer son budget de tentatives.

Une préemption Voice rend le reçu immédiatement disponible sans consommer son budget d'échec. La
sortie préparée peut exister dès `running` et reste réutilisée lors d'une reprise.
Pour `skill.learn_task_outcome`, le premier checkpoint contient les preuves et leur empreinte,
puis le checkpoint préparé contient les opérations structurées sur les compétences. Un succès `observe`
peut être réclamé une fois lors du passage à `learn`, sans relancer le modèle. L'application ajoute
une preuve idempotente et recalcule le score ; elle ne touche pas Memory. Une nouvelle preuve
tardive ne rouvre pas le reçu terminal : elle crée un autre sujet
`<task UUID>:<empreinte>`. Toutes les tâches terminales sans reçu sont donc parcourues, historique
compris, de la plus ancienne à la plus récente. Le scheduler conserve son débit borné à une
opération par passage ; le rattrapage n'est pas un traitement massif parallèle.
Le scheduler n'exécute qu'une opération par passage et fait tourner le mécanisme prioritaire pour
éviter la famine. `DREAM_POLL_SECONDS` commence après la fin de cette opération avant qu'une autre
puisse démarrer ; la durée de l'opération ne consomme donc jamais cette pause.

Autorité : `back/app/dream/models.py`, `service.py` et `scheduler.py`.

## Générations média et opérations du Lab

Ces opérations conservent leur état dans leur domaine ; elles ne créent ni définition ni run
de processus métier. Leur durée ou leur besoin de reprise ne change pas cette responsabilité.

| Objet durable | Domaine propriétaire | Lecture et contrôle |
|---|---|---|
| Génération média | `app.multimedia` | `multimedia_get_run` ; les fichiers finaux doivent être écrits avant le succès. |
| Génération de dataset, proposition d’attendu ou analyse Lab | `app.lab` | `lab_operation_get` et `lab_operation_cancel`. |

Leurs snapshots acceptent `queued`, `running`, `waiting`, `cancelling`, `success`, `error`,
`cancelled` et `unknown`. `success`, `error` et `cancelled` sont terminaux : une observation
tardive ne remplace pas leur résultat. Une soumission média ambiguë n’est pas répétée ;
une livraison interrompue exige la vérification de la destination. Un callback média ne suffit
pas à prouver le résultat : le fournisseur est interrogé avec les credentials serveur.
L’annulation du Lab est une demande durable, sans garantie d’arrêt d’un appel déjà soumis.
La génération média n’annonce pas d’annulation distante sans confirmation du fournisseur.

Autorité : `back/app/multimedia/generation_contracts.py`, `generation_store.py`,
`generation_execution.py` et `back/app/lab/operation_contracts.py`, `operation_store.py`,
`operation_execution.py`.

## Processus

Le profil natif v2 normalise les entrées avant l'intention d'activité. Les appels
MCP/REST sont préparées en `tool_ready`/`rest_ready`, réclamées en `claiming`, puis
marquées `started` juste avant effet, sous une garde contre annulation et worker périmé.
Les jobs possèdent une session DB indépendante ; un appel lent ne retient pas la progression
des autres branches. Un claim expiré avant dispatch peut être repris ; un effet `started`
sans reçu n'est jamais réémis automatiquement. Les sorties
validées sont conservées avant l'intégration : une réponse externe acquise passe par
`returned` avant `completed`, sans réémission de l'appel après interruption. La réception
du résultat et son intégration sont deux étapes distinctes ; le reçu du run rend la seconde
idempotente. Une erreur de contrat interdit l'intégration et toute admission du successeur.
Les tâches à plusieurs prédécesseurs attendent toutes leurs arrivées de la même invocation.
Les phases de code conservent leurs identités et observations dans l'occurrence :
`queued`/`running` restent en attente, et `success` n'est utilisable qu'avec `stopped=true`.
Une annulation attend elle aussi la confirmation physique ; aucun résultat tardif ne
rouvre un terminal. L'adapter Monty ferme son worker isolé avant de confirmer l'arrêt.
Seule cette computation pure peut être recalculée après perte du résultat ; les effets
externes ne sont pas rejoués. Un IF configuré suit une seule sortie True/False après
validation de son booléen. Son mode humain réutilise `human_waiting` et les choix Messenger,
sans tâche IA d'attente et sans intégration du booléen dans les données du run.
Dans le traitement IA, le sous-mode `task` conserve la tâche agentique ; `llm` place la
tentative en `llm_waiting` et observe une inférence durable. Seul son résultat réussi et
validé termine la tentative. Échec ou interruption ne sélectionne aucune branche.
L'arrêt du Process attend la confirmation d'arrêt de l'inférence, et un résultat acquis
est réutilisé sans nouvel appel après reprise du moteur.

États terminaux : `success`, `error`, `cancelled`.

Pour les processus internes, la première erreur d'exécution interdit toute nouvelle
activité et demande l'arrêt des tâches et enfants actifs. Le run passe par `cancelling`
puis `error` après confirmation des arrêts, en conservant `error_code` et les données.
Un effet externe incertain renvoie `effect_outcome_unknown` et reste en arrêt en cours
jusqu'à réconciliation. Aucun traitement de secours ou réessai automatique n'est exécuté.

La finalisation d'une attente est distincte du statut du run : `await_resolved_at` reste nul
jusqu'à la clôture de la tâche enfant et à la reprise de son parent. Cette étape est rejouable
par callback, refresh ou réconciliation périodique. `cancelling` reste éligible au polling.

| État courant | Cibles autorisées |
|---|---|
| `queued` | running, waiting, success, error, cancelled |
| `running` | waiting, success, error, cancelling, cancelled, unknown |
| `waiting` | running, success, error, cancelling, cancelled, unknown |
| `unknown` | running, waiting, success, error, cancelling, cancelled |
| `cancelling` | cancelled, success, error |
| `success` | aucune |
| `error` | aucune |
| `cancelled` | aucune |

Une transition vers le même état est idempotente. Toute tentative, acceptée ou refusée, peut
être journalisée comme événement. `started_at` est fixé à la première entrée en `running` ou
`waiting`; `finished_at` à l’entrée dans un terminal.

Autorité : `TERMINAL_STATUSES` et `TRANSITIONS` dans
`back/app/process/process_service.py`.

Une activité native `human_task` crée une tentative `human_waiting` et une occurrence
`waiting`. Seule la réponse valide de l'utilisateur affecté passe la tentative à `completed` ;
le prochain passage du moteur passe l'occurrence à `success` et poursuit le flux.
Une réponse identique rejoue le reçu ; une réponse différente après complétion est un conflit.
Un autre utilisateur, un utilisateur inactif ou un Run en annulation/terminal ne peut plus
créer de reçu. Une annulation ferme le Run sans admettre de tâche IA pour l'activité humaine.
Ces garanties sont exercées par `test_human_activity_waits_for_assignee_and_replays_one_receipt`.

## Évaluations du Lab IA

Un run d’évaluation du Lab suit `queued → running`, puis exactement un état terminal parmi
`completed`, `partial`, `failed` et `cancelled`. Une demande d’annulation est durable ; un run en
attente est annulé immédiatement, tandis qu’un run déjà en cours termine l’appel isolé courant
avant de s’arrêter.

Chaque run fige les cas, le LLM candidat, le juge et la version du barème avant son démarrage.
Le candidat et le juge se sélectionnent séparément dans le Lab. Sans `judge_llm_id` explicite,
l’API utilise l’usage **Lab** du profil courant. Un résultat de cas constitue un checkpoint
durable et unique pour le couple run/cas.
Le registre couvre Dispatcher, Planner, classification thématique, extraction mémoire,
apprentissage et suivi d’objectif. Chaque mécanisme déclare le
format natif de son entrée et de sa sortie (`text` ou `json`), son prompt système de production et
son schéma de sortie. Les workers Dispatcher et mécanismes génériques ont des réclamations
disjointes. Ils ne traitent qu’un cas par passage et possèdent un lease récupérable, sans créer ni
faire transiter une tâche et sans déclencher d’outil ou de message.

Les benchmarks Planner possèdent une copie éditable du system prompt de décomposition, initialisée
depuis le Param de production. Le run en fige la valeur exacte avant toute exécution, comme pour
l'extraction mémoire.

Le benchmark `memory_extraction` est spécialisé : chaque cas contient une source classée et son
propre corpus de souvenirs existants. Il classe ce corpus local puis évalue directement
`CREATE|LINK|IGNORE`, sans lire ni modifier la mémoire de production. Son prompt appartient au
dataset et sa valeur exacte est figée dans le run.

Pour les mécanismes autres que Dispatcher, `score_percent` est une pertinence sémantique pondérée
par une rubrique propre au mécanisme. La sortie attendue est un exemple de référence non normatif :
une autre réponse correcte ne perd aucun point pour sa formulation, son ordre ou sa stratégie. La
similarité structurelle avec cette référence reste un diagnostic séparé et ne participe pas au
pourcentage principal. Une défaillance que le juge qualifie d’invalidante plafonne la pertinence à
50 %, afin qu’elle ne soit pas diluée par de bonnes sous-notes secondaires.

`completed` signifie que tous les cas ont reçu un résultat et un jugement exploitables ; `partial`
qu’au moins un cas candidat a échoué ou que son jugement sémantique est indisponible. Une erreur du
seul juge conserve la sortie candidate et le diagnostic de similarité, mais laisse son score de
pertinence nul (`null`) au lieu de lui substituer un pourcentage trompeur. Une erreur candidat vaut
0 % et reste distinguée explicitement d’une mauvaise réponse.

Autorité : `back/app/lab/models.py`, `dispatcher_evaluation_service.py`,
`mechanism_registry.py`, `mechanism_rubrics.py` et `mechanism_evaluation_service.py`.

## Motifs d’échecs IA

Chaque appel LLM ou outil en échec ajoute une occurrence immuable. Son motif agrégé suit le cycle
de revue ci-dessous ; ce statut ne modifie jamais les occurrences historiques.

| Événement | Source | Cible |
|---|---|---|
| première occurrence | absent | `new` |
| analyse humaine | `new`, `regression` | `triaged` |
| correctif décidé | `new`, `triaged`, `regression` | `fix_planned` |
| correctif vérifié | `triaged`, `fix_planned`, `regression` | `resolved` |
| décision de ne pas agir | tout état | `ignored` |
| nouvelle occurrence | `resolved` | `regression` |
| nouvelle occurrence | autre état | état inchangé |

Un succès terminal du même run marque ses occurrences antérieures comme récupérées sans les
supprimer ni résoudre leur motif. Pour une conversation texte, le scheduler applique ce marquage
après persistance de `SUCCEEDED` pour ce round uniquement. Attente d’autorisation, interruption,
remplacement, perte de lease, annulation, échec et livraison incertaine ne suffisent pas.
La réouverture `resolved → regression` est atomique avec
l’ajout de l’occurrence. Les autres transitions sont des décisions de revue administratives et
peuvent être corrigées manuellement.

Autorité : `back/app/incident/models.py` et `service.py`.
