# 0182 — Capacité REST des Services et connexions

- Date : 2026-10-14.
- Statut : accepté.

La demande utilisateur ajoute une capacité REST facultative aux Services, indépendante de MCP.
`rest_config` porte l'adresse de base HTTP(S), éventuellement référencée par un paramètre
de connexion, les noms des paramètres d'authentification et d'en-têtes, un timeout et une
limite de réponse. L'interface expose **Activer API**. Aucun secret littéral ne fait partie
de ce contrat : les paramètres globaux et les connexions conservent leur héritage,
chiffrement, masquage et protection de l'administration des destinations.

`app.services.execute_rest_request` et son export par `app.services.facade` sont la surface
publique asynchrone. L'appel désigne l'agent exécutant, le Service et une requête typée
(méthode, chemin relatif, paramètres, en-têtes et corps JSON ou texte). La connexion est
résolue côté serveur et doit être active et appartenir à cet agent et à ce Service.
La réponse conserve statut HTTP, en-têtes et corps JSON ou texte ; les secrets connus
réfléchis par le serveur sont masqués. Un statut HTTP d'erreur est une réponse exploitable.

Les permissions par endpoint appartiennent exclusivement au service tiers, selon le token.
Galaris n'exige ni OpenAPI, ni catalogue d'opérations, ni filtre d'URL, ni accord par appel REST.
Les permissions MCP existantes restent propres à MCP. Le confinement du chemin à l'adresse
configurée et l'absence de suivi de redirection protègent la destination des identifiants ;
ils ne constituent pas une politique d'autorisation métier.

Les activités REST de Process et l'outil MCP natif `rest_request` consomment la façade.
Chaque Service déclarant REST expose la même fonction sur ses propres connexions.
L'agent choisit le `service_code` publié par `rest_request` et `services_list`, complété par
`account_email` lorsque plusieurs comptes Mail utilisent ce Service. L'autorisation MCP
porte sur cette connexion et la requête précise, avec **Sur demande** par défaut.
Pour un upload MCP, la façade Fichiers matérialise chaque URI dans le contexte de l’agent.
Le consentement couvre le contenu, le nom et le type de chaque fichier. Le transport envoie
les octets bruts ou les parties multipart, accompagnées des champs de formulaire.
L'exposition conversationnelle suit le réglage du Service. Les appels directs de Process
conservent leur propre admission. Une erreur de transport laisse l'effet distant incertain.
