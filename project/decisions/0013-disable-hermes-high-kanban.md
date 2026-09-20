# ADR 0013 — Désactivation interne du Kanban Hermès pour `high`

- Statut : Accepted
- Date : 2026-07-24

## Contexte

L’ADR 0012 associait l’effort Hermès `high` à une carte Kanban afin de profiter d’un worker
persistant, de tentatives internes et de profils partageant un tableau. Cette hypothèse ne
correspond pas au déploiement Hermès historique de Galaris : chaque agent possède son propre
conteneur et aucun profil distinct ne partage l’instance. La Task PostgreSQL fournit déjà le lease,
les tentatives, la reprise, l’annulation et l’état terminal.

Dans cette topologie, la carte ajoute un second cycle de vie sans capacité métier inaccessible au
run direct. Elle dégrade aussi le contrat d’exécution : polling au lieu du stream complet,
approbations Hermès non relayées par le worker et reconstruction provisoire des appels d’outil à
partir des `LLMCall`.

L’adaptateur Kanban peut rester isolé pour lire les anciens checkpoints, mais il ne justifie pas
une topologie de profils partageant un runtime.

## Décision

Une constante interne, `HERMES_HIGH_KANBAN_ENABLED`, vit dans
`bridge.hermes.driver`. Elle vaut `False` et n’est exposée ni dans l’environnement, ni dans
`core.params`, ni dans l’API ou l’interface d’administration. La réactivation exige donc une
modification de code, ses validations et un nouveau déploiement.

Tant que cette constante vaut `False`, la matrice est :

| Driver | `standard` | `high` | Briefing Galaris |
|---|---|---|---|
| `internal` | exécution directe | exécution directe | `high` uniquement |
| `hermes` | `/v1/runs` direct | `/v1/runs` direct avec le modèle `high` | jamais |

L’effort et le modèle restent `high` ; seule la stratégie de transport redevient directe.
`app.agent` ne porte aucune politique Kanban propre à Hermès et produit son
`AgentRunRequest` avec la stratégie directe par défaut. Le driver Hermès possède seul la bascule :
il refuse une nouvelle demande Kanban tant que la constante est désactivée et peut rétablir
Kanban pour les runs `high` si elle est réactivée.

La reconstruction des appels de fonction depuis `LLMCall.tool_calls` est gouvernée par la même
constante et n’est plus appelée par l’exécuteur direct. Celui-ci utilise le stream Hermès et sa
session persistante canonique pour les étapes de raisonnement et d’outil. Le suivi des `LLMCall`
reste utilisé séparément pour le coût et la détection d’une interruption fournisseur.

Un checkpoint qui contient déjà `execution_strategy=kanban` n’est jamais converti en run direct,
car cela pourrait rejouer des effets déjà produits et confondre un identifiant de carte avec un
identifiant `/v1/runs`. Depuis la suppression du runtime partagé par l’ADR 0058, aucune reprise
Kanban ne dispose toutefois d’un transport de management actif : elle échoue explicitement au
lieu de recréer une carte. Les checkpoints historiques sans stratégie continuent d’être
interprétés comme des runs directs.

L’adaptateur Kanban et ses tests restent présents, sans backend de management en production.
Réactiver la stratégie exigerait une nouvelle décision et une implémentation compatible avec
l’isolation d’un conteneur par agent.

## Conséquences

- Les nouvelles Tasks Hermès `high` bénéficient du modèle High, du streaming, du relais
  d’approbation et de la reprise `/v1/runs`, sans créer de carte.
- Le niveau `high` ne possède plus de cycle de vie différent de `standard`.
- Aucun paramètre opérateur, schéma ou migration n’est ajouté.
- Les instances historiques n’ont plus besoin du Kanban pour exécuter de nouvelles Tasks.
- Une ancienne carte n’est pas transformée en run direct et ne peut donc pas rejouer ses effets.
- Une future réactivation reste un choix d’architecture documenté, pas une bascule
  d’exploitation accidentelle, et ne peut pas réintroduire un runtime partagé.

## Références et preuves

- Politique : `back/bridge/hermes/driver.py`.
- Reprise et routage : `back/app/agent/facade.py` et `back/bridge/hermes/driver.py`.
- Trace : `back/bridge/hermes/executor.py` et `kanban.py`.
- Tests : `back/app/agent/tests/test_registry.py`, `test_facade.py`,
  `back/bridge/hermes/tests/test_executor_llm_tools.py` et `test_kanban_executor.py`.
