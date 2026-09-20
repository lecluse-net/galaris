<p align="right"><strong>Français</strong> · <a href="../../en/admin/README.md">English</a></p>

# Guide administrateur

Ce guide couvre le déploiement, la configuration et l’exploitation de Galaris. Les
commandes partent de la racine du dépôt.

Pour une première installation, suivez le [guide en trois étapes](installation.md) :
**`make install` → configurer `.env` → `make start`**. Les sections suivantes détaillent
les options d’administration.

## 1. Préparer l’hôte

Prérequis recommandés :

- Linux x86-64 ou ARM64 récent ;
- Docker Engine avec le plugin Compose ;
- Git, GNU Make et OpenSSL ;
- au moins 4 Go de mémoire pour un petit déploiement ;
- un nom DNS et un proxy TLS pour une exposition hors réseau local.

Le modèle fourni démarre le frontend, le backend, SearXNG et la Console SSH locale. Par défaut,
Make ajoute aussi PostgreSQL avec pgvector depuis `compose.postgres.yaml`. Le fichier
`compose.override.yaml.example` publie le frontend avec `8484:8484` et définit le volume
applicatif `galaris_data`, monté dans `/data`. Adaptez l’override pour un proxy externe et
sélectionnez le mode de base de données dans `.env`.

Le frontend écoute sur 8484 en développement (Vite) comme en production (Nginx).
Sur une installation existante, remplacez `8484:8000` par `8484:8484` dans l’override
et adaptez à 8484 la cible d’un proxy qui joint directement le conteneur frontend.
Appliquez ensuite la configuration avec `make update`.

`compose.yaml` monte systématiquement les fichiers `data/search/settings.yml` et
`data/search/limiter.toml` initialisés par `make start`. Ce montage est requis pour
l'API JSON de `search_web`, même avec un ancien override personnalisé. La configuration
initiale conserve la sélection de moteurs de la version SearXNG épinglée, sans forcer Bing ;
les installations existantes conservent leurs choix explicites.
Après une modification de ces fichiers, recréez uniquement le service `search` avec
les fichiers Compose de votre installation, puis vérifiez une recherche JSON réelle.

`make check-search` envoie quatre requêtes publiques synthétiques (français, anglais,
allemand), affiche les premières sources et les dégradations. Le script termine avec
0 si chaque requête a des sources sans dégradation déclarée, 1 s'il manque des sources
ou si une requête échoue, 2 si toutes ont des sources mais certains moteurs sont dégradés.
Make signale les deux derniers cas comme échecs ; lire les lignes JSON pour le détail.
Un verdict 0 ne certifie pas la pertinence : examiner aussi titres et URL. Ce contrôle
volontaire est séparé du healthcheck et des tests sans réseau externe.
Pour comparer une instance isolée :
`make check-search ARGS='--url http://<instance>:8080/search'`.

Les anciennes configurations peuvent forcer Bing. Si le corpus confirme des résultats
hors sujet, retirer cette surcharge de `data/search/settings.yml` ou définir
`disabled: true` pour ce moteur, puis recréer uniquement Search. Une mise à jour ne
réécrit pas cette configuration administrée et ne contourne pas les protections des moteurs.

Chaque tentative de conversation est limitée à 15 minutes, recherches et réponse finale
comprises. Cette borne laisse les modèles à raisonnement long terminer après leurs appels
d'outils ; l'annulation et la perte de lease continuent d'arrêter immédiatement le round.

```bash
git clone https://github.com/lecluse-net/galaris.git galaris
cd galaris
make install
```

`make install` :

1. vérifie Docker, Compose et OpenSSL ;
2. propose PostgreSQL inclus (oui par défaut), puis crée `.env` s’il n’existe pas ;
3. copie l’override Docker d’exemple ;
4. initialise SearXNG ;
5. génère les secrets absents.

Configurez ensuite `.env`, puis lancez `make start` pour construire les images au premier démarrage et lancer
Galaris. L’override fourni convient à l’installation standard.

L’installation ne remplace jamais un `.env` existant. Lors d’une mise à niveau,
un ancien `docker-compose.override.yaml` est renommé automatiquement en
`compose.override.yaml` sans modifier son contenu.
Le choix `POSTGRES_MODE` existant est conservé. Pour une installation automatisée
sans PostgreSQL inclus, utilisez
`make install POSTGRES_MODE=external`.

## 2. Configurer `.env`

Traitez `.env` comme un secret. Ne le commitez pas et ne le joignez pas à un rapport de
bug. `.env.example` présente tous les paramètres de déploiement acceptés dans `.env`,
y compris les options avancées. Les paramètres facultatifs sont commentés avec leur
valeur par défaut ; décommentez uniquement ceux que vous personnalisez. L’installation
renseigne les valeurs générées. Réduire la configuration signifie supprimer ou déplacer
ses paramètres, jamais cacher une option encore acceptée dans le code. Les réglages
fonctionnels déplacés sont documentés et administrés dans **Préférences**.

### Application et réseau

| Variable | Rôle |
|---|---|
| `APP_NAME` | préfixe des conteneurs et nom technique |
| `APP_HOST` | URL publique canonique, avec schéma |
| `APP_ENV` | Libellé libre, `prod` par défaut. Seul `dev` active le développement ; toute autre valeur (`pp`, `test`, `demo`…) applique le comportement production. |
| `POSTGRES_MODE` | `embedded` (défaut) pour le conteneur fourni, `external` pour une base existante |
| `TZ` | fuseau horaire des conteneurs |
| `BACK_ALLOWED_HOSTS` | noms d’hôtes ou IP supplémentaires facultatifs, séparés par des virgules, sans schéma ni port |

Le backend autorise automatiquement `localhost`, `127.0.0.1`, le nom de service Docker
`backend`, `${APP_NAME}-back`, `${APP_NAME}-front` et les hôtes extraits de `APP_HOST` et
de l’éventuelle `HARNESS_MANAGER_GALARIS_API_URL`. Ces accès fonctionnent avec leurs ports
respectifs, directement ou via Nginx. Laissez `BACK_ALLOWED_HOSTS` vide sauf pour déclarer
d’autres alias ou IP, par exemple `api.interne.example,192.0.2.10`. Une valeur explicite `*`
reste acceptée et désactive le filtrage des hôtes, y compris en production ; le développement
l’ajoute automatiquement. Ce réglage valide l’en-tête HTTP `Host` et ne modifie pas CORS,
dont l’origine autorisée reste `APP_HOST`.

`APP_NAME` isole les ressources techniques de plusieurs installations ; il ne renomme pas le
produit, dont l’identité visible reste toujours **Galaris**. La version applicative ne se configure
pas dans `.env` : Make utilise un tag Git exact lorsqu’il existe, sinon la branche courante ou le
commit détaché, puis inscrit cette référence dans l’image backend pour la télémétrie.

En production, placez un reverse proxy HTTPS devant le frontend et donnez à `APP_HOST`
l’URL réellement utilisée par les utilisateurs.

Raccordez le proxy externe uniquement au frontend. Le réseau applicatif Compose relie déjà le
frontend, le backend et SearXNG ; le backend n'a pas besoin de rejoindre le réseau partagé du
proxy. Cette topologie reste compatible avec Caddy, Traefik ou un autre terminateur TLS externe.

Le proxy HTTPS externe doit conserver `Host` et remplacer `X-Forwarded-Proto` par le protocole
réel du client (`https`). Nginx transmet cette indication au backend ; sans elle, une redirection
API peut revenir en HTTP et être bloquée par le navigateur. Le frontend doit être accessible
depuis ce proxy de confiance. Pour un accès HTTP direct, l’absence de cet en-tête conserve HTTP.

Le Nginx fourni accepte jusqu'à 1 Gio uniquement sur
`/api/chat/rooms/<uuid>/attachments`, 52 Mio sur l'import d'un package de skill et 16 Mio sur
le reste de l'API. La limite métier par pièce jointe, administrable avec
`MESSENGER_CONTENT_MAX_MB`, vaut 1 000 Mo décimaux. Un proxy externe doit appliquer une exception
équivalente sur la route des pièces jointes : sa propre limite, si elle est inférieure, reste
prioritaire.

Les appels audio depuis le navigateur traversent directement WebRTC et ne passent pas dans le
proxy HTTP. `compose.turn.yaml` fournit un conteneur coturn léger sur le réseau hôte. Make
l'ajoute par défaut quand `WEBRTC_TURN_MODE=embedded`. Avec `WEBRTC_TURN_HOST=auto`, le backend
dérive son nom public depuis `APP_HOST` et utilise le port dédié 3479 :

