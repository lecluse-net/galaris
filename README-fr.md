<p align="right">
  <a href="README.md">English</a> · <strong>Français</strong>
</p>

<p align="center">
  <img src="resources/galaris.svg" width="170" alt="Logo Galaris">
</p>

<h1 align="center">Galaris</h1>

<p align="center"><strong>Ne discutez plus avec l’IA. Mettez-la au travail.</strong></p>

<p align="center">
  Le centre de contrôle auto-hébergé pour des agents qui agissent, collaborent, mémorisent<br>
  et progressent. Vos modèles, vos outils, vos données, vos règles.
</p>

<p align="center">
  <a href="#demarrage-rapide"><strong>Lancer Galaris</strong></a> ·
  <a href="#ce-que-galaris-apporte">Découvrir la plateforme</a> ·
  <a href="docs/fr/features.md">Tour complet des fonctionnalités</a> ·
  <a href="docs/fr/README.md">Documentation</a>
</p>

<p align="center">
  <img alt="Auto-hébergé" src="https://img.shields.io/badge/d%C3%A9ploiement-auto--h%C3%A9berg%C3%A9-0f766e">
  <img alt="Prêt pour Docker" src="https://img.shields.io/badge/Docker-pr%C3%AAt-2496ED?logo=docker&logoColor=white">
  <img alt="PWA Android et iOS" src="https://img.shields.io/badge/PWA-Android%20%26%20iOS-5A0FC8?logo=pwa&logoColor=white">
  <img alt="Licence CeCILL" src="https://img.shields.io/badge/licence-CeCILL-2563eb">
</p>

Un modèle sait raisonner. Une force de travail IA opérationnelle a aussi besoin d’identités, de
permissions, d’outils, de mémoire, de coordination, d’exécutions durables et de preuves.

**Galaris fournit cette couche opérationnelle.** Donnez à des agents nommés un rôle, un modèle,
des skills, des outils et des objectifs de long terme. Ils peuvent répondre dans les canaux de
votre équipe, déléguer un travail borné, utiliser le web et vos systèmes métier, reprendre après
un incident et construire une connaissance gouvernée à partir du travail accompli.

> **Les modèles répondent. Galaris livre — et conserve les preuves.**

<a id="ce-que-galaris-apporte"></a>

## Ce que Galaris apporte

| Avant | Avec Galaris |
|---|---|
| Des prompts isolés | Des agents nommés avec identité, consignes, skills, outils et workspace privé |
| Un chat éphémère | Des conversations texte et voix historisées, supervisées en direct et capables de lancer un travail de fond |
| Une réponse en un coup | Des tâches, plans, délégations, reprises, annulations et checkpoints sûrs |
| Un contexte à reconstruire | Une session partagée et une mémoire durable avec révisions, provenance, ACL et rappel hybride |
| Des notes dispersées | Des documents de travail collaboratifs et dossiers thématiques reliant les connaissances entre canaux |
| Des agents figés | Un entretien Dream optionnel qui consolide la mémoire et apprend des retours d’expérience fondés sur des preuves |
| Une automatisation opaque | Des traces LLM/outils, coûts, erreurs, runs de processus et benchmarks reproductibles dans le Lab IA |
| L’écosystème d’un fournisseur | Les runtimes Pydantic AI interne ou Hermès, des bridges LLM, MCP et n8n derrière un contrôle unique |

### Transformer une mission complexe en opération durable

Demandez de comparer des offres, rechercher les risques, vérifier les totaux, construire une
matrice de décision et envoyer la recommandation pour validation. Galaris route la demande vers
une exécution directe ou un plan persistant, délègue des étapes spécialisées, attend les
informations manquantes et reprend après un redémarrage. Tâches, tentatives, processus et
livrables restent liés et consultables.

### Rendre chaque conversation actionnable

Les agents répondent depuis le web, la PWA Android/iOS, Matrix, Nextcloud Talk, OneBot, Telegram
et WhatsApp Business. Les échanges courts passent par un contrôle conversationnel dédié qui
agrège les rafales et évite les boucles de réponses ; le travail réel devient une Task ou un
Processus durable sans bloquer la conversation. La voix en direct accepte aussi bien un pipeline
STT → agent → TTS composable que des fournisseurs speech-to-speech natifs lorsqu’ils sont configurés.

### Construire une connaissance plutôt que perdre le contexte

Galaris associe l’historique récent à une mémoire privée et gouvernée. Les agents recherchent de
façon lexicale ou sémantique, maintiennent des documents Markdown collaboratifs, conservent la
provenance et organisent les connaissances dans des dossiers thématiques indépendants d’un salon.
Dream peut profiter des périodes calmes pour dédupliquer et consolider les souvenirs, puis retenir
une leçon uniquement lorsque les preuves de la tâche la justifient.

