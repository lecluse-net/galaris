# Conversations Deep

Statut `partial` · 20 novembre 2026.

Le socle couvre l’admission directe, la reprise du flux, les permissions managées,
la provenance des appels et l’affichage du Chat. Le checkout Code peut être utilisé
via les outils Console. Codex reçoit les nouvelles consignes texte pendant un tour
actif. L’édition dans le terminal natif sur le même checkout et l’attachement à un
terminal déjà ouvert restent à qualifier. Les versions distantes doivent annoncer
la capacité de session utilisée par leur adaptateur.

Deep relie une conversation du Chat directement au harnais. Celui-ci reçoit les
messages et exécute sa propre boucle. Un même agent peut avoir plusieurs sessions
Deep actives. Pour développer Galaris, le harnais et le panneau Code utilisent
le même worktree autorisé.

## Activer Deep dans le Chat

`@deep` figure dans le menu des commandes existantes, avec `@task`. Envoyée seule,
la commande bascule le mode de la conversation. En tête d’un message, elle active
Deep et transmet la demande qui suit au harnais. L’en-tête affiche **Deep désactivé**
en mode habituel et **Deep** après activation. Galaris déduplique chaque envoi.

Le mode est mémorisé par conversation et retrouvé à la réouverture ou dans un
autre onglet. Un basculement pendant un tour s’applique au tour suivant. Réactiver
Deep reprend la session existante du harnais. Les échanges en mode standard
restent lisibles dans le même fil. Le harnais reprend l’historique de sa session,
auquel l’utilisateur peut ajouter une consigne explicite depuis le Chat.

## Modèle proposé

| Objet | Propriétaire proposé | Identité et état |
|---|---|---|
| Conversation | `app.conversation` et `app.messenger` | Le mode est mémorisé pour le salon du Chat interne. Le journal garde les messages envoyés et les réponses finales, avec leur provenance Deep lorsqu’elle s’applique. |
| Session Deep | `app.conversation` | Identifiant Galaris, `room_id` d’origine, agent, affectation du harnais, référence persistante de session native, checkout facultatif, état et position dans le flux. Une seule session courante par salon. |
| Activité Deep | `app.conversation` | Événements ordonnés de la session, regroupables par tour natif quand le harnais en fournit l’identité. Le Chat projette le texte, les résultats et l’état du travail. |
| Appel LLM | `app.llm` | Si Galaris transporte l’inférence, `deep_session_id` relie l’appel à la session et à son salon d’origine. Les champs `task_id` et `conversation_round_id` restent vides. |
| Checkout | `app.code` | Référence canonique au checkout et droits existants. Le runtime résout cette référence en répertoire de travail dans le périmètre attribué. |
| Adaptateur de session | `app.agent` et provider du harnais | Contrat d’ouverture/reprise, de soumission, d’événements et d’interruption. Chaque provider conserve les particularités du protocole natif. |

Le premier lot s’applique aux conversations privées du Chat interne. Un changement
de harnais ou de checkout ouvre explicitement une nouvelle session,
avec conservation du fil et de l’historique consultable. La session native est gardée
côté runtime. Galaris conserve sa référence, les événements visibles et les identités
nécessaires à la reconnexion. Un deuxième onglet sur le même salon retrouve la même
session. Deux salons du même agent obtiennent deux identifiants natifs.

## Dialogue direct et provenance des appels

Le Chat enregistre le message puis transmet son contenu et ses pièces jointes prises
en charge à la session. Le harnais charge ses skills et utilise les outils autorisés.
Deep contourne le dispatcher, le contrôleur conversationnel ordinaire et l’admission
de tâches. Le mode ne crée ni `Task` ni `ConversationRound`. Le lien au harnais
et l’accès MCP sont établis à l’échelle de la session. Les droits des ressources et
les approbations applicables sont vérifiés à l’usage. Aucun justificatif Galaris
par tour n’est requis pour les appels LLM Deep.

Pour un harnais qui appelle la passerelle Galaris, un point d’accès lié à la
session est configuré à son ouverture. La passerelle identifie la session à
partir de ce point d’accès. Le harnais interne transmet la même identité de
session directement au service LLM. Le lien suit
`LLMCall.deep_session_id → DeepSession.room_id → Room.id`. **Activité LLM** peut identifier les appels comme
Deep, filtrer par conversation et ouvrir le fil d’origine. Si un fil accueille
plusieurs sessions successives, le filtre les rassemble et chaque appel garde
sa session d’origine.

Un harnais entièrement externe peut appeler son fournisseur directement. Galaris
conserve le lien au salon, les messages et les événements reçus, sans créer de
`LLMCall` pour ces appels. Un usage déclaré par le runtime peut être affiché
avec sa provenance. Le harnais interne et les harnais distants exposent au Chat
un contrat commun de session, de flux, de reprise et d’arrêt. Un adaptateur
Claude Agent SDK peut notamment être hébergé là où tourne Claude Code et reprendre
une session enregistrée par identifiant. L’attachement à un terminal déjà actif
demande une capacité distincte à qualifier.

## Affichage et reprise

Le Chat conserve sa liste des conversations, sa saisie et le panneau Code. Le texte
de la réponse et les commentaires publics de progression s’affichent au fil de
leur réception. Le résultat final reste lisible dans le fil et les détails
d’exécution peuvent être repliés.

Une réponse longue reste un seul message dans le fil. Les fragments de transport
sont bornés et le texte reçu est conservé par blocs. Le rendu Markdown avance par
lots, en actualisant le bloc en cours et en conservant les blocs terminés. Les
blocs d’une réponse volumineuse et les sorties détaillées d’outils sont chargés à
la demande. Quand l’utilisateur remonte pour relire, le Chat conserve sa position
et lui permet de revenir au direct.

