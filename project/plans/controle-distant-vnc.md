# Intégration VNC pour le contrôle des PC distants

- Statut : `design`
- Date : 2026-10-11.
- Périmètre proposé : contrôle par les agents et contrôle manuel dans Galaris.
- Première cible : un PC avec un serveur VNC accessible depuis l'infrastructure Galaris ; système et serveur à préciser lors du prototype.

## Résultat recherché

Depuis Galaris, ouvrir une session sur un PC distant, voir son bureau, prendre une capture
d'écran, saisir du texte par événements clavier, utiliser des raccourcis et contrôler
la souris : déplacement, clic simple/double/droit, défilement et glisser-déposer.
Les agents disposent des mêmes opérations via MCP. Un humain peut observer puis reprendre
le contrôle ; un seul acteur émet les entrées à un instant donné.

Le PC distant doit déjà disposer d'un serveur VNC autorisant ces opérations. Galaris devient
un client VNC ; l'installation et la configuration du serveur distant font partie du guide
d'utilisation. Un accès au bureau physique, aux écrans verrouillés ou aux invites système
dépend du serveur et de l'OS : aucune compatibilité universelle n'est présumée.

Le premier parcours de réception utilise un bureau et un éditeur de texte synthétiques :
connexion, capture initiale, clic dans l'éditeur, saisie de `Bonjour, été !`, raccourci,
défilement, déplacement d'une fenêtre, capture finale et fermeture. Il doit fonctionner
sans console SSH attachée à l'agent.

## Socle existant et garanties à préserver

| Surface actuelle | Conséquence pour l'intégration |
|---|---|
| `back/app/browser/mcp.py`, `service.py` et `tests/test_mcp.py` | Référence pour l'exécuteur isolé, le propriétaire agent/Task, le nettoyage et les images MCP. Le navigateur reste consacré au Web. |
| `back/app/connection/facade.py`, `models.py` et `tests/test_function_states.py` | Réutiliser configuration, secrets et modes Actif/Bloqué/Sur demande. Une seule Connection existe par couple Tool/agent. |
| `back/app/tools/contracts.py`, `tests/test_live_authorization.py` | Réutiliser l'identité d'opération et la révocation vérifiée à l'appel ; une découverte ancienne ne confère aucun droit. |
| `back/app/file_share/__init__.py` et `resource_contracts.py` | Toute capture conservée est créée via la façade publique et rend une URI canonique. |
| `browser-executor/`, `compose.yaml` | Référence de déploiement pour un service technique isolé et authentifié, sans port hôte public. |

Les déclarations inspectées dans `back/modules.py` et `front/modules.ts` ne comportent pas
de module VNC. Les captures du navigateur existant renvoient déjà des images MCP sans
stockage local obligatoire : préserver cette garantie pour le nouveau Tool.

Ne pas élargir les droits du navigateur, de la console, des fichiers ou des agents pour
introduire VNC. Une session distante est un canal technique ; sa durée ne justifie pas
un Process métier. Les Tasks existantes restent responsables des workflows agentiques.

## Architecture proposée

```text
Agent / Task ── MCP ──────────────┐
                                 v
Utilisateur ── API / WebSocket ── bridge.vnc
                                 │ authentification, droits, propriétaire,
                                 │ cible configurée et contrôle exclusif
                                 v
                              vnc-executor
                                 │ client RFB, framebuffer,
                                 │ file ordonnée des entrées
                                 v
                           Serveur VNC du PC

Images MCP / vue du bureau ← captures du framebuffer
Captures conservées       → app.file_share → URI canonique
```

Proposer `back/bridge/vnc` pour traduire le protocole externe et posséder ses sessions,
avec une surface publique légère. `app.connection`, `app.tools` et `app.file_share`
conservent leurs responsabilités actuelles. Ajouter `front/bridge/vnc` pour la configuration,
le guide et la vue dédiée au contrôle VNC. Le chargeur de modules et les budgets
d'architecture doivent déclarer ces contributions explicitement.

Un nouveau `vnc-executor/` possède les connexions RFB et le framebuffer. Il reçoit seulement
des commandes validées et authentifiées. Les sockets et traitements bloquants restent hors
de la boucle async du backend. Un worker par session sérialise les entrées ; son allocation
reste bornée par un quota global et par propriétaire. Les workers backend utilisent ce
service partagé, sans verrous exclusivement en mémoire dans un worker HTTP.

