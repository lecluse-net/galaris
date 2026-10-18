<p align="right"><strong>Français</strong> · <a href="../../en/admin/code-editor.md">English</a></p>

# Configurer l’éditeur de code conversationnel

Le runtime `code-executor` supervise code-server 4.141.0, dont l’image et le digest sont
figés dans `code-executor/Dockerfile`. La passerelle intégrée au backend utilise
`/api/code/gateway/` sur la même URL que Galaris et revalide les sessions HTTP et WebSocket.
Ne publiez pas le broker sur 8766 ni les sockets Unix de code-server.

## Origines et accès

`APP_HOST` est l’unique origine publique, par exemple `https://galaris.example.net`.
Aucun sous-domaine, port IDE public ou paramètre `CODE_EDITOR_ORIGIN` n’est nécessaire.
En production, Nginx transmet les requêtes et WebSockets de `/api/code/gateway/` au backend,
avec le Host et le protocole externes. Cette route conserve les en-têtes de l’IDE sans
hériter de la CSP du shell ni du traitement des fichiers statiques de l’application.
En développement (`APP_ENV=dev` exactement), Vite assure le même routage ;
`APP_HOST=http://localhost:8484` convient. Les autres labels exigent HTTPS pour l’éditeur.

Le cookie IDE est propre au chemin de sa session et reste HttpOnly, `SameSite=Strict` et
Secure en HTTPS. La passerelle filtre cookies applicatifs et bearer avant de contacter
code-server. Le shell et l’IDE partagent toutefois une origine navigateur : code-server
et ses extensions frontend appartiennent donc au même périmètre de confiance que le shell.
L’isolation des dépôts et processus reste assurée par le broker et les namespaces Linux.
Après préparation de la configuration et de la documentation, appliquez les changements
avec la procédure de mise à jour habituelle, sur demande explicite.

Attribuez `CODE_ACCESS` aux rôles humains concernés. Le propriétaire de l’agent reçoit
un grant explicite sur chaque nouvel espace présenté ; l’agent reçoit son propre grant.
Les grants enregistrés restent précis, distincts des accès Chat et Agent ; le panneau
ne propose plus de gestion du partage.
Les tickets de lancement durent 60 secondes, s’utilisent une fois et passent dans le
fragment URL. Les cookies IDE sont limités à la session, HttpOnly, Secure en HTTPS,
et rattachés à la famille de connexion du navigateur.

## Console embarquée

Le broker accède aux volumes de `ssh-executor` sur un réseau privé, avec un credential
indépendant initialisé par `code-secrets`. Chaque processus IDE reçoit seulement le
checkout autorisé, ses métadonnées Git et son profil. Les profils modifiables reçoivent
en lecture seule `.gitconfig`, `.config/git` et `.ssh` du compte Unix. Les autres dépôts,
secrets Galaris et le socket Docker ne sont pas montés dans l’éditeur.

Le lanceur est un composant de confiance : Bubblewrap utilise des namespaces Linux,
des identités non système et aucun capability dans l’éditeur. Les exceptions seccomp,
AppArmor et systempaths de Compose s’appliquent au broker. Elles exigent un hôte Linux
qui autorise les namespaces utilisateur. Un hôte incompatible doit annoncer l’IDE
indisponible ; il ne peut pas simuler la consultation avec un réglage visuel.
La Console agent conserve son interdiction de forwarding SSH.

Le répertoire doit être un checkout Git non bare à l’intérieur du home canonique.
Le home entier et les symlinks qui en sortent sont refusés. Les worktrees sont reconnus,
y compris leurs métadonnées communes dans ce home. Le serveur vérifie les identités des
répertoires à la découverte et sur les descripteurs utilisés pour les montages : une
connexion modifiée ou un dépôt remplacé ne redirige pas silencieusement un ancien espace.

## Console externe préparée