La reconnexion reprend au dernier événement appliqué, sans doubler le texte ni
relancer le travail. Après interruption du runtime, le Chat affiche l’état natif
disponible et les reçus conservés. Un effet d’issue inconnue demande une
réconciliation avant tout rejeu. Pendant un tour, une consigne rejoint le tour
actif si le harnais le permet. Sinon, le Chat indique qu’elle attend le prochain
tour. Le Chat distingue arrêt demandé, arrêt confirmé et échec. Les entrées et
commandes sont idempotentes.

### Parcourir l’activité d’exécution

Le fil affiche des blocs courts à l’endroit où le harnais lance une délégation,
une commande ou un outil. Un bloc de sous-agent s’ouvre sur sa mission, son état,
ses messages visibles, ses commandes et son résultat quand le harnais les fournit.
Les activités parallèles se mettent à jour chacune dans leur bloc. Une commande
affiche son libellé et son état, puis son répertoire de travail, sa sortie et son
code de retour lorsqu’ils sont disponibles. Le journal est consultable en direct
si le harnais émet des fragments, ou à la réception du résultat. Une approbation
en attente reste visible même quand le bloc est replié.

Pour une session longue, le panneau latéral existant du Chat peut proposer une
vue **Activité** avec des filtres pour retrouver les exécutions en cours, les
échecs et les approbations en attente. Chaque entrée mène au bloc correspondant
dans le fil. Une exécution en arrière-plan continue à mettre à jour son bloc
d’origine après la fin de la réponse principale. Une action d’arrêt ciblé est
proposée lorsque le harnais sait agir sur cette exécution précise.

L’adaptateur s’appuie sur les identifiants natifs de session, d’activité et de
parent lorsqu’ils sont fournis. Galaris s’en sert pour rattacher les fragments
sans mélanger les branches ou les commandes parallèles et pour reprendre après
reconnexion. Une activité sans parent connu reste visible au niveau de la session.
Les délégations natives restent des événements Deep.

L’App Server de Codex documente les liens entre fils, les événements de commande
et les fragments de sortie. Claude Agent SDK documente les liens vers le sous-agent
via `parent_tool_use_id`, la progression des activités en arrière-plan et le
streaming du texte. La qualification de chaque bridge doit vérifier ce qu’il
transmet effectivement, en particulier la sortie du terminal en direct.
[Codex App Server](https://learn.chatgpt.com/docs/app-server#items) ·
[Sous-agents Claude](https://code.claude.com/docs/en/agent-sdk/subagents#detect-subagent-invocation) ·
[Référence Python Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/python#taskprogressmessage)

## Développement de Galaris

Le panneau Code et le harnais résolvent la même référence de checkout. La
qualification doit couvrir la découverte des `AGENTS.md`, les éditions, les commandes
de test dans l’environnement Docker de développement et la visibilité des changements
Git. Plusieurs chantiers d’écriture peuvent utiliser des worktrees distincts du même
dépôt. Le droit d’accès à un checkout est revérifié avant la reprise. Une session
ne permet pas d’écrire sur le serveur de production. Pour modifier le Chat ou le
harnais, le premier parcours utilise une instance de développement distincte de
l’instance qui porte la session.

## Lots et critères de réception

1. **Harnais interne et Codex.** Vérifier le basculement `@deep`, son indication dans
   le Chat, la mémorisation du mode et la reprise de la session. Exercer le harnais
   interne avec une réponse Markdown longue alternant texte, code et outils. Remonter
   pour relire pendant le flux, recharger la page et retrouver le texte complet.
   Avec Codex, mener une correction de Galaris dans un worktree autorisé, jusqu’aux
   tests et à la revue du diff dans le panneau Code. Pour les deux harnais, vérifier
   que les appels passant par Galaris ouvrent le bon fil depuis **Activité LLM** et
   qu’aucune tâche ni `ConversationRound` n’est créée pour ces échanges.
2. **Durabilité et concurrence.** Avec le même agent, faire tourner cinq fils sur
   des worktrees distincts. Rediriger et arrêter un seul tour pendant que les autres
   continuent. Vérifier l’isolation des messages, appels LLM, approbations et outils.
   Dans un même fil Codex, suivre deux délégations parallèles et ouvrir la commande
   de l’une pendant que l’autre continue. Retrouver le bon bloc après reconnexion.
   Tester une reconnexion en cours de tour, un redémarrage du runtime, une révocation
   d’accès et une réponse d’approbation tardive. Contrôler la conservation des
   décisions après compaction sur une longue session.
3. **Harnais distants.** Qualifier la reprise, le flux et l’arrêt pour Hermès, Claude
   Agent et DeepSeek selon les capacités de chaque version. Exercer un Claude Code
   entièrement externe, avec des appels directs au fournisseur et un historique
   Deep consultable dans le Chat. Vérifier que ces appels directs ne créent aucune
   entrée dans **Activité LLM**. Avec Claude Agent, vérifier le rattachement d’une
   commande à son sous-agent et la mise à jour d’un bloc d’arrière-plan après la
   réponse principale. Un endpoint générique devient sélectionnable
   lorsqu’il démontre le contrat de session.

La réalisation dépend de la corrélation des appels par session, de la qualification
du flux repris et de la liaison sécurisée entre le runtime et le checkout. Le
schéma SQL final et le mécanisme d’exposition du checkout seront confirmés sur
les premiers parcours du harnais interne et de Codex.
