<p align="right"><strong>Français</strong> · <a href="../en/README.md">English</a></p>

# Documentation de Galaris

## Par où commencer ?

| Votre situation | Point de départ |
|---|---|
| J’ai reçu une invitation | [Activer mon compte et trouver les agents de mon équipe](user/README.md#first-login) |
| J’ai accès à un agent et je veux l’essayer | [Transformer des notes en document avec la première mission guidée](user/README.md#first-mission) |
| Je cherche comment utiliser un écran de Galaris | [Interroger un agent sur la documentation installée](user/README.md#ask-about-galaris) |
| J’installe Galaris pour mon équipe | [Installer la plateforme et configurer le premier fournisseur](admin/installation.md) |
| Je découvre les possibilités ou je cherche une fonction précise | [Découvrir les usages](features.md) · [Consulter le catalogue fonctionnel](reference/functional-catalogue.md) |

## 1. Utilisateur et néophyte

[Lire le guide utilisateur](user/README.md)

[Trouver un écran, un menu ou un onglet](user/navigation.md)

[Confier et suivre une tâche](user/tasks.md)

| Parcours | Guide |
|---|---|
| Accepter une invitation, trouver son équipe et ouvrir un profil | [Accueil et comptes](user/navigation.md), [équipes](user/teams.md) |
| Comprendre un plafond atteint et demander du crédit | [Consommation et renouvellements](user/usage.md#request-credit) |
| Choisir le harnais du Chat et des tâches | [Claude Agent embarqué](components/claude-agent.md) |
| Partager un MCP local ou une capture depuis son poste | [Client Windows/Linux](user/desktop.md) |
| Retrouver un document annoncé dans le Chat et obtenir l’accès | [Résultats documentaires](user/documents.md#find-deliverable) |
| Répondre à un agent ou comprendre une tâche en attente | [Questions et reprises](user/tasks.md#reply-to-task) |
| Retrouver un fichier ou une pièce jointe dans une boîte mail | [Fichiers de l’agent](user/files.md#browse-files), [boîtes mail](user/files.md#browse-mail) |
| Donner accès à une API ou comprendre pourquoi un outil manque | [Connecter le Service](user/services.md#connect-service), [vérifier l’accès](user/services.md#service-access) |
| Écrire, citer un objet, partager ou exporter | [Contenus riches](user/rich-content.md) |
| Créer et réutiliser du JSON | [Documents Données](user/datasets.md) |
| Gérer les méthodes génériques et personnelles des agents | [Compétences](user/skills.md) |
| Travailler sur un checkout Git avec l'agent | [Éditeur de code](user/code-editor.md) |
| Concevoir et suivre un workflow BPMN | [Processus internes](user/internal-processes.md) |

Ce parcours explique avec des exemples :

- ce qu’est un agent et ce que Galaris orchestre réellement ;
- comment [installer Galaris comme application](user/pwa.md) sur Android ou iPhone et conserver
  sa session ;
- comment discuter, demander une action et lancer un travail de fond ;
- comment suivre séparément conversations texte, appels vocaux, tâches et processus de fond ;
- comment faire résumer une réunion ou une vidéo YouTube à partir d’un fichier ou d’une URL ;
- comment exploiter la mémoire, les documents de travail et les dossiers thématiques ;
- la différence entre effort `standard`/`high`, suivi par jalons et plan de tâches ;
- comment interpréter une tâche, une étape, une question ou un échec ;
- comment obtenir un résultat fiable sans apprendre le vocabulaire technique ;
- comment utiliser le [Lab IA](user/lab-ai.md) pour analyser une tâche, construire un dataset et
  interpréter un benchmark.

## 2. Administrateur

[Lire le guide administrateur](admin/README.md)

[Installer et exploiter Galaris](admin/installation.md)

[Donner la connaissance de Galaris à n'importe quel agent](admin/product-knowledge.md)

[Régler l'admission et la concurrence des fournisseurs IA](admin/provider-admission.md)

[Déléguer les privilèges et les réglages par fonction](admin/privileges.md)

Ce parcours couvre l’installation et l’exploitation :

- Docker, `.env`, secrets, base PostgreSQL et mises à jour Atlas ;
- fournisseurs LLM et modèles utilisés par chaque fonction ;
- sélection et configuration des harnais d’exécution ;
- messageries, outils, objectifs durables, compétences, transcription multimédia et YouTube, n8n, voix,
  permissions et comptes ;
- mémoire hybride, Dream, apprentissage, navigateur isolé et supervision temps réel ;
- réglage de l’ordonnanceur, sauvegardes, journaux et dépannage.

## 3. Développeur

[Lire le guide développeur](dev/README.md)

Ce parcours décrit le contrat du code :

- modularité `core`, `app` et `bridge` ;
- séparation `app.agent`, `app.harness`, `bridge.hermes` et `app.task` ;
- control planes des conversations texte et voix, mémoire gouvernée, Dream et Lab IA ;
- création d’un module et d’un futur `AgentDriver` ;
- SQLAlchemy, Atlas, RBAC, API, toolsets MCP, Vue, Pinia et i18n ;
- tests isolés, typage strict et règles de contribution.

Avant de publier le tag, exécutez `make release-check RELEASE_REF=<commit>`. Ce contrôle exige la réussite du workflow Security pour le commit exact et une nouvelle analyse des sources. Le résultat de Quality est présenté séparément. [Contrôle avant publication](dev/security-validation.md)

Pour une navigation orientée maintenance, consulter aussi
[`docs/fr/architecture`](architecture/README.md) : invariants, flux, machines d’état et
[cartographie générée](architecture/generated/project-map.md) des modules, routes, tables,
dépendances et outils MCP. Les choix structurels et leur justification sont conservés séparément
dans les [décisions du projet](../../project/decisions/README.md).

## Documentation technique des composants

- [Bridge Hermès](components/hermes.md)
- [Claude Agent Harness](components/claude-agent.md)
- [DeepSeek Harness](components/deepseek-harness.md)
- [Gestionnaire de harnais conteneurisés](components/harness-manager.md)
- [Exécuteur SSH embarqué](components/ssh-executor.md)

## Ce qui fait foi

En cas de divergence, l’ordre de confiance est le suivant :

1. contrats, modèles, implémentation et tests présents dans le dépôt ;
2. `.env.example`, `back/core/settings.py` et déclarations de modules ;
3. cette documentation et décisions acceptées ;
4. la cartographie générée, comme index statique du code ;
5. les plans, anciens tickets, captures ou discussions.

Une page qui recommande LangGraph, Alembic, un module `employee` ou un appel direct à
`app.harness` depuis une fonctionnalité métier est obsolète : l’architecture
actuelle n’utilise aucun de ces chemins.
