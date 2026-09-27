# Modèles de décision — qualification et extensions restantes

- Statut : `partial`
- Revue documentaire : 2026-09-27
- Contrats courants : [0127](../decisions/0127-optional-dispatcher-decision-model.md),
  [0129](../decisions/0129-shared-decision-model-workflows.md) et
  [0130](../decisions/0130-live-message-topic-decisions.md).

## 1. Qualification comparative des usages

Mesurer les gains du modèle spécialisé face au chemin texte sur les mêmes cas synthétiques
FR/EN, avec répétitions et corpus de qualification séparé du réglage. Le pilote dispatcher
rapporté dans 0129 ne possède ni témoin texte ni répétitions suffisantes pour cette comparaison.

| Usage | Preuve restante |
|---|---|
| Dispatcher et porte des pairs IA | Exactitude route/effort/langue, escalades inutiles, sous-estimation de l'effort et coût jusqu'au début du travail utile |
| Topics des messages et Tasks | Continuité, changement de sujet, réemploi, création pertinente et coût de la rédaction éventuellement nécessaire |
| Rétention mémoire | Aucun fait durable perdu par `ignore` ou `link`, notamment pour les faits mêlés, nouveaux ou contradictoires |
| Dédoublonnage mémoire | Équivalence complète, faux rattachements et conservation des informations distinctes |
| Classement parallèle des messages | Latence de disponibilité du topic et impact sur les traitements concurrents, sans ralentir l'admission |

Réutiliser les candidats et bindings hybrides du Lab existant. Les campagnes de candidat
sans repli et les observations du système complet avec repli répondent à des questions
séparées ; publier la provenance de chaque mesure. La qualification distante des nouveaux
usages avec Jev reste ouverte.

Mesurer préparation, persistance, attente du worker, transport, inférence, validation et
application, puis p50/p95, coûts physiques et taux de repli. Pour les parcours hybrides,
compter aussi les appels de rédaction : une décision suivie d'une rédaction ne garantit
pas un gain global. Inclure ambiguïtés, ordre des options, contenu adversarial et erreurs
fournisseur ; une campagne incomplète ne devient pas une bonne note.

Réception : gain de bout en bout à qualité métier acceptable sur un holdout, avec limites
publiées et aucun effet réel rejoué. Les mesures utilisateur complètes sont coordonnées avec
la [fiabilisation conversationnelle](fiabilisation-conversationnelle.md) ; étalonnage,
comparabilité et gardes relèvent du [plan du Lab](lab-evaluation-mecanismes-ia.md).

## 2. Optimisations conditionnées par les mesures

- Évaluer la réutilisation des clients HTTP et connexions OpenRouter, les attentes du worker
  et la concurrence bornée ; mesurer débit et impact sur les autres traitements sous charge.
- Ajuster une politique d'incertitude seulement après qualification par usage, modèle,
  version et langue ; une confiance absente reste absente.
- Étudier un coupe-circuit de disponibilité uniquement si les campagnes en montrent le besoin.
- Fixer les objectifs chiffrés de latence, d'erreurs métier et d'impact sur le modèle texte à
  partir des comparaisons, sans ajouter de double appel spéculatif systématique.

Préserver les courts-circuits déterministes, le gel des modèles, les droits, l'annulation,
les budgets, le journal et les coûts. Ne pas réintroduire les plafonds pilotes de 10/30 s
supprimés par 0129. Aucun cache sémantique de décisions n'est prévu dans ce périmètre.

## 3. Extensions différées

- API TypeSafe directe et adaptateurs locaux, dont Laya ; services Docker spécialisés,
  essais CPU/GPU, démarrage à froid, contention et entraînement.
- Classement de ressources, compétences et outils ; usages Goal, planner et briefing,
  seulement après démonstration qu'une décision fermée évite un travail génératif utile.
- Primitives booléennes ou ordinales lorsqu'un consommateur concret et sa sémantique de
  repli les justifient ; le contrat courant reste le choix fermé.

Un fournisseur supplémentaire implémente le port public de décisions sans modifier le
workflow métier. Préserver le fonctionnement texte lorsque la sélection spécialisée est
vide et l'absence de fournisseur cloud implicite. Les contrats et conditions des candidats
externes devront être revérifiés au moment de reprendre leur conception.

## 4. Validation et clôture

Renforcer les garanties existantes dans `test_decision_inference.py`,
`test_decision_workflows.py`, `test_live_topic_decisions.py` et les suites Dispatcher,
profils et Lab. Les tests à transport simulé couvrent les branchements et les effets durables ;
ils ne remplacent pas les campagnes comparatives avec le fournisseur réel.

Pour toute extension : premier parcours complet, refus d'accès, concurrence, arrêt avant
repli, réponse tardive, crash, reprise, coûts et relecture. Les changements de contrat
s'accompagnent de tests et des contrôles Make appropriés ; toute publication requiert
`make validate` sur l'instantané final.

Clôturer lorsque les campagnes retenues sont publiées et les extensions livrées, transférées
ou explicitement abandonnées. Le catalogue, le profil, l'adaptateur OpenRouter, l'inférence
durable et les branchements métier réalisés restent documentés dans les ADR ci-dessus.
