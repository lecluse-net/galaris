<p align="right"><a href="../../en/admin/installation.md">English</a> · <strong>Français</strong></p>

# Installer Galaris

**`make install` → personnaliser la configuration → `make start`.**

## Prérequis

Un hôte Linux avec Docker démarré, le plugin Docker Compose, Git, GNU Make, OpenSSL
et `ss` (paquet `iproute2`) pour vérifier les ports.
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

Ouvrez `.env` dans votre éditeur. Pour commencer sur la machine locale :

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
Pour l’installation standard, aucun autre fichier n’est à modifier.
`compose.override.yaml` sert principalement à personnaliser les **ports, volumes et réseaux**.
Pour changer ensuite le port exposé, adaptez ce fichier avant de démarrer
(par exemple `8585:8484`) et indiquez l’adresse correspondante dans `APP_HOST`.
Les fournisseurs IA et leurs clés se configurent ensuite dans l’interface.

## 3. Démarrer Galaris

```bash
make start
```

Au premier démarrage, la commande construit les images depuis les sources présentes,
prépare les droits du volume applicatif partagé, crée les conteneurs,
initialise la base et attend la disponibilité. Les réglages de `.env` et
`compose.override.yaml` sont conservés.
Le premier lancement peut prendre plusieurs minutes.

Ensuite, `make start` relance les conteneurs existants sans construire. Si un service manque,
est en échec ou ne devient pas disponible, il tente une seule mise à jour complète. Une erreur
d’accès à Docker ou de lecture de la configuration arrête la commande.
Cette récupération utilise les sources déjà présentes : `start` ne change pas de version Git.

Ouvrez l’adresse définie dans `APP_HOST` — <http://localhost:8484> avec les valeurs ci-dessus.
Cliquez sur **Connexion** : tant qu’aucun utilisateur n’existe, ce bouton ouvre le formulaire
de création du premier compte administrateur. Ensuite, il ouvre la connexion habituelle. Le parcours de bienvenue
vous guide pour connecter un modèle et créer votre premier agent.

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
`make clean` supprime aussi les volumes : cette commande est destructive.

Pour mettre à jour la branche courante, récupérez les sources puis déployez-les :

```bash
git pull --ff-only
make update
```

Ou récupérez et déployez un tag ou une branche en une commande (remplacez `v1.2.3` par la référence souhaitée) :

```bash
make update VERSION=v1.2.3
```

Sans `VERSION`, aucune récupération ni sélection Git n’est effectuée : les sources présentes
sont utilisées, y compris avec des modifications locales, un tag détaché ou sans upstream.
Avec `VERSION`, `.git` doit exister dans l’installation (répertoire ou fichier de worktree).
Le tag exact est prioritaire sur la branche du même nom ; une référence
inconnue provoque une erreur avant toute action sur les conteneurs.

Les sources modifiées localement bloquent la récupération Git ; `.env` et les overrides
ignorés sont conservés. Pour appliquer seulement leur configuration, utilisez `make update`.
Sans `.git`, `update` conserve la construction depuis les sources présentes et refuse `VERSION`.
La distribution par registre d’images n’est pas encore prise en charge par ce chemin.

Si le démarrage échoue, consultez `make logs-back` ou `make logs`.

[Configuration avancée et exploitation](README.md) ·
[Guide utilisateur](../user/README.md) · [Toutes les commandes Make](../dev/make-commands.md)
