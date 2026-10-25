# Répartition des modèles entre conversation, supervision et exécution

- Statut : `design`
- Création : 2026-10-11 ; revue du code, des tests et des preuves versionnées : 2026-10-25.
- Nature : programme de recherche, benchmarks et conception progressive ; architecture à décider.
- Intention : conserver le modèle conversationnel actuel, mesurer l'intérêt d'un gros modèle
  superviseur et de petits modèles exécutants, avec recours à un exécuteur puissant.
- Le socle d'expérimentation est en partie réalisé ; la supervision LLM et l'escalade
  automatique entre modèles restent à concevoir. Aucune campagne A/B/C/D identifiée dans
  les preuves versionnées consultées. La comptabilité par appel est implémentée dans
  [0238](../decisions/0238-physical-call-cost-evidence.md), sans activer la supervision ni lancer de modèle.

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
| Une feuille `BLOCKED:` peut déclencher une récupération bornée ; le parent synthétise les résultats. | Ce mécanisme n'est pas un superviseur contrôlant chaque résultat ni une politique d'escalade entre modèles. |
| Le planner contrôle déjà certains artefacts et reçus avant de terminer ; la livraison des tâches conversationnelles appartient au contrôleur de conversation. | Réutiliser ces preuves et leur propriétaire ; elles ne vérifient pas seules l'exhaustivité et la qualité sémantique. |
| Le modèle et son effort de raisonnement sont figés avant chaque run. | Une escalade doit avoir une frontière durable explicite, sans substitution cachée dans le driver. |

Les tests de résolution, dispatcher, planner, checkpoints et contrats de drivers sont
recensés dans le [catalogue fonctionnel](../../docs/fr/dev/functional-tests.md).
Le [Lab](../../docs/fr/architecture/ai-lab-evaluation.md) compare déjà plusieurs mécanismes,
dont les exécuteurs. Ses outils d'enregistrement sans effet permettent des essais ciblés ;
ils ne qualifient pas seuls une tâche complète avec persistance, reprise et livraison.
Réutiliser ce socle avant d'ajouter les extensions décrites ci-dessous.

## Acquis réutilisables et limites au 25 octobre 2026

Le statut `design` porte sur la nouvelle répartition supervision/exécution. Les briques
communes ci-dessous existent déjà ; leur présence ne démontre pas le gain de cette architecture.
La revue initiale a lu les tests sans rejouer les campagnes. La tranche de comptabilité
0238 ajoute ses vérifications ciblées ; elle ne qualifie aucun candidat LLM.
L'état décrit est celui du dépôt de travail consulté ; il ne prouve aucun déploiement.

| Acquis constaté | Preuve et limite pour cette étude |
|---|---|
| Choix `standard`/`high` par feuille, brief, critères de réussite, outils autorisés et exécution séquentielle. | `planner_contracts.py`, `planner_service.py`, `test_planner_service.py` et `test_planner_collections.py` sous `back/app/agent/`. Pas de verdict de supervision avant la feuille suivante ; une réussite ordinaire fait avancer le curseur. |
| Récupération `BLOCKED:` bornée, vérification de présence d'artefacts et rapprochement des reçus de livraison. | `back/app/agent/tests/test_planner_service.py` couvre récupération unique, fichier manquant, reçu absent et destination durable exacte. Ce contrôle déterministe ne remplace pas un vérificateur du contenu demandé. |
| Portée/provenance, préflight durable, working set et contrat de checkpoint par driver. | ADR [0170](../decisions/0170-execution-scope-and-durable-controls.md), [0206](../decisions/0206-contextual-task-write-targets.md), `back/app/task/tests/test_execution_scope.py` et `back/app/agent/tests/test_checkpoint_contract.py`. Une reprise de checkpoint existante ne prouve pas sa portabilité vers un autre modèle. |
| Lab `task_executor`, `conversation_executor` et `voice_executor`, candidat et juge distincts, snapshots, répétitions, budgets et rejugement sans régénération du candidat. | `back/app/lab/tests/test_contracts_and_passes.py` et `test_stability_and_review.py`. Le budget de campagne peut être dépassé par l'évaluation déjà engagée ; il n'est pas un plafond cumulé de Task supervisée. |
| Corpus FR/EN de capacités, décisions et transfert ; outils simulés avec schémas natifs, réponses ciblées, relecture du contenu écrit et contrôles indépendants des déclarations du modèle. | [Corpus de référence](../../docs/fr/dev/lab-reference-corpus.md), `back/app/lab/tests/test_reference_corpus.py` et `test_executor_outcomes.py`. Les refus, révisions, valeurs JSON, pertes de faits et faux succès sont testables ; l'état simulé reste local au cas, sans persistance métier réelle. |
| Comparaison de runs, couverture, régressions critiques/dimensionnelles et médianes appariées coût/durée/première sortie ; étalonnage humain et incertitude par cas. | `back/app/lab/comparison_schemas.py`, `tests/test_comparison.py`, ADR [0230](../decisions/0230-lab-human-calibration-and-case-uncertainty.md). Pas encore de mesure complète A/B/C/D, de garde de promotion automatique ni de coût par tâche réellement réussie sur toute la chaîne. |
| Rapport API de répétabilité du juge sur sorties candidates fixes. | ADR [0236](../decisions/0236-lab-fixed-output-judge-repeatability.md), `back/app/lab/judge_repeatability.py` et son test, présents dans les changements locaux au moment de la revue. Ne pas les considérer comme publiés ; affichage dédié, campagnes représentatives et séparation des variances restent ouverts. |
| Admission partagée par fournisseur, priorité voix/texte/fond, capacité protégée et attente avant claim d'inférence. | ADR [0181](../decisions/0181-provider-llm-admission.md), `back/app/llm/provider_scheduler.py` et `tests/test_provider_scheduler.py`. Socle mono-worker ; provenance exhaustive, transports non tracés, coordination multi-backend et charge réelle restent dans le [plan fournisseur](ordonnancement-llm-par-fournisseur.md). |

