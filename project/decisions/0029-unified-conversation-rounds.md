# ADR 0029 — Rounds conversationnels communs au texte et à l’audio

- Statut : Accepted
- Date : 2026-08-09
- Remplace partiellement : ADR 0016, ADR 0022 et ADR 0027 pour la persistance des tours audio

## Contexte

Voice persistait ses propres `voice_conversation_turns` et
`voice_conversation_turn_messages`, alors que Conversation possédait déjà
`conversation_rounds` et `conversation_round_messages`. Cette bifurcation recopiait les mêmes
messages et imposait une seconde corrélation `voice_turn_id` dans LLM, Dream, Memory, Topic et
Lab. Un message audio canonique était donc traité différemment d’un message texte sans que cette
différence soit justifiée par l’exécution agentique.

Une room Messenger audio identifie l’espace d’un appel, mais ne suffit pas à conserver son état
temps réel : appel actif ou terminé, erreur et ordre atomique des rounds.

## Décision

`ConversationRound` et `conversation_rounds` représentent tous les runs conversationnels, texte
comme audio. Chaque round audio référence `voice_sessions` et chaque message qu’il consomme ou
produit est relié par `conversation_round_messages`. `conversation_round_id` est l’unique
corrélation conversationnelle des appels LLM et l’unique provenance de round pour Dream, Memory,
Topic et Lab.

`voice_sessions` conserve uniquement le cycle de vie du direct : room Messenger, statut,
prochaine séquence, erreur et dates de début et de fin. Agent, connexion, transport, topic,
contact, identifiant distant et langue sont dérivés de la room, des messages, de la connexion ou
des rounds et ne sont pas recopiés dans cette table.

Les moteurs Voice restent responsables du média éphémère, VAD, STT/TTS, barge-in et timings
audio. Cette responsabilité opérationnelle ne crée plus une seconde entité de run. Un round sans
transcript n’invente aucun message vide.

## Migration achevée

La première mise en production additive a créé `voice_sessions`, étendu
`conversation_rounds`, conservé les UUID des anciens tours et copié les liaisons de messages. Après
validation en production, la contraction a supprimé les trois anciennes tables Voice, les colonnes
`voice_turn_id` et les anciennes projections Dream/Memory. Le schéma ne conserve désormais que les
structures canoniques.

## Conséquences

### Complément du 18 septembre 2026 — interruption texte

Un nouveau post texte admis joue le rôle du barge-in audio pour la génération de réponse.
Le signal durable est le successeur `FROZEN` de la même room ; le harnais l'observe en
sessions courtes pendant l'inférence (250 ms) et avant chaque outil. Il n'introduit ni état
persistant parallèle, ni dépendance à une notification locale susceptible d'être perdue.
Les hooks de génération annulent le modèle via son token Pydantic AI. Ils cessent de
surveiller pendant un outil : son résultat doit être conservé avant de reprendre la main.
Les conversations exécutent leurs outils séquentiellement ; cette garantie doit être revue
avant toute activation de leur parallélisme.

La clôture reste dans `app.conversation` : sans effet, fusion des entrées non consommées
vers le successeur ; après effet commencé, consommation du round précédent sans rejeu
automatique. La trace partielle reste consultable. Le code du barge-in audio ne change pas.

### Complément du 19 septembre 2026 — préparation et conflits d'amendement

Le dispatcher conversationnel et la construction d'objectif utilisent aussi l'observation
durable du successeur, dans une portée limitée à leur préparation sans effet métier.
L'annulation attend le nettoyage de l'adaptateur structuré, qui demande l'arrêt de son
inférence durable. `ConversationSuperseded` est un signal de contrôle, propagé hors des
erreurs d'outils ordinaires. Le scheduler applique ensuite la même clôture transactionnelle
et conserve la trace disponible. Préparer un objectif ne marque plus un effet commencé :
la garde reste immédiatement avant l'admission effective de la Task. Les envois et autres
effets engagés ne sont pas placés dans cette portée d'annulation.

La projection serveur des Tasks liées fige une empreinte de leur définition : objectif,
identités et portée, plan, forçages, approbation automatique, compteur d'amendements et état
terminal. L'amendement conversationnel peut accepter une révision devenue plus récente
seulement si cette empreinte connue correspond toujours sous verrou. Ressources, checkpoints
et progression ne changent pas cette définition. Les états d'attente et pauses gardent leurs
règles existantes, et le choix CURRENT/QUEUED est normalisé sous le même verrou.
Il n'y a ni nouvelle colonne ni modification de la version optimiste ORM ; sans empreinte
connue pour la révision demandée, le contrôle reste strict. L'empreinte provient du tour
serveur ou d'une révision effectivement retournée par les outils de liste/statut/conflit,
pas d'un argument choisi par le modèle. Ces observations sont bornées à 40 Tasks dans
le contexte du run ; elles ne créent ni cache global ni persistance parallèle.

Tout amendement indisponible rend `action=CONFLICT`, sans création de repli, en conversation
et sur la soumission vocale générique : conflit de révision, cible incomplète/indisponible,
portée incompatible ou état non amendable. Le modèle peut relire et réévaluer sa décision,
puis appeler explicitement CREATE_NEW pour un travail indépendant. Une commande d'amendement
ne change pas implicitement de nature lorsque sa précondition échoue. Les prévalidations
sans écriture ne marquent pas un effet commencé. Le reçu de création reste idempotent.
Une simple question n'arrête donc pas une Task et CREATE_NEW conserve son sens.
Le remplacement durable arrêt → confirmation → successeur reste un chantier distinct.

Le raccourci d'arrêt ne consomme qu'une commande entière, sans autres entrées ou pièces
jointes, et dont la cible active est unique. Toute demande nécessitant une interprétation
traverse le contrôleur normal avec son texte complet. Aucun découpage par conjonction ni
liste d'exceptions métier n'est ajouté. La garde de fraîcheur avant un renvoi de fichier
propage également `ConversationSuperseded`, avant le transport, pour conserver les entrées
au lieu de terminer le round en erreur. Les prompts ne changent pas ; la description de
l'outil est alignée sur le contrat général d'amendement.

Lors de la préparation d'un objectif, le Working Set lié est une projection de contexte,
pas une liste de travaux obligatoires. Les inspections Web seules, `robots.txt` lu comme
sonde et les reçus de transport ne deviennent pas automatiquement des ressources à réutiliser.
Les références explicitement demandées, documents, pièces jointes, sources lues, ressources
produites et références historiques sans provenance restent accessibles. Le registre d'audit
et le contexte ordinaire du contrôleur ne sont pas réécrits.

- L’audio et le texte partagent le même modèle de run et les mêmes mécanismes Dream/Memory/Topic.
- Les textes visibles ont une seule source : `messenger_messages`.
- La supervision Voice demeure une projection adaptée, reconstruite depuis sessions, rounds et
  messages canoniques.
- L'ancien schéma n'est plus une surface de repli ; la restauration relève des sauvegardes de
  production.

## Preuves dans le code

`back/app/conversation/models.py`, `back/app/voice/models.py`,
`back/app/voice/conversation_service.py`, `back/app/voice/monitoring_service.py`,
`back/app/dream/mechanisms/conversation_memory.py`.