```dotenv
#WEBRTC_TURN_MODE=embedded
#WEBRTC_ICE_URLS=
#WEBRTC_TURN_HOST=auto
#WEBRTC_TURN_PORT=3479
#WEBRTC_TURN_MIN_PORT=47000
#WEBRTC_TURN_MAX_PORT=47100
#WEBRTC_TURN_RELAY_IP=auto
#WEBRTC_TURN_TTL_SECONDS=3600
```

Ces valeurs sont commentées dans `.env.example` : décommentez uniquement les réglages à
personnaliser. Le secret partagé et l’adresse de relais calculée restent renseignés
automatiquement dans `.env`.

`bin/update-secrets.sh`, appelé à l'installation, au démarrage du mode intégré et avant
`make update`, génère
`WEBRTC_TURN_SHARED_SECRET`. Ce même secret est injecté dans coturn et dans le backend, qui dérive
des identifiants TURN REST temporaires pour chaque utilisateur authentifié. Le secret partagé ne
quitte jamais le serveur. Aucune variable WebRTC n'est donc requise pour le mode intégré : le
navigateur utilise le nom dérivé d'`APP_HOST` ainsi que l'IPv4 LAN détectée comme chemin de secours,
et le backend rejoint automatiquement coturn par `host.docker.internal`, y compris lorsque le nom
applicatif est résolu différemment par le navigateur, un DNS interne ou l'hôte Galaris.
Au lancement, le compose détecte l'adresse publique et force les sockets relay sur l'adresse IPv4
LAN principale. Il passe cette paire à coturn sous la forme `--external-ip=<public>/<LAN>` afin que
les candidats annoncent l'adresse publique sans allouer les ports média sur un bridge Docker. Sur
un hôte dont la première adresse n'est pas celle qui reçoit la plage TURN du routeur,
`WEBRTC_TURN_RELAY_IP` doit contenir explicitement cette IPv4 LAN.
`bin/update-secrets.sh` résout autrement `auto` depuis la route IPv4 par défaut et conserve le
résultat machine dans `WEBRTC_TURN_RELAY_IP_RESOLVED` ; aucune adresse LAN n'est codée dans les
images ou le dépôt. Le backend publie l'adresse publique et cet alias LAN dans sa réponse ICE. Il
fournit aussi le locator TURN numérique LAN au navigateur, qui peut obtenir son propre candidat
relay sans dépendre de la résolution du nom applicatif ni du hairpin NAT. Un smartphone présent sur
le même réseau peut ainsi joindre directement le relay lorsque le routeur accepte le hairpin NAT
HTTP mais pas le hairpin NAT UDP.

Pour réutiliser un TURN existant, l'administrateur change le mode et remplace la configuration
dérivée. Make n'ajoute alors pas `compose.turn.yaml` :

```dotenv
WEBRTC_TURN_MODE=external
WEBRTC_ICE_URLS=stun:turn.example.org:3478,turn:turn.example.org:3478?transport=udp,turn:turn.example.org:3478?transport=tcp
WEBRTC_TURN_SHARED_SECRET=<même valeur que static-auth-secret dans coturn>
```

Le coturn existant doit utiliser `use-auth-secret`. Aucun conteneur TURN Galaris n'est alors requis.
`WEBRTC_TURN_MODE=disabled` exclut également le compose dédié et masque le bouton d'appel en
production, même si d'anciennes URLs subsistent dans `.env`.

Le pare-feu et, le cas échéant, le routeur en amont doivent publier le port
`WEBRTC_TURN_PORT` en UDP **et** TCP ainsi que la plage
`WEBRTC_TURN_MIN_PORT`–`WEBRTC_TURN_MAX_PORT` en UDP vers l'hôte Galaris. Les valeurs par défaut
3479 et 47000–47100 évitent les ports TURN usuels afin de pouvoir cohabiter avec un autre coturn sur
le même hôte ; elles peuvent être changées ensemble dans `.env`. Cette ouverture ne concerne pas
Galaris lorsqu'il réutilise uniquement un TURN externe.

Dans un environnement `prod`, `preprod` ou `demo`, Galaris masque le bouton d'appel tant qu'aucun
relais `turn:`/`turns:` authentifié n'est configuré ; STUN seul n'est pas une garantie suffisante
derrière Docker ou sur un réseau mobile. Au démarrage d'un appel, le backend vérifie en plus que
`aiortc` a réellement obtenu un candidat `relay` et refuse l'appel si le relais est indisponible,
au lieu d'enregistrer un appel muet avec une adresse Docker privée.

### PWA et sessions persistantes

La PWA est générée par le frontend et ne demande aucun service Docker supplémentaire. Pour
qu’un téléphone puisse l’installer, l’URL publique doit être servie en HTTPS et le frontend
ainsi que `/api` doivent rester sur la même origine. Le reverse proxy doit préserver le header
`Host` : les routes `/api/auth/refresh` et `/api/auth/logout` refusent une origine différente.

Les jetons d’accès durent 30 minutes, les sessions de renouvellement expirent après 30 jours
d’inactivité et deux renouvellements concurrents disposent d’une tolérance fixe de 10 secondes.
Le cookie de renouvellement porte toujours le nom `galaris_refresh`.

`APP_HOST` doit commencer par `https://` en production afin que le cookie soit marqué
`Secure`. Il est également `HttpOnly`, `SameSite=Lax` et limité au chemin `/api/auth`. Ne
placez jamais le frontend et l’API sur des domaines publics différents sans revoir ce contrat.

À la connexion, le backend crée une famille de session dans `user_refresh_sessions` et ne
stocke que le SHA-256 du jeton opaque. Chaque renouvellement verrouille la ligne, remplace le
jeton et prolonge l’expiration. Une réutilisation après la courte fenêtre de concurrence est
traitée comme un rejeu et révoque toute la famille. La déconnexion révoque la session courante ;
un changement de mot de passe ou la désactivation du compte révoque toutes les sessions
persistantes de l’utilisateur.

Lors d’une mise à jour, `make update` crée automatiquement la table déclarative avec Atlas avant
de rendre le backend disponible. Le `nginx.conf` fourni empêche la mise en cache durable de `sw.js`
et du manifeste ; conservez ces règles dans tout proxy qui les remplace. Le mode d’emploi côté
utilisateur se trouve dans le [guide PWA](../user/pwa.md).

### Durcissement des comptes

Chaque utilisateur peut activer un second facteur TOTP depuis son profil. Le secret est chiffré
avec `ENCRYPTION_MASTER_KEY`, les dix codes de secours sont stockés sous forme de condensats et ne
sont affichés qu’au moment de leur génération. Un code TOTP déjà accepté dans la même fenêtre ne
peut pas être rejoué.

Les échecs de connexion déclenchent une politique fixe de verrouillage progressif par compte :
après 5 échecs, le délai commence à 30 secondes puis augmente exponentiellement jusqu’à 1 heure.
Une authentification par mot de passe et MFA réussie remet le compteur à zéro. La configuration du
déploiement ne permet pas d’affaiblir cette protection.

### Secrets obligatoires

| Variable | Utilisation |
|---|---|
| `ENCRYPTION_MASTER_KEY` | chiffrement des secrets de connexions |
| `POSTGRES_PASSWORD` | compte PostgreSQL |
| `WEBRTC_TURN_SHARED_SECRET` | identifiants temporaires du relais audio coturn intégré ou externe |

`bin/update-secrets.sh` génère uniquement les valeurs absentes. Changer
`ENCRYPTION_MASTER_KEY` sans procédure de rotation rend les secrets déjà stockés
illisibles. **Ne jamais modifier, supprimer ni régénérer cette clé après l’installation :
sans la clé d’origine, les données chiffrées sont irrécupérables. Sauvegardez-la avec la base.**
Changer `AUTH_SECRET_KEY` invalide les jetons d’accès en cours, mais ne remplace
pas la révocation des sessions persistantes enregistrées en base.

`AUTH_SECRET_KEY` est désormais un paramètre interne chiffré : il est créé une seule fois
par DbAdmin, chargé avant l’ouverture de l’API et absent des Préférences et de leur API.
La première mise à jour génère une nouvelle clé si le paramètre interne est absent,
sans reprise du `.env` : les anciens jetons d’accès et codes de secours MFA deviennent
invalides. Les mises à jour suivantes conservent cette clé. Une valeur persistée invalide bloque
le démarrage au lieu de provoquer une rotation silencieuse.

