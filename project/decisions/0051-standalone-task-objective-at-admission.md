# ADR 0051 — Objectif de Task autonome construit à l’admission

- Statut : Accepted
- Date : 2026-08-25

## Contexte

Le texte qui déclenche une Task depuis une conversation n’est pas nécessairement un objectif
exécutable. Une directive comme « `@task vas-y, fais-le` » ne porte son sens que dans les messages
précédents, leurs corrections, leurs pièces jointes et les ressources déjà produites. De son côté,
`conversation_task_submit` reçoit un libellé et un objectif rédigés par le modèle conversationnel,
qui peut condenser excessivement la demande ou oublier une contrainte.

Copier l’historique dans la Task ne résout pas cette ambiguïté : le dispatcher et chaque mécanisme
aval devraient encore reconstruire l’intention, avec des résultats potentiellement différents. Le
modèle conversationnel ne doit pas non plus devenir l’autorité des informations techniques de
salon, d’interlocuteur ou des choix de routage explicites.

## Décision

Toute création d’une Task racine depuis une conversation, qu’elle provienne d’une directive
déterministe ou de `conversation_task_submit`, exécute avant le dispatcher de Task un appel LLM
spécialisé. Cet appel utilise obligatoirement le niveau texte `standard` du profil effectif de
l’agent, avec une sortie structurée limitée à deux champs : `label` et `objective`. Il n’existe ni
objet intermédiaire persistant, ni version de contrat dédiée. Depuis le complément du
19 septembre 2026, `objective` contient le contexte complémentaire généré ; le serveur compose
l'objectif durable avec la demande source conservée séparément.

La consigne système de cet appel est le Param Markdown
`ai.task-objective-system-prompt`. Elle suit le mécanisme commun des prompts administrables : une
valeur `NULL` adopte le défaut livré par Galaris et une personnalisation est conservée avec suivi
de l’évolution du défaut. Une valeur vide revient au défaut et ne peut pas désactiver le contrat.

L’entrée fusionne la chronologie canonique disponible avec le tour gelé effectivement admis. Ce
dernier reste toujours présent même lorsqu’un provider ne peut pas résoudre le contact Messenger.
Le rappel Memory gouverné, la continuité, les travaux liés, les URL, les URI canoniques, les pièces
jointes et les arguments fournis à `conversation_task_submit` sont présentés comme des données non
fiables. Les arguments du tool ne sont que des indices : ils ne peuvent supprimer une exigence
présente dans le contexte. La correction utilisateur applicable la plus récente prévaut.

Le serveur conserve les messages sources du tour admis avant le budget du contrôleur et avant les
annotations d'affichage. Leurs textes et références de pièces jointes sont cités dans une section
« Demande originale », échappés comme texte même s'ils contiennent du HTML. Cette section ne passe
pas par une réécriture LLM. La voix et les appelants sans instantané utilisent la demande admise,
jamais leur historique complet. Le contexte généré apparaît dans une seconde section « Contexte
d'exécution ». `Task.data._original_demand` conserve la demande source seule pour ces admissions ;
les autres chemins de création gardent leur contrat existant. Les tâches historiques ne sont pas
réécrites.

L'ensemble doit être autonome, complet et directement exécutable sans la conversation. Le contexte
explicite les antécédents, décisions et corrections applicables ; il complète la demande sans
remplacer ses contraintes. Une correction de présentation n'annule pas une fonctionnalité demandée
précédemment. Si le message porte plusieurs résultats indépendants, le contexte précise le périmètre
de cette Task et le travail déjà assigné ailleurs. Il
conserve les contraintes, livrables, destinataires et destinations explicitement demandés ainsi
que les références exactes utiles, et explicite les ressources requises lorsque nécessaire. La
restitution terminale dans la conversation d’origine étant automatique, elle ne fait jamais partie
de l’objectif et ne peut pas être déduite des métadonnées de salon ou d’interlocuteur. Une action de
communication ou de livraison n’est conservée que si elle constitue elle-même une demande
explicite, par exemple envoyer un message, un courriel ou un fichier vers un destinataire donné. Un
validateur refuse toute URL ou URI que le modèle aurait ajoutée sans source dans l’entrée. Les
directives `@task`, `@exec`, `@plan`, `@briefing`, `@standard`, `@high` et `@approve` ne sont pas
recopiées dans le contexte généré. Si elles figurent encore dans le message source canonique,
elles restent une citation ; les contrôles de routage sont déjà fixés par le serveur.

