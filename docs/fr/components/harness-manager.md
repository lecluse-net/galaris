<p align="right"><strong>Français</strong> · <a href="../../en/components/harness-manager.md">English</a></p>

# Gestionnaire de harnais conteneurisés

## Versions des runtimes

Les builds Codex et Claude Agent installent les versions épinglées de leur SDK Python
dans leurs fichiers `requirements.txt` respectifs. Le fichier
`requirements-resolved.txt` dans l'image conserve les versions effectivement installées.
Chaque nouvelle version est qualifiée avant de modifier ces références.
Les mises à jour interviennent lors d'une construction/reconstruction explicite, jamais au
milieu d'une Task. Les conteneurs existants ne changent pas à la seule modification du code.

Au 17 septembre 2026, Hermès cible `v2026.9.14` (0.21.3) et DeepSeek Harness cible
`dsh-v0.1.6-alpha.1`, au commit `0a15e36e7f82b6ed45af6fa9759f29b40dcd965d`.
DeepSeek reste une préversion ; ces deux références restent épinglées.
Codex utilise `openai-codex==0.154.0` et Claude Agent `claude-agent-sdk==0.2.154`.

## Responsabilités

La réponse de supervision fournit `available_actions`, calculé depuis le cycle de vie durable,
l'état observé et les capacités actuelles du provider. La carte Agent utilise cette projection,
sans reconstruire sa propre matrice. `absent` propose « Créer » via `restart`, `stopped` propose
`start`, et `provisioning`/`deprovisioning` ne proposent aucune commande concurrente.
Les gardes serveur sur les Tasks non terminales restent autoritaires lors d'une reconstruction.

Ce service FastAPI générique permet à Galaris de créer, piloter et supprimer des instances de
harnais isolées par répertoire. Il s'exécute sur l'hôte qui possède Docker, en dehors de la stack
Galaris, et limite toutes ses opérations à `BASE_DIR`.

Il ne connaît aucun runtime particulier : ni Hermès, ni Claude Code, ni Codex, ni DSH. Le bridge
backend de chaque runtime construit ses fichiers, son Compose et sa configuration, puis utilise ce
gestionnaire uniquement pour le cycle de vie et le transport de fichiers.

```text
bridge.<runtime> dans Galaris
       │ requêtes HTTP authentifiées
       ▼
harness_manager sur l'hôte
       │ fichiers et actions Make bornées
       ▼
BASE_DIR/<instance> ──► Docker Compose ──► harnais choisi
```

## Contrat

Le service annonce `bridge.harness` et les capacités `compose-lifecycle` et `file-share` sur
`GET /`. Les routes publiques sont volontairement génériques :

| Route | Rôle |
|---|---|
| `GET /instances` | inventorier les instances |
| `POST /instances` | créer un répertoire vide ou depuis un template |
| `DELETE /instances/{id}` | arrêter puis supprimer une instance |
| `GET /instances/{id}/status` | lire l'état Docker Compose |
| `GET /instances/{id}/logs` | lire les dernières lignes de logs |
| `POST /instances/{id}/actions/{action}` | exécuter `start`, `stop`, `restart` ou `update` |
| `/instances/{id}/files/...` | lire, écrire ou supprimer un petit fichier texte chiffré |
| `/instances/{id}/raw/...` | streamer un fichier binaire authentifié |
| `DELETE /instances/{id}/trees/...` | purger une arborescence bornée |

Chaque instance fournit son propre `Makefile`; seules les quatre actions listées ci-dessus sont
acceptées. Le gestionnaire n'exécute aucune CLI propre à un harnais et ne fabrique aucun
répertoire métier. Ces responsabilités appartiennent au bridge consommateur.
`restart` est convergent : lorsque l'instance ne possède encore aucun conteneur Compose, le
gestionnaire exécute son action `start` afin de le créer.

## Installation

Prérequis : Linux, Docker Engine avec le plugin Compose, GNU Make, Python 3 et `curl`.