Le webhook générique `/api/webhook/*` est désactivé ; `AUTH_WEBHOOK_TOKEN` est retiré.
Les callbacks des bridges de messagerie et les tokens utilisateur restent indépendants.
Après vérification des secrets persistés, `make update` retire du `.env` les anciennes
variables `AUTH_SECRET_KEY`, `BROWSER_EXECUTOR_TOKEN` et `AUTH_WEBHOOK_TOKEN`.
`ENCRYPTION_MASTER_KEY` reste dans `.env`, avec sa valeur et son mécanisme de lecture inchangés.

Les clés Web Push sont également générées une seule fois en paramètres internes chiffrés,
sans reprise des anciennes variables. La mise à jour retire les quatre `WEB_PUSH_*`
du `.env` après vérification des clés internes. Lors du premier passage, recharger l’application
sur chaque appareil puis désactiver et réactiver les notifications avec la cloche du Chat.
Les abonnements restent ensuite valides d’une mise à jour à l’autre. Le contact et le délai
d’envoi se règlent dans **Préférences → Messagerie → Chat**. Une nouvelle installation
génère sa paire automatiquement ; renseigner un contact `mailto:` ou HTTPS adapté à l’instance.

Les secrets de messagerie, n8n et Hermès sont saisis dans les Préférences, chiffrés avec
`ENCRYPTION_MASTER_KEY` et ne sont jamais relus en clair par l’API. Le secret privé de
SearXNG est généré directement dans `data/search/settings.yml`.

### Observabilité centralisée

`LOG_LEVEL` reste dans le `.env` pour s’appliquer dès le démarrage, avant la base de données.
`LOG_LEVEL=DEBUG` ou `TRACE` active également le middleware de diagnostic WebSocket avec
assainissement des données sensibles ; il n’existe plus de drapeau de debug applicatif séparé.

`LOGFIRE_TOKEN` est facultatif et se configure dans **Préférences → Système**. Il est stocké
chiffré et n’est jamais retourné en clair par l’API. Son ajout, remplacement ou effacement
s’applique sans redémarrage. Les logs locaux démarrent avant la base ; l’export distant
ne commence qu’après le chargement des paramètres. Une ancienne valeur du `.env` est importée
une seule fois si le paramètre est absent, puis la ligne est retirée par `make update`.
Lorsqu’il est renseigné, le backend exporte vers le projet Logfire
correspondant les traces FastAPI, spans SQLAlchemy et HTTPX, événements Pydantic AI, métriques
système et journaux Loguru. Les headers, corps HTTP, prompts et contenus binaires ne sont pas
collectés par cette instrumentation. Sans jeton, aucun export vers Logfire n’est activé.
Les tests automatisés isolent explicitement leur télémétrie ; le libellé `APP_ENV=test`
ne modifie pas à lui seul le fonctionnement applicatif.

### Base de données

`POSTGRES_MODE=embedded`, utilisé par défaut, ajoute `compose.postgres.yaml` et attend que son service
soit sain avant le démarrage du backend :

```dotenv
POSTGRES_MODE=embedded
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=galaris
POSTGRES_USER=galaris
POSTGRES_PASSWORD=<secret>
```

Pour utiliser une base existante, désactivez uniquement le conteneur fourni et indiquez une adresse
joignable depuis le backend. `compose.postgres.yaml` n’est alors pas chargé :

```dotenv
POSTGRES_MODE=external
POSTGRES_HOST=postgres.example.net
```

Configurez aussi le port, la base, l’utilisateur et son mot de passe ; pgvector doit être disponible.
Le service et le volume PostgreSQL sont déclarés dans `compose.postgres.yaml`, jamais dans
l’override d’installation. Lors du passage au mode externe, les commandes de démarrage et
d’arrêt retirent uniquement l’ancien conteneur PostgreSQL, sans supprimer son volume.

Le backend exige toujours PostgreSQL et `make update` continue d’y appliquer le schéma déclaratif
et les datasets avec DbAdmin. Le mode externe ne désactive donc pas la synchronisation.

`DB_POOL_SIZE + DB_MAX_OVERFLOW` doit rester supérieur au nombre maximal de tâches
simultanées, avec une marge pour l’API, les WebSockets et les opérations d’administration.
Le contrôle `DB_POOL_PRE_PING=true` est particulièrement important avec une base distante.

Ces réglages avancés sont facultatifs et figurent, commentés, dans `.env.example`.
Sans ligne correspondante dans le `.env`, le backend applique les valeurs suivantes :

| Réglage | Valeur par défaut |
|---|---|
| `DB_POOL_SIZE` | 20 connexions |
| `DB_MAX_OVERFLOW` | 20 connexions supplémentaires |
| `DB_POOL_TIMEOUT` | 30 secondes |
| `DB_POOL_RECYCLE` | 1800 secondes |
| `DB_POOL_PRE_PING` | `true` |
| `DB_STATEMENT_TIMEOUT_MS` | 120000 ms |
| `DB_LOCK_TIMEOUT_MS` | 10000 ms |
| `DBADMIN_COMMAND_TIMEOUT_SECONDS` | 600 secondes |

Les lignes commentées ou égales à ces valeurs peuvent être retirées sans changer le
fonctionnement. Les surcharges restent disponibles en cas de besoin, au démarrage :
la connexion et les opérations DbAdmin doivent fonctionner avant de lire les préférences.
Les délais SQL et de verrou bornent chaque opération, pas la durée totale d’un agent ;
Atlas et la matérialisation de sa cible disposent du délai DbAdmin séparé.

### Langue et recherche

- **Préférences → Langue** configure la langue de repli des tâches sans utilisateur ainsi
  que le lieu donné aux agents pour contextualiser date et heure. Une nouvelle installation
  utilise respectivement l’anglais et `Paris, France`.
- **Préférences → Recherche** configure notamment la langue utilisée par SearXNG.
- L’usage **Vectoriel** du profil courant active le rappel sémantique de Memory. Sa dimension est enregistrée
  avec chaque projection et n'est pas un réglage Memory.

Tous les prompts présents dans Préférences utilisent le même éditeur Markdown. Le badge indique
s’ils suivent le défaut Galaris ou s’ils sont personnalisés. **Voir les différences** compare la
version éditée au défaut courant et **Revenir au défaut** réactive le suivi automatique. Après une
mise à jour qui change un défaut, une personnalisation n’est jamais écrasée : l’éditeur demande de
garder la version de l’instance ou d’adopter la nouvelle version fournie.

Un changement de modèle vectoriel déclenche une reconstruction asynchrone. Tant qu'elle n'est pas
terminée, le rappel approfondi se replie explicitement sur la recherche lexicale.
Les chunks textuels de chaque mémoire sont transmis au provider choisi : ne sélectionnez un
provider externe que si sa politique de confidentialité l'autorise. Laisser
Un usage Vectoriel vide conserve le fonctionnement lexical sans aucun envoi d'embedding.

### Mémoire des agents

**Préférences → Mémoire** contrôle séparément :

- le nombre de messages et de caractères de la session récente reconstruite depuis Messenger ;
- l'activation et le budget du brief durable injecté avant une exécution ;
- la cadence et les tentatives du worker d'acquisition.

**Préférences → Dream** contrôle le scanner opportuniste, ses leases, ses reprises et le mode
d'apprentissage.
Le paramètre `ai.memory-extraction-system-prompt` règle le prompt complet de l’extracteur de
souvenirs. Il s’applique aux Tasks, rounds texte et tours audio transcrits possédant déjà un Topic ;
le Lab en copie la valeur à la création d’un dataset, puis laisse cette copie évoluer indépendamment.
Le réglage **Création des dossiers thématiques** propose trois politiques : **Interdire** réutilise
uniquement les dossiers existants, **Demander une autorisation** (valeur par défaut) envoie à
l'utilisateur d'origine un choix persistant entre création, réemploi et absence de classement, et
**Créer automatiquement** crée immédiatement seulement après l'échec des contrôles renforcés de
réemploi. Une proposition sans conversation humaine exploitable n'est jamais créée implicitement.
L’usage **Dream**, sélectionné dans **Modèles IA → Usages**, doit référencer un petit modèle texte.
Sans modèle sélectionné, aucun sujet nécessitant une inférence n'est réclamé. Dream exécute un
mécanisme à la fois, sans driver ni outil, cède la priorité aux Tasks et s'interrompt dès qu'une
conversation Voice commence.