Dans la connexion **Console** de l’agent, choisissez une cible externe et cliquez directement
sur **Déployer l’éditeur de code**, puis enregistrez la connexion. La vérification SSH est
automatique ; un test manuel préalable n’est pas nécessaire. L’infobulle explique ce que le
déploiement installe. Une configuration globale imposée affiche une raison explicite au clic. Cette action
administrative explicite envoie le bundle versionné par SFTP avec la clé hôte approuvée,
construit et démarre code-server, vérifie le service à travers le tunnel SSH et enregistre
son accès chiffré dans Galaris. Aucun jeton n’est retourné au navigateur.

**Tester** et **Déployer l’éditeur de code** conservent l’état actif déjà enregistré
de la connexion. Une nouvelle connexion reste inactive jusqu’à son enregistrement ;
une connexion volontairement désactivée n’est pas réactivée par ces actions.
`repository_show` exige une Console active : vérifiez cet état si l’accès est refusé.

La cible doit être Linux, disposer de Python 3, de Docker avec Compose accessibles au compte
SSH et autoriser les namespaces utilisateur et le transfert de port local. Le bouton
n’installe pas Docker et ne modifie pas sshd. Sans ces prérequis, le déploiement échoue
explicitement et peut être relancé après correction. Le build initial peut prendre plusieurs
minutes et nécessite l’accès aux images et paquets de l’image épinglée.

Chaque compte Unix reçoit un service privé, avec un port loopback attribué par Docker et
un profil conservé. Seul son home est monté dans le broker ; les processus IDE gardent leurs
montages limités aux dépôts approuvés. Après l’installation initiale, le bouton de déploiement
disparaît. Chaque `make update`, en développement comme en production et depuis une release,
vérifie les éditeurs des connexions SSH externes actives déjà configurées. Le bundle livré avec
Galaris est comparé au bundle installé : un service à jour est vérifié sans reconstruction ni
interruption de ses sessions ; un bundle différent est mis à niveau automatiquement.
Les connexions inactives et sans éditeur configuré ne sont pas équipées automatiquement.
Un broker administré manuellement reste sous votre responsabilité et est signalé sans modification.

Enregistrez vos fichiers et terminez les sessions avant une mise à niveau ; les sessions masquées
restent ouvertes. Une session active bloque le remplacement, et une panne SSH, Docker ou de
vérification fait échouer la mise à jour globale, sans annoncer un succès incomplet. Les autres
cibles indépendantes sont tout de même vérifiées. Corrigez le problème puis relancez `make update`.
Le diagnostic indique l’étape (`inspection` ou `upgrade`) et un motif reconnu, par exemple
`sessions_active`, `docker_access` ou `user_namespaces`, sans afficher les sorties distantes ni
les secrets. `unknown` signifie que le contrôleur n’a pas fourni de motif reconnu. Cette étape
vient après le redémarrage et la disponibilité de Galaris : son échec ne signifie pas que
l’application est arrêtée. Pour `sessions_active`, fermez les sessions de toutes les connexions
qui utilisent le même compte Unix, y compris les sessions masquées.
La mise à niveau conserve le port privé, le credential et les profils retenus, et restaure l’image
précédente si la construction ou la vérification locale échoue. La création de sessions est bloquée
pendant le remplacement. L’automatisation ne modifie jamais les paramètres d’accès enregistrés.
Une session IDE ouverte empêche aussi de changer son accès
au runtime ; enregistrez ses buffers et terminez-la avant cette modification.
Les dépôts présentés avant le déploiement conservent leur URI
si leur identité vérifiée est inchangée ; un checkout remplacé reste refusé.

`repository_show` n’installe rien à distance. Pour une installation administrée manuellement,
distribuez le répertoire versionné `code-executor/` sur la cible Linux, puis utilisez
[`compose.external.yaml`](../../../code-executor/compose.external.yaml) :

