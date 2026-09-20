# ADR 0022 — Control plane conversationnel distinct des Tasks

- Statut : Accepted
- Date : 2026-08-01

> La sélection et les replis de modèle décrits ici sont remplacés par la
> [décision 0039](0039-exclusive-llm-profiles-and-agent-voice.md).

## Contexte

Un message humain court suivait historiquement le même chemin qu’un travail de fond : création
d’une Task, réclamation par le scheduler et exécution par le driver de l’agent. Cette confusion
augmentait la latence, exposait un catalogue d’outils trop large et empêchait un agent occupé de
répondre rapidement. Elle rendait aussi l’attribution des appels LLM fragile avec Hermès, car le
proxy pouvait déduire la Task depuis l’unique exécution active de l’agent.

Une conversation et une Task n’ont pourtant pas la même sémantique. La première est un control
plane court qui comprend, répond et pilote. La seconde est une unité durable de travail qui peut
chercher, planifier, utiliser un driver externe et durer longtemps.

## Décision

Les messages humains Messenger valides entrent dans `app.conversation`, jamais directement dans
`app.task`. Une mailbox durable est identifiée par l’agent, la connexion, la room exacte et, pour
une conversation directe, l’interlocuteur. Elle ne possède qu’un round actif. Le message le plus
récent en est l’ancre LIFO ; tous les messages encore non consommés sont agrégés et présentés dans
l’ordre chronologique.

Le scheduler conversationnel possède ses tables, leases et workers. Il n’acquiert ni lease Task,
ni slot d’agent. Son contrôleur est toujours le harnais interne Pydantic AI avec la colonne
`conversation_llm_id` de l’unique profil effectif de l’agent. Une colonne vide ne reprend ni
l’exécuteur ni un autre profil. Son catalogue est
deny-by-default : connexion active, case `Tool.conversation_enabled`, politique de fonction
`short | deferred | forbidden` pour les fonctions natives et profil du runtime doivent tous
autoriser la fonction. Pour un connecteur MCP externe, la case du Tool constitue l’autorisation
conversationnelle explicite ; les états de fonctions de sa connexion continuent de s’appliquer.

Le prompt système de ce contrôleur reste dédié et plus court que celui de l’executor. Il conserve
cependant le nom, le genre, le poste, la personnalité et la fiche de poste de l’agent, puis ajoute
l’inventaire autorisé et le catalogue compact des Process qui lui sont affectés. Il impose une
réponse rapide : appel court direct, lancement asynchrone d’un Process correspondant, ou création
d’une Task autonome pour tout autre travail substantiel. Le contrôleur n’attend jamais leur fin.

Le round ne possède ni plafond total de tokens ni timeout mural propre. Les limites de requêtes et
d’appels d’outils le bornent sans qu’un contexte déjà assemblé ou une réponse fournisseur lente
soit interrompu artificiellement.

Le travail substantiel devient une Task racine autonome. Son objectif est autosuffisant, son lien
au round est commité avec elle et son exécution repasse par le scheduler et le driver ordinaires.
Cette Task est un mode d’exécution de la même identité agentique, pas une délégation à une autre
entité. Elle conserve son contrat Messenger complet : planner, driver, demandes d’autorisation,
messages intermédiaires et résultat final s’expriment directement. Le lien conversationnel sert au
suivi et n’installe aucun chemin terminal concurrent.

Le catalogue réduit du round ne décrit jamais les capacités de la Task. Le prompt impose de
transmettre le résultat demandé sans convertir l’absence d’un outil conversationnel en incapacité
de fond ; la Task retrouve le catalogue complet autorisé de son driver. Réciproquement, les outils
de contrôle `conversation_*` sont marqués indisponibles en Task afin de ne pas faire fuiter le
contrôleur court dans l’executor normal.
Les UUID de Task et de Process restent des données de contrôle internes pour les appels d’outils.
Le contrôleur ne produit aucun reçu structuré de lancement. Au besoin, il indique seulement en
langage naturel que le travail se poursuit en arrière-plan ; libellé, état et référence technique
restent masqués sauf demande explicite de l’utilisateur.
La sérialisation actuelle d’une Task active par agent reste inchangée. Les Process sont lancés sans
attente et liés de la même manière.

Les résultats de Process reviennent par une outbox séparée des entrées humaines. Les Tasks parlent
par leur contrat Messenger ordinaire ; leurs messages ne sont jamais réinjectés comme nouvelles
entrées humaines du scheduler conversationnel. Une erreur d’outbox après dispatch potentiel
devient `UNKNOWN` et n’est jamais rejouée aveuglément.

Avant le premier effet et avant la réponse finale, le round vérifie son watermark. Un nouveau
message supersède un round sans effet et provoque une réagrégation complète. Après un effet, la
réponse libre obsolète est supprimée et seul l’ancien watermark est consommé.

Chaque appel LLM conversationnel porte explicitement `conversation_round_id` et `agent_run_id`,
avec `task_id=NULL`. En présence de cette corrélation, le proxy ne consulte jamais la Task active
Hermès. Les appels de Task Hermès conservent leur corrélation et leur scheduler actuels.

Le pipeline vocal STT/TTS pourra produire les mêmes entrées textuelles dans un lot suivant. Le
realtime audio natif, qui raisonne directement sur le flux et gère le barge-in, reste séparé dans
`app.voice`.

## Conséquences

- Des interlocuteurs et canaux distincts peuvent avancer en parallèle sans ouvrir plusieurs
  Tasks simultanées pour le même agent.
- Les réponses courtes restent possibles pendant une longue Task Hermès.
- Une fonction native doit déclarer sa compatibilité conversationnelle. Pour un MCP externe, la
  case Tool reste une décision administrative explicite.
- La projection conserve les derniers messages complets dans un budget souple et trace les
  omissions. La compression résumée est différée.
- La priorité d’admission au provider LLM, la voix pipeline et les chats humains OpenAI/Janus
  restent des évolutions séparées. Aucun plafond provider rigide n’est introduit dans cette V1.
- L’isolation transverse des principaux reste un chantier distinct ; les contrôles existants ne
  sont ni contournés ni élargis ici.
- Si Hermès introduit ultérieurement ses propres files conversation/travail, Galaris devra soit
  désactiver les fonctions doublons, soit retirer ce harnais, comme pour planner et briefing.

## Preuves dans le code

`back/app/conversation/`, `back/app/harness/conversation.py`,
`back/app/messenger/service.py`, `back/app/tools/mcp_loader.py`,
`back/app/llm/llm_call_service.py`, `back/app/agent/facade.py`,
`back/app/agent/planner_service.py`, `front/app/tools/components/ToolsList.vue` et
`front/app/conversation/components/ConversationHistory.vue`.
