# 0134 — Pilotage des Labs par les agents

Statut : accepté. Date : 2026-09-25.

## Garantie

Un agent autorisé peut piloter les onze mécanismes du Lab et le diagnostic des Tasks
avec les outils MCP natifs. Les expériences, captures, runs et campagnes restent les
mêmes objets que ceux affichés dans le Workbench. Les modifications expérimentales
ne changent pas les réglages de production.

## Décision

Le Tool intégré `lab` expose cinquante fonctions `lab_*` dans le serveur MCP existant.
Sa connexion est provisionnée inactive. L'activer délègue l'administration des Labs ;
les restrictions par fonction et par contexte du catalogue commun continuent à s'appliquer.
Chaque appel et chaque nouvelle unité de travail vérifient les autorisations courantes.
La découverte et la capture de sources réelles, ainsi que les diagnostics de Tasks,
exigent également `galaris_admin` avec ses quatre fonctions d'inspection des exécutions.
Une connexion limitée à la documentation ne remplit pas cette condition.

Le skill système `galaris-lab`, désactivé par défaut, se distribue par `app.skill` aux
harnais internes et Hermès. Il est autonome et ne confère aucun droit. Le guide général
`galaris` y renvoie. Son activation et celle de la connexion sont indépendantes.

Les commandes courtes partagent la transaction du transport : les services publient par
flush dans ce contexte, tout en conservant leurs commits pour les consommateurs HTTP
existants. `LabCommand` garde l'identité agent/Task, une clé d'invocation, l'empreinte des
arguments et la réponse. Un verrou transactionnel sérialise les doublons. Même clé et
autres arguments provoquent un conflit. Les révisions protègent les éditions ; les
captures conservent leur protocole de confirmation lié aux paramètres observés.

Les benchmarks restent exécutés par le worker Lab, avec leurs snapshots, leases et deux
passes existantes. L'auteur agent et la Task d'origine sont conservés sur le run.
La génération synthétique, la proposition d'attendus et les analyses utilisent un moteur
intégré `lab` de `app.process`. L'admission fige le modèle, son empreinte, l'effort et les
révisions pertinentes. `LabOperationResult` publie le résultat dans la transaction de
l'effet métier. Les définitions techniques de ces opérations sont exclues du catalogue
des processus personnels. Une opération interrompue après son début n'est pas relancée
aveuglément : son statut peut devenir `unknown`.

Les évaluations d'agents sont conservées dans `LabAgentReview`, liées à l'agent, à la
campagne et au résultat. Elles utilisent la rubrique figée et restent immuables. Elles
n'écrivent ni un avis humain ni le score du juge. Le Workbench les affiche avec leur
provenance. Le masquage du jugement sur la route de revue ne prouve pas que l'auteur
n'a jamais vu les scores par une autre route.

Les listes sont paginées en SQL, avec 50 éléments par défaut et les tailles
10/20/50/100/500. Les réponses sont bornées à 1 Mo ; `summary_only` et `lab_content_read`
permettent de retrouver puis lire les grandes ressources sans troncature silencieuse.
Les résultats des opérations longues possèdent aussi une continuation par caractères.
Le comparateur explicite l'axe étudié, les différences de corpus/configuration/juge,
les sorties manquantes et les appariements ambigus. Ses écarts restent descriptifs.

## Limites et validation

Le budget des benchmarks reste un seuil entre évaluations, susceptible d'être dépassé
par l'appel en cours. Les analyses et générations sont facturées séparément. Une annulation
ne garantit pas l'arrêt du fournisseur. Les reçus protègent la publication et les reprises
connues ; ils ne constituent pas une garantie de facturation distante exactement une fois.

Les tests de `app.lab.tests.test_mcp` traversent les services et la base réels, avec un
client MCP pour le transport, et remplacent les inférences externes. Ils couvrent les
onze contrats, les doublons, conflits, révocations, générations durables, comparaisons,
revues et la projection du skill. Les tests existants des captures, deux passes, budgets,
publications et revues humaines restent applicables. `lab-insights.spec.mjs` vérifie la
distinction des avis d'agents et des scores automatiques sur ordinateur et mobile.

L'étalonnage statistique, les tendances, les gardes de promotion et la qualification
avec des fournisseurs réels restent dans le plan qualité du Lab.
