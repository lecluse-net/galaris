<p align="right"><a href="../../en/admin/installation.md">English</a> · <strong>Français</strong></p>

# Installer Galaris

**Cloner le dépôt → `make install` → déployer un bundle qualifié → renseigner le token OpenRouter
dans Fournisseurs → discuter avec Galaris.**

Sur une installation neuve, les modèles et le profil par défaut sont préconfigurés, et
l’agent **Galaris** est créé avec le premier compte administrateur.

## Prérequis

Un hôte Linux avec Docker démarré, le plugin Docker Compose, Git, GNU Make, OpenSSL
avec `flock` (`util-linux`) pour les verrous et `ss` (`iproute2`) pour vérifier les ports.
Python, Node.js et PostgreSQL sont fournis dans les conteneurs.

Récupérez les sources depuis le dépôt officiel :

```bash
git clone https://github.com/lecluse-net/galaris.git galaris
cd galaris
```

## 1. Préparer l’installation

```bash
make install
```

Sur une installation neuve, la commande demande :

1. Inclure PostgreSQL ? **Oui par défaut** (`embedded`).
2. Quel port exposer ? **8484 par défaut**. Si le port TCP est déjà utilisé sur l’hôte
   ou publié par Docker, elle le signale et demande un autre port.

Elle crée `.env` avec `APP_HOST=http://localhost:<port>`, renseigne `<port>:8484` dans
`compose.override.yaml`, prépare la configuration et génère les secrets. Accepter les
valeurs par défaut suffit pour préparer une installation locale avec PostgreSQL intégré
sur <http://localhost:8484>, si ce port est libre.

Les fichiers existants sont conservés à la réinstallation. Si un override existe déjà sans
`.env`, ses ports sont conservés et le script invite à vérifier leur cohérence avec `APP_HOST`.
La construction et le démarrage auront lieu à l’étape 3.
Pour automatiser les choix : `make install POSTGRES_MODE=embedded INSTALL_PORT=8484`.
`POSTGRES_MODE=external` sélectionne une base externe. Un port explicite occupé ou invalide,
ou une fin d’entrée sans port utilisable, arrête l’installation sans créer la configuration.

## 2. Personnaliser la configuration si nécessaire

La configuration générée suffit pour une installation locale ; cette étape est facultative.
Modifiez `.env` uniquement si besoin. Exemple de configuration locale :

```dotenv
APP_HOST=http://localhost:8484
APP_ENV=prod
TZ=Europe/Paris
```

- **`APP_HOST`** : l’adresse utilisée pour ouvrir Galaris. Pour un serveur, indiquez votre URL
  publique, par exemple `https://galaris.example.org`, et configurez votre proxy HTTPS vers
  le port 8484. Cette variable ne crée ni le domaine ni le certificat.
- **`TZ`** : votre fuseau horaire.
- Gardez les autres valeurs par défaut, notamment `POSTGRES_MODE=embedded`, et les secrets générés.

Par défaut, `compose.postgres.yaml` fournit la base de données. Avec `POSTGRES_MODE=external`,
ce fichier n’est pas chargé : renseignez `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`,
`POSTGRES_USER` et `POSTGRES_PASSWORD` pour votre base PostgreSQL avec pgvector.
Si besoin, `compose.override.yaml` permet de personnaliser les **ports, volumes et réseaux** Docker.
Pour changer ensuite le port exposé, adaptez ce fichier avant de démarrer
(par exemple `8585:8484`) et indiquez l’adresse correspondante dans `APP_HOST`.
Les fournisseurs IA et leurs clés se configurent ensuite dans l’interface.

## 3. Démarrer Galaris

```bash
make update RELEASE_DIR=/chemin/vers/bundle-qualifie
```

La production exige des images immuables déjà qualifiées, sans reconstruction au déploiement.
Voir le [parcours de qualification](../dev/reliability-operations.md)
pour préparer ce bundle. La commande prépare le volume partagé, initialise la base et attend
la convergence complète du schéma et la disponibilité. Les réglages locaux sont conservés.
En développement seulement, `APP_ENV=dev make start` construit les sources.

Ensuite, `make start` relance les conteneurs existants sans construire. Si un service manque,
est en échec ou ne devient pas disponible, il tente une seule mise à jour complète. Une erreur
d’accès à Docker ou de lecture de la configuration arrête la commande.
En production, une récupération qui exige un déploiement nécessite également `RELEASE_DIR` ;
`start` ne reconstruit pas les sources et ne change pas de version Git.

## 4. Renseigner le token OpenRouter et discuter

1. Ouvrez l’adresse définie dans `APP_HOST` — <http://localhost:8484> avec les valeurs ci-dessus.
2. Cliquez sur **Connexion** pour créer le premier compte administrateur. Tant qu’aucun
   utilisateur n’existe, ce bouton ouvre l’inscription ; ensuite, il ouvre la connexion habituelle.
   L’agent **Galaris** est créé automatiquement pour ce premier administrateur.