### Mesurer le comportement de l’IA avant de lui faire confiance

Le Lab IA transforme de vraies Tasks, conversations texte et conversations vocales en jeux de
données versionnés. Comparez Dispatcher, Briefing, Planner, exécuteurs Task/Conversation/Voice et
mécanismes Dream/Goal avec rubriques sémantiques, cas figés, runs reprenables et diagnostics du juge.

## Une surface d’action complète

- catalogue MCP avec connexions par agent, restrictions par fonction et découverte différée selon
  les droits réels ;
- recherche web locale et navigateur Chromium isolé, sessions privées, snapshots accessibles et
  captures de page complète bornées ;
- fichiers privés ou partagés, génération/retouche/analyse d’images et exécution SSH contrôlée ;
- transcription audio/vidéo, segmentation des enregistrements longs et synthèse hiérarchique ; les
  sous-titres YouTube publics suivent le même parcours sans télécharger la vidéo ;
- processus personnels et administratifs durables, dont n8n avec idempotence, callbacks,
  annulation et suivi lié aux Tasks ;
- objectifs de long terme avec propriétaire, référent, planning, cycles, preuves et contrôles manuels.

Les capacités sont gouvernées par agent et les plus spécialisées restent inactives par défaut. Le
runtime ne voit que les outils et fonctions autorisés par ses connexions actives et les droits de
l’utilisateur courant.

<a id="demarrage-rapide"></a>

## Démarrage rapide

Prérequis : Docker avec Compose, GNU Make, Git et OpenSSL.

Clonez le dépôt officiel :

```bash
git clone https://github.com/lecluse-net/galaris.git galaris
cd galaris
make install
```

La configuration générée est prête pour une installation locale. Personnalisez-la uniquement si besoin :

- `.env` : adresse de Galaris (`APP_HOST`), fuseau horaire (`TZ`) et réglages applicatifs ;
- `compose.override.yaml` : ports, volumes et réseaux Docker. Si vous changez le port exposé,
  adaptez aussi `APP_HOST`.

Conservez les secrets générés, puis démarrez Galaris :

```bash
make start
```

Ouvrez l’adresse définie dans `APP_HOST` (<http://localhost:8484> par défaut).
Le premier compte devient administrateur. Le parcours de bienvenue
vous guide ensuite pour connecter un modèle, créer un agent, lui accorder des outils et ajouter un
canal de messagerie.

Au premier démarrage, `make start` construit les images, démarre les services, initialise la base
et attend leur disponibilité. Réutilisez cette commande pour relancer les conteneurs existants.

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

Aucune installation locale de Python, Node.js ou PostgreSQL n’est nécessaire. Pour une mise en
production, consultez le [guide d’installation et d’exploitation](docs/fr/admin/installation.md) avant d’exposer
l’instance.

## Un centre de contrôle pour toute la stack IA

```text
Web · PWA · API · Matrix · Nextcloud · OneBot · Telegram · WhatsApp
                              │
                              ▼
                    CENTRE DE CONTRÔLE GALARIS
      identités · RBAC · conversations · tâches · objectifs · processus
       planification · délégation · reprise · validations · traces
                 mémoire · dossiers · Dream · évaluation
                              │
             ┌────────────────┼─────────────────┐
             ▼                ▼                 ▼
       Pydantic AI         Hermès          MCP · n8n · fichiers
      agents internes   runtime externe    navigateur · médias · SSH
             └────────────────┴─────────────────┘
                              │
                              ▼
             modèles cloud ou locaux · votre infrastructure
```

Galaris propose des bridges natifs vers les grands écosystèmes de modèles — notamment OpenAI,
Anthropic, Google, Mistral, OpenRouter, Ollama et d’autres fournisseurs compatibles — sans faire du
choix du fournisseur l’architecture de vos agents.

## Documentation

- [Tour complet des fonctionnalités](docs/fr/features.md)
- [Installation et exploitation](docs/fr/admin/installation.md)
- [Portail documentaire](docs/fr/README.md)
- [Guide utilisateur](docs/fr/user/README.md)
- [Guide administrateur](docs/fr/admin/README.md)
- [Guide développeur et architecture](docs/fr/dev/README.md)
- [Cartographie et flux d’architecture](docs/fr/architecture/README.md)
- [Décisions du projet](project/decisions/README.md)
- [English overview](README.md)

## Vos modèles sont capables. Rendez-les opérationnels.

Construisez des agents qui agissent, conversent, reprennent, mémorisent et progressent tout en
gardant le contrôle de l’infrastructure, des permissions et des preuves.

**Clonez Galaris. Connectez un modèle. Donnez-lui une mission.**

Galaris est distribué sous licence libre CeCILL. Voir [LICENSE-FR.md](LICENSE-FR.md) et
[LICENSE.md](LICENSE.md).
