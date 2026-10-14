# 0182 — Capacité REST des Tools et connexions

- Date : 2026-10-14.
- Statut : accepté.

La demande utilisateur ajoute une capacité REST facultative aux Tools, indépendante de MCP.
`rest_config` porte l'adresse de base HTTP(S), éventuellement référencée par un paramètre
de connexion, les noms des paramètres d'authentification et d'en-têtes, un timeout et une
limite de réponse. L'interface expose **Activer API**. Aucun secret littéral ne fait partie
de ce contrat : les paramètres globaux et les connexions conservent leur héritage,
chiffrement, masquage et protection de l'administration des destinations.

`app.tools.execute_rest_request` et son export par `app.tools.facade` sont la surface
publique asynchrone. L'appel désigne l'agent exécutant, le Tool et une requête typée
(méthode, chemin relatif, paramètres, en-têtes et corps JSON ou texte). La connexion est
résolue côté serveur et doit être active et appartenir à cet agent et à ce Tool.
La réponse conserve statut HTTP, en-têtes et corps JSON ou texte ; les secrets connus
réfléchis par le serveur sont masqués. Un statut HTTP d'erreur est une réponse exploitable.

Les permissions par endpoint appartiennent exclusivement au service tiers, selon le token.
Galaris n'exige ni OpenAPI, ni catalogue d'opérations, ni filtre d'URL, ni accord par appel REST.
Les permissions MCP existantes restent propres à MCP. Le confinement du chemin à l'adresse
configurée et l'absence de suivi de redirection protègent la destination des identifiants ;
ils ne constituent pas une politique d'autorisation métier.

La façade n'expose aucun proxy HTTP ni outil MCP générique. Les futures activités API et
Code la consommeront ; ce lot ne modifie pas le moteur Process et n'enveloppe pas chaque
appel dans un Run. Les retries, callbacks et suivi de jobs REST ne sont pas ajoutés.
Une erreur de transport ne prouve pas l'absence d'effet et ne déclenche aucun rejeu.
