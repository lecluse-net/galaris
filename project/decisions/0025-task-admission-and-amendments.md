# ADR 0025 — Admission conversationnelle et amendements durables des Tasks

- Statut : Accepted
- Date : 2026-08-03

## Contexte

Le control plane conversationnel pouvait créer une Task de fond et afficher ses phases, mais une
nouvelle demande substantielle créait systématiquement une nouvelle racine. Le modèle voyait
quelques travaux récemment liés sans leur objectif, leur révision, la cause d'une attente ni leur
éligibilité à une modification. Une Task suspendue après une question inter-agent apparaissait
donc principalement comme `paused=true`, et les corrections successives fragmentaient un même
livrable en plusieurs UUID.

Réécrire directement l'objectif d'une Task déjà lancée n'est pas sûr : le run reçoit une requête
immuable, le planner peut avoir matérialisé des enfants et une exécution peut être protégée par un
lease. L'arbitrage sémantique appartient au modèle, tandis que l'éligibilité, la concurrence et la
persistance doivent rester déterministes.

## Décision

Toute surface conversationnelle expose des candidats bornés avant la création d'un travail de
fond. Chaque candidat porte son objectif borné, sa révision et un état opérationnel dérivé :
`QUEUED`, `RUNNING`, `WAITING`, `PAUSED` ou `TERMINAL`. Les attentes sont des objets explicites
indiquant leur nature, la question, l'interlocuteur, l'échéance et la Task de coordination. Cette
projection ne remplace ni `Task.status`, ni `Task.paused`, ni les enfants durables.

Le modèle choisit une disposition structurée :

- `AMEND_CURRENT` lorsque la demande modifie le même artefact ou la même cible principale active
  tout en conservant des critères de réussite substantiellement identiques ;
- `AMEND_QUEUED` selon la même définition lorsque la Task est `QUEUED` ;
- `CREATE_NEW` dès que la demande ajoute une autre cible, un autre dépôt, une autre ressource, un
  autre livrable ou un résultat vérifiable indépendamment, même si elle découle du même incident ;
- aucune action et une question concise lorsque la relation reste ambiguë.

Le backend vérifie ensuite l'agent, la connexion, la room, la racine, la phase et la révision. Une
Task terminale, un enfant, une Task ayant un plan matérialisé ou des enfants délégués actifs ne
peut pas être amendé silencieusement. Une course de révision est rejetée et impose une nouvelle
lecture.

Chaque amendement accepté crée un `TaskAmendment` immuable avec source et clé d'idempotence, puis
fusionne l'instruction dans l'objectif canonique. Une exécution en cours est annulée par le
mécanisme normal de lease et de checkpoint. Hors attente interne, la Task revient en `CREATE` par
l'événement `REVISE` afin que le dispatcher voie l'objectif révisé. Une attente corrélée conserve
son point de reprise et reprend avec le même UUID après fan-in.

Chaque checkpoint porte l'empreinte de l'objectif immuable de son run. Après amendement, le runtime
interne conserve le journal des effets terminés pour rejouer leurs résultats sans les reproduire,
mais écarte l'historique fournisseur et le résultat partiel de l'ancien objectif. Le nouveau prompt
repart donc de l'objectif fusionné et du briefing recalculé. Les sauvegardes de progression,
checkpoints et résultats terminaux comparent cette empreinte après rechargement de la Task ; une
écriture issue d'un run devenu obsolète est refusée. Le scheduler traite ce rejet comme
l'annulation attendue de l'ancien attempt, sans retry ni erreur reportée sur l'objectif révisé.

La création conserve son `ConversationTaskLink`. Un amendement garde l'UUID de la Task et utilise
son `TaskAmendment` immuable comme lignée vers le round source ; les snapshots de round exposent
ces amendements séparément afin qu'une admission réussie ne soit pas invisible.

Le texte et la voix temps réel utilisent la même politique et les mêmes garanties du service
Task ; la voix traverse `AgentTaskPort` afin de préserver la frontière de `app.agent`. Les outils
d'inspection généraux exposent également l'état opérationnel et les amendements, afin qu'un agent
ne confonde plus une pause humaine avec une réponse attendue.

## Conséquences

- Une correction ou un ajout de format ne crée plus nécessairement une Task concurrente.
- PostgreSQL conserve l'explication de la décision et l'instruction effectivement fusionnée.
- Le modèle choisit la relation sémantique, mais ne peut ni contourner le scope conversationnel,
  ni écraser un plan actif, ni ignorer une écriture concurrente.
- L'état opérationnel reste une projection recalculable ; la machine de phases ne reçoit aucun
  pseudo-statut `WAITING`.
- Les reprises continuent d'utiliser les checkpoints existants et ne donnent aucune autorisation
  générale de rouvrir une Task terminale.

## Preuves dans le code

`back/app/task/operational_state.py`, `back/app/task/amendment_service.py`,
`back/app/task/models.py`, `back/app/conversation/mcp.py`,
`back/app/harness/conversation.py`, `back/app/agent/realtime.py` et
`back/app/voice/realtime_tools.py`.