1. Choisissez `CODE_TARGET_HOME_ROOT`, parent des homes approuvés, et conservez leurs chemins
   absolus dans les montages. Ne montez ni `/`, ni un socket Docker dans le runtime.
2. Démarrez explicitement `docker compose -f compose.external.yaml up -d --build` dans ce
   répertoire après l’autorisation de préparation. Le port 8766 est publié seulement sur loopback.
3. Transmettez le credential de contrôle à l’administrateur de Galaris par un canal privé.
   Renseignez les paramètres Console `code_runtime_port=8766` et `code_runtime_token`.
   Ce dernier est chiffré comme les autres mots de passe de connexion.
4. Épinglez la clé hôte SSH de la Console. Autorisez pour cette identité de transport
   `AllowTcpForwarding local` avec `PermitOpen 127.0.0.1:8766`, selon la configuration OpenSSH
   administrée. Les autres destinations restent interdites.
5. Vérifiez l’ouverture dans le Chat. Un tunnel refusé, une clé hôte changée ou un runtime
   absent donnent une erreur ; aucune copie ou installation de secours n’est effectuée.

Un accès SSH fonctionnel au dépôt ne suffit pas pour ouvrir l’éditeur. Si le port ou le
jeton du runtime manque dans la connexion Console, le Chat signale que cette Console externe
n’est pas configurée pour l’éditeur. Vérifiez ces deux paramètres après la préparation.
Une modification manuelle de la configuration de la Console change l’identité de la cible :
demandez à l’agent de présenter à nouveau le dépôt avec `repository_show` avant de l’ouvrir.

La clé SSH de transport Console et les clés SSH de forge sont deux usages différents.
Le Git humain utilise les secondes depuis le runtime, avec la configuration déjà présente
dans le dépôt/home. Les chemins externes au home, agents SSH non montés, moteurs de
credential spéciaux et paquets absents du runtime nécessitent une préparation administrée.
Le terminal complet de la Console et le redémarrage de ses services ne sont pas fournis.

## Exploitation, récupération et vérification

Le backend réconcilie les sessions toutes les dix secondes. Les flux revérifient les droits
et la connexion à la même fréquence. Les profils IDE sont conservés après expiration ou
révocation pour permettre une récupération autorisée ; leur conservation n’accorde aucun
accès. Le panneau ne propose pas de suppression de session ; le nettoyage des profils
devenus inutiles relève d’une maintenance administrateur après sauvegarde des brouillons.
Les quotas refusent une nouvelle instance au lieu d’évincer un buffer potentiellement sale.
Le broker accepte au plus huit IDE actifs et 64 profils conservés au total. La limite
de huit par compte Unix concerne les IDE actifs, pas les profils arrêtés.
L'instance synthétique mesurée occupait environ 510 Mio avec
un IDE ; ces limites correspondent au plafond mémoire de 8 Gio par défaut. Les extensions
et les dépôts plus lourds peuvent augmenter cette consommation ; surveillez ce plafond.
Les logs techniques du runtime sont bornés à 1 Mio par session. Les profils eux-mêmes
peuvent contenir des données de travail ; dimensionnez et surveillez le volume `code_profiles`.

Un profil appartient à une session humaine : dépôt (connexion Console et checkout),
utilisateur Galaris, mode lecture/édition et famille de connexion du navigateur.
La réouverture réutilise la session active correspondante ou un profil arrêté du même
utilisateur/dépôt/mode. Les autres connexions actives restent indépendantes.
Le chemin interne est `/var/lib/galaris-code/sessions/<uuid>/profile/`, dans le volume
`code_profiles` de la Console embarquée ou `profiles` du runtime distant.