3. Ouvrez **Fournisseurs** (`/llm?tab=providers`) et sélectionnez **OpenRouter**.
4. Renseignez votre **token / clé API OpenRouter**, puis enregistrez.
5. Ouvrez **Chat** (`/chat`), choisissez **Galaris** et envoyez votre premier message.

**Galaris est prêt à discuter : votre token OpenRouter est le dernier réglage nécessaire.**
Sur une base neuve, le fournisseur **OpenRouter**, neuf modèles et le profil **Défaut** sont
déjà configurés ; l’agent Galaris utilise ce profil. Vous pourrez ensuite personnaliser cette
configuration. Le token est celui de votre compte OpenRouter ; aucune clé ni aucun compte
OpenRouter n’est fourni avec Galaris.

Seul le Chat interne est activé à l'installation. Pour utiliser Nextcloud Talk, Matrix,
OneBot, Telegram ou WhatsApp, activez et configurez le canal dans **Préférences → Messagerie**.
Les mises à jour conservent les choix de canaux déjà enregistrés.

### Configuration fournie

Les quatre niveaux texte utilisent DeepSeek V4.1 Flash avec les efforts de raisonnement
`none`, `low`, `medium` et `high`. Le profil propose également GPT 5.4 Nano pour les documents,
Nemotron 3 Nano Omni pour l'audio et la vidéo, Nano Banana Pro pour les images, Whisper pour
la transcription, Qwen3 Embedding 4B pour les vecteurs, Jev 1.13 pour les décisions,
Lyria 3 Clip Preview pour la musique et Hailuo 3 Max pour la génération vidéo.
La génération de sons reste non configurée. Les tarifs peuvent être actualisés depuis le fournisseur.

Cette sélection est une proposition modifiable et supprimable. Pour supprimer le profil,
créez d'abord un autre profil, éventuellement vide : Galaris conserve toujours au moins un profil.
Les mises à jour ne réinstallent pas les éléments supprimés et ne remplacent pas vos réglages.
Les bases déjà installées ne reçoivent pas cette configuration rétroactivement.

## Ensuite

`make stop` arrête les conteneurs sans les supprimer ; `make start` les relance.
`make build` construit les images seules, sans modifier les conteneurs.
`make uninstall` supprime les conteneurs et réseaux du projet et propose trois confirmations
distinctes, toutes à **non par défaut** :

- supprimer les volumes gérés par Compose : `oui` ou `yes` efface définitivement leurs
  données, y compris PostgreSQL embarqué et les fichiers stockés ;
- supprimer les images locales générées par Compose pour le projet (`--rmi local`) :
  elles devront être reconstruites au prochain démarrage ;
- supprimer les conteneurs orphelins du même projet, absents de la configuration actuelle.

Entrée, un refus ou l’absence d’entrée conserve chaque ressource facultative. Les images
avec un tag explicite, notamment PostgreSQL et search, et le cache de construction partagé
sont conservés. Aucun `prune` global n’est exécuté. La configuration, les dossiers montés
depuis l’hôte et les bases ou volumes externes restent conservés. Si les volumes sont
conservés, un prochain `make start` réutilise leurs données.

`make uninstall FORCE` répond automatiquement **oui aux trois confirmations**, sans lire
l’entrée utilisateur. Les volumes et leurs données sont donc définitivement supprimés,
ainsi que les images locales Compose et les conteneurs orphelins du projet.

`make clean` supprime aussi les volumes : cette commande est destructive.

En production, déployez les images qualifiées :

```bash
make update RELEASE_DIR=/chemin/vers/bundle-qualifie
```

En développement seulement, récupérez et déployez un tag ou une branche :

```bash
APP_ENV=dev make update VERSION=0.3.1
```

Pour consulter les cibles disponibles avant de choisir :

```bash
make update VERSIONS
```

Cette commande interroge le dépôt Git distant configuré et liste tous les tags (versions les
plus élevées d’abord), puis toutes les branches par ordre alphabétique. Elle ne modifie pas les
sources locales et ne lance aucun déploiement, même avant `make install` ou avec des changements
locaux. Un checkout Git et l’accès au dépôt distant sont nécessaires.

En développement, `make update` récupère les images d’infrastructure, dont SearXNG, avant le build et le
redémarrage. La version SearXNG suit celle épinglée
dans `compose.yaml`, sans effacer la configuration existante. Un échec de récupération
arrête la mise à jour en conservant les services actifs.

