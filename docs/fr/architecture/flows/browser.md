<p align="right"><strong>Français</strong> · <a href="../../../en/architecture/flows/browser.md">English</a></p>

# Flux du navigateur agentique

Le navigateur intégré est un Tool Galaris gouverné comme les autres capacités MCP. Une connexion
`browser` est créée automatiquement pour chaque agent, mais reste inactive par défaut. Son
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

Le Tool est désactivé par défaut. L’interface générique des connexions permet de l’activer pour un
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

Le sidecar n’expose aucun port hôte. Le backend le joint sur `executor_net` avec un secret partagé;
seul le sidecar possède aussi une sortie Internet. Le proxy local résout lui-même chaque
destination et connecte Chromium à toute URL HTTP(S) joignable depuis ses réseaux, y compris les
noms de services Docker, les adresses privées ou réservées, le loopback du sidecar et
`host.docker.internal`. Les redirections et sous-ressources bénéficient du même accès. Les URL qui
embarquent des identifiants et les schémas autres que HTTP(S) restent refusés afin de ne pas
introduire de credentials dans les appels d’outil ni d’exposer le système de fichiers du sidecar.

Cette ouverture permet notamment de prévisualiser une application en construction servie par un
autre conteneur sur `executor_net`, ou par l’hôte via `host.docker.internal`. Comme `localhost`
désigne le sidecar lui-même, une application lancée ailleurs doit employer le nom DNS de son
conteneur ou `host.docker.internal`, et écouter sur une interface accessible depuis Docker. Un
serveur lancé dans la Console embarquée est ainsi joignable sous `http://ssh-executor:<port>` s’il
écoute sur `0.0.0.0`.

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
- Exécuteur : `browser-executor/server.mjs` et `lib.mjs`.
- Gouvernance des connexions : `back/app/tools/mandatory_tools.py`,
  `back/app/tools/mcp_loader.py`.
- Alignement Hermès : `back/bridge/hermes/manager.py`.