La page **Dream** montre en temps réel son état courant, le mécanisme et le sujet réclamés, la phase,
les souvenirs créés, les reprises, les erreurs et le coût.
Chaque témoin peut être ouvert pour consulter la Task source et la sortie structurée préparée. La
page est en lecture seule, exige `TASK_ACCESS` et ne rafraîchit ses données que lorsqu'elle est
ouverte.

La page **Mémoire** permet de choisir l'identité d'un agent puis de rechercher ses souvenirs avec
ses droits réels. Son onglet **Recherche** utilise toujours le rappel approfondi hybride, sans
sélecteur local. Les poids, le vivier de candidats et la diversité se règlent globalement dans la
section **Mémoire** des préférences. Le moteur conserve un repli lexical automatique si la voie
sémantique est indisponible. Le rappel est borné à
20 résultats et n'est jamais lancé à la frappe. La page expose aussi le contenu, les révisions, la
provenance, les relations et les accès
directs et, sans ambiguïté, l'agent propriétaire. Il n'existe aucun espace mémoire : un accès
inter-agent est accordé directement sur le souvenir concerné, tandis qu'une acquisition automatique
reste privée. Les acquisitions admissibles sont appliquées immédiatement et les refus sont
automatiques : cette page sert à consulter, corriger, partager explicitement, archiver ou oublier,
jamais à valider une entrée. Les trois privilèges sont `MEMORY_ACCESS`, `MEMORY_EDIT` et
`MEMORY_ADMIN`.

Les documents de travail Markdown utilisent le même stockage et les mêmes ACL, mais ne sont ni
dédupliqués avec les souvenirs ordinaires, ni oubliés pour simple inactivité. Leur partage direct
`read` ou `edit` est administré par le propriétaire et chaque révision conserve l’agent ainsi que
la Task auteure lorsqu’elle existe.

La page **Dossiers thématiques** administre les sujets globaux utilisés pour relier mémoire, Tasks
et conversations indépendamment de leur canal. Dream classe d’abord les Tasks et tours Voice, puis
projette les liens mémoire. Une correction manuelle change l’affectation sans modifier les sources ;
fusion et scission automatiques ne font pas partie du contrat actuel.

Les fiches Agent, Goals et comptes rendus de cycles apparaissent aussi comme documents générés.
Leur bannière l'indique clairement et leur propriétaire reste visible. Ils sont privés, en lecture
seule, non partageables et non supprimables dans cette page, y compris pour un administrateur :
modifiez ou supprimez la fiche Agent ou le Goal source pour les faire évoluer. Les mots-clés et le
contenu sont recalculés automatiquement; aucune validation humaine n'est demandée.

La liste utilise la pagination standard de l'application : 50 lignes par défaut, avec un choix de
10, 20, 50, 100 ou 500 lignes. Le contenu Markdown est rendu dans la fenêtre de consultation et les
souvenirs Markdown ordinaires se modifient avec l'éditeur visuel.
Pour borner durablement le volume, seuls les 100 derniers cycles de chaque Goal possèdent une
projection mémoire ; les cycles métier plus anciens restent inchangés dans leur table canonique.

`DREAM_SKILL_LEARNING_MODE` vaut `off`, `observe` ou `learn` et reste `off` par défaut. `observe`
conserve les preuves et propositions dans les reçus Dream sans modifier les skills ; `learn`
crée, renforce, révise ou affaiblit des candidates propres à l'agent. Dream parcourt aussi toutes
les Tasks terminales historiques, de manière progressive et idempotente, une opération par
passage. Une candidate devient une skill injectable en plus des skills affectées lorsque le nombre
de Tasks distinctes confirmant la même procédure atteint `DREAM_SKILL_MIN_EVIDENCE` (3 par défaut)
et que sa note atteint `DREAM_SKILL_ACTIVATION_SCORE`, dans la limite de
`DREAM_SKILL_MAX_ACTIVE`. Ces seuils sont paramétrables dans **Préférences → Dream**. La page
**Skills → Auto-apprises**, masquée lorsque le mode vaut `off`, expose score, preuves et état
d'injection, et permet de suspendre immédiatement une procédure. Dream ne crée plus de nœud Memory
`experience` et les anciens nœuds ne sont plus injectés.

Le contenu du provider natif réside dans le répertoire fixe `/data/memory`, avec une
taille maximale par ressource définie par `MEMORY_RESOURCE_MAX_BYTES`. En production, ce chemin est
dans le volume Compose `galaris_data`; en développement, il correspond à `./data/memory`. Une
sauvegarde cohérente doit capturer PostgreSQL et ce volume au même point logique : les révisions en
base contiennent des pointeurs opaques vers les ressources du volume.

Archiver conserve le contenu mais le retire du rappel ordinaire. **Oublier définitivement** efface
le contenu courant, toutes ses révisions, sources, ACL, liens, chunks vectoriels et traces
d'usage; seul un tombstone sans contenu demeure. Cette action est irréversible. L’installation de
Memory et les mises à jour de ses modèles sont appliquées automatiquement par `make update` avant
que le backend soit déclaré sain.

Pour réparer uniquement les sources dont le lien mémoire manque :

```bash
make rebuild-source-memory
```

Cette réconciliation oublie aussi les documents générés dont la fiche Agent, le Goal ou le Goal
parent du cycle n'existe plus, par exemple après un événement de suppression momentanément manqué.

Pour vérifier et rafraîchir toutes les projections sans changer leurs UUID :

```bash
make rebuild-source-memory ARGS='--all'
```

Lors d'un changement de fournisseur, enregistrez d'abord le nouveau provider puis recréez les
projections depuis les sources canoniques :

```bash
make rebuild-source-memory ARGS='--recreate --provider CODE_DU_PROVIDER'
```

Cette dernière commande efface les anciennes ressources projetées, crée de nouveaux items et met à
jour les UUID dans les tables Agent, Goal et GoalCycle. Elle n'altère pas les données métier.

Pour réparer l'index sémantique courant sans recalculer les chunks déjà à jour :

```bash
make rebuild-memory-index
```

Pour forcer un recalcul complet après un changement contrôlé de provider ou pour un diagnostic :

```bash
make rebuild-memory-index ARGS='--all'
```

Après une suppression accidentelle des arêtes du graphe, reconstruisez les liens déterministes
depuis leurs sources canoniques avec :

```bash
make rebuild-memory-links
```

La commande ne crée aucun lien tant qu'une Task ou session Voice portant une provenance mémoire
n'a pas encore de dossier thématique. Elle remet en attente les classifications épuisées : laissez
alors Dream terminer les classements, puis relancez la commande. Elle reconstruit les liens
`cycle_of`, `result_of` et `topic_contains`; les liens manuels ou issus d'une décision de
consolidation ne sont pas récupérables après une suppression SQL intégrale.

Les commandes `rebuild-memory-index` ne calculent rien dans le processus CLI : elles inscrivent
des jobs durables que le worker traite en arrière-plan. Sans modèle Vectoriel dans le profil courant, elles
n'effectuent aucune mutation. `rebuild-memory-links` réconcilie en revanche les arêtes
immédiatement et affiche le nombre de liens recréés.

## 3. Démarrer et initialiser

```bash
make update
make logs-back
```

L’entrypoint du backend est idempotent. Avant de lancer l’API, il :

- compare les modèles SQLAlchemy au schéma PostgreSQL avec Atlas ;
- applique l’évolution déclarative ;
- synchronise les privilèges, paramètres et outils système ;
- synchronise les données de référence et les projections réparables.

Ouvrez ensuite `APP_HOST`. Le premier utilisateur enregistré reçoit automatiquement le rôle
`admin` si ce rôle existe. Créez ce compte dans une fenêtre contrôlée, puis vérifiez les
affectations dans l’administration.

## 4. Configurer les modèles de langage

Les fournisseurs et modèles sont administrés dans l’interface LLM. Un modèle contient le
nom attendu par le fournisseur, ses paramètres de coût et sa capacité éventuelle
d’embedding.

Les affectations vivent exclusivement dans des profils de modèles. Le paramètre global
`llm_profile_id` ne contient aucun modèle : il pointe seulement vers le profil courant. Un agent
peut choisir un profil personnel ou conserver « Profil courant » ; ce second choix est persisté
par un `profile_id` nul et suit immédiatement tout changement de profil courant.