```bash
cd harness_manager
make install
make start
```

`make install` installe `uv` et l'environnement sous `.local/`, crée `.env` s'il manque, génère
une clé Fernet et initialise par défaut `~/galaris-harnesses` comme `BASE_DIR`. Relire `.env`
avant d'exposer le service sur le réseau.

Pour une exploitation durable :

```bash
make service-install
make service-status
```

Configurez ensuite **Préférences → Harnais → Harnais managés → Configurer le Harness Manager** dans Galaris : URL du
manager, URL API vue par les harnais (facultative) et secret partagé. Ces préférences sont
enregistrées en base et appliquées immédiatement ; le secret est chiffré et masqué à la lecture.
Aucune variable du manager n’est nécessaire dans le `.env` de Galaris.

Pour une nouvelle installation, l’écran génère une clé Fernet, puis prépare le `.env` du
service hôte avec l’IP et le port d’écoute, le filtrage IP, le répertoire des instances et les
limites de fichiers. Enregistrez les préférences avant de copier ou télécharger le fichier.
Placez-le sous le nom `.env` dans `harness_manager` sur la machine cible, créez `BASE_DIR` avec
les droits du compte de service, puis suivez les commandes affichées. Le fichier contient un
secret : protégez-le avec `chmod 600 .env`. L’export ne modifie pas la machine distante.

**Télécharger le ZIP prêt à installer** réunit le code et ce `.env` dans une archive privée,
réservée au droit de modifier les préférences. Le ZIP du code seul ne contient aucun secret.
L'adresse `GALARIS_UPDATE_URL`, modifiable dans les options de préparation, doit être joignable
depuis l'hôte du manager. Le README inclus permet une installation sans le dépôt complet.

Pour un manager existant, réutilisez sa clé et son répertoire. Les anciennes variables
`HARNESS_MANAGER_URL`, `HARNESS_MANAGER_GALARIS_API_URL` et `HARNESS_MANAGER_SECRET` sont
importées une seule fois par DbAdmin si la préférence correspondante n’existe pas. Après cette
synchronisation, elles peuvent être retirées du `.env` de Galaris ; les valeurs en base font foi.

Le secret est provisionné par un canal sûr : aucun checkout Galaris ne lit le `.env` du manager.
Galaris dérive les URL d'API injectées de `HARNESS_MANAGER_GALARIS_API_URL`, avec repli sur `APP_HOST/api`
si cette valeur est vide. Sur un réseau local isolé, utiliser `http://backend:8000/api` évite de
dépendre du DNS public et du reverse proxy. Pour un manager distant, choisir une URL joignable
depuis ses conteneurs. Les réseaux sont définis explicitement dans l’onglet **Harnais managés**
de **Préférences → Harnais**, dans le Compose commun (`harness.default.compose`). La surcharge est commune à Hermès, Codex, Claude
Agent et DeepSeek Harness ; `services.agent` cible leur service principal. Aucun réseau n'est
ajouté depuis l'environnement du backend. La variable historique `HARNESS_MANAGER_DOCKER_NETWORK`
n'attache plus de réseau. Le backend appelle encore chaque runtime par son nom de conteneur
stable : la topologie opérateur doit fournir cette route, sans présumer un hôte commun.
L'ancien paramètre `hermes.default.compose` est transféré vers le paramètre commun par DbAdmin,
sans écraser une valeur commune déjà présente. Les éventuels réglages propres à Hermès doivent
être déplacés vers sa surcharge individuelle avant de recréer d'autres harnais. Après avoir appliqué le
réglage dans l’IHM, lancez depuis le
checkout Galaris :

```bash
make test-harness-management
```

Ce test n'écrit aucun paramètre en base et ne charge aucune option Hermès.

## Diagnostic guidé