### Choix du client à qualifier

Utiliser un client RFB existant, pas une nouvelle implémentation du protocole.
LibVNCClient est le candidat initial pour le moteur : son API expose les entrées clavier,
les événements souris et les mises à jour d'écran. Le lot 0 doit vérifier empaquetage,
licence, maintenance, sécurité de la version retenue et intégration dans les images Docker.
Si un binding Python est retenu, sa compatibilité avec Python 3.14 doit être démontrée.
[API LibVNCClient](https://libvnc.github.io/doc/html/group__libvncclient__api.html).

Pour la vue humaine initiale, envoyer des frames bornées et des commandes typées sur un
WebSocket Galaris. Cela permet de conserver exactement la même frontière d'autorisation
pour un utilisateur et un agent. Mesurer la fluidité avant de retenir ce transport.

noVNC reste une alternative si un client navigateur RFB complet s'avère nécessaire.
Son API propose le clavier, la capture et un mode observation ; websockify adapte
WebSocket vers TCP. Le mode observation côté navigateur ne suffit pas à appliquer les
permissions : un flux RFB brut exige un contrôle serveur des entrées, de la reprise et des
secrets. Cette variante doit donc être conçue et chiffrée séparément avant adoption.
[API noVNC](https://novnc.com/noVNC/docs/API.html),
[websockify](https://github.com/novnc/websockify).

## Connexions et accès

Le Tool intégré `vnc` reste optionnel et inactif par défaut. La configuration existante
porte la cible, le port, le mode d'authentification, les secrets chiffrés selon le mécanisme
actuel, le profil clavier et les limites de session. Les secrets sont résolus côté serveur ;
ils ne figurent ni dans les arguments MCP, ni dans le navigateur, ni dans les résultats.

Pour la première version, une connexion VNC sélectionne une seule cible par agent,
conformément à l'unicité actuelle `(tool_id, agent_id)`. L'adresse est administrée dans
la connexion ; `vnc_open` n'accepte pas un hôte arbitraire. Un changement de cible,
d'identifiants ou de droits invalide les sessions associées. Le contrôle de plusieurs PC
par le même agent nécessitera ensuite un catalogue de cibles et des affectations explicites,
sans supprimer l'unicité des Connections ni stocker des secrets dans un JSON libre.

Les droits humains distinguent configuration, observation et contrôle. Ils portent sur
un périmètre de cibles explicite, à composer avec les règles de gestion des agents
existantes : choisir une connexion agent dans l'interface ne donne pas ses droits MCP
à l'utilisateur. Aucune session humaine n'utilise un agent fictif.

Les appels agents suivent les modes de fonction existants, avec lecture et actions
configurables séparément. Les accords Sur demande passent par le mécanisme commun
et portent sur la cible et les arguments de l'action. Les entrées manuelles relèvent des
droits humains et du bail de contrôle ; elles ne produisent pas une demande par frappe.

Le réseau doit autoriser explicitement la destination configurée, y compris privée,
vérifier DNS/IP/port et connecter l'adresse validée. Interdire les accès implicites aux
services internes, métadonnées cloud et destinations non configurées. Le transport
Galaris/exécuteur est authentifié ; pour le PC distant, retenir TLS vérifié si le client et
le serveur le permettent, ou un réseau privé protégé/VPN. Le chiffrement du WebSocket
du navigateur ne protège pas à lui seul le segment exécuteur/PC.

## Contrat MCP proposé

Noms et schémas à figer après le prototype. Chaque appel vérifie le propriétaire et les
droits courants avant son effet.

| Fonction | Effet attendu |
|---|---|
| `vnc_open()` | Résoudre la cible autorisée, ouvrir la session et retourner `session_id`, dimensions, génération de géométrie et capacités. |
| `vnc_status(session_id)` | Lire état, capacités, détenteur du contrôle et dernière frame, sans rouvrir la session. |
| `vnc_screenshot(session_id, region?, format?, max_size?, destination?)` | Rendre une image MCP et sa géométrie ; sauvegarder seulement si une destination canonique est demandée. |
| `vnc_type(session_id, text, interval_ms?)` | Émettre des appuis et relâchements clavier, avec longueur et cadence bornées. |
| `vnc_press(session_id, keys)` | Émettre une touche ou combinaison normalisée, puis relâcher tous les modificateurs. |
| `vnc_mouse(session_id, action, x?, y?, button?, end_x?, end_y?, delta?, geometry_generation)` | Déplacer, cliquer, double-cliquer, défiler ou glisser, avec coordonnées et durée bornées. |
| `vnc_close(session_id)` | Fermer et libérer les ressources ; une fermeture répétée est sans nouvel effet. |

`vnc_open` ouvre en observation. La prise de contrôle explicite par l'API humaine ou une
première action agent autorisée acquiert un bail exclusif ; une action agent échoue si
un humain contrôle déjà la cible. Ce bail porte sur la cible effective, et pas seulement
sur la session, pour éviter deux connexions concurrentes vers le même PC.

Le schéma des commandes inclut l'identité d'opération Galaris pour dédupliquer un appel
reçu deux fois. Les sorties distinguent rejet avant effet, événements envoyés et effet
incertain. Le protocole RFB transporte les entrées mais ne confirme pas l'exécution métier
dans l'application distante ; une capture ultérieure sert à vérifier le résultat.
[Messages RFB](https://github.com/rfbproto/rfbproto/blob/master/rfbproto.rst).

### Images et coordonnées

L'observation de l'agent suit ses décisions, sans cadence fixe de capture. Prendre une
image initiale, puis une nouvelle capture après chaque action pour vérifier son résultat
avant de décider la suivante. Une action peut être une saisie complète ou un raccourci :
aucune capture par caractère, événement souris ou intervalle d'une seconde n'est requise.

Pendant un chargement, vérifier le changement attendu à intervalles configurables,
progressivement espacés si l'écran reste identique, avec un nombre de vérifications et
une échéance bornés. Utiliser les mises à jour RFB pour détecter une évolution du bureau
quand c'est possible ; un changement visuel ne prouve pas à lui seul la fin du chargement.
La fermeture, la fin du run ou la révocation arrête ces vérifications.

Séparer la réception des mises à jour RFB, l'affichage humain, la production des captures
et les appels au modèle. La boucle agentique reste capture récente → analyse → action
courte → nouvelle capture ; elle ne lance pas de captures ni d'inférences en parallèle
pendant l'analyse en cours. La vue humaine peut rester fluide indépendamment de cette
boucle. Conserver la dernière image et un historique borné ; ne pas sauvegarder toutes
les frames. Aucun trafic technique ne prolonge indéfiniment le TTL d'inactivité du
propriétaire, ni ne crée une file de décisions sur des images périmées.

Une capture inclut largeur/hauteur du bureau, région capturée, facteur d'échelle,
horodatage, numéro de frame et génération de géométrie. Les actions souris utilisent les
pixels du framebuffer distant ; la transformation depuis une image réduite ou une région
est explicite. Refuser une génération périmée après changement de résolution et demander
une nouvelle capture. Une image ancienne à géométrie identique n'assure pas que le bouton
visé existe encore : l'agent vérifie visuellement avant et après une action importante.

Attendre une première frame complète avant de réussir une capture. Après une action,
demander une actualisation avec délai borné et indiquer si une nouvelle frame a été reçue ;
ne pas présenter une ancienne image comme un résultat actualisé. Borner pixels, octets,
fréquence et régions ; ne pas confondre un bureau immobile avec une connexion morte.

Sans destination, retourner les blocs image MCP avec `uri: null`. Une destination explicite
passe par `app.file_share` et ses ACL ; aucune nouvelle URI locale `vnc://` ni chemin hôte
n'est nécessaire. L'échec d'une sauvegarde reste distinct de la capture déjà obtenue.

### Clavier

Distinguer texte à saisir et touches physiques/raccourcis. RFB utilise notamment des
keysyms et des événements appui/relâchement ; la restitution du texte dépend aussi du
serveur et du clavier distant. Qualifier AZERTY et QWERTY, accents, ponctuation, AltGr,
touches mortes, Tab/Entrée et raccourcis. Unicode étendu et IME restent annoncés selon
les combinaisons réellement testées. Ne pas remplacer silencieusement la simulation
clavier demandée par un collage. Le presse-papiers est une extension séparée et opt-in.
[Contrat KeyEvent](https://github.com/rfbproto/rfbproto/blob/master/rfbproto.rst#744keyevent).

## Sessions, concurrence et récupération

- Identité agent : `{agent_id, task_id}` issue du contexte ; identité humaine : utilisateur
  authentifié et cible autorisée. Un identifiant de session opaque ne vaut jamais droit d'accès.
- États : `opening → ready → closing → closed`, ou `failed` depuis un état actif.
  Expiration, révocation et panne terminent la session ; les états terminaux ne se rouvrent pas.
- TTL d'inactivité, durée maximale, quotas, nettoyage en fin de run et après panne.
  Aucun verrou SQL ni transaction longue pendant l'attente réseau.
- Reprise humaine : suspendre les entrées agent, annuler les commandes encore en file,
  attendre ou interrompre proprement l'action en cours, relâcher les entrées suivies,
  puis transférer le bail. L'agent doit reacquérir le contrôle après restitution et recapturer.
- À la fermeture, perte de focus, annulation et transfert : relâcher touches/boutons connus
  tant que le transport répond. En cas de coupure totale, signaler que leur libération
  distante ne peut être garantie ; vérifier le comportement du serveur au disconnect.
- File bornée et ordonnée ; agréger seulement les déplacements sans bouton lorsque c'est
  sûr. Ne jamais éliminer ou inverser les appuis/relâchements et étapes d'un glisser.
- Après timeout ou perte réseau, aucun rejeu automatique des clics ou frappes. Conserver
  le reçu d'opération dans une fenêtre bornée ; une issue ambiguë exige observation et
  décision explicite. Après redémarrage de l'exécuteur, invalider les sessions précédentes.
- Revérifier les sessions longues et fermer les flux après révocation ou perte du contrôle
  d'autorisation. Journaliser cible opaque, acteur, opération, état et durées, sans texte
  saisi, mot de passe, presse-papiers ni captures brutes.

L'exclusivité garantit les entrées passant par Galaris. Un utilisateur présent sur le PC
ou un client VNC externe peut toujours agir ; rendre cette limite visible et la tester.

## Interface et usage par les agents

La configuration du Tool reste dans les écrans Connexions existants. Une vue VNC dédiée
affiche cible, état, bureau, observation/contrôle, capture, déconnexion et arrêt du contrôle.
La fermeture ou la navigation libère la session humaine et les entrées en cours. Une réponse
tardive d'une ancienne cible ne remplace pas le bureau courant.

Adapter zoom et coordonnées à la taille affichée. Sur petits écrans, proposer déplacement
du pointeur, clic et clavier logiciel sans confondre le geste de navigation avec un clic
distant. Vérifier le focus, les raccourcis interceptés par le navigateur, l'arrêt au clavier
et la sortie du plein écran. Appliquer les conventions Vue/Quasar, Solaire et i18n FR/EN.

Les agents utilisent la boucle capture → action bornée → capture → vérification.
Tester que les images du Tool atteignent réellement le modèle multimodal dans chaque
harness supporté ; pour un modèle sans vision, annoncer la limitation. Ne pas ajouter
d'OCR obligatoire, de contrôle via shell distant ou de second workflow de Tasks.
Les contenus affichés sur le PC restent des données externes, sans autorité pour élargir
les permissions d'un agent.

## Lots et critères de réception

| Lot | Travail | Preuve attendue |
|---|---|---|
| 0 — Prototype | Choisir OS/serveur, transport protégé et client RFB ; fixer les capacités initiales. | Bureau synthétique réel : capture, `Bonjour, été !`, raccourcis, souris et disconnect ; compatibilité de l'image Docker démontrée. |
| 1 — Connexion et sessions | Bridge, Tool optionnel, schéma de paramètres, exécuteur, isolation et limites. | Deux propriétaires isolés ; cible non autorisée refusée ; session expirée/fermée non réutilisable ; panne et redémarrage nettoyés. |
| 2 — Captures MCP | Captures synchronisées avec les actions, observation espacée pendant les attentes, frames complètes, métadonnées, régions, réduction, persistance via File Share. | Image reçue sans console ; saisie complète sans capture par frappe ; attente observée jusqu'au changement ou délai ; aucune boucle fixe ni capture pendant une analyse ; arrêt de l'observation à la fermeture ; transformation de coordonnées correcte ; refus d'ACL de sauvegarde distinct ; résolution changée détectée. |
| 3 — Actions | Clavier, raccourcis, souris, file ordonnée, déduplication et bail par cible. | Texte exact dans l'éditeur, glisser complet, modificateurs relâchés ; doublon sans deuxième effet ; timeout sans rejeu. |
| 4 — Vue humaine | Observation, contrôle, reprise à l'agent et fermeture. | Reprise pendant une saisie sans mélange ; refus RBAC serveur ; navigation/réouverture, petit écran, clavier et réponses tardives. |
| 5 — Parcours agentique | Exposition commune, permissions Sur demande, images, nettoyage. | Un agent réalise le parcours complet ; révocation sur catalogue déjà monté ; reprise de Task sans réutilisation aveugle d'une session. |
| 6 — Qualification | Matrice OS/serveur, mesures, exploitation et documentation. | Capacités supportées documentées par combinaison ; panne réseau, expiration, limites et charge mesurées ; validation globale avant publication. |

Les lots 1 à 5 livrent la première version fonctionnelle. Commencer par une combinaison
OS/serveur prouvée, puis élargir aux PC Windows/Linux/macOS demandés. Installation distante
automatique, transfert de fichiers VNC, audio, enregistrement vidéo, accès hors réseau avec
relais dédié et sélection avancée multi-écrans restent hors première version.

## Vérification et documentation

Réutiliser les garanties existantes sur autorisation, connexions et File Share ; ajouter
la couverture VNC distincte aux bons niveaux : règles pures pour les coordonnées et touches,
intégration DB pour les droits, et serveur VNC réel isolé pour les effets d'entrée.
Un mock réseau seul ne prouve pas une saisie ni un déplacement sur le bureau.
Prévoir quelques parcours dans l'application assemblée avec bureau synthétique,
rupture réseau et concurrent agent/humain. Ne conserver aucune capture de PC réel.

Mesurer connexion et première frame, capture, latence entrée→image, images/seconde,
débit, CPU/RAM et coût par session, sur le même bureau/réseau/résolution.
Définir les budgets de qualité après le lot 0 ; ne pas annoncer une fluidité sans mesure.
Tester saturation et nettoyage après fermeture pour vérifier que les ressources se stabilisent.

À l'implémentation : tests ciblés via Make, `make typecheck`, `make architecture-check`,
`make docs-prepare`, `git diff --check`, puis `make validate` avant publication.
Créer les cibles Make nécessaires à l'exécuteur et au serveur VNC de test.
Tout nouveau modèle SQLAlchemy passe par DbAdmin, sans migration manuscrite.

Consigner les choix structurels acceptés dans une décision ; actualiser le statut ici
et dans l'index des plans. Ajouter les parcours utilisateur FR/EN de configuration,
connexion, observation, contrôle, reprise et dépannage au moment où ils deviennent réels.
Mettre à jour le catalogue des tests, le guide des outils, le skill runtime Galaris,
les licences/crédits et les cartes générées. Les réglages d'infrastructure permanents
doivent apparaître dans `.env.example` et leurs settings.

## Arbitrages à résoudre au lot 0

1. OS et serveur VNC prioritaires, bureau physique ou session virtuelle, exigences d'accès
   aux écrans verrouillés et invites privilégiées.
2. Usage prioritaire agent, humain ou les deux ; nécessité immédiate de plusieurs PC par agent.
3. Chemin réseau entre Galaris et le PC, et authentification/chiffrement réellement supportés.
4. Client RFB retenu et budget acceptable de fluidité, de résolution et de sessions.
5. Politique de conservation des captures explicitement sauvegardées et périmètres humains.

Ces arbitrages précisent la réalisation ; ils ne bloquent pas la conservation de cette
conception et ne déclenchent aucune installation sur un PC distant.
