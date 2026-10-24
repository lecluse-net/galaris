# Répartition des modèles entre conversation, supervision et exécution

- Statut : `design`
- Date : 2026-10-11.
- Nature : programme de recherche, benchmarks et conception progressive ; architecture à décider.
- Intention : conserver le modèle conversationnel actuel, mesurer l'intérêt d'un gros modèle
  superviseur et de petits modèles exécutants, avec recours à un exécuteur puissant.
- Aucune campagne exécutée ni modification du runtime par la création de ce plan.

## Garantie recherchée et hypothèses

Réduire le coût et, si possible, le délai des tâches effectivement réussies, sans dégrader
leur qualité, leurs effets vérifiés, leurs droits ni la réactivité conversationnelle.
Le modèle de conversation et son comportement constituent une référence à préserver.
Un changement de modèle de conversation ne fait pas partie de cette étude.

L'hypothèse centrale est qu'un modèle puissant peut concentrer son raisonnement sur la
stratégie, le contrôle et la récupération, tandis qu'un modèle plus petit réalise une
part importante des missions bornées. Elle doit pouvoir être réfutée par les mesures.
La capacité à produire un appel d'outil valide ne prouve ni la bonne sélection des actions,
ni la maîtrise d'une longue trajectoire, ni la détection d'un résultat incorrect.

Questions à instruire : quelles familles sont délégables, quelle granularité de mission,
quelles informations transmettre, quand contrôler, quand reprendre avec un gros modèle,
et à partir de quel volume le coût de coordination absorbe-t-il le gain ?
« Petit » et « gros » désignent des candidats à qualifier par capacités, coût et latence ;
la taille en paramètres, lorsqu'elle est publique, ne suffit pas à les classer.

## Socle observé et écart à concevoir