Dans **Préférences → Harnais → Harnais managés**, l'état de connexion, les champs de raccordement
et les versions du manager restent visibles. **Préparer l’installation** ouvre les options
du ZIP et du `.env` ; **Mettre à jour le manager** ouvre les instructions et le ZIP du code.
Le bouton **Aide à la connexion** donne accès aux deux guides, **Manager sur cette machine**
et **Manager déporté**. Chaque guide détaille
installation, adresse d'écoute, secret partagé, URL API, réseaux et vérifications finales.
Le Compose standard du backend définit `host.docker.internal:host-gateway` ; cet alias
n'ajoute aucun réseau aux harnais et ne remplace pas la configuration du service manager.

`GET /api/harness-manager/diagnostics` est réservé aux privilèges de configuration.
Le diagnostic distingue secret absent/invalide, DNS, TLS, délai, refus HTTP et service
incompatible. Il ne renvoie jamais le secret, les tokens ou le corps d'erreur distant.
Les URL affichées excluent leurs identifiants, paramètres de requête et fragments.

La vérification est automatique toutes les 30 secondes et également déclenchable à la demande.
Une connexion au manager réussie ne prouve pas l'accès des conteneurs à l'API Galaris :
ce second trajet reste explicitement **non vérifié** jusqu'à un test depuis un harnais.
Le diagnostic n'exécute aucun outil MCP et ne modifie ni configuration ni conteneur.

## Configuration

| Variable | Valeur initiale | Rôle |
|---|---|---|
| `API_HOST` | `127.0.0.1` | adresse d'écoute |
| `API_PORT` | `8485` | port d'écoute |
| `ALLOWED_IP` | vide | client accepté en plus de localhost |
| `HARNESS_MANAGER_SECRET` | générée | clé Fernet partagée avec les clients autorisés |
| `GALARIS_UPDATE_URL` | adresse fournie par Galaris dans le ZIP préparé | point d'entrée des mises à jour du manager |
| `BASE_DIR` | `~/galaris-harnesses` après installation | racine absolue des instances |
| `IGNORE_DIRS` | vide | enfants de `BASE_DIR` protégés de toute opération |
| `MAX_FILE_SIZE_MB` | `1` | limite des écritures texte chiffrées |
| `MAX_RAW_FILE_SIZE_MB` | `512` | plafond des uploads binaires, vérifié pendant le stream |

Les noms d'instance acceptent les minuscules ASCII, chiffres, tirets et underscores. Un nom doit
commencer par une lettre ou un chiffre. Les templates peuvent porter un nom libre, mais restent
obligatoirement sous `BASE_DIR`.

## Sécurité et fichiers

Chaque requête doit fournir `X-Harness-Token`, un nonce Fernet chiffré avec le secret partagé et
valide pendant 60 secondes. Les petits fichiers texte sont chiffrés une seconde fois dans leur
corps. Le canal binaire est streamé sans chiffrement applicatif supplémentaire : il doit donc
rester sur un réseau privé ou passer par TLS.
Une écriture texte peut demander uniquement `0600`, `0644` ou `0755`; le fichier est préparé avec
ce mode puis remplacé atomiquement. Les bridges utilisent notamment `0600` pour les credentials
SSH matérialisés dans un runtime.

Le service applique aussi :

- une politique IP optionnelle ;
- la résolution canonique des chemins et le refus des traversées ;
- l'interdiction des répertoires listés dans `IGNORE_DIRS` ;
- une liste fermée d'actions de cycle de vie ;
- l'exclusion des variables du manager lors des sous-processus Compose ;
- des timeouts explicites pour Docker, Make et les logs.

La suppression arrête l'instance et retire ses volumes Compose déclarés, puis renomme atomiquement
son répertoire vers un répertoire caché avant d'effacer ses données. Le nom canonique est ainsi
immédiatement libéré même si un conteneur a laissé des fichiers non supprimables par l'utilisateur
hôte ; ces reliquats restent alors en quarantaine et sont signalés dans le journal du gestionnaire
au lieu de bloquer la recréation. Les volumes Compose déclarés `external` restent naturellement
hors de ce nettoyage.