Le contexte d'admission typé (`back/app/llm/admission.py`), également présent dans les
changements locaux, distingue les Tasks de leur conversation d'origine et partage leur
propriétaire entre file durable et appel physique. Réutiliser ce contrat pour les futurs
appels de supervision ; ne pas leur donner la priorité conversationnelle par simple filiation.
Cette tranche ne qualifie pas la provenance de tous les demandeurs ni les transports non tracés.

Des campagnes avec fournisseur réel sont déjà documentées dans le
[guide du corpus](../../docs/fr/dev/lab-reference-corpus.md#qualification-du-24-octobre-2026)
et la [qualification conversationnelle](../audits/2026-10-24-conversation-qualification.md).
Elles comparent des consignes ou qualifient des parcours, pas la répartition de modèles
A/B/C/D. Elles montrent notamment qu'une baisse des appels ne suffit pas à établir une
baisse du coût brut. Réutiliser leurs scénarios et vérificateurs ; refixer la référence
après ces corrections et constituer une réserve indépendante, puisque ces cas publics
ont servi au réglage. Aucun résultat économique de supervision n'est acquis.

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

Étendre les corpus existants par un premier parcours complet vérifiable : lire un jeu de documents synthétiques,
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

| Lot | État de la revue | Livrable restant et condition pour poursuivre |
|---|---|---|
| 0 — Cadrer | Inventaire des paliers et socles réalisé ; référence active non relevée. | Figer configuration effective, consommateurs, hypothèses, budget et critères de décision de la campagne. Aucun changement de configuration active. |
| 1 — Mesurer les exécuteurs | Corpus et outils Lab disponibles ; comparaison de modèles et parcours complet de l'étude non démontrés. | Campagne A/B appariée sur missions puis parcours persistant. Enveloppe de compétence du petit modèle mesurée ; échecs et coûts reproductibles. |
| 2 — Prototyper la supervision | À concevoir. | Variante C isolée, contrat de mission et contrôles aux étapes. Gain ou absence de gain face à B établi ; faux succès et coût du superviseur mesurés. |
| 3 — Qualifier l'escalade | À concevoir. | Variante D, budgets, arrêt, reprise et tests de panne/concurrence. Aucun double effet dans les scénarios testés ; couverture, coût et intérêt de l'escalade mesurés. |
| 4 — Arbitrer l'architecture | Non engagé dans les preuves consultées. | Holdout, charge, revue humaine et comparaison par famille ; ADR si choix structurel. Conclusion adoptable/rejetée/indéterminée avec limites. |
| 5 — Intégrer progressivement | Conditionné à la décision. | Configuration compatible, diagnostics, guides FR/EN, activation réversible. Parcours assemblés et drivers concernés qualifiés, retour à la référence prouvé ; `make validate` reste réservé à l'utilisateur avant publication. |

### Prochaines implémentations proposées

Ordre recommandé : obtenir une comparaison exploitable avant de rendre les rôles permanents.
Ces propositions ne sont pas des fonctionnalités livrées ni un accord d'implémentation.

1. **Pilote A/B reproductible dans le Lab existant.** Ajouter un lanceur de campagne qui
   apparie les mêmes cas/répétitions, alterne l'ordre des candidats et conserve un manifeste
   commun : révision du code, références des runs, modèles exacts, reasoning, prompts, outils,
   état initial, concurrence et cache. Réutiliser snapshots et empreintes existants. Tester
   d'abord sur `task_executor` avec contrôles d'effets FR/EN, puis sur un plan figé. Choisir
   le candidat explicitement par expérience ; modifier `standard` dans le profil actif
   changerait aussi les Goals. Réception : reprise sans doublon, configuration incompatible
   signalée, aucun changement de conversation/Goals ; performances et qualité appariées.
2. **Comptabilité implémentée — ADR [0238](../decisions/0238-physical-call-cost-evidence.md).**
   Registre par appel physique, provenance/tarifs figés, échecs et reprises conservés,
   bilan Task par usage sans addition des totaux parents/enfants, coûts candidat/juge
   séparés et ratio du benchmark conditionné aux preuves. Les appels non publiés après
   perte de lease restent rapprochables, même après suppression de leur trace détaillée.
   Les anciens montants sans preuve restent inconnus ; aucune refacturation historique.
   Restent la réussite indépendante des tâches métier du point 3 et la mesure explicite
   de l'attente fournisseur ; aucune durée de file ni fin vérifiée n'est inventée.
3. **Premier scénario persistant avec vérificateur indépendant.** Réutiliser les services
   Document, Dataset, Task et livraison dans une infrastructure isolée réinitialisable pour
   le parcours documents → extraction → Dataset JSON + récapitulatif HTML → livraison.
   Vérifier valeurs, exhaustivité, ACL, révisions, artefacts et reçus depuis leur état durable.
   Injecter omission discrète, faux succès, conflit, interruption et retour tardif. Réception :
   un compte rendu plausible ou un juge favorable ne peut pas valider un effet absent ; la
   reprise conserve les effets acquis. Commencer par ce parcours avant de généraliser les mocks.
4. **Supervision expérimentale à une frontière de mission, puis escalade.** Seulement après
   le pilote, introduire dans l'orchestration `app.agent` un contrat versionné de verdict
   (accepter, demander une correction bornée, escalader, arrêter), fondé sur preuves et
   inconnues. `app.task` persiste l'attente et le verdict avant tout successeur ; conserver
   les terminaux publiés. Le superviseur ne remplace pas le juge indépendant du benchmark.
   Réception : omission détectée, verdict tardif ignoré après arrêt, contrôles/escalades
   bornés et reprise sans double effet ; comparer C à B avant d'ajouter D. La migration de
   checkpoint entre modèles exige une capacité prouvée ; sinon préparer un nouveau run depuis
   les preuves durables compatibles, après réconciliation des effets incertains.

Les points 1–3 améliorent déjà les décisions de modèle et la détection des faux succès,
même si l'étude conclut que la supervision ne paie pas. L'étalonnage, la répétabilité du
juge et les gardes communes restent dans le plan Lab ; ne pas les réimplémenter ici.

Les lots peuvent revenir en arrière. Aucun calendrier de livraison n'est fixé avant
le pilote. Chaque campagne a un budget et une revue ; les benchmarks réels ne sont
pas déclenchés par l'écriture de ce plan.

Le [plan Lab](lab-evaluation-mecanismes-ia.md) possède les mécanismes communs de comparaison,
pas la décision d'architecture de cette étude. Articuler le contrat de mission avec le
[contrat de portée/provenance](../decisions/0170-execution-scope-and-durable-controls.md),
complété par les [cibles contextuelles](../decisions/0206-contextual-task-write-targets.md), et les mesures sous
charge avec l'[ordonnancement par fournisseur](ordonnancement-llm-par-fournisseur.md).
Les socles du Lab et de l'admission fournisseur sont réalisés ; leurs extensions ouvertes
ne conditionnent pas tout essai isolé. Une garantie de conversation sous charge demande
cependant une mesure assemblée : la priorité d'admission ne préempte pas un appel actif,
notamment sur un fournisseur limité à une place.
L'étude ne dépend pas d'un entraînement LoRA ni de l'achat de matériel.

Pour les futurs changements de runtime, renforcer les tests existants du contrat affecté,
puis exécuter tests ciblés, typecheck, architecture et validation proportionnée.
Les mesures avec fournisseurs réels restent distinctes des tests de transport simulé.
Conserver diagnostics bruts sous `artifacts/` ou hors dépôt ; les rapports versionnés
contiennent protocole, agrégats, conclusions et limites, sans données individuelles ni secrets.

## Suivi et clôture

Prochaine sortie attendue : manifeste du pilote A/B, familles/candidats/budget proposés et
vérificateur du premier parcours persistant. La sélection des modèles dépendra du catalogue
et des capacités disponibles au lancement ; aucun fournisseur ni achat n'est imposé ici.

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
