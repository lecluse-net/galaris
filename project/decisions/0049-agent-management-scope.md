# ADR 0049 — Périmètre de management des Agents

- Statut : Accepted
- Date : 2026-08-24

## Contexte

Les privilèges fonctionnels autorisaient l’accès à une famille d’écrans ou d’API, mais ne
restreignaient pas systématiquement les lignes à l’utilisateur humain désigné comme gestionnaire
de l’Agent. Plusieurs projections transversales — Tasks, conversations, mémoire, processus,
connexions et API compatibles OpenAI — pouvaient ainsi exposer ou accepter l’identifiant d’un
Agent géré par un autre utilisateur.

Le contrôle ne peut pas être seulement appliqué dans le frontend : les identifiants peuvent être
envoyés directement aux routes et les corrélations compatibles OpenAI peuvent référencer des
ressources indirectes.

## Décision

`app.agent` possède le contrat public `AgentManagementScope`. Pour un utilisateur humain, il
contient exclusivement les identifiants des Agents dont `Agent.user_id` désigne cet utilisateur.
Le privilège `AGENT_MANAGE_ALL` transforme ce périmètre en accès global. Le rôle administrateur,
qui reçoit tous les privilèges déclarés, conserve donc le comportement global.

Les routes humaines et leurs services appliquent ce périmètre aux listes, lectures, mutations,
agrégats et ressources indirectes. Une ressource hors périmètre est traitée comme absente lorsque
cela évite d’en divulguer l’existence. Les opérations intrinsèquement globales exigent
`AGENT_MANAGE_ALL`.

Les API `/agent/openai`, Janus et les corrélations de processus des façades compatibles
OpenAI/Anthropic appliquent la même frontière. Un token de runtime reste borné à son Agent ; une
session humaine utilise son périmètre de management.

Le frontend consomme les Agents déjà filtrés par l’API et utilise le composant public
`AgentSelect`, avec avatar dans la valeur sélectionnée et dans les options. Les modules disposant
déjà d’une projection d’avatar propre, notamment Chat, conservent cette projection afin de ne pas
créer une dépendance frontend supplémentaire.

## Conséquences

- Un gestionnaire ne voit et ne sélectionne que ses Agents dans toutes les projections métier.
- Un identifiant deviné ne permet ni lecture ni mutation hors périmètre.
- Les opérations de catalogue ou de supervision qui affectent plusieurs gestionnaires sont
  réservées au management global.
- `app.connection`, `app.chat` et `app.dream` dépendent explicitement de la surface publique
  `app.agent`; leurs plafonds de fan-out reflètent cette frontière de sécurité transversale.

## Preuves dans le code

`back/app/agent/management_scope.py`, les assertions Agent, les routers et services des domaines
portant un `agent_id`, `back/app/agent/openai_router.py`, `back/app/llm`, `back/app/process`,
`front/app/agent/components/AgentSelect.vue` et les tests de `app.agent`.
