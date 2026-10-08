<p align="right"><strong>Français</strong> · <a href="../../../en/architecture/flows/browser.md">English</a></p>

# Flux du navigateur agentique

Le navigateur intégré est un Tool Galaris gouverné comme les autres capacités MCP. Une connexion
`browser` est créée automatiquement pour chaque agent. Son
activation, puis les éventuelles désactivations fonction par fonction, déterminent exactement ce
que le harnais interne et Hermès voient dans leur catalogue.

```text
Agent / Task
   → fonctions MCP app.browser
   → validation et propriétaire {agent_id, task_id}
   → API authentifiée sur executor_net
   → browser-executor
      ├── un processus Chromium partagé
      ├── un BrowserContext isolé par session
      ├── proxy sortant avec résolution DNS
      ├── réseau interne executor_net
      └── réseau sortant browser_egress
   → contenu ARIA avec refs, ou capture verticale bornée
   → blocs image MCP + fichiers `console://` lorsque la console est active
```

## Sessions et autorisation

`browser_open` crée une session opaque. Il accepte facultativement un viewport en pixels CSS,
borné à 320–3840 px de large et 240–2160 px de haut, afin de choisir dès le chargement la mise en
page responsive (par exemple 1440 × 900 en desktop ou 390 × 844 en mobile). Chaque opération
suivante doit fournir le même
`agent_id` et le même `task_id`; une autre tâche, même portée par le même agent, ne peut donc pas
reprendre cette session. Les contextes Chromium ne partagent ni cookies, ni cache, ni stockage
local. Ils expirent après une durée d’inactivité bornée et `browser_close` libère immédiatement
leurs ressources.

Chromium démarre à la première demande de session, pas lors du démarrage du sidecar ni des
contrôles de santé. Après expiration ou fermeture du dernier contexte, le passage de nettoyage
suivant ferme aussi Chromium. Une création en cours réserve déjà sa place et interdit cette
mise en veille ; les demandes arrivant pendant la fermeture attendent un nouveau navigateur.
L’expiration conserve `BROWSER_SESSION_TTL_SECONDS` (120 secondes par défaut), avec un passage
de nettoyage toutes les 10 secondes. Le premier appel après mise en veille supporte
le coût du lancement. `/health` reste sain pendant la veille ; une déconnexion inattendue de
Chromium termine toujours le sidecar en erreur pour permettre sa récupération.

L’interface générique des connexions permet d’activer le Tool pour un
agent et d’autoriser ou retirer séparément `open`, `content`, `screenshot` et les actions. Lorsque
le Tool Galaris est actif pour un agent Hermès, le manager désactive le toolset navigateur natif
d’Hermès afin de conserver une seule frontière d’autorisation et d’audit.

## Sorties

Le paramètre de connexion `default_output` accepte `content` ou `screenshot`.

- `content`, valeur par défaut, renvoie le snapshot d’accessibilité de la page avec des références
  stables utilisables par `browser_click` et `browser_type`. Un contenu trop long indique
  `next_offset` pour être relu par tranches.
- `screenshot` capture la hauteur de page complète dans la limite configurée. Une page haute est
  divisée en bandes verticales; le manifeste indique les dimensions, les URI `console://` et
  `truncated=true` si une limite de hauteur, de nombre de bandes ou d’octets est atteinte.
  `browser_screenshot` peut modifier facultativement le viewport avant la capture; la résolution
  choisit la mise en page CSS, sans désactiver la capture de la page complète ni son découpage.
  La sauvegarde `console://` est auxiliaire : sans Console, ou si cette sauvegarde échoue, les blocs
  image MCP et leur manifeste restent le résultat réussi de la capture, avec `path: null` pour la
  bande non sauvegardée.

Les actions acceptent aussi un choix explicite qui surcharge le défaut de la connexion pour cet
appel. Les images retournent à la fois des blocs MCP visibles par les modèles multimodaux et,
lorsqu’une console est active, des fichiers durables sous `console://browser/<session>/`. Sans
console, aucune destination locale implicite n’existe.

Le contrat remis au modèle prescrit la séquence robuste : ouvrir avec `output="content"`, conserver
le `session_id`, effectuer les interactions dans la même Task, relire `browser_content` pour
contrôler l’URL et l’état final, puis capturer immédiatement. Il conseille `1440 × 900` pour le
desktop, `390 × 844` pour le mobile, JPEG par défaut et PNG pour les détails fins. Une session
expirée n’est jamais réessayée : le modèle ouvre une nouvelle session et emploie son nouvel ID.

## Accès réseau

Le sidecar n’expose aucun port hôte. Le backend le joint sur `executor_net` avec un secret partagé.
Chaque contexte possède son proxy local, associé à son propriétaire. Pour chaque requête, le
proxy résout le DNS, transmet origine, méthode et adresses à
`POST /api/browser/network/authorize`, puis se connecte à une adresse déjà vérifiée. Le callback
exige le secret partagé ; les corps, chemins et paramètres des requêtes ne lui sont pas transmis.
Une indisponibilité du contrôle bloque la requête.

La connexion `browser` porte cinq réglages réseau, configurables globalement ou par agent :