Sources : [flux d'exécution](../../docs/fr/architecture/flows/agent-execution.md),
[états](../../docs/fr/architecture/state-machines.md),
[usages des modèles](../../back/app/llm/model_usages.py),
[résolution](../../back/app/agent/model_resolver.py),
[contrat du planner](../../back/app/agent/planner_contracts.py) et
[service du planner](../../back/app/agent/planner_service.py).

| Contrat actuel | Conséquence pour l'étude |
|---|---|
| Conversation et dispatcher texte partagent `low`, avec une sélection Décision facultative pour le dispatcher. | Garder la conversation fixe ; isoler l'effet d'un changement de routage. |
| Exécuteur courant et suivi des Goals partagent `standard`. | Un petit exécuteur ne doit pas modifier implicitement le jugement des Goals. |
| Planner, synthèse du plan, exécuteur `high` et Lab partagent `high`. | Distinguer les rôles avant de proposer une configuration permanente. |
| Les feuilles ont un effort `standard` ou `high` ; le plan active une seule feuille à la fois. | Tester le choix par mission ; ne pas attribuer à l'architecture actuelle un parallélisme absent. |
| Une feuille `BLOCKED:` peut déclencher une récupération bornée ; le parent synthétise les résultats. | Une préparation et une synthèse ne constituent pas une vérification continue des effets ou de la qualité. |
| Le modèle et son effort de raisonnement sont figés avant chaque run. | Une escalade doit avoir une frontière durable explicite, sans substitution cachée dans le driver. |

Les tests de résolution, dispatcher, planner, checkpoints et contrats de drivers sont
recensés dans le [catalogue fonctionnel](../../docs/fr/dev/functional-tests.md).
Le [Lab](../../docs/fr/architecture/ai-lab-evaluation.md) compare déjà plusieurs mécanismes,
dont les exécuteurs. Ses outils d'enregistrement sans effet permettent des essais ciblés ;
ils ne qualifient pas seuls une tâche complète avec persistance, reprise et livraison.
Inventorier précisément les extensions nécessaires avant de créer une infrastructure parallèle.

## Variantes à comparer

La référence A reproduit le système réellement configuré au début de la campagne,
y compris son routage et ses éventuels plans. Un gros exécuteur direct peut servir
de témoin supplémentaire ; il ne remplace pas arbitrairement cette référence.

| Variante | Répartition | Question isolée |
|---|---|---|
| A — Référence | Configuration actuelle figée. | Qualité, coût et délai de départ. |
| B — Petit exécuteur | Même orchestration, exécuteur moins coûteux sur les missions retenues. | Le changement de modèle suffit-il ? |
| C — Supervision aux étapes | Gros superviseur, petit exécuteur, contrôles aux frontières de mission. | La supervision apporte-t-elle un gain net par rapport à B ? |
| D — Supervision et escalade | C avec reprise explicite par un exécuteur puissant. | Quelle couverture gagne-t-on et à quel coût ? |

Introduire les variantes progressivement. Pour B, publier séparément les missions
réellement confiées au petit modèle et les tâches restées sur le gros modèle.
Comparer d'abord une même mission ou un même plan figé, puis la chaîne complète où
la décomposition peut varier. Ces deux expériences répondent à des questions différentes.

Après un premier résultat, ablations ciblées : contrôle final seul, contrôle à chaque
mission, contrôle déclenché par événements ; contexte complet ou sélectionné ; granularité
plus fine ou plus large ; vérification déterministe seule ou complétée par un superviseur.
Faire varier modèle et effort de raisonnement séparément, sur les niveaux réellement
supportés. Ne pas lancer une grille exhaustive sans budget ni hypothèse précise.

## Corpus et niveaux de benchmark

Tous les jeux versionnés sont entièrement synthétiques, avec état initial, objectif,
contraintes, effets attendus et vérificateur indépendant du compte rendu du candidat.
Séparer développement, calibration et holdout par famille et provenance de génération,
pas seulement par reformulation. Inclure FR/EN et publier la couverture effective.

| Niveau | Cas et preuves attendues |
|---|---|
| Appels et décisions | Choix d'outil, arguments, références canoniques, valeurs manquantes, sorties malformées et erreurs structurées. |
| Missions bornées | Recherche puis extraction, transformation d'un document ou dataset, mutation contrôlée, vérification du résultat ; un à plusieurs outils. |
| Tâches complètes | Découverte, travail sur plusieurs ressources, synthèse, livraison et reçus ; dépendances et contexte qui évolue. |
| Difficultés cognitives | Ambiguïté, sources contradictoires, diagnostic, choix entre hypothèses et rédaction exigeante ; déterminer quand exécuter directement avec le gros modèle. |
| Défaillances | Faux succès, omission discrète, blocage non signalé, résultat partiel, outil indisponible, réponse tardive, interruption et effet distant incertain. |
| Charge et interaction | Plusieurs tâches avec conversation simultanée, saturation du fournisseur, contexte long et réouverture/reprise. |

Commencer par un parcours complet vérifiable : lire un jeu de documents synthétiques,
extraire les données, produire un dataset et un document récapitulatif, puis vérifier
exhaustivité, valeurs, références et livraison. Ajouter ensuite les autres familles.
La qualité d'une synthèse ne compense pas l'absence d'un artefact ou d'un effet demandé.

Combiner trois niveaux de preuve : essais sans effet du Lab, outils avec état dans une
infrastructure isolée réinitialisable, puis parcours assemblés en développement avec
fournisseurs réels. Les doubles remplacent les frontières externes, pas les services
internes dont on prétend vérifier le workflow. Aucun benchmark ne rejoue d'effets sur
des ressources de production.

## Protocole de comparaison

Figer pour chaque campagne : révision du code, corpus et vérificateurs, modèles exacts
ou alias avec date et limite de reproductibilité, providers, harnais et capacités,
prompts/skills/outils, droits, mémoire, budgets, niveaux de raisonnement, contexte,
politique de contrôle/escalade, concurrence et conditions de cache.

Réinitialiser l'état entre variantes ; apparier les mêmes cas et alterner ou randomiser
l'ordre. Séparer essais à froid, essais avec cache et essais sous charge. Répéter les
cas pour mesurer la variabilité sans présenter leurs répétitions comme des situations
indépendantes. Les branches de reprise doivent rester comparables et leurs coûts visibles.

Un pilote détermine dispersion, couverture manquante et taille de campagne nécessaire.
Fixer ensuite, avant le holdout, le nombre de cas/répétitions, les marges de non-infériorité
par dimension, le gain économique minimal et les conditions d'arrêt. Les valeurs restent
à arbitrer ; aucun pourcentage d'économie ni seuil de réussite n'est présumé acquis.
Rapporter les différences appariées et leur incertitude en tenant compte des familles
et répétitions ; conclure « indéterminé » lorsque la puissance ou la couverture manque.

L'évaluation indépendante utilise d'abord les états, artefacts et reçus, puis des rubriques
étalonnées humainement pour les résultats ouverts. Masquer l'identité du candidat lors
de la revue. Distinguer le superviseur qui participe à la tâche du juge qui mesure sa
réussite ; l'auto-évaluation ne constitue pas la référence. Réutiliser les travaux du
[plan Lab](lab-evaluation-mecanismes-ia.md) pour l'étalonnage et l'incertitude.

## Mesures et décision

| Dimension | Mesure |
|---|---|
| Réussite réelle | Objectif et contraintes satisfaits, états/artefacts/reçus vérifiés ; résultats par famille, longueur et langue. |
| Fiabilité de supervision | Succès incorrect accepté, résultat correct rejeté, anomalie détectée, récupération réellement réussie. |
| Coût de fonctionnement | Tous les appels de préparation, exécution, supervision, synthèse, correction et escalade ; tentatives échouées incluses. |
| Coût par réussite | Coût total de la campagne de fonctionnement divisé par le nombre de tâches vérifiées réussies ; sans réussite, ratio non calculable. |
| Délai | Admission, attente, première sortie utile, contrôle, reprise et fin vérifiée ; p50/p95 avec taille d'échantillon et incertitude. |
| Coordination | Nombre de missions, appels, contrôles, escalades, boucles, tokens transmis et informations perdues entre rôles. |
| Ressources | Débit sous charge, mémoire/contexte, calcul local et coût d'hébergement amorti selon hypothèses publiées ; un modèle local n'est pas gratuit. |
| Conversation | Délai et qualité sur les scénarios de référence pendant les tâches ; réponses cohérentes avec leur état durable. |

Séparer coût de fonctionnement et coût du benchmark, dont les juges et la revue humaine.
Publier aussi le coût d'exploitation et les dépendances supplémentaires introduites.
Évaluer l'escalade par taux, pertinence, réussite et part du coût total ; une reprise
systématique par le gros modèle ne prouve pas l'intérêt du petit exécuteur.

Aucune moyenne favorable ne compense une nouvelle défaillance critique de droits,
perte de données, répétition d'effet ou succès mensonger sur un effet requis.
L'absence d'incident observé reste une preuve bornée au corpus, pas une garantie universelle.
Décider par famille : adopter, réserver à certains cas, conserver l'exécution puissante
directe, abandonner la variante ou poursuivre faute de preuve. Chercher le compromis
qualité/coût/délai plutôt qu'un unique classement global.

## Conception candidate, après les premières mesures

La supervision doit porter sur des missions utiles, pas sur chaque token ou appel par
défaut. Préciser un contrat versionné comprenant objectif, contraintes, références
autorisées, contexte nécessaire, preuve de réussite et conditions d'arrêt/escalade.
L'exécuteur rend les artefacts, reçus, vérifications et inconnues ; le superviseur peut
consulter les sources utiles plutôt que dépendre uniquement de ce résumé.

Arbitrages à documenter avant implémentation durable :

- Rôles configurables ou paliers partagés ; compatibilité des profils existants, des
  Goals, du Lab, des commandes explicites et des efforts hérités par les descendants.
- Contrôles avant effet lorsque nécessaire, aux frontières de mission et à la fin ;
  responsabilités respectives du code, du superviseur et de l'exécuteur.
- Droit du superviseur de modifier la suite d'un plan, granularité de délégation et
  stratégie pour les tâches cohérentes qui se décomposent mal.
- Reprise après escalade : frontière du nouveau run, état figé, résultats déjà acquis,
  compatibilité des checkpoints, outils interrompus et effets incertains.
- Budgets cumulés de coût, durée, contrôles et escalades ; arrêt explicite en cas
  d'épuisement, sans boucle de correction indéfinie.
- Indisponibilité du superviseur ou d'un modèle : repli explicite autorisé, attente
  ou échec ; aucun fournisseur ni second modèle choisi silencieusement par un driver.

`app.agent` garde la politique et la résolution ; `app.task` garde transitions, leases
et tentatives ; `app.harness` exécute le contrat ; `app.llm` garde l'inférence et les coûts.
Le superviseur n'accorde pas de droits supplémentaires. Préserver les URI canoniques,
documents existants, ACL, autorisations ponctuelles et reçus de livraison.
Une réussite terminale publiée reste immuable : l'acceptation d'une mission par la
supervision doit intervenir avant sa publication, ou avoir un état durable distinct
explicitement conçu. Une escalade ne doit jamais rejouer automatiquement un effet incertain.

Qualifier d'abord le harnais interne ; les autres drivers exigent leur propre preuve
de capacité et de reprise. Ne pas imposer PLAN aux drivers qui ne le déclarent pas.
La voix temps réel et le parallélisme de feuilles restent hors premier prototype.

## Lots, dépendances et preuves de sortie

| Lot | Livrable | Condition pour poursuivre |
|---|---|---|
| 0 — Cadrer | Inventaire des consommateurs, référence active, hypothèses, questions ouvertes et protocole budgété. | Familles, garanties et critères de décision identifiés ; aucun changement de configuration active. |
| 1 — Mesurer les exécuteurs | Corpus initial, vérificateurs et campagne A/B sur missions puis premier parcours complet. | Enveloppe de compétence du petit modèle mesurée ; échecs et coûts reproductibles. |
| 2 — Prototyper la supervision | Variante C isolée, contrats de mission et contrôles aux étapes, essais de faux succès. | Gain ou absence de gain face à B établi ; coût du contrôle et erreurs du superviseur connus. |
| 3 — Qualifier l'escalade | Variante D, budgets, arrêt, reprise et tests de panne/concurrence. | Aucun double effet dans les scénarios testés ; couverture, coût et intérêt de l'escalade mesurés. |
| 4 — Arbitrer l'architecture | Holdout, charge, revue humaine et comparaison par famille ; ADR si choix structurel. | Conclusion adoptable/rejetée/indéterminée avec limites ; représentation des rôles justifiée par les résultats. |
| 5 — Intégrer progressivement | Configuration compatible, observabilité, guides FR/EN, activation réversible et surveillance. | Parcours assemblés et drivers concernés qualifiés, repli/rollback prouvés et validation complète avant publication. |

Les lots peuvent revenir en arrière. Aucun calendrier de livraison n'est fixé avant
le pilote. Chaque campagne a un budget et une revue ; les benchmarks réels ne sont
pas déclenchés par l'écriture de ce plan.

Le [plan Lab](lab-evaluation-mecanismes-ia.md) possède les mécanismes communs de comparaison,
pas la décision d'architecture de cette étude. Articuler le contrat de mission avec le
[contrat de portée/provenance](../decisions/0170-execution-scope-and-durable-controls.md),
complété par les [cibles contextuelles](../decisions/0206-contextual-task-write-targets.md), et les mesures sous
charge avec l'[ordonnancement par fournisseur](ordonnancement-llm-par-fournisseur.md).
Les extensions du Lab et de l'ordonnancement ne sont pas présumées réalisées ni des
prérequis à tout essai isolé.
L'étude ne dépend pas d'un entraînement LoRA ni de l'achat de matériel.

Pour les futurs changements de runtime, renforcer les tests existants du contrat affecté,
puis exécuter tests ciblés, typecheck, architecture et validation proportionnée.
Les mesures avec fournisseurs réels restent distinctes des tests de transport simulé.
Conserver diagnostics bruts sous `artifacts/` ou hors dépôt ; les rapports versionnés
contiennent protocole, agrégats, conclusions et limites, sans données individuelles ni secrets.

## Suivi et clôture

Chaque revue conserve les hypothèses encore ouvertes, les campagnes et leurs références,
les résultats par famille, la décision et le prochain lot utile. Requalifier les candidats
après changement matériel de modèle, harnais, outils ou protocole ; ne pas mélanger les séries.
Transférer les contrats acceptés vers les décisions et la documentation, les protections
vers les tests et les campagnes communes vers le Lab. Mettre à jour le statut dans l'index.

Clore ou réduire l'étude si le gain est absent, si le coût de supervision/reprise domine,
si les erreurs passent trop souvent le contrôle ou si une solution plus simple apporte
le même résultat. Une conclusion limitée à certaines familles est une issue acceptable.

## Références de discussion

- [Building effective agents — Anthropic](https://www.anthropic.com/engineering/building-effective-agents) : orchestration, routage et évaluation.
- [Small Language Models are the Future of Agentic AI](https://arxiv.org/abs/2506.02153) : hypothèse de systèmes hétérogènes et usages spécialisés des petits modèles.
- [Multi-agent research system — Anthropic](https://www.anthropic.com/engineering/multi-agent-research-system) : bénéfices et coûts de coordination dans un domaine particulier.

Ces références motivent les expériences ; elles ne prouvent aucun gain dans Galaris.
Revalider leur version et les capacités des candidats au lancement des campagnes.