| Usage du profil | Fonction |
|---|---|
| Exécuteur | exécution `standard` du harnais interne |
| Exécuteur high | exécution `high`, avec seul repli autorisé vers l’exécuteur standard du même profil |
| Conversation | réponses rapides du control plane des conversations texte |
| Dispatcher | choix `EXEC`/`PLAN` et effort des Tasks ; il n’exécute pas les conversations |
| Planner | création de plans et synthèse finale |
| Briefing | mécanisme conservé pour le Lab et une éventuelle réactivation ; désactivé en production |
| Goal | jugement et suivi des cycles de Goals |
| Lab | analyse de Tasks, proposition de références, jugement et analyse des benchmarks du Lab IA |
| Dream | classement, extraction et apprentissage Dream |
| Vectoriel | embeddings de mémoire |
| Vision | analyse d’images |
| Document | analyse de documents |
| Audio | compréhension audio multimodale lorsque le provider la supporte |
| Vidéo | compréhension vidéo multimodale lorsque le provider la supporte |
| Image | génération et retouche d’images |
| Transcription | modèle STT dédié aux messages vocaux et au tool `audio_transcribe` |

Un usage vide reste vide dans le profil choisi. Un profil personnel n’emprunte jamais une valeur
au profil courant. L’absence d’exécuteur ou de modèle de conversation empêche le chemin concerné ;
elle n’est jamais masquée par un modèle choisi implicitement.

### Modèle du Lab IA

Sélectionnez l’usage **Lab** dans **Fournisseurs & modèles → Usages**. Le modèle doit posséder la
capacité `chat` et produire de façon fiable les sorties structurées demandées. Il remplit quatre
rôles volontairement centralisés :

- analyser les preuves d’une Task ;
- proposer une sortie de référence éditable ;
- juger chaque dimension sémantique d’un benchmark ;
- produire le rapport Markdown d’un run terminal.

Choisissez un modèle suffisamment puissant pour juger les modèles candidats. Son coût s’ajoute à
chaque cas : un benchmark générique appelle normalement une fois le candidat et une fois le juge,
puis une analyse facultative effectue un appel supplémentaire pour le run. Les contenus des cas
sont transmis au fournisseur du modèle du Lab ; appliquez la même politique de confidentialité que
pour les Tasks métier.

Lancer le même modèle comme candidat et juge est autorisé mais augmente le risque d’auto-préférence.
Avant d’utiliser les scores comme garde de livraison, calibrez le juge sur des sorties notées par
des humains. Le [guide opérateur](../user/lab-ai.md) décrit la procédure et la
[documentation d’architecture](../architecture/ai-lab-evaluation.md) détaille les biais et
les formules.

Si le modèle du Lab est absent, les boutons de proposition, benchmark et analyse sont désactivés ou
retournent une erreur explicite. Une panne du juge ne doit pas être interprétée comme un mauvais
résultat candidat : les mécanismes sémantiques affichent alors un score absent et un run `partial`.

## 5. Drivers agentiques

Le harnais interne est toujours disponible. Un driver externe n’est proposé sur la fiche
d’un agent que lorsqu’il est activé et correctement configuré dans **Préférences → Harnais**.

Cette page comporte trois onglets, avec la même présentation que la page Agents et sans sous-menu par harnais :

- **Harnais managés** : informations et configuration du Harness Manager visibles directement,
  interrupteurs d’activation et
  configuration Hermès affichée dès son activation. La désactivation demande confirmation
  et réaffecte les agents concernés au harnais interne. Le Compose commun est replié dans
  les réglages avancés de cet onglet.
- **Harnais externes** : liste des services indépendants, avec ajout et modification en modale.
- **Paramètres avancés** : réglages de fiabilité et capacités des harnais, accessibles aux
  administrateurs autorisés à modifier les préférences.

### Harnais interne

Code : `internal`.

Dans **Préférences → Harnais → Réglages avancés**, la taille maximale des fichiers binaires
envoyés au modèle vaut 20 Mio par défaut (20 971 520 octets). La modification s’applique
aux prochains fichiers sans redémarrage ; les fichiers exclus restent accessibles par
leur référence. Ce réglage concerne uniquement le harnais Pydantic AI interne.

- exécution par Pydantic AI dans le backend ;
- aucune façade de stockage local implicite ; les fichiers locaux passent exclusivement par une
  console active ;
- planner activé ;
- briefing conservé mais désactivé pendant l’évaluation des objectifs autonomes ;
- modèles standard/high résolus dans la configuration Galaris.

### Driver Hermès

Code : `hermes`.

Hermès reste un runtime autonome. Galaris lui transmet une requête normalisée et supervise
le résultat, mais ne lui impose ni planner ni briefing afin d’éviter deux systèmes de
raisonnement concurrents.

Le niveau d’effort sélectionne le modèle, pas un second ordonnanceur :

| Effort | Exécution |
|---|---|
| `standard` | run direct dans la session Hermès habituelle (`/v1/runs`) |
| `high` | run direct `/v1/runs` avec le modèle High |

Le Kanban est désactivé par une constante interne au code du driver Hermès. Ce choix n’est pas
configurable dans `.env`, les paramètres ou l’administration. Le code et les routes Kanban restent
disponibles uniquement pour reprendre une carte créée avant la désactivation et ouvrir la voie à
une future réactivation. Le briefing n’est actuellement activé par aucun harnais.

Le manager se configure dans **Préférences → Harnais → Harnais managés → Configurer le Harness Manager** : URL, secret
partagé et URL API vue par les harnais. Ces réglages s’appliquent sans redémarrer Galaris.
Le formulaire génère aussi le `.env` du service manager, à copier ou télécharger puis installer
sur son hôte. Les guides local/distant et le diagnostic aident à vérifier les accès.

Aucune variable du manager n’est nécessaire dans le `.env` de Galaris. Les anciennes valeurs
sont importées une seule fois lors de la synchronisation DbAdmin. Sans URL API spécifique,
`APP_HOST/api` reste utilisé : cette adresse doit être joignable depuis les conteneurs.
Les réseaux se règlent dans le Compose commun. Le test `make test-harness-management`
contrôle le service générique ; il ne prouve pas le fonctionnement des runtimes distants ou MCP.
Voir le [guide d’installation](../components/harness-manager.md).

Le provider **OpenAI Codex** réutilise automatiquement le fournisseur **OpenAI — ChatGPT** configuré
et connecté dans Galaris, et accepte un modèle optionnel (`gpt-5.4` par défaut). Galaris reste propriétaire du
refresh token OAuth : le runtime demande un access token court via une route interne protégée par
son token système, puis l'injecte dans l'App Server Codex sans le persister dans son `.env` ni dans
son volume. Le même courtier répond aux demandes de renouvellement émises pendant un long tour.
Aucune clé supplémentaire n'est donc demandée lors de l’ajout ou de la mise à jour. Le handoff
`chatgptAuthTokens` restant une surface instable de l'App Server, le SDK et le binaire Codex sont
épinglés ensemble et leur compatibilité est vérifiée à la construction.
Le conteneur est non-root, limité en ressources, relié au réseau du Harness Manager et reçoit le
MCP, les skills et le répertoire de travail persistant propre au runtime de cet agent. Ce
répertoire n’est pas un provider `file_share` et n’est jamais annoncé comme stockage de fichiers.

La section **Configuration Hermès** de l’onglet **Harnais managés** regroupe les fichiers par
défaut. Elle apparaît lorsque le harnais est activé, même si aucun agent ne l’utilise encore.
Ses réglages sont conservés lors d’une désactivation. Pour configurer un agent, ouvrez sa
fiche puis son onglet **Hermès** ; un bandeau rappelle ce chemin dans les préférences.

Chaque agent Hermès possède une instance, un volume et un conteneur `<agent.code>-agent` propres.
Le harness manager générique est seulement le plan de contrôle de ces instances et n’exécute
aucune CLI Hermès. Le transport Kanban historique est explicitement refusé et n’est plus utilisé
pour une nouvelle Task `high`.

Les fichiers de conversation conservent leur URI provider et ne passent pas par l’API de fichiers
Hermès limitée à 100 Mio. Les consommateurs compatibles les lisent via `file_share` et les
matérialisations techniques restent temporaires. Les surcharges Compose restent bornées à
l’instance de l’agent et sa mise à jour reste indépendante. Le contrat de déploiement est détaillé
dans [`docs/fr/components/hermes.md`](../components/hermes.md). Le serveur hôte
générique est documenté dans
[`docs/fr/components/harness-manager.md`](../components/harness-manager.md).

Une connexion **Console** active en mode externe devient aussi la cible du terminal SSH natif
d'Hermès lors de la synchronisation de l'agent. Galaris projette la clé privée et le `known_hosts`
dans le volume propre à l’instance avec des permissions `0600`, force la vérification stricte de la
clé d'hôte et ne place jamais la clé dans `config.yaml`. Le mode Console embarqué conserve le
terminal Hermès configuré par l'opérateur. Désactiver la connexion externe retire les fichiers
projetés et restaure cette configuration antérieure.