- `public_access_mode=allow`, initialisé pour les nouvelles installations, autorise les sites publics
  sans demande par site pour les méthodes HTTP et WebSocket. Les refus explicites et les filtres
  restent prioritaires ; ce mode n’autorise aucune adresse locale et ne crée pas d’accord mémorisé.
  `ask` réactive l’autorisation par site et reste le repli en l’absence de valeur.
  Une instance existante sans ce paramètre reçoit `ask` à la mise à jour ; ses autres choix sont conservés.
- `allow_local_network=false` par défaut interdit les réseaux privés, le loopback, les adresses
  réservées et link-local, y compris en IPv6. `true` permet de demander une permission locale.
- `network_filter_mode=block` refuse les destinations de `network_filter` ; `allow` n’admet que
  les destinations de cette liste, et une liste vide bloque tout.
- `network_filter` accepte domaines exacts, `*.example.test`, IP et CIDR, séparés par virgules ou
  espaces, avec port facultatif. Un joker ne couvre pas le domaine racine. En liste positive,
  toutes les adresses DNS doivent correspondre. Un domaine ne dispense jamais du contrôle local.
- `permission_methods` contient par défaut `POST PUT PATCH DELETE WEBSOCKET`. Les méthodes
  demandent un accord en mode `ask`, ainsi que sur le réseau local lorsqu’il est activé.
  Les méthodes HTTP connues peuvent y être ajoutées ou retirées ; vide rétablit le défaut, une valeur inconnue
  bloque l’accès. Les GET publics passent sans question dans la configuration par défaut.

Les interdictions de configuration précèdent toujours les permissions. Une demande locale et
une demande POST sont distinctes. La clé déterministe
`browser:v1:post:https://example.test:443` couvre une méthode et une origine normalisée, tous
chemins confondus, pour un seul agent. Le port, le protocole et les sous-domaines restent séparés.
`app.messenger.request_permission` conserve question, réponse, responsable et date ; une
contrainte SQL empêche les doublons actifs entre workers. Il utilise les interactions communes,
avec réponses textuelles ou boutons du chat interne. Une question expire après sept jours et
peut être renouvelée ; les accords et refus restent valables jusqu’à suppression. Un changement
de responsable invalide la décision à sa prochaine utilisation.

Les redirections, sous-ressources et connexions WebSocket passent par le proxy. HTTPS est
déchiffré dans le processus du sidecar pour vérifier la méthode, puis rechiffré vers la destination
avec validation normale du certificat et du nom distant. Le certificat du proxy est éphémère.
Les service workers, QUIC et sorties WebRTC sans proxy sont désactivés. Les WebSocket ouverts
sont revérifiés chaque seconde, sans contrôles simultanés ; une indisponibilité les ferme au
terme du délai de contrôle de 15 secondes. La vérification conserve leur adresse de connexion,
même si le DNS change. Les requêtes HTTP déjà transmises ne sont pas annulées rétroactivement.

Le résultat `network_issues` distingue demande en attente, refus et blocage de configuration.
L’action bloquée n’est pas rejouée automatiquement après la réponse : l’agent doit attendre la
décision et retenter l’action appropriée, sans resoumettre aveuglément un formulaire. Les
sessions humaines sans connexion agent conservent les restrictions par défaut et ne créent
pas de permission pour un agent fictif.

Pour prévisualiser une application locale, activer `allow_local_network` sur la connexion de
l’agent, autoriser sa destination dans le filtre, puis répondre à la demande. `localhost`
désigne le sidecar ; employer le DNS du conteneur cible ou `host.docker.internal` et un service
qui écoute sur une interface accessible depuis Docker. Les URL avec identifiants et les
schémas hors HTTP(S)/WebSocket restent refusés.

La durée d’inactivité, le nombre maximal de sessions, les délais d’opération,
contenu, HTML, dimensions par défaut, bandes et octets
sont stockés dans `params`, configurables sous **Préférences → Navigateur** lorsqu’au moins
une connexion `browser` est active. Le backend expose cette disponibilité via
`GET /api/browser/status`, réservé aux droits de préférences. Une URL directe masque aussi
les champs lorsque le Tool n’est pas utilisé.

Chaque appel au sidecar transporte un instantané des préférences dans `settings`, après
authentification avec le token du volume partagé. Le sidecar valide les bornes et
applique ces valeurs uniquement à cette opération, y compris sur une session existante.
Les dimensions par défaut s’appliquent aux nouvelles fenêtres ; les viewports explicitement
demandés restent bornés. Le modèle ne contrôle pas les plafonds administrateur.

La capacité est vérifiée à chaque ouverture, créations en cours comprises ; une réduction
ne ferme aucune session existante. Le délai d’inactivité est mémorisé par session et
actualisé à sa prochaine action. L’expiration part de la fin de l’action et ne ferme
jamais une session occupée. Les exports PDF conservent leur propre limite de concurrence.

## Points d’entrée à lire

- Tool et client : `back/app/browser/mcp.py`, `service.py`, `schemas.py`.
- Exécuteur : `browser-executor/server.mjs`, `network-proxy.mjs` et `lib.mjs`.
- Politique et décisions : `back/app/browser/network.py`, `back/app/messenger/permissions.py`.
- Gouvernance des connexions : `back/app/tools/mandatory_tools.py`,
  `back/app/tools/mcp_loader.py`.
- Alignement Hermès : `back/bridge/hermes/manager.py`.
