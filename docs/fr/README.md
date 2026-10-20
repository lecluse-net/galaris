<p align="right"><strong>Français</strong> · <a href="../en/README.md">English</a></p>

# Documentation de Galaris

La documentation est organisée selon la responsabilité de la personne qui la lit. Il
n’est pas nécessaire de comprendre l’architecture pour utiliser Galaris, ni de connaître
le code pour l’administrer.

## Découvrir la plateforme

[Découvrir les usages de Galaris](features.md)

Ce tour montre comment les capacités se combinent dans le travail quotidien. Les guides ci-dessous
expliquent les actions à réaliser ; ils conservent chacun leurs procédures.

Le [catalogue fonctionnel exhaustif](reference/functional-catalogue.md) reste une référence à part,
notamment pour préparer le site web : capacités détaillées, conditions, limites et inventaires.

## 1. Utilisateur et néophyte

[Lire le guide utilisateur](user/README.md)

[Trouver un écran, un menu ou un onglet](user/navigation.md)

[Confier et suivre une Task](user/tasks.md)

| Parcours | Guide |
|---|---|
| Classer les documents et agir sur une sélection | [Bibliothèque documentaire](user/documents.md) |
| Écrire, citer un objet, partager ou exporter | [Contenus riches](user/rich-content.md) |
| Créer et réutiliser du JSON | [Jeux de données](user/datasets.md) |
| Parcourir les ressources d'un agent | [Fichiers](user/files.md) |
| Travailler sur un checkout Git avec l'agent | [Éditeur de code](user/code-editor.md) |
| Concevoir et suivre un workflow BPMN | [Processus internes](user/internal-processes.md) |

Ce parcours explique avec des exemples :

- ce qu’est un agent et ce que Galaris orchestre réellement ;
- comment [installer Galaris comme application](user/pwa.md) sur Android ou iPhone et conserver
  sa session ;
- comment discuter, demander une action et lancer un travail de fond ;
- comment suivre séparément conversations texte, appels vocaux, Tasks et processus de fond ;
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

Ce parcours couvre l’installation et l’exploitation :

- Docker, `.env`, secrets, base PostgreSQL et mises à jour Atlas ;
- fournisseurs LLM et modèles utilisés par chaque fonction ;
- sélection et configuration des harnais d’exécution ;
- messageries, outils, objectifs durables, skills, transcription multimédia et YouTube, n8n, voix,
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
