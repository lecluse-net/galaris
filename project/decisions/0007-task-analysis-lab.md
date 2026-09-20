# ADR 0007 — Lab centré sur l’analyse des tasks

- Statut : Superseded par [ADR 0021](0021-semantic-relevance-ai-lab.md)
- Date : 2026-07-20

Cette décision décrit la simplification du Lab au 20 juillet 2026. Elle reste utile pour comprendre
l’analyse macro de Tasks, qui existe toujours, mais sa décision d’exclure définitivement les
benchmarks a été remplacée le 31 juillet 2026 par un domaine de datasets isolés et reproductibles.

## Contexte

Le Lab historique traitait dispatcher, briefing, planner, executor et task comme cinq cibles
rejouables. Il persistait des snapshots JSON, des attendus, des suites, des runs et des résultats,
puis entretenait un worker dédié. Cette structure suggérait que les mécanismes internes du
pipeline étaient des surfaces paramétrables alors que leur activation est définie statiquement
par la politique de chaque driver. Elle dupliquait aussi des données dont `app.task`, `app.llm` et
`app.process` sont déjà les sources canoniques.

Le besoin opérateur est différent : partir d’une task réelle, comprendre si son objectif
fonctionnel a été atteint, expliquer son déroulement et identifier les leviers Galaris qui peuvent
améliorer une prochaine exécution.

## Décision historique

Les règles ci-dessous décrivent le contrat décidé le 20 juillet 2026. Elles ne doivent plus être
interprétées comme le contrat courant pour les benchmarks ; voir l’[ADR 0021](0021-semantic-relevance-ai-lab.md).

Le Lab devient exclusivement un outil d’analyse de tasks.

- La sélection d’une task reste limitée à `lab_tasks.task_id`, clé étrangère et clé primaire. Aucun
  JSON ni snapshot de task n’est copié dans cette table.
- Chaque analyse réussie ajoute un diagnostic immuable dans `lab_task_diagnoses`. Il contient la
  sortie structurée, la couverture des preuves, la révision de task, la langue, la version du prompt,
  le modèle, la durée, le coût et les métadonnées d’audit. Le dossier de preuves complet et le
  contexte humain facultatif ne sont pas persistés comme champs sources distincts ; le diagnostic
  peut naturellement reformuler les attentes qu’il analyse.
- L’ajout d’une task est idempotent. Sa suppression du Lab retire uniquement la référence, jamais
  la task canonique ni ses diagnostics ; ceux-ci redeviennent visibles si la task est ajoutée de
  nouveau.
- Au moment d’une analyse, le backend recharge un dossier borné depuis les domaines propriétaires :
  task et lignée, tentatives du scheduler, appels LLM et outils, process liés, configuration sûre de
  l’agent, skills, capacités et préférences Tasks courantes.
- Le dossier est nettoyé des valeurs de type secret, ses blocs sont explicitement non fiables et
  toute troncature est rendue visible.
- Un appel Pydantic AI direct utilise le paramètre `ai.model.lab` et une sortie structurée. Il ne
  crée, ne reprend et ne rejoue aucune task et n’appelle aucun driver Galaris. Sa sortie validée est
  enregistrée avant d’être retournée à l’interface.
- Le prompt décrit l’architecture et les leviers réels de Galaris. Il interdit de confondre un
  statut `SUCCESS` avec une preuve fonctionnelle ou un texte du modèle avec une preuve d’effet
  externe. Il distingue aussi la configuration actuelle d’une configuration historique non
  capturée.
- Dispatcher, briefing, planner et executor ne sont plus des cibles du Lab. Les suites, jeux de
  tests, runs comparatifs, résultats persistés et le worker de replay sont supprimés.

## Conséquences historiques

- Une analyse reflète toujours l’état canonique disponible au moment où elle est demandée ; elle
  conserve son diagnostic, mais pas le dossier canonique qui l’a produit. La révision de task et la
  version du prompt rendent son contexte identifiable sans prétendre à une reproduction complète.
- La qualité du diagnostic dépend de la couverture des traces. Une réponse structurée peut être
  `inconclusive` et doit exposer les preuves manquantes.
- Les recommandations portent sur les surfaces réellement administrables : définition de task,
  agent, modèles standard/high, skills, outils, connexions, préférences Tasks ou dépendances
  externes. Elles ne proposent pas de paramétrage fictif du pipeline interne.
- Atlas supprime les anciennes tables `evaluation_cases`, `evaluation_suites`, `evaluation_runs`
  et `evaluation_results`, puis crée `lab_tasks` et `lab_task_diagnoses`.
- Le Lab n’est plus un framework de non-régression ou de benchmark. Un futur besoin de datasets
  reproductibles devra être conçu comme un domaine distinct au lieu de recopier les tasks dans ce
  module d’analyse.

## Preuves dans le code

`back/app/lab/models.py`, `evidence_service.py`, `prompts.py`, `analysis_service.py`,
`diagnosis_service.py`, les routes `/api/evaluation/tasks`, l’écran
`front/app/lab/pages/ai-evaluations.vue` et
`back/app/lab/tests/test_evaluation.py`.
