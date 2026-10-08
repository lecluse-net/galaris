# Lab IA — étalonnage, comparaisons et gardes

- Statut : `partial`
- Revue des sources : 2026-10-08. Les campagnes ne sont pas rejouées par cette revue.

## Socle réalisé

Campagnes, snapshots, comparaisons, répétitions/budgets, revue humaine et bindings hybrides
appartiennent à l'[architecture](../../docs/fr/architecture/ai-lab-evaluation.md),
au [guide](../../docs/fr/user/lab-ai.md) et aux décisions
[0078](../decisions/0078-lab-variable-and-judgment-campaigns.md),
[0082](../decisions/0082-lab-stability-human-review.md),
[0134](../decisions/0134-agent-lab-control.md).
Un score, rôle holdout ou digest ne prouve pas à lui seul étanchéité, qualité ou comparabilité.

## Lots restants

| Lot | Travail | Réception |
|---|---|---|
| Étalonnage humain | Corpus annotés par mécanisme, arbitrage justifié, biais/corrélation/faux passages du juge. | Erreur de passage mesurable contre référence humaine revue, juge/corpus/date versionnés ; panne/couverture faible sans bonne note fictive. |
| Incertitude | Intervalles adaptés au volume et aux dépendances ; variance candidat distincte de variance juge. | Répétitions d'un épisode non présentées comme observations indépendantes ; insuffisance de données visible. |
| Comparabilité/tendances | Campagnes réelles du protocole FR/EN ; politiques pour changement de rubrique/corpus/juge ; tendances dimensionnelles. | Aucun changement de référence présenté comme gain du candidat ; résultats liés aux snapshots et incertitude publiée. |
| Gardes | Baseline approuvée/remplaçable, seuils dimensionnels/globaux/erreurs/couverture, verdict machine et export CI. | Nouvelle défaillance critique bloquante malgré une moyenne meilleure ; verdict reconstructible, rapport narratif sans pouvoir de lever la garde. |
| Portabilité/gouvernance | Import/export versionné des datasets/résultats ; revue des références, rétention, gel/ouverture des holdouts. | Corpus/paramètres/provenance préservés, secrets et droits des sources respectés. |
| Jugement renforcé | Juges multiples/arbitrage si besoin mesuré ; biais de position, verbosité et auto-préférence. | Risque réduit et coût connu face au juge courant ; nombre de juges sans valeur probante propre. |

Préparer étalonnage/comparabilité, puis incertitude, avant gardes décisionnelles.
Les datasets versionnés restent entièrement synthétiques. Une revue masquée ne supprime
pas l'exposition passée aux réponses.

## Campagnes de modèles de décision regroupées

Le plan `modeles-decision.md` est absorbé ici : catalogue, profil, adaptateur et workflows
sont réalisés dans
[0127](../decisions/0127-optional-dispatcher-decision-model.md),
[0129](../decisions/0129-shared-decision-model-workflows.md) et
[0130](../decisions/0130-live-message-topic-decisions.md).
Le pilote dispatcher sans témoin texte ni répétitions suffisantes ne conclut pas la comparaison.

Comparer spécialisé/texte sur mêmes cas FR/EN, configuration figée, répétitions et holdout ;
qualifier Jev réel séparément du transport simulé.

| Usage | Mesure spécifique |
|---|---|
| Dispatcher / pairs IA | Route, effort, langue, escalades inutiles et délai jusqu'au début utile. |
| Topics messages/Tasks | Continuité, frontières, réemploi et créations pertinentes. |
| Rétention | Aucun fait durable perdu par ignore/link, surtout mêlé, nouveau ou contradictoire. |
| Déduplication | Équivalence complète, faux rattachements et informations distinctes préservées. |
| Classement parallèle | Topic disponible sans ralentir l'admission ni les traitements concurrents. |

Séparer candidat sans repli et système avec repli ; compter aussi les appels de rédaction.
Mesurer préparation, persistance, attente, transport, inférence, validation/application,
p50/p95, coûts et taux de repli. Inclure ambiguïté, ordre d'options, contenu adversarial,
erreurs et arrêt avant repli ; réponses tardives/crash/relecture sans double effet.

Optimisations seulement après mesure : clients/connexions réutilisés, attente/concurrence
bornée, politique d'incertitude par usage/version/langue, coupe-circuit si besoin.
Pas de double appel spéculatif systématique ni cache sémantique de décision.
Préserver choix texte quand sélection vide, budgets et absence de provider implicite.

Les adaptateurs directs/locaux différés sont conservés dans la
[convergence SDK](convergence-pydantic-ai.md).
Usages supplémentaires (ressources/skills/outils, Goal/planner, booléens/ordinaux)
restent des expériences à justifier par une décision fermée évitant un travail génératif utile.

## Mesures communes et clôture

Le [protocole délai/coût/qualité](../../docs/fr/dev/lab-reference-corpus.md#campagne-délai-coût-et-qualité)
mesure le Lab ; son admission simulée ne qualifie pas le transport utilisateur.
Le [plan conversationnel](fiabilisation-conversationnelle.md) possède cette mesure complète,
et le [plan mémoire](amelioration-globale-memoire.md) les questions de rappel.

Réutiliser suites de décisions, workflows/Topics et Lab recensées dans le
[catalogue fonctionnel](../../docs/fr/dev/functional-tests.md).
Publier les campagnes et limites, retirer les lots démontrés ou transférés.
Une recette fournisseur ordinaire ne justifie pas de conserver un plan d'implémentation terminé.