Si l'arrêt ou le nettoyage Docker échoue, le répertoire canonique est conservé et son identité
n'est pas réutilisable. Les créations, suppressions et commandes concurrentes sont protégées
par un verrou inter-processus ; une opération incompatible retourne HTTP 409.

Le canal `raw` applique un plafond configurable de 512 Mio par défaut, y compris lorsque la
taille n'est pas annoncée. Les clients doivent aussi streamer et borner les fichiers
avant l'appel lorsque leur contexte l'exige.

## Mise à jour

Le manager possède son propre cycle de déploiement et peut résider sur une autre machine que
Galaris. Sa version fixe provient de `harness_manager/pyproject.toml` (actuellement `1.1.0`)
et est annoncée par `GET /`. Les préférences affichent les versions installée et proposée,
avec une alerte si une mise à jour est disponible, si le manager est plus récent ou si sa
version est inconnue. Une différence de version ne déclare pas la connexion défaillante.

Depuis son répertoire sur l'hôte Docker, avec le compte qui exécute le service :

```bash
cd harness_manager
make update
```

La cible `make update` du dépôt Galaris ne met jamais à jour ni ne redémarre le manager. Chaque
déploiement doit coordonner séparément leurs versions et conserver les coordonnées réseau et le
secret partagé cohérents.

La commande utilise `GALARIS_UPDATE_URL` du `.env`, avec une surcharge ponctuelle possible
par `make update UPDATE_URL=https://galaris.example/api/harness-manager/updates`. Le client
authentifie le téléchargement avec la clé partagée, vérifie le manifeste signé, la version
et l'empreinte SHA-256 avant toute modification. Redirections et versions antérieures sont
refusées. Seuls les fichiers de code distribués peuvent être remplacés ; le `.env`, les
instances et les autres fichiers locaux sont conservés.

Le code précédent est sauvegardé sous `.local/backup-<version>-…`, les dépendances verrouillées
sont installées et un manager déjà actif est redémarré dans son mode initial (systemd
utilisateur ou arrière-plan). Sa version est vérifiée après redémarrage. En cas d'échec,
la commande tente de restaurer le code et l'environnement précédents ; elle indique le chemin
de sauvegarde si la restauration échoue. Un manager arrêté reste arrêté. Les conteneurs des
harnais ne sont pas reconstruits. Éviter les opérations de gestion pendant cette interruption.

Pour une installation ancienne dépourvue de cette cible, arrêter le service, extraire une
première fois le **ZIP du code seul** dans son répertoire existant, exécuter `make install`
puis relancer le service. Ajouter `GALARIS_UPDATE_URL` au `.env` existant en reprenant l'adresse
affichée par Galaris. Conserver sa clé et son `BASE_DIR`.

Le backend embarque les sources distribuées dans son image. Après l'ajout de ce mécanisme,
reconstruire cette image ; en développement, recréer le conteneur backend pour activer le
montage des sources du manager. Les éditions suivantes utilisent ce montage.

Le renommage depuis l'ancien serveur Hermès est volontairement incompatible : le répertoire, la
variable de secret, l'en-tête d'authentification et les routes ont changé. Réinstaller le service
et reconfigurer ses consommateurs est la procédure attendue.

Si le répertoire local déplacé contient déjà un `.env`, `make install` le préserve. Remplacez
explicitement `GALARIS_BRIDGE_HERMES_SECRET` par `HARNESS_MANAGER_SECRET` et vérifiez
`BASE_DIR`, ou archivez cet ancien fichier avant une installation neuve. Ne conservez pas les deux
variables comme mécanisme de compatibilité.

Si l'ancien service systemd utilisateur était installé, arrêtez-le avant d'activer le nouveau :

```bash
systemctl --user disable --now galaris-bridge-hermes.service
cd harness_manager
make service-install
```
