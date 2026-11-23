# 0320 — Rattachement des permissions des outils natifs

Statut : accepté — 23 novembre 2026.

Le rattachement déclaré dans le registre MCP détermine les connexions dont les permissions
de fonction peuvent affecter un outil. Plusieurs connexions peuvent proposer un outil de
protocole. Le catalogue l’expose si une de ces connexions le permet et l’appel vérifie la
permission de la connexion sélectionnée.

La portée de gestion appartient normalement au Service de la ressource. Les valeurs admises
et les défauts du catalogue et de l’autorisation viennent du même contrat. Les inspections
d’exécution déclarent leur recours à la portée Services dans le registre. Elles conservent
leurs permissions de fonction d’origine. Le Lab résout ces permissions à partir du registre.
Les ACL, la politique de pair de la messagerie et la participation au contexte métier
continuent de s’appliquer à leurs propres frontières.

Une réponse Agent qui décrit une ressource liée à un agent expose son `agent_id`.
Les entités partagées et les humains exposent `null`. Les listes mixtes portent le
rattachement sur chaque entrée. Les identifiants historiques sont conservés.
