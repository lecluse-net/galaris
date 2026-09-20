<p align="right"><a href="docs/en/admin/installation.md">English</a> · <strong>Français</strong></p>

# Installer Galaris

**`make install` → configurer `.env` → `make update`.**

## Prérequis

Un hôte Linux avec Docker démarré, le plugin Docker Compose, Git, GNU Make et OpenSSL.
Python, Node.js et PostgreSQL sont fournis dans les conteneurs.

Remplacez `<repository-url>` par l’URL du dépôt à publier, puis récupérez les sources :

```bash
git clone '<repository-url>' galaris
cd galaris
```

## 1. Préparer l’installation

```bash
make install
```

La commande propose d’inclure PostgreSQL (**oui par défaut**), crée `.env`, prépare
la configuration Docker et génère les secrets.
Elle préserve les réglages existants. La construction et le démarrage auront lieu à l’étape 3.
Pour automatiser une installation avec une base externe : `make install POSTGRES_MODE=external`.

## 2. Configurer `.env`

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
Les fournisseurs IA et leurs clés se configurent ensuite dans l’interface.

## 3. Démarrer Galaris

```bash
make update
```

La commande construit les images avec votre configuration, démarre les services, initialise
la base de données et attend leur disponibilité. Le premier lancement peut prendre plusieurs minutes.

Ouvrez l’adresse définie dans `APP_HOST` — <http://localhost:8484> avec les valeurs ci-dessus.
Créez votre compte : le premier utilisateur devient administrateur. Le parcours de bienvenue
vous guide pour connecter un modèle et créer votre premier agent.

## Ensuite

Après une modification de `.env` ou la récupération d’une nouvelle version du dépôt,
relancez **`make update`**. Cette commande utilise les sources présentes dans votre copie du dépôt ;
elle ne fait pas de `git pull`.

Si le démarrage échoue, consultez `make logs-back` ou `make logs`.

[Configuration avancée et exploitation](docs/fr/admin/README.md) ·
[Guide utilisateur](docs/fr/user/README.md) · [Toutes les commandes Make](docs/fr/dev/make-commands.md)
