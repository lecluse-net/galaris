# 0313 — Rattachement des outils aux services métier

Statut : accepté — 22 novembre 2026.

Multimédia reprend les outils des anciens services Audio et Image. Navigateur reprend
`search_web`. Agent reprend `team_*`, Documents reprend les `document_*` de Galaris et
Conversation, et Processus reprend `conversation_process_*`. Contact et Tâches sont deux
services système actifs pour chaque agent. Ils portent respectivement `contact_*` et les
familles `task_*` et `conversation_task_*`. Les noms des outils, les restrictions de contexte,
les vérifications métier et les URI de ressources restent stables.

DbAdmin transfère les règles et les traces d’accord. Pour les fusions, l’activation des services
d’origine est transcrite en autorisations par fonction. Si seul un ancien service était actif,
les outils du service de destination qui étaient inaccessibles restent bloqués. Les outils de
transcription restent bloqués par défaut pour les nouveaux agents. Une règle contradictoire ou
une référence qui empêcherait le transfert annule l’opération concernée.