Utilisez `make test-hermes-management` pour contrôler ensuite l'adaptateur Hermès sélectionné. Les
écrans d’administration Hermès peuvent appeler directement son bridge ; toutes les
exécutions métier passent toutefois par `app.agent`.

Les champs historiques Hermès de la table des agents sont conservés pendant la migration.
La table de configuration propre au driver est la source d’exécution ; le backfill est
idempotent et ne journalise jamais les secrets.

Chaque agent Hermès possède un réglage **Utiliser un LLM fourni par Galaris** :

| Mode | Configuration effective | Visibilité dans Galaris |
|---|---|---|
| activé, valeur par défaut | Galaris injecte son endpoint OpenAI, le modèle sélectionné et un jeton limité dans `config.yaml` et `data/.env` | appels LLM, outils observés par le proxy, coûts et erreurs sont tracés |
| désactivé | les sections LLM de `config.yaml`, les clés de `data/.env` et les variables Docker Compose restent gérées par Hermès | les runs restent visibles, mais pas les appels LLM ni leur coût détaillé |

En mode LLM Galaris, le contexte du run transporte les identifiants de Task, de run et de modèle :
les appels restent donc rattachés à la bonne Task même si une autre exécution du même agent existe.
Lorsque le LLM est configuré directement dans Hermès, cette trace détaillée demeure indisponible.

Lors du passage au LLM configuré directement dans Hermès, la synchronisation retire uniquement
une ancienne injection LLM qu’elle reconnaît comme générée par Galaris. Les valeurs du YAML global
et du YAML propre à l’agent sont ensuite réappliquées. Renseignez donc le fournisseur, le modèle et
ses secrets dans la configuration Hermès avant de redémarrer l’instance. Les outils MCP Galaris
restent injectés avec les deux configurations LLM.

## 6. Ordonnanceur et fiabilité

Tous les réglages de tâches se trouvent dans **Préférences → Tâches**. Cet onglet avancé les
regroupe par intention :

- ordonnanceur, parallélisme, leases et durée maximale d’une action ;
- tentatives courtes pour les erreurs applicatives et fenêtre longue pour les pannes réseau ;
- profondeur, nombre d’étapes et nombre de feuilles des plans ;
- requêtes modèle, appels d’outils et budgets cumulés de jetons ;
- attente et nombre de tours lors des collaborations entre agents.

Commencez avec peu de tâches simultanées, puis augmentez en observant le pool de connexions,
les quotas LLM et la charge des outils. Une lease trop courte peut rendre une action
récupérable alors qu’elle travaille encore ; une lease trop longue retarde la reprise après
un crash. Les changements s’appliquent aux nouvelles actions sans redémarrer le backend.

Le Dispatcher ne traite que les Tasks et ne produit que `EXEC` ou `PLAN`. Les échanges courts
utilisent le control plane conversationnel avec le modèle Conversation du profil effectif, ses limites
d’agrégation et une garde de réponse IA→IA fondée sur une requête fraîche. Pour diagnostiquer une
boucle, inspectez les rounds de conversation plutôt que les résultats du Dispatcher.

Les leases et tentatives sont persistées. Après un crash, une lease expirée peut être
récupérée et un parent de plan peut être réconcilié avec une étape fille déjà terminée.

Les drivers interne et Hermès annoncent explicitement leur capacité d’annulation. Le driver
interne annule le run, nettoie les sessions Console/MCP/Browser et reprend depuis des checkpoints
d’outils persistés ; Hermès relaie l’annulation au run corrélé. **Forcer la fin** reste une
opération de récupération lorsque l’annulation normale ne peut plus joindre le runtime.

## 7. Messageries, outils et processus

Les réglages communs de **Préférences → Messagerie** limitent les pièces jointes incluses
directement dans une requête au modèle à 4 Mio par défaut. Cette limite est indépendante
de la taille maximale des téléchargements. Les fichiers plus grands restent disponibles
par les outils. Toute modification s’applique aux prochains traitements sans redémarrage.

Nextcloud Talk, Matrix, OneBot, Telegram et WhatsApp peuvent être actifs simultanément pour un
même agent. Dans **Préférences → Messagerie**, configurez et activez chaque plateforme. Une réponse
utilise toujours la connexion et la room exactes de la conversation d'origine. Pour initier un
échange hors conversation, recherchez l'utilisateur puis fournissez son identifiant distant et le
canal choisi ; un canal indisponible échoue sans repli silencieux.

Créez une connexion distincte par plateforme dans **Outils → Messagerie**. Le healthcheck agrège
tous les comptes actifs et chaque listener est supervisé indépendamment. Le réglage historique
`MESSENGER_DRIVER` n'est plus un sélecteur de plateforme active ; il subsiste uniquement pour la
compatibilité des anciennes connexions génériques.

La recherche d'utilisateurs interroge toutes les connexions actives dont le protocole expose un
annuaire. Les résultats indiquent séparément la plateforme, l'identifiant utilisateur et
l'identifiant de connexion. Ils sont éphémères : Galaris ne gère, ne fusionne et ne persiste aucune
fiche de contact. Telegram Bot et WhatsApp Cloud n'offrent pas d'annuaire arbitraire et ne peuvent
donc pas compléter cette recherche sans un futur cache technique.

Les réglages communs sont stockés dans la table `params`; les identifiants propres aux agents
restent dans leurs connexions chiffrées.

Pour Nextcloud Talk, configurez au minimum l’URL de base et le mode entrant (`polling` ou
`signaling`). Les réglages généraux de voix se trouvent dans **Préférences → Voix**.

Les outils intégrés sont synchronisés au démarrage du backend. Leur activation par agent et les
fonctions désactivées sont gérées dans l’interface. Un driver n’obtient une fonction native
que si son profil de capacités l’autorise ; l’absence d’une capacité entraîne un refus par
défaut. Les fonctions personnelles de processus font partie du socle `galaris`. Le package
technique `process_admin` est réservé à l’administration globale et reste inactif par défaut.

Le catalogue envoyé au driver respecte d’abord les droits de l’agent et les fonctions désactivées.
Lorsque le runtime le permet, la découverte est différée : le modèle reçoit un index borné puis
charge uniquement les packages pertinents. Une recherche d’outil ne contourne jamais une
connexion inactive ni un privilège absent. Utilisez le diagnostic de connexion MCP dans
**Outils** pour distinguer une erreur réseau, d’authentification ou de découverte.

### Conversations et voix temps réel

Galaris possède trois profils de prompt d’exécuteur : Task, conversation texte et voix. Leur
suffixe administrable se règle dans **Préférences** avec `ai.executor-system-prompt`,
`ai.conversation-executor-system-prompt` et `ai.voice-executor-system-prompt`; le reste de l’arbre
JSON est construit par le code. Les jeux de données du Lab reprennent les mêmes catégories,
copient le suffixe courant à leur création puis peuvent le personnaliser et le figer par run.

Sur chaque agent, le sélecteur de voix réunit deux familles :

- une ressource TTS active le pipeline STT → agent → TTS et nécessite l’usage
  **Transcription** dans le profil effectif de l’agent ;
- une voix native d’un modèle `realtime_conversation` active la session speech-to-speech de ce
  fournisseur. L’implémentation initiale est fournie par le bridge OpenAI.

Ce sélecteur alimente une seule valeur durable sur l’agent : `tts:<id>` ou
`realtime:<id>:<code-voix-encodé>`. Les autres modèles sont tous résolus depuis son profil LLM.

Matrix et Nextcloud Talk transportent les appels temps réel. Telegram et WhatsApp transportent
leurs notes vocales comme médias entrants, sans devenir pour autant des transports d’appel. Une
session speech-to-speech peut ne produire aucune transcription utilisateur ; supervisez alors le
tour audio natif et ses appels de fonctions plutôt que d’attendre un texte intermédiaire.

### Navigateur agentique isolé

La connexion intégrée **Navigateur** est inactive par défaut et doit être activée agent par agent.
Le sidecar `browser-executor` héberge Chromium, mais chaque couple agent/Task reçoit un
`BrowserContext` privé et éphémère. Les sessions expirent automatiquement et sont fermées lors de
l’annulation du run.