Le serveur reste seul propriétaire de tous les autres champs : identité de l’agent, langue,
connexion, salon, message déclencheur, interlocuteur, Topic, contact, clé d’idempotence et lien au
round. Les contrôles explicites deviennent `forced_route`, `forced_effort`, `auto_approve` et, pour
le harnais interne, l’exigence de briefing ; le modèle de construction ne choisit jamais ces
valeurs. `plan` et `briefing` sont refusés avant création lorsque la politique du driver ne les
expose pas.

L’idempotence est vérifiée avant l’appel spécialisé afin qu’une reprise d’un effet déjà commis ne
refacture pas et ne recrée pas la Task. La fraîcheur du round est vérifiée une seconde fois après
l’appel : un message arrivé entre-temps annule la création et laisse le round suivant décider. Le
coût de la construction est attribué à la Task créée. Pour ces admissions, l’historique complet
n’est plus dupliqué dans `Task.messages`; le message déclencheur et ses alias techniques restent
dans `Task.data`, tandis que le journal Messenger demeure la source canonique.

La Task porte en outre un marqueur serveur indiquant que son objectif est autonome. À partir de
cette frontière, le dispatcher, le planner, le briefing et l’exécuteur ne relisent ni la
chronologie Messenger, ni Memory, ni la capsule de continuité qui ont servi à construire
l’objectif. Le dispatcher reçoit le libellé et l’objectif durables ; les contrôles imposés restent
des champs typés de la Task. Les métadonnées exactes de connexion, salon, message et interlocuteur
restent disponibles dans `Task.data` et le contexte de messagerie. Le Working Set courant ainsi
que les apports propres au plan, au briefing et au harnais restent autorisés : ils décrivent le
travail en cours, pas une seconde reconstruction de la demande.

Les amendements acceptés conservent le contrat de l’ADR 0025. Le générateur s’applique à toute
nouvelle racine, y compris lorsqu’un amendement devenu dangereux bascule vers une création séparée.

## Conséquences

- Une confirmation elliptique devient un objectif durable compréhensible par le dispatcher, le
  planner, le briefing et le harnais sans dépendre de l’interprétation du modèle conversationnel.
- Une omission dans la synthèse ne peut plus effacer le texte du message source. Les exigences
  des échanges antérieurs restent à expliciter dans le contexte généré ; leur restitution relève
  toujours du modèle et ne constitue pas une garantie de fidélité sémantique absolue.
- Les métadonnées sociales et de routage restent déterministes et auditables ; aucun LLM ne peut
  changer silencieusement de salon, d’interlocuteur ou de stratégie imposée.
- La création ajoute un appel LLM `standard`, corrélé au round sous le purpose
  `conversation.task_objective`; son échec empêche la création d’une Task sous-cadrée.
- La composition multi-niveaux des prompts successifs reste une décision distincte, mais elle part
  désormais de l’objectif autonome et ne peut réinjecter le contexte source déjà consommé.

## Preuves dans le code

`back/app/conversation/task_objective.py`, `back/app/conversation/mcp.py`,
`back/app/conversation/directives.py`, `back/app/harness/conversation.py`,
`back/app/agent/context.py`, `back/app/agent/dispatcher.py`, `back/app/memory/bootstrap.py`,
`back/app/messenger/session.py` et `back/app/llm/purposes.py`.
