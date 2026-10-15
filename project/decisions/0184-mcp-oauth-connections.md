# 0184 — OAuth pour les connexions MCP

L’audience `resource` utilisée pour l’autorisation et les échanges de jetons provient des
métadonnées de la ressource protégée ; elle peut différer de l’URL de transport MCP.
Les erreurs de préparation et d’échange conservent le statut HTTP et un code OAuth standard
autorisé, sans réponse brute ni jeton. Le bouton Réessayer relance l’action en échec.

- Date : 2026-10-15.
- Statut : accepté.

Les connexions MCP HTTP/SSE proposent un bouton **Connecter le compte**, sans réglage
OAuth dans le Tool ni saisie habituelle de Client ID, scopes ou secret. `app.connection` possède
le parcours humain et les grants par connexion ; `app.tools`
construit les transports et conserve ses règles d'exposition et d'autorisation des fonctions.
Les jetons ne sont ni des paramètres EAV, ni des secrets globaux du Tool, ni des données
fournies au modèle. Une table `connection_oauth`, supprimée avec sa connexion, conserve
le grant et la demande temporaire dans des enveloppes chiffrées par la clé existante.
Le bouton enregistre d’abord le brouillon de connexion, puis ouvre le fournisseur ;
un échec d’enregistrement ne lance aucune autorisation. Les anciennes configurations
OAuth du Tool restent lisibles, normalisées vers une authentification ordinaire sans
identifiants. Les accords liés à leur ancienne empreinte demandent une reconnexion.

Le navigateur ouvre le fournisseur puis revient sur `/connection/oauth-callback`. Cette
page transmet code et state à une API authentifiée par JWT web, protégée par
`CONNECTION_EDIT`, le périmètre de gestion de l'agent et l'identité de l'initiateur.
Il n'existe pas de callback backend public. Le state est aléatoire, stocké sous forme de
condensat, expire après dix minutes et se consomme avant l'échange du code. PKCE S256
et l'indicateur `resource` sont obligatoires ; l'issuer retourné, s'il existe, est vérifié.

Le navigateur transmet son origine à l’API : seules l’origine configurée et les origines de
boucle locale sont admises comme retour direct, avec le chemin fixe de Galaris. Un accès
localhost utilise ainsi son propre port et supprime le besoin d’un relais. Les métadonnées
client publiques (CIMD), l’enregistrement dynamique et les clients existants sont utilisables.
Le document client public ne contient que l’identité de Galaris et ses retours, sans donnée de
connexion. Il n’est utilisé que si le fournisseur annonce CIMD et si une lecture publique
valide le document. DCR négocie un client public, puis les méthodes Basic/POST annoncées en
cas de refus des métadonnées du client. Une absence de déclaration PKCE permet un essai S256,
sans autoriser un repli plain ni l’absence de PKCE.

Si le retour direct ne peut pas être préparé, l’autorisation par code d’appareil RFC 8628
annoncée par le fournisseur est essayée avant tout relais. Le code d’appareil reste dans
l’enveloppe chiffrée temporaire ; seuls le code utilisateur, la page d’activation, l’intervalle
et un state opaque sont renvoyés au navigateur. L’API de polling exige la session web,
CONNECTION_EDIT, le périmètre de l’agent et le même initiateur. L’intervalle est réservé en
base avant l’appel, `slow_down` ajoute cinq secondes, et un nouvel accord ou une déconnexion
empêche un résultat tardif d’être appliqué. Le refus et l’expiration restent terminaux.

En dernier recours, le même client Galaris essaie `http://127.0.0.1:3334/oauth/callback`.
Le navigateur propose alors un script Python
autonome à lancer sur son poste. Ce relais ponctuel écoute uniquement sur la boucle locale,
vérifie Host, chemin et state, puis renvoie le navigateur vers le retour web de Galaris.
Il ne reçoit ni jeton, ni session, ni vérificateur PKCE ; il s’arrête après le retour ou dix
minutes, sans journaliser les URL. Le serveur conserve l’URI effectivement enregistrée pour
l’échange du code et réutilise ce client lors d’une reconnexion. Aucune identité ou URL
d’une autre application n’est empruntée. Le retour dans un nouvel onglet utilise une association
state/connexion dans le stockage local du navigateur, limitée à dix minutes et remplacée à la
prochaine tentative sur cette connexion. Les contrôles serveur restent identiques. L’instance
Galaris n’a pas besoin d’être rendue publique, mais le poste doit pouvoir la joindre.

La découverte suit les métadonnées de ressource protégée puis du serveur d'autorisation
(avec repli OIDC et découverte historique du SDK MCP). Le client peut être enregistré
dynamiquement ; les scopes sont découverts dans les métadonnées et le challenge du serveur.
Un fournisseur sans enregistrement automatique propose la saisie des identifiants d’un
client pré-enregistré. Le secret éventuel est transmis à l’API web puis uniquement conservé
dans l’enveloppe chiffrée. Ce formulaire n’est jamais le parcours initial. Les requêtes de découverte et de jetons sont bornées, sans
redirection, avec résolution DNS épinglée. Une origine tierce découverte doit être publique ;
la destination MCP explicitement configurée peut être privée. HTTPS est requis sauf localhost.
Les configurations OAuth propriétaires hors métadonnées MCP restent hors de ce lot.

Un marqueur typé, non sérialisé dans les paramètres, relie les transports à leur connexion
et indique si celle-ci possède un accord ou une demande OAuth. Les autres connexions
du même Tool conservent leur authentification ordinaire. Le grant OAuth remplace les
en-têtes d’authentification ordinaires et ne place jamais de jeton dans l’URL.
L'adaptateur HTTPX commun aux clients FastMCP et Pydantic AI résout le grant au moment
de chaque requête, dans une transaction autonome courte. Le verrou de ligne sérialise
le renouvellement et sa rotation entre workers. L'empreinte lie le grant à l'agent, au Tool,
à l’URL résolue. Une réponse 401 invalide seulement le token
utilisé ; elle ne rejoue jamais l'effet distant. Une déconnexion ou une nouvelle demande
pendant l'échange du code empêche une réponse tardive de restaurer l'ancien grant.

La déconnexion est locale. La révocation de l'accord chez le fournisseur reste accessible
dans sa propre interface. Aucun process métier ni nouveau moteur d'exécution n'est ajouté.