Chaque tentative écrit un fichier privé `artifacts/updates/update-*.log`, dont le chemin
est affiché au terminal. Il conserve les étapes, les codes de sortie, la sortie de la
commande de démarrage et l'ensemble des logs du backend depuis le début de la tentative,
sans limite aux dernières lignes. Les erreurs DbAdmin fatales et non fatales restent ainsi
consultables dans ce fichier, même si le backend ne démarre pas ou si la tentative suivante
recrée son conteneur. Les secrets reconnus sont masqués avant écriture et les 100 derniers
journaux sont conservés. En cas d'échec, transmettre ce fichier suffit pour consulter ces
erreurs ; aucune requête SQL n'est nécessaire. Une collecte incomplète est signalée et
fait échouer une mise à jour autrement réussie, sans remplacer une erreur initiale.
Au démarrage suivant, DbAdmin réaffiche aussi les causes enregistrées des actions
inachevées avant de les retenter : une erreur antérieure peut donc être retrouvée
dans le nouveau journal même si l'ancien conteneur a été recréé.
Les anciens journaux qui ne contiennent que les étapes ne peuvent pas reconstituer les
sorties qu'ils n'ont pas enregistrées.

En développement sans `VERSION`, aucune récupération ni sélection Git n’est effectuée : les sources présentes
sont utilisées, y compris avec des modifications locales, un tag détaché ou sans upstream.
Avec `VERSION`, `.git` doit exister dans l’installation (répertoire ou fichier de worktree).
Le tag exact est prioritaire sur la branche du même nom ; une référence
inconnue provoque une erreur avant toute action sur les conteneurs.

Les sources modifiées localement bloquent la récupération Git ; `.env` et les overrides
ignorés sont conservés. Pour appliquer la configuration en production, redéployez le bundle qualifié.
Sans `.git`, le développement conserve la construction des sources présentes et refuse `VERSION`.

Si une mise à jour de la séparation Memory/Document a été arrêtée sur une contrainte
`memory_items.share_id` ou `share_kind` lors de la création de contacts, récupérez le correctif
puis relancez `make update`. DbAdmin reprend le transfert et la préparation des anciennes
colonnes automatiquement ; les archives et les droits existants restent conservés.
La distribution par registre d’images n’est pas encore prise en charge par ce chemin.

## Sauvegarde et restauration

```bash
make save
make save FILE=/sauvegardes/galaris.tar.gz
make restore /sauvegardes/galaris.tar.gz
# Équivalent, notamment pour un chemin contenant des espaces :
make restore FILE=/sauvegardes/galaris.tar.gz
```

Sans `FILE`, l'archive est créée dans `artifacts/backups/`. Elle contient un dump complet de
la base (tous les schémas, dont les archives de migration), `/data` sauf **`/data/files`**,
la configuration et les clés de récupération, un manifeste et des sommes SHA-256. Les liens
symboliques sont conservés sans suivre leur cible. Les sockets ne sont pas des fichiers
persistants et ne sont pas archivés. L'archive contient des secrets ; ses droits sont `0600`.
Elle n'est pas chiffrée et doit être stockée dans un emplacement protégé.

La commande utilise l'image du backend installé, sans lancer DbAdmin. Elle arrête temporairement
les services applicatifs actifs pour figer leurs écritures ; PostgreSQL reste disponible.
Après sauvegarde, ces services sont relancés, même si la copie échoue. Un verrou commun interdit
les sauvegardes, restaurations et déploiements concurrents depuis ces commandes.

Pour capturer aussi `/data/files` au même point logique, utilisez `make save KEEP_STOPPED=1` :
les services restent arrêtés après l'archive. Effectuez alors le rsync séparé, puis `make start`.
PostgreSQL reste actif pendant cette maintenance. L'option conserve l'arrêt même si la
sauvegarde échoue, afin de permettre une décision de reprise explicite.

La restauration vérifie l'intégrité, les chemins, la version majeure PostgreSQL et la clé de
chiffrement avant l'arrêt. Si la clé diffère, récupérez `ENCRYPTION_MASTER_KEY` dans le membre
`secrets.json` de l'archive et configurez-la dans `.env` avant de relancer la commande. Une archive
`before-restore-*.tar.gz` conserve l'état courant. Le dump est restauré dans une base temporaire,
puis la base et les données sont remplacées. Un échec traité tente de rétablir l'état précédent
et conserve les diagnostics. Le rôle PostgreSQL doit pouvoir créer et renommer des bases ; les
rôles référencés par les ACL du dump doivent exister. Aucun privilège n'est élevé automatiquement.

Après restauration, les services restent arrêtés. `/data/files` n'est ni sauvegardé ni modifié :
coordonnez sa copie **rsync séparée** avec la sauvegarde et sélectionnez le binaire compatible
avant le redémarrage. La création d'une archive de secours ne protège pas d'une perte du disque
qui la contient ; conservez une copie extérieure. `make tests-backup` exerce ces commandes sur
une installation Docker entièrement synthétique.

Si le démarrage échoue, consultez `make logs-back` ou `make logs`.

[Configuration avancée et exploitation](README.md) ·
[Guide utilisateur](../user/README.md) · [Toutes les commandes Make](../dev/make-commands.md)
