# ADR 0032 — Capsule de continuité figée par interlocuteur

- Statut : Accepted
- Date : 2026-08-12

## Contexte

Une Task issue de Messenger recevait surtout l'historique récent de sa room et un rappel mémoire.
Ce cadre perdait les documents et livrables manipulés lors de Tasks antérieures, tout en pouvant
réinjecter les messages d'autres participants d'une room. Utiliser le Topic comme frontière ne
convient pas : Dream le détermine après l'admission et peut le réviser. Recalculer le contexte à
chaque étape rendrait en outre un plan non reproductible lorsqu'un nouveau message ou souvenir
arrive pendant son exécution.

## Décision

Pour une Task humaine dont le contact canonique est prouvé, `app.agent.context` compose une capsule
de continuité à partir de candidats structurés : messages du même contact, Tasks racines récentes
du même agent et du même contact, ressources actives de leurs Working Sets, et mémoires strictement
scellées à ce contact. Le Topic n'entre ni dans la clé de sélection ni dans le filtre de rappel.
L'historique peut traverser rooms et connexions parce que l'identité sociale canonique reste le
contact privé `(agent, messaging_id, user_id)` ; la room demeure la portée du round et du routage.

Chaque candidat conserve type, référence exacte, révision éventuelle, date, extrait borné et
provenance. Le compositeur déduplique, classe par pertinence lexicale, récence et score de source,
applique des quotas par type ainsi qu'un budget global, puis rend explicitement ces extraits comme
données non fiables et non comme instructions.

Le manifeste retenu est écrit une seule fois dans
`Task.data["interlocutor_context"]` sur la racine sous verrou. Le dispatcher, le planner, les
feuilles et les retries relisent ce même manifeste ; le Working Set courant reste dynamique afin
que les ressources produites pendant le plan deviennent immédiatement accessibles. Les providers
ne relancent pas leurs recherches lorsqu'une capsule existe. La vue Task expose le manifeste,
sa date, son contact, sa troncature et ses provenances sous « Contexte fourni ».

Une Task humaine sans contact prouvé ne reçoit ni historique de room ni rappel pertinent
conversationnel. Les mémoires `core` propres à l'agent et les contextes sans origine humaine
conservent leurs règles existantes. La propagation du contact est effectuée sur l'objet Messenger
hydraté avant l'admission ; les messages sortants liés à un round et les enfants de Task héritent
ensuite cette identité indépendamment de l'existence d'un Topic.

Une conversation directe ou audio temps réel n'a pas de Task racine sur laquelle figer ce
manifeste. Le provider produit donc une capsule éphémère limitée aux documents actifs des Working
Sets récents et aux URI `document://` vérifiées dans les traces d'outils des rounds terminés du
même agent et du même contact. Il expose leurs dates et provenances, et n'utilise ni la room, ni les
fichiers temporaires, ni le texte libre comme élargissement implicite.

## Conséquences

- Deux interlocuteurs d'une même room ne contaminent plus leurs contextes implicites.
- Une nouvelle demande retrouve les discussions, Tasks et ressources de la même personne, même
  si elle arrive dans une autre room ou avant le classement Dream.
- Un plan et ses reprises restent reproductibles ; l'interface montre exactement ce qui a été
  fourni au modèle.
- Les références sont figées, pas le contenu des documents : une révision reste visible et les
  lectures détaillées continuent de traverser les ACL des domaines propriétaires.
- Aucun modèle ni table n'est ajouté. L'upgrade déterministe rattache les sorties historiques aux
  contacts déjà portés par leurs rounds.
- La capsule est un contexte de travail borné, pas une nouvelle mémoire durable ni un second
  système de Topic.

## Preuves dans le code

`back/app/agent/context.py`, `back/app/agent/contracts.py`, `back/app/agent/facade.py`,
`back/app/task/working_set.py`, `back/app/messenger/session.py`,
`back/app/messenger/service.py`, `back/app/conversation/service.py`,
`back/app/memory/bootstrap.py`, `back/app/memory/retrieval.py` et
`front/app/task/components/TaskDetail.vue`.