Le service d’initialisation `browser-secrets` crée une seule fois le secret partagé dans le
volume Docker `browser_credentials`, sans reprise d’un ancien token d’environnement.
Le backend et le navigateur montent ce volume en lecture seule ; seul l’initialiseur peut
l’écrire. Celui-ci n’a ni réseau ni accès aux autres secrets du backend. Incluez ce volume
dans les sauvegardes. La durée d’inactivité (120 secondes par défaut), le nombre maximal
de sessions (32 par défaut), les délais d’opération, limites de contenu et de HTML, captures et dimensions par défaut
se règlent dans **Préférences → Navigateur**, visible dès qu’un agent a une connexion
Navigateur active. Ces réglages prennent effet aux prochaines opérations sans redémarrage ;
les dimensions par défaut concernent les nouvelles fenêtres. Réduire la capacité ne ferme
pas les sessions existantes : seules les nouvelles ouvertures sont limitées. Une session
reprend le délai d’inactivité courant lors de sa prochaine action. Le réseau
`browser_egress` et le proxy du sidecar refusent les destinations privées ou réservées après
résolution DNS ; ne raccordez pas directement le conteneur à un réseau d’administration.

Le résultat textuel normal est un snapshot accessible paginé. Les captures visuelles sont
découpées en tuiles, écrites sous `console://browser/…` lorsqu’une console est active et
explicitement tronquées si elles dépassent les limites. Sans console, aucune destination locale
implicite n’est disponible. Lorsque ce Tool est actif pour Hermès, son navigateur natif est désactivé afin de
conserver une seule politique d’autorisation.

### Réserver les capacités d’administration aux agents spécialisés

Trois packages intégrés spécialisés sont créés pour chaque agent avec une connexion **inactive** :

| Code technique | Libellé | Fonctions |
|---|---|---|
| `goal_management` | Gestion des objectifs | `goal_create`, `goal_list`, `goal_get`, `goal_update`, `goal_pause`, `goal_resume`, `goal_complete`, `goal_run_now`, `goal_delete` |
| `skill_management` | Gestion des skills | `skills_list`, `skill_read` |
| `process_admin` | Administration des processus | CRUD des définitions et gestion des runs de tous les agents |

Après `make update` :

1. ouvrez les connexions de l’agent DRH ;
2. activez **Gestion des objectifs**, **Gestion des skills** et, si nécessaire,
   **Administration des processus** uniquement sur cet agent ;
3. laissez ces connexions inactives sur les autres agents ;
4. désactivez éventuellement certaines fonctions au niveau de la connexion, par exemple
   `goal_delete`, si la DRH doit superviser sans pouvoir supprimer.

L’activation d’une connexion contrôle ce que le modèle peut appeler. Le RBAC HTTP contrôle, lui,
les utilisateurs capables de modifier cette configuration dans l’interface : ce sont deux niveaux
distincts et cumulatifs.

`goal_create` choisit explicitement l’agent propriétaire et un agent référent différent. Les
commandes de modification et de cycle utilisent `expected_revision`, obtenue avec `goal_get`, pour
éviter les écrasements concurrents. `goal_get` expose aussi le suivi Markdown, la tâche courante,
les verdicts, preuves, erreurs, coûts et derniers cycles. `goal_complete` conserve l’historique et
arrête les cycles futurs ; `goal_delete` effectue une suppression logique et refuse un objectif
ayant encore un cycle inachevé.

`skills_list` ne retourne par défaut que les skills présents, valides et effectivement autorisés
pour l’agent demandé. Son option `include_unavailable` permet un audit complet des états global et
individuel. `skill_read` lit uniquement le `SKILL.md` d’un skill indexé dans la bibliothèque
centrale ; il n’expose aucun autre fichier du package.

### Transcription de fichiers audio, vidéo et liens YouTube

Le tool intégré `audio` expose la fonction MCP suivante :

```text
audio_transcribe(file: str, destination: str = "", language: str = "") -> str
```

`file` accepte une URI canonique lisible annoncée par `file_schemes`, ou une URL HTTPS de vidéo YouTube. Il
n’existe pas de fonction YouTube distincte : ce contrat unique permet aux agents de traiter de la
même façon une pièce jointe audio, une pièce jointe vidéo ou un lien reçu dans une conversation.

Après la mise à jour qui introduit la fonction :

1. `make update` synchronise automatiquement le Tool et crée les connexions manquantes ;
2. activez la connexion intégrée **Audio** sur chaque agent autorisé à l’utiliser ;
3. pour les fichiers audio ou vidéo, configurez un fournisseur actif capable de transcription ;
4. ajoutez ou sélectionnez une ressource portant la capacité `transcription` ;
5. affectez-la à l’usage **Transcription** du profil concerné.

La connexion Audio est créée inactive par défaut, comme les autres capacités spécialisées. Si
elle est activée sans modèle STT configuré, un fichier audio ou vidéo produit une erreur explicite
au lieu de choisir un modèle implicite. Le service prend en charge OpenRouter, ElevenLabs et les
fournisseurs OpenAI-compatible selon leur endpoint de transcription configuré. Une URL YouTube
avec sous-titres ne nécessite pas de modèle STT, mais requiert toujours la connexion **Audio**.

Un agent auquel on demande une transcription doit donc avoir sa connexion **Audio** active. Si le
tool est absent, l’exécuteur s’arrête avec une erreur de configuration. Pour un fichier local, il
s’arrête aussi si le STT dédié n'est pas configuré ; il ne doit jamais tenter un repli par la
console ou par son propre modèle de chat.

Le fichier source reste chez son provider. Le backend le matérialise temporairement via
`file_share`, utilise PyAV pour ouvrir le conteneur, sélectionner sa première piste audio et
ignorer les flux vidéo. Il produit toujours un
MP3 mono 32 kHz à 96 kbit/s avant l’appel fournisseur. Les uploads multipart compatibles sont lus
depuis le disque ; OpenRouter nécessite encore un encodage base64 du MP3 normalisé. Les fichiers
temporaires sont supprimés après succès comme après erreur.

Pour une URL YouTube, `bridge.youtube` valide strictement le schéma HTTPS et les hôtes YouTube,
extrait l’identifiant de la vidéo, puis utilise `youtube-transcript-api` pour récupérer une piste
manuelle ou automatique. Aucun fichier vidéo ou audio n’est téléchargé et aucun appel STT n’est
effectué. Le transcript par défaut est `youtube-<identifiant>.txt`. Les vidéos de plus de dix
minutes suivent la même réduction hiérarchique et produisent
`youtube-<identifiant>.summary.md` avec un prompt adapté au contenu vidéo.

Cette récupération utilise l’interface de sous-titres du client web YouTube, qui n’est pas une API
publique garantie. YouTube peut modifier son comportement, demander une preuve d’origine ou
bloquer l’adresse IP d’un serveur, en particulier dans certains hébergements cloud. Galaris
renvoie alors une erreur explicite. Il n’utilise ni compte YouTube, ni cookie, ni proxy, et ne
télécharge pas l’audio comme solution de repli. La vidéo doit être publique et exposer des
sous-titres accessibles.

À partir de 10 minutes, l’encodeur produit plusieurs MP3 numérotés d’environ 10 minutes. Le salon
reçoit un unique message de progression indiquant la durée et le nombre estimé de segments, sans
que ce message ne remplace la réponse finale de la tâche. Chaque transcription partielle est
immédiatement résumée par le modèle exécuteur de la tâche ; une réduction hiérarchique consolide
ensuite ces résumés et écrit `<nom>.summary.md`. Le verbatim horodaté complet reste dans
`<nom>.txt`, mais seul le fichier de synthèse doit être relu par l’agent.

Le média original n’est jamais ajouté comme entrée multimodale du modèle exécuteur, même si ce
modèle déclare accepter l’audio ou la vidéo et même si le fichier est inférieur à la limite
d’upload générique. Le prompt ne reçoit que l’URI canonique de la source ; seul le MP3 normalisé est
envoyé au fournisseur STT dédié. Cette séparation évite qu’un média soit recompté dans le contexte
à chaque tour d’outil et épuise le budget cumulé de jetons de la tâche avant la transcription.

Prévoyez assez d’espace temporaire pour le média source et le MP3 normalisé, ainsi qu’un délai
fournisseur compatible avec les réunions longues. La conversion réduit le réseau pour les vidéos,
les sources PCM et les médias à haut débit, mais la plupart des services STT facturent à la durée :
elle ne garantit donc pas une baisse du prix de transcription.

