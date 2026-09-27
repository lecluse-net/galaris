# ADR 0036 — Exécution cohérente `high` avant planification

- Statut : Accepted
- Date : 2026-08-15

## Contexte

Le dispatcher associait trop facilement la difficulté à la planification. Une demande portant sur
un livrable unique pouvait être envoyée vers `PLAN` dès qu'elle mentionnait des phases de recherche,
production, validation et livraison. Cette fragmentation augmente le coût d'orchestration, dilue le
contexte créatif ou technique entre les feuilles et peut optimiser les étapes locales au détriment
de la qualité globale du résultat.

Le pipeline possède déjà une autre réponse aux tâches difficiles : `EXEC high`. Pour le driver
interne, cette route déclenche un briefing concis avant une exécution qui conserve la responsabilité
de bout en bout du livrable.

## Décision

Le dispatcher distingue désormais la difficulté de la décomposabilité :

- `EXEC standard` traite une action petite, autonome et peu risquée ;
- `EXEC high` est préféré pour un résultat ou livrable cohérent, même lorsque sa réalisation exige
  plusieurs outils ou des passes de recherche, construction, raffinement, vérification et
  livraison ;
- `PLAN` exige au moins deux unités significatives et indépendamment exécutables, dont les résultats
  durables bénéficient de checkpoints, spécialisation, fan-out/fan-in, récupération ou coordination.

Une longue exécution, plusieurs appels d'outils ou les phases du cycle de vie d'un même artefact ne
suffisent pas à sélectionner `PLAN`. En cas d'ambiguïté entre `EXEC high` et `PLAN`, le dispatcher
choisit `EXEC high`. Un `forced_route` explicite conserve son autorité dans les limites déclarées
par le driver.

Le dispatcher choisit toujours seulement la route et l'effort. Il ne décide pas directement du
briefing : `DriverPipelinePolicy` reste l'autorité, et active automatiquement le briefing interne
pour `high`. Le driver Hermès conserve sa politique sans briefing Galaris.

## Conséquences

- Les exécuteurs conservent plus souvent une vision de bout en bout des livrables cohérents.
- Le planner devient un mécanisme de coordination de travaux décomposables, pas un synonyme de
  difficulté ou de durée.
- Les décisions restent observables dans `DispatchResult` : route et effort choisis, driver,
  routes autorisées et politique de pipeline appliquée.
- Le Lab Dispatcher demeure la surface de comparaison des modèles et jeux de cas ; les benchmarks
  doivent inclure des livrables uniques complexes attendus en `EXEC high` et des travaux réellement
  indépendants attendus en `PLAN`.

## Preuves dans le code

`back/app/agent/dispatcher.py`, `contracts.py`, `workflow.py`,
`tests/test_dispatcher_planning.py`, `docs/fr/architecture/flows/agent-execution.md` et
`docs/fr/dev/README.md`.

## Précision du 27 septembre 2026 — lots autonomes et cohérence logique

La préférence pour `EXEC high` en cas de doute ne doit pas assimiler tout objectif global à
un livrable indivisible. `PLAN` est préféré lorsque plusieurs livrables peuvent être terminés,
vérifiés et repris séparément et que leur coordination apporte un bénéfice concret, même avec
une méthode commune, un suivi partagé ou un ordre séquentiel imposé. Si la séparation ou son
bénéfice est incertain, la préférence reste `EXEC high`. Aucun seuil de volume ou de probabilité
n'est ajouté.

Les chapitres, brouillons, notes de recherche et passes de revue d'un même document ne deviennent
pas des livrables autonomes parce qu'ils sont sauvegardés séparément. Les travaux dont les
décisions tardives imposent de reprendre les parties précédentes pour préserver la cohérence
restent ensemble. Un petit traitement mécanique reste `EXEC standard`.

Le prompt est consommé par le dispatcher Task, ses chemins texte et décision spécialisée, et
le Lab Dispatcher. Les datasets Lab conservent leur prompt figé ; une comparaison doit choisir
explicitement les versions avant/après. Les garanties à préserver sont les choix autorisés par
le harnais, les forçages explicites, l'effort high de PLAN, l'absence de replanification des
enfants et le profil conversationnel distinct. Les transitions et la reprise ne changent pas.

Le corpus synthétique `back/app/lab/dispatcher_boundaries_corpus.json` contient les cas positifs
et leurs contre-exemples. Les tests de contrats et d'import ne prouvent pas un gain de routage :
celui-ci doit être mesuré dans le Lab avec le même modèle et des répétitions, en distinguant
les PLAN manqués des PLAN abusifs sur un livrable cohérent.
