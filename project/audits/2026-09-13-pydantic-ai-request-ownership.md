# Appels internes Pydantic AI — preuves des deux premiers lots

Date : 2026-09-13. Périmètre : [ADR 0095](../decisions/0095-pydantic-ai-request-ownership.md).
La [convergence complète](../plans/convergence-pydantic-ai.md) reste en cours.

## Exécutions du premier lot

| Vérification | Résultat observé |
|---|---|
| Reproduction `test_chat_sdk_applies_profile_before_internal_transport` avant correction du constructeur | Rouge : le constructeur copié ignorait la restriction de sampling du profil SDK |
| `make tests-providers`, état final du transport | **1 075 réussis** ; JUnit `artifacts/provider-contracts.xml` |
| Matrice paramètres + modèle interne + utilitaires LLM, derniers ajustements | **938 réussis** |
| `app/llm/tests app/harness/tests app/agent/tests app/goal/tests` | **736 réussis, 1 échec indépendant** décrit ci-dessous |
| Comptage local, instructions JSON et fusion système après simplification du compteur | **3 réussis** |
| `make typecheck` final | Succès : Pyright, vue-tsc, 244 tests frontend et catalogues i18n |
| `make lint` final | Succès Python et frontend |
| `make project-context`, puis `make architecture-check` | Cartographie à jour ; échec de parité documentaire préexistant décrit ci-dessous |
| `git diff --check` | Succès |

Les tests providers emploient un transport HTTP simulé et interdisent le réseau fournisseur.
Le nouveau scénario de transport remplace les accès DB/comptabilité ; les autres suites
de workflow utilisent la base PostgreSQL éphémère du workflow `make tests`.
Les suites se recouvrent : ne pas additionner ces nombres comme des tests distincts.

## Exécutions du second lot

Pydantic AI reste à **2.43.0**, OpenAI à **3.13.0**. L’extra officiel Groq ajoute uniquement
**groq 1.7.0** au verrou du premier lot ; il sert à importer le résolveur officiel de profil.
Les appels Galaris restent sur les endpoints OpenAI compatibles.

| Vérification | Résultat observé |
|---|---|
| Scénarios à identifiant opaque avant correction | **3 échecs, 1 réussite** : capacités DeepSeek ignorées et contraintes Codex absentes avant le proxy |
| Première matrice après branchement du profil Codex | **14 échecs, 929 réussites** : réponses simulées terminales sans événements de contenu, auparavant consommées comme JSON |
| Scénarios Codex, reprise du raisonnement, modèles opaques et Qwen3.8 après correction des fixtures SSE | **63 réussis** |
| `make tests-providers`, état final | **1 123 réussis** ; JUnit `artifacts/provider-contracts.xml` |
| `app/llm/tests app/harness/tests app/agent/tests` | **653 réussis** |
| `make typecheck` | Succès : Pyright, vue-tsc, 244 tests frontend et catalogues i18n |
| `make lint` | Succès Python et frontend |
| `make project-context`, puis `make architecture-check` | Cartographie à jour ; même divergence préexistante de `features.md` que dans le premier lot |
| `git diff --check` | Succès |

Les fixtures SDK Responses produisent désormais les événements de création, d’items et
de deltas texte/outils/raisonnement, puis l’événement terminal. Les assertions de contenu,
validation structurée, signature opaque, identifiants d’outils et comptage sont conservées ou
renforcées. La reprise Codex est testée aussi avec un terminal dont `output` est vide.
Les tests du gateway externe conservent les streams réduits (terminal seul ou items `done`)
et le renouvellement OAuth. Seule la trace des appels internes Codex change volontairement
de `stream=false` à `stream=true`, pour refléter le transport maintenant imposé par le SDK.

Les règles de nom ont disparu du résolveur Groq et de la politique de paramètres DeepSeek.
Elles restent notamment dans la politique d’effort Groq : le profil 2.43 ne décrit pas les
niveaux gradués Qwen3.8, pourtant documentés dans la
[référence API Groq](https://console.groq.com/docs/api-reference). La matrice est étendue
à ce cas pour interdire sa rétrogradation lors d’un prochain retrait de cette protection.

Les suites Goals et la qualification globale `make validate` ne sont pas relancées dans ce
second lot ; l’échec Goals rapporté ci-dessous reste une observation du premier lot.

## Échecs extérieurs au lot

- `app/goal/tests/test_goal_runner.py::test_finish_judgement_refreshes_task_before_releasing_retention`
  attend exactement `{"concurrent_update": true}`. Les changements concurrents de suivi des
  tâches ajoutent `_lifecycle_timing` à `Task.data`. Ce scénario ne passe pas par le modèle
  ni le transport LLM modifiés. Les fichiers de suivi et cette attente ont été laissés intacts.
- `make architecture-check` relève des nombres de blocs de code, niveaux de titres et cibles
  de liens différents entre les versions FR/EN de `features.md`. Ces deux fichiers sont
  identiques à leur état dans HEAD : la divergence ne provient pas de ce lot.

La cartographie a été régénérée depuis l’ensemble du code courant, y compris les contributions
concurrentes. Les changements indépendants d’admission, livraison, comptabilité et suivi
des tâches ne sont pas attribués à cette migration.

## Limites

La réussite des tests simulés ne qualifie pas les comptes providers réels. `make validate`
n’a pas été exécuté et aucune qualification globale de publication n’est revendiquée.
Le filtrage tardif et les règles de noms existantes restent présents : les sondes SDK
hors réseau documentées dans le plan montrent notamment des écarts d’effort sur OpenAI et
DeepSeek. L’objectif « aucune discrimination par modèle dans Galaris » n’est pas réalisé.

Les assertions qui figeaient le constructeur privé ont été remplacées par des appels publics
du SDK prouvant les mêmes garanties de contenu. La matrice d’endpoints et ses valeurs
attendues n’ont pas été assouplies pour faire réussir la migration.