Pour n8n, ouvrez **Préférences → Processus**, renseignez l’URL, le jeton API et les URL de
callback visibles depuis chaque côté, puis utilisez le bouton de test. Les jetons de callback
sont propres aux runs ; n’utilisez pas un secret
global comme paramètre de fichier public. Chaque appel fournit aussi une clé d’idempotence,
l’identifiant du run et son URL de callback dans des headers. Le contrat complet et le
gabarit importable sont décrits dans la [documentation n8n](../n8n/README.md).

## 8. Comptes, rôles et privilèges

Galaris applique un RBAC à trois niveaux :

1. un privilège protège une opération ou une ressource ;
2. un rôle regroupe des privilèges ;
3. une affectation lie un utilisateur et un rôle.

Les privilèges sont générés depuis le code puis synchronisés au démarrage du backend. Après une
mise à jour, vérifiez toujours le rôle administrateur et les rôles personnalisés. Accordez
les privilèges de gestion des connexions avec prudence : ils donnent accès à la modification
de secrets, même si les valeurs ne sont pas retournées en clair.

## 9. Sauvegarde et restauration

Un exercice entièrement isolé est disponible avec `make tests-restore` : dump et
restauration PostgreSQL, fichiers, clés de chiffrement et de signature. Voir la
[validation de sécurité](../dev/security-validation.md).

Sauvegardez ensemble :

- PostgreSQL ;
- `.env` dans un coffre sécurisé ;
- le volume Docker `browser_credentials`, avec ses propriétaires et permissions ;
- le volume ou répertoire `data`, notamment les workspaces, les médias et les données de
  l’exécuteur SSH embarqué ;
- la configuration du bridge Hermès et de n8n lorsqu’ils sont externes.

Exemple avec le service PostgreSQL fourni :

```bash
docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB" > galaris.dump
```

La restauration est une opération intrusive : arrêtez les écritures, restaurez dans une
base vide de même version majeure, puis démarrez la version de code correspondante. Son entrypoint
synchronise le schéma et le dataset avant l’API. Testez régulièrement la procédure sur un
environnement distinct.

### Cohérence des pièces jointes Messenger internes

Les lignes `messenger_files` ne contiennent que les métadonnées. Les octets du canal interne sont
dans `/data/chat`, donc dans le volume `data` de
l'installation standard. PostgreSQL et ce répertoire constituent un même point de restauration.

Pour une sauvegarde cohérente, placez l'installation en fenêtre de maintenance sans nouvel envoi,
produisez le dump PostgreSQL, puis archivez le répertoire `chat` avant de rouvrir les
écritures. Conservez ensemble le dump, l'archive, la version Git et la date. À la restauration,
restaurez d'abord la base et le répertoire avec leurs propriétaires et permissions, puis lancez la
version de code correspondante. Vérifiez ensuite un téléchargement autorisé et laissez le job de
réconciliation retirer les seuls blobs réellement orphelins.

Une sauvegarde PostgreSQL sans ce répertoire est incomplète et laisse des messages dont les pièces
jointes sont irrécupérables. Une copie du répertoire sans la base n'est pas exploitable non plus.
N'utilisez pas `make clean` pour préparer ou tester cette procédure : cette cible supprime les
volumes.

## 10. Mise à jour

```bash
make update
# Ou sélectionner un tag exact, sinon une branche distante :
make update VERSION=v1.2.3
```

Sans `VERSION`, `make update` construit et déploie les sources présentes sans récupération Git,
même si elles sont modifiées localement ou sur un tag détaché. Avec `VERSION` et un `.git`,
la commande récupère les références distantes et donne priorité à un tag exact sur une branche
du même nom. Une référence inconnue, une branche divergente ou des sources modifiées localement
arrêtent cette sélection avant toute action Docker. Les fichiers `.env` et overrides ignorés
sont conservés. La récupération automatique de `start` conserve également les sources présentes.
Le chemin `RELEASE_DIR` ne fait aucune opération Git et ne se combine pas avec `VERSION`.

Pour examiner les changements avant déploiement, récupérez-les séparément puis utilisez
`make update`. `make update` complète les secrets
absents, prépare SearXNG, récupère les images et reconstruit en réutilisant le cache Docker.
Après un build réussi, elle recrée le backend et le frontend, puis attend que l’entrypoint du
backend ait synchronisé Atlas et les données de référence et que les services soient disponibles.
Le frontend et SearXNG disposent de sondes HTTP ; PostgreSQL redémarre automatiquement avec Docker
sauf arrêt explicite. Les services d’infrastructure inchangés restent actifs, sans arrêt global
de la stack. La commande est
idempotente et constitue l’unique chemin de montée de version en production. Elle ne décide pas
à votre place des nouvelles options métier ;
ne remplacez pas la synchronisation déclarative par des modifications SQL manuelles.

Les couches Docker inchangées sont réutilisées, notamment pour les dépendances et les exécuteurs.
Un changement des sources frontend déclenche leur recompilation ; un frontend inchangé peut
conserver son image et son cache PWA. Chaque compilation frontend renouvelle intégralement les
ressources du cache PWA. Les onglets visibles recherchent une mise à jour toutes les minutes,
ainsi qu’au retour dans l’onglet ou en ligne, puis se rechargent automatiquement après son
installation. Les anciens fichiers
précachés sont supprimés ; les cookies, sessions et données utilisateur sont conservés.
Enregistrez les formulaires en cours avant le déploiement : le rechargement remplace la page.
Avec `RELEASE_DIR`, les images déjà qualifiées sont déployées telles quelles, sans reconstruction.

Le harness manager possède un cycle de déploiement indépendant et peut résider sur une autre
machine. `make update` ne le met jamais à jour et ne redémarre aucun service hôte externe. Sa mise
à jour s'effectue sur son propre hôte avec le Makefile de `harness_manager`, en coordonnant
explicitement la compatibilité avec les déploiements Galaris qui le consomment.

## 11. Surveillance et dépannage

Commandes sans effet destructif :

```bash
docker compose ps
make logs-back
make logs-front
make logs-search
make typecheck
```

`make typecheck` contrôle Pyright, TypeScript et la parité de toutes les clés anglaises et
françaises du frontend. `make tests` contrôle aussi la parité et les placeholders des
catalogues backend dans une base PostgreSQL éphémère.

Diagnostic rapide :

| Symptôme | Vérifications |
|---|---|
| aucune tâche ne démarre | driver disponible, executor configuré, scheduler actif, pool DB non saturé |
| une tâche reste en exécution | lease, délai d’action, appels LLM/MCP, connectivité fournisseur |
| Hermès indisponible | état de l’instance de l’agent, conteneur `<code>-agent`, URL et authentification du harness manager, URL MCP vue depuis Hermès |
| erreur pgvector | modèle d’embedding sélectionné et état de l’index sémantique Memory |
| navigateur indisponible | santé du sidecar, token partagé, limites de sessions, destination publique et proxy de sortie |
| action affirmée mais non faite | trace d’outils et garde « réponse sans action » |
| conversation sans réponse | état de la room et du round, messages en attente, usage Conversation du profil effectif, livraison sur la connexion d’origine |
| boucles entre agents | garde de réponse du control plane conversationnel, fraîcheur de la requête et origine des messages |
| appel vocal sans transcript | vérifier si la voix sélectionnée utilise une session speech-to-speech native ; ce mode peut être normal sans texte utilisateur |
| permission refusée | rôle courant, privilèges synchronisés, affectation active |
| PWA non proposée à l’installation | HTTPS, manifeste et service worker accessibles, navigateur hors navigation privée |
| reconnexion demandée à chaque lancement | cookie autorisé, `APP_HOST` en HTTPS, hostname stable, route `/api/auth/refresh` sans erreur 401/403 |

Pour signaler un incident, fournissez la version Git, l’identifiant de tâche, l’heure avec
fuseau et les journaux expurgés. Ne fournissez jamais `.env`, un header d’autorisation ou
une configuration Hermès contenant une clé.

## 12. Commandes à risque

- `make clean` supprime les volumes Docker, donc potentiellement PostgreSQL.
- une restauration écrase des données ; validez la cible et la sauvegarde.
- réduire un schéma manuellement contourne Atlas et peut rendre les modèles incompatibles.
- exécuter pytest directement dans le conteneur de développement est refusé : utilisez
  `make tests`, qui crée une base éphémère isolée.

La procédure hôte, le modèle de sécurité et le service systemd du harness manager sont détaillés
dans [`docs/fr/components/harness-manager.md`](../components/harness-manager.md). Les
particularités Hermès restent dans
[`docs/fr/components/hermes.md`](../components/hermes.md).
