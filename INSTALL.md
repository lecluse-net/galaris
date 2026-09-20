<p align="right"><a href="docs/en/admin/installation.md">English</a> · <strong>Français</strong></p>

# Installer Galaris

**`make install` → personnaliser si besoin `.env` et `compose.override.yaml` → `make start`.**

## Prérequis

Un hôte Linux avec Docker démarré, le plugin Docker Compose, Git, GNU Make et OpenSSL.
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

La commande propose d’inclure PostgreSQL (**oui par défaut**), crée `.env`, prépare
la configuration Docker et génère les secrets.
Elle préserve les réglages existants. La construction et le démarrage auront lieu à l’étape 3.
Pour automatiser une installation avec une base externe : `make install POSTGRES_MODE=external`.

## 2. Personnaliser la configuration si besoin

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
Si besoin, personnalisez les ports, volumes et réseaux Docker dans `compose.override.yaml`.
Si vous changez le port exposé, adaptez aussi l’adresse dans `APP_HOST`.
Les fournisseurs IA et leurs clés se configurent ensuite dans l’interface.

## 3. Démarrer Galaris

```bash
make start
```

Au premier démarrage, la commande construit les images avec votre configuration, démarre les services, initialise
la base de données et attend leur disponibilité. Le premier lancement peut prendre plusieurs minutes.
Ensuite, `make start` permet de relancer les conteneurs existants.

Ouvrez l’adresse définie dans `APP_HOST` — <http://localhost:8484> avec les valeurs ci-dessus.
Créez votre compte : le premier utilisateur devient administrateur. Le parcours de bienvenue
vous guide pour connecter un modèle et créer votre premier agent.

## Ensuite

Pour mettre à jour la branche courante, récupérez les sources puis déployez-les :

```bash
git pull --ff-only
make update
```

Ou récupérez et déployez un tag ou une branche en une commande (remplacez `v1.2.3` par la référence souhaitée) :

```bash
make update VERSION=v1.2.3
```

`make update` reconstruit les images, synchronise la base et attend la disponibilité des services.
Sans `VERSION`, elle utilise les sources présentes sans récupération Git. Utilisez-la aussi après
une modification de `.env` ou de `compose.override.yaml`.

Si le démarrage échoue, consultez `make logs-back` ou `make logs`.

[Configuration avancée et exploitation](docs/fr/admin/README.md) ·
[Guide utilisateur](docs/fr/user/README.md) · [Toutes les commandes Make](docs/fr/dev/make-commands.md)
