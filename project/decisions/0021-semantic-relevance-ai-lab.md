# ADR 0021 — Pertinence sémantique des benchmarks du Lab IA

- Statut : Accepted
- Date : 2026-07-31

## Contexte

Les sorties ouvertes de Briefing, Planner et Dream peuvent être correctes avec des formulations,
ordres, nombres d’items, taxonomies ou stratégies différents. Comparer les feuilles JSON ou le
texte à une unique sortie attendue confond donc ressemblance et qualité. Sur un cas Briefing réel,
une réponse pertinente a ainsi reçu environ 31 % parce que l’ordre et la formulation différaient,
alors que les ressources et l’objectif essentiels étaient couverts.

Les travaux G-Eval montrent les limites des métriques de recouvrement pour les productions
ouvertes. MT-Bench et les études ultérieures montrent qu’un LLM juge peut mieux suivre le jugement
humain, mais reste exposé aux biais de position, de verbosité et de préférence pour ses propres
sorties. LLM-Rubric et Prometheus soutiennent des rubriques multidimensionnelles explicites plutôt
qu’un verdict global opaque. PaperBench complète cette approche en décomposant l’objectif en
exigences indépendamment évaluables et en testant aussi la qualité du juge.

Références : [G-Eval](https://aclanthology.org/2023.emnlp-main.153/),
[MT-Bench](https://arxiv.org/abs/2306.05685),
[LLM-Rubric](https://aclanthology.org/2024.acl-long.745/),
[Prometheus](https://arxiv.org/abs/2310.08491),
[biais de position](https://aclanthology.org/2025.ijcnlp-long.18/),
[biais d’auto-préférence](https://aclanthology.org/2025.emnlp-main.86/) et
[PaperBench](https://openai.com/index/paperbench/).

## Décision

Dispatcher conserve son barème hybride v1, car ses choix de route, effort, langue et action ont
des valeurs contractuelles largement exactes.

Tous les autres mécanismes utilisent une rubrique sémantique v2 propre au mécanisme. Chaque
dimension décrit un critère observable et un poids ; les poids totalisent 100 %. Le modèle du Lab
note le candidat **pointwise** contre l’objectif, les données d’entrée, les contraintes et le
contrat du mécanisme. Il retourne un score et une appréciation par dimension, puis le serveur
calcule lui-même la moyenne pondérée.

La sortie attendue devient un `reference_example` non normatif. Elle peut révéler une exigence
oubliée, mais ne rend pas incorrecte une alternative équivalente. Le juge reçoit des ancres
explicites de 0, 25, 50, 75 et 100 et l’interdiction de récompenser le recouvrement lexical, la
verbosité, l’assurance du ton ou l’identité du modèle.

Lorsqu’il déclare une défaillance critique, réservée à un défaut capable d’invalider le résultat,
le serveur plafonne la pertinence à 50 %. Une bonne forme ou des qualités secondaires ne peuvent
ainsi masquer un non-respect majeur de l’objectif ou d’une contrainte essentielle.

La similarité structurelle à la référence reste persistée comme diagnostic
`reference_similarity`, sans participer au pourcentage de pertinence. Si le candidat échoue, le
cas vaut 0 %. Si le juge échoue, le cas n’a pas de score sémantique, le run devient `partial` et sa
couverture de jugement est affichée ; aucune similarité stricte ne remplace la note absente.

## Conséquences

- Plusieurs bonnes réponses peuvent obtenir une forte pertinence sans ressembler à la référence.
- Le pourcentage mesure l’alignement au besoin par dimensions, pas une distance textuelle.
- Les versions historiques v1 et v2 restent interprétables grâce au snapshot du barème.
- Le détail du juge, les poids, ses échecs et la couverture des cas restent auditables.
- Une rubrique ou un modèle juge peut encore être biaisé : les scores doivent être étalonnés sur
  des cas notés par des humains, les désaccords revus et le juge benchmarké périodiquement.
- Les datasets doivent contenir cas nominaux, alternatives valides, frontières, contradictions,
  entrées incomplètes et sorties dangereusement plausibles afin de détecter les dérives utiles.

## Preuves dans le code

`back/app/lab/mechanism_rubrics.py`,
`back/app/lab/mechanism_evaluation_service.py`,
`back/app/lab/tests/test_evaluation.py` et
`front/app/lab/components/MechanismEvaluationTab.vue`.

La spécification détaillée, les formules, les rubriques, le protocole d’étalonnage et les limites
se trouvent dans [Architecture et théorie d’évaluation du Lab IA](../../docs/fr/architecture/ai-lab-evaluation.md).
Le parcours d’interface se trouve dans le [guide opérateur](../../docs/fr/user/lab-ai.md).