Après une expiration, **Réessayer** revérifie les droits, la famille de connexion et
l'identité du dépôt, relance au besoin le même profil et renouvelle le cookie sans
remplacer l'iframe. Si le processus IDE a été arrêté, le panneau garde cette fenêtre et
ouvre une fenêtre de récupération sur le même profil. Le client natif ne rétablit pas
ses anciennes connexions IPC après un redémarrage complet. L'utilisateur peut retrouver
et copier ses brouillons depuis la fenêtre précédente. Une nouvelle panne exige une
confirmation avant remplacement de la fenêtre de récupération, jamais de l'originale ;
il y a au plus deux iframes par dépôt ouvert. Une panne réseau conserve le buffer ;
un droit retiré reste refusé.

### Archiver et récupérer un profil

Cette maintenance s'effectue seulement lors d'une intervention administrateur autorisée.
Enregistrez les fichiers et fermez les onglets Galaris qui utilisent l'éditeur avant
d'arrêter son runtime. L'outil refuse de modifier les profils tant que le broker tourne,
ainsi que les profils encore montés par un processus IDE orphelin. Il ne modifie pas les dépôts.

Pour la Console embarquée, créez un répertoire de sauvegarde privé, puis :

```bash
mkdir -p artifacts/ide-backups
chmod 700 artifacts/ide-backups
docker compose stop code-executor
docker compose run --rm --no-deps --entrypoint python3 \
  -v "$PWD/artifacts/ide-backups:/backup" code-executor \
  /opt/galaris-code/profiles.py list
```

L'outil ne fait aucun appel réseau. Pour les commandes suivantes, reprenez la commande
`run` en remplaçant `list` par l'action voulue :

- `archive <uuid> --output /backup/<uuid>.tar.gz` sauvegarde le profil sans le retirer.
- `retire <uuid> --output /backup/<uuid>.tar.gz` crée d'abord une archive privée complète,
  puis retire le profil du quota. Une erreur de sauvegarde ou une archive déjà existante
  laisse le profil intact. Aucun brouillon n'est supprimé automatiquement.
- `restore /backup/<uuid>.tar.gz` restaure sous le même UUID, sans écraser un profil existant.

Conservez ces archives privées sur un stockage sauvegardé. Relancez ensuite
`docker compose start code-executor` et rouvrez le dépôt avec l'utilisateur autorisé.
Pour une Console externe, utilisez sur la cible son fichier Compose déployé et le service
`runtime` à la place de `code-executor`, avec le même volume `profiles`. Une restauration
n'accorde aucun accès et ne peut pas rediriger le profil vers un checkout différent.

`make tests-code` vérifie les montages, la consultation, les worktrees et le cycle Git sur
une forge SSH synthétique. Les tests backend Code utilisent la base PostgreSQL éphémère
de `make tests`. Les parcours du panneau utilisent les composants réels avec des fixtures
explicites ; les essais natifs de `compose.code-tests.yaml` utilisent code-server réel.
Ces tests ne déploient aucune installation existante.

La qualification navigateur exerce la sauvegarde réelle à travers la passerelle dans
Chromium, Firefox et WebKit. Les webviews Markdown natives sont qualifiées séparément
lorsqu'elles fonctionnent. Avec cette version upstream, le chargement des ressources de
l'aperçu Firefox échoue via son CDN virtuel ; cette limite est acceptée pour la première
livraison stable. Utilisez Chromium ou WebKit pour cet aperçu ; l'édition source Firefox
reste prise en charge. Un scénario distinct en échec attendu surveille cette limitation
sans masquer les régressions d'édition ou de reprise. Un problème
upstream connexe est suivi dans [code-server #7913](https://github.com/coder/code-server/issues/7913).
L'image ne contient pas non plus les assets navigateur VSDA facultatifs ; l'édition
native utilise son fonctionnement de secours.

Galaris et son extension de navigation conservent CeCILL 2.1. Les notices MIT de code-server,
VS Code OSS et les notices tierces restent dans l’image upstream ; l’extension embarque
la licence Galaris. Aucun Marketplace Microsoft n’est ajouté ; le catalogue upstream
reste celui de code-server. Vérifiez les licences des extensions supplémentaires distribuées.
