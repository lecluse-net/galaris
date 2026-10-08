# Corpus de rappel mémoire conversationnel / Conversational memory recall corpus

Ce corpus évalue **quels souvenirs doivent parvenir à une conversation**, y compris
lorsque le message n'est pas une demande explicite de recherche. Il ne modifie pas le
moteur mémoire. Le générateur, le validateur et le calcul des scores utilisent seulement
la bibliothèque standard Python, sans importer Galaris ni accéder à une base de données.

## Comparer deux versions du moteur

La variante `baseline` utilise le moteur courant. `previous` charge une copie figée
de `relevance.py`, `service.py`, `retrieval.py` et `facade.py`, placée **avant les
modifications** sous `artifacts/memory-benchmark/reference-v10/`. Ces fichiers sont
des sources de code de confiance, pas des données de conversations. Le chargeur
reste réservé au conteneur de tests et refuse une référence hors de ce répertoire
d'artefacts. Les empreintes des deux versions et de l'adaptateur sont contrôlées
avant/après la campagne. Une copie du moteur courant ne représente pas une ancienne
version ; conserver la provenance de la référence lors de la préparation.

Pour comparer l'admission finale, ajouter aussi `admission.py` à la référence figée.
Le chargeur l'utilise pour la recherche, le calendrier et le brief final ; son empreinte
figure dans le manifeste. Sans ce fichier, les anciennes campagnes conservent leur
comportement et partagent l'admission courante.

Le benchmark d'admission opt-in mesure les lots de 1, 8, 48, 100 et 500 résultats,
ainsi que les chemins de graphe valides sur des lots de 8 et 48 résultats,
sur 6 000 souvenirs synthétiques, les refus d'accès, les révisions obsolètes et les
chemins de graphe supprimés. Il compare aussi les extraits de la recherche paginée,
avec ordre alterné, deux échauffements par contrôle et répétitions configurables :

```bash
make tests ARGS='tests/test_memory_admission_benchmark.py -s -p tests.memory_benchmark_plugin --memory-benchmark-reference /repo/artifacts/memory-benchmark/reference-before-admission --memory-benchmark-output /repo/artifacts/memory-benchmark/admission-measurement --memory-benchmark-repeats 30'
```

`report.json` conserve p50/p95, nombres SQL, erreurs et rappel des résultats valides ;
`measurements.jsonl` conserve chaque mesure appariée. Les cas d'invalidation sont
volontairement provoqués : leur taux d'erreur ne mesure pas leur fréquence en production.
Ne pas lancer une autre campagne ou un contrôle CPU intensif pendant une mesure de latence.

```bash
make tests ARGS='tests/test_memory_benchmark_campaign.py -k campaign_on -s -p tests.memory_benchmark_plugin --memory-benchmark-corpus /repo/artifacts/memory-benchmark/corpus-v1 --memory-benchmark-output /repo/artifacts/memory-benchmark/paired-example/shard-0 --memory-benchmark-profile-sample --memory-benchmark-workers 1 --memory-benchmark-variants previous,baseline --memory-benchmark-reference /repo/artifacts/memory-benchmark/reference-v10'
make memory-benchmark ARGS='aggregate /output/corpus-v1 /output/paired-example --output /output/paired-example-aggregate --expected-queries 5280'
```

Les deux versions utilisent les mêmes fixtures, horloges, paramètres et schéma,
avec ordre alterné et état de lecture réinitialisé. Elles **préservent la priorité
du calendrier**, contrairement aux prototypes `relevance_first` et `combined`.
`paired_retrieved` mesure les gains et régressions du rappel ordinaire ; `paired`
mesure ceux du contexte effectivement injecté. Le corpus sature volontairement
le calendrier : des gains de recherche peuvent donc coexister avec un contexte
entièrement consacré aux échéances. Ce stress ne mesure pas leur fréquence réelle.

Les quantiles p50/p95/p99, nombres SQL et erreurs sont publiés avec la concurrence.
La comparaison sur un schéma commun ne mesure pas le stockage supplémentaire,
l'ingestion ou la construction initiale d'une nouvelle projection. Aucun résultat
ne qualifie les embeddings réels ou les réponses du modèle.

## Données et couverture

Tout est **inventé dès l'origine** : personnes, organisations, événements, historiques,
identifiants, quantités et décisions. Aucune conversation réelle n'est utilisée, même
avec des noms remplacés. Le conteneur de génération n'a ni réseau, ni environnement
applicatif, ni volume de base de données ; il ne voit que les sources du générateur et
le répertoire de sortie. Les fichiers générés restent dans `artifacts/`, hors Git.

Le lot par défaut contient **56 000 souvenirs et 26 400 messages de test** :

| Contexte | Univers métier ou situations | Messages |
| --- | --- | ---: |
| Entreprise | Production, RH, informatique, achats, logistique, vente, qualité, énergie, restauration, design | 6 600 |
| Cabinet indépendant | Comptabilité, administration juridique, architecture, rendez-vous confidentiels, conseil, traduction, artisanat, formation, photographie, ingénierie | 6 600 |
| Personnel | Famille, logement, voyage, budget, apprentissages, loisirs, accompagnement administratif, voisinage, garde d'animal fictif, déménagement | 6 600 |
| Association | Sport, culture, solidarité, environnement, bénévolat, collecte, gouvernance, bibliothèque, jardin partagé, réparation | 6 600 |

Les 40 contextes sont déclinés en 200 mondes indépendants. Chaque monde contient 80
souvenirs structurants, dont des traductions et des échéances parasites, et 200 souvenirs
parasites supplémentaires. Ses 132 messages couvrent 33 familles × 2 langues × 2 formulations.
Ces variantes constituent des mesures répétées, pas 26 400 situations entièrement originales.

Les familles couvrent personnes, surnoms, relations, organisations, lieux, projets,
préférences, quantités, négations, décisions, procédures, corrections, état historique,
hier, mention implicite d'une personne et d'hier, semaine précédente, ordre des événements,
engagement futur, fuseaux horaires, pronoms, relances, changement de sujet, plusieurs
personnes, entité inconnue, homonymes, séparation des contacts et des agents, retrait de
partage, oubli, rappel entre langues, passages longs, concurrence du calendrier et
instructions dangereuses citées dans un document.

Les dates incluent des journées de 23 et de 25 heures, un changement de mois et d'année.
La date de l'événement est distincte de sa date d'enregistrement. Les scénarios médicaux
et juridiques portent sur l'organisation et le partage d'informations, sans conseil
clinique ou juridique. Les fautes testées sont l'absence d'accents et la typographie ;
ce n'est pas une simulation complète des erreurs de reconnaissance vocale.

## Produire et vérifier

L'image locale `python:3.14-slim-trixie` doit être disponible. Le script n'effectue pas
de téléchargement automatique. Depuis la racine du dépôt :

```bash
make memory-benchmark
make memory-benchmark ARGS='validate /output/corpus-v1'
make memory-benchmark ARGS='generate --output /output/corpus-seed-42 --seed 42'
make memory-benchmark ARGS='generate --output /output/small --profiles family accounting sports manufacturing --repetitions 1 --distractors 20'
make tests ARGS='tests/test_memory_benchmark.py'
```

Dans le conteneur, `/output` correspond à `artifacts/memory-benchmark` sur l'hôte.
Une sortie existante n'est jamais écrasée. Les paramètres permettent de tester plusieurs
graines et plusieurs densités de parasites ; changer la graine ne crée pas de nouvelle
grammaire de conversation.

| Fichier | Contenu | Accès du moteur évalué |
| --- | --- | --- |
| `memories.jsonl` | Souvenirs HTML, provenance synthétique, ACL, portée contact, état et dates | Adaptateur d'indexation uniquement |
| `queries.jsonl` | Message, historique, horloge, fuseau, agent, contact et étiquettes d'évaluation | Message/historique/contexte uniquement ; garder les étiquettes hors prompt |
| `answers.jsonl` | Facettes indispensables, alternatives acceptables, souvenirs facultatifs/interdits, réponse attendue, fenêtre temporelle | Évaluateur uniquement |
| `manifest.json` | Version, graine, couverture, limites et empreintes SHA-256 | Administration du benchmark |

Le validateur vérifie les références, la cohérence des droits et des états, les fenêtres
temporelles, la couverture, les partitions et les empreintes. Un même contexte métier,
ses mondes, ses traductions et ses formulations restent dans une seule partition :
60 % développement, 20 % validation, 20 % réserve (`heldout`). Les grammaires restent
partagées entre partitions : cette réserve mesure le transfert à d'autres contextes,
pas à des formulations entièrement nouvelles.

## Contrat d'un adaptateur de moteur

Chaque `world_id` est un jeu de données indépendant. Initialiser un espace isolé avec
**tous** ses souvenirs, parasites inclus. Respecter ses ACL, contacts, états et horloge.
Traduire ces champs vers les contrats publics du moteur, en conservant un mapping de ses
identifiants vers ceux du corpus. Réinitialiser l'état entre messages, ou employer un
instantané immuable : un test ne doit pas devenir une source pour le suivant.

Ne pas donner au moteur les réponses, les facettes, les étiquettes `family`, `split`,
`surface`, ni les noms internes du générateur. Les titres et textes des souvenirs ne
contiennent pas de signatures de test à rechercher. Le contact et l'agent courants
font partie du contexte autorisé ; les identifiants techniques servent au mapping.

Évaluer le chemin conversationnel complet lorsque l'intégration le permet :
construction de requête, recherche, reclassement, assemblage du contexte. Enregistrer les
identifiants à chaque étape accessible, **après les contrôles d'accès**. N'inventer aucune
étape manquante. `injected` désigne les souvenirs effectivement présentés au modèle,
pas seulement ceux renvoyés par l'API. Les modèles et paramètres doivent rester fixes
entre deux comparaisons ; documenter les index disponibles et le mode lexical/sémantique.

L'adaptateur réel se trouve dans `back/tests/memory_benchmark_adapter.py`. La campagne
opt-in charge les fixtures dans la base éphémère de `make tests`, puis appelle la recherche,
les ACL, le fournisseur de contexte mémoire et la capsule de contexte agent de Galaris.
Une garde refuse toute base autre que `db-test/test_db`. Le chargement utilise les modèles
ORM et le stockage natif de test ; les recherches passent par les contrats applicatifs.
Chaque appel est annulé par savepoint : usages et fraîcheur ne contaminent pas le suivant.
L'horloge de scénario couvre aussi l'admission finale, qui revérifie indépendamment la
validité temporelle. Un test de recherche réelle vérifie qu'un fait courant entre dans
les résultats et qu'un fait expiré reste exclu avec cette horloge future.
Une erreur du fournisseur mémoire reste une observation avec un contexte vide, un échec
de rappel et son code d'erreur dans la trace. Elle n'est jamais retirée du dénominateur.
Les recherches commencées sont comptées même si elles échouent. Un test vérifie aussi
qu'un échec ne réutilise pas le contexte d'un appel précédent.

La campagne actuelle mesure le **repli lexical réel**, sans fournisseur d'embeddings,
index vectoriel ni réponse finale LLM. L'historique entre à la frontière
`AgentContextRequest` ; le transport de messagerie et le scheduler ne sont pas exécutés.
`injected` correspond aux entrées mémoire de la capsule réellement préparée, sans prétendre
mesurer leur attention par un modèle. Les candidats constituent une union non ordonnée des
canaux : seule leur disponibilité est mesurée, pas un score de classement artificiel.

```bash
make tests ARGS='tests/test_memory_benchmark.py tests/test_memory_benchmark_campaign.py -k "not campaign_on"'
make tests ARGS='tests/test_memory_benchmark_campaign.py -k campaign_on -s -p tests.memory_benchmark_plugin --memory-benchmark-corpus /repo/artifacts/memory-benchmark/corpus-v1 --memory-benchmark-output /repo/artifacts/memory-benchmark/sample-v1 --memory-benchmark-worlds 4 --memory-benchmark-workers 4'
```

`--memory-benchmark-worlds 0` sélectionne tout le corpus. Pour une campagne partitionnée,
lancer la même commande avec `--memory-benchmark-shards 8 --memory-benchmark-shard N`,
pour chaque `N` de 0 à 7, et une sortie distincte `.../measure-baseline-v3/shard-N`.
Chaque processus possède sa base éphémère indépendante. Tous les mondes de sa partition
sont chargés avant la mesure. Cette configuration ne mesure pas un index unique de
56 000 souvenirs ; la latence inclut la charge concurrente des campagnes.

La référence complète peut utiliser `--memory-benchmark-variants baseline`. Pour comparer
les six variantes sur les 40 contextes, `--memory-benchmark-profile-sample` sélectionne
un monde par contexte, en alternant les cinq configurations calendaires : 5 280 messages,
1 320 par domaine, avec une sortie `.../measure-comparison-v3/shard-N`. Conserver une référence `baseline` dans cette comparaison pour que
les latences et les scores soient appariés dans les mêmes conditions.

```bash
make memory-benchmark ARGS='aggregate /output/corpus-v1 /output/measure-baseline-v3 --output /output/measure-baseline-v3/aggregate'
make memory-benchmark ARGS='aggregate /output/corpus-v1 /output/measure-comparison-v3 --output /output/measure-comparison-v3/aggregate --expected-queries 5280'
```

L'agrégation refuse une partition manquante, des messages dupliqués, une campagne
incomplète ou des empreintes de sources/paramètres différentes. Elle produit observations,
rapports détaillés, comparaisons appariées, candidats de revue et `rapport.md`.
Les sources critiques sont fingerprintées au début et vérifiées à la fin de chaque campagne.

Les six variantes restent exclusivement dans les tests : `baseline`, `relevance_first`,
`history`, `entities`, `time`, `combined`. Toutes les variantes autres que `baseline`
priorisent les résultats ordinaires pertinents devant les échéances. Comparer les quatre
enrichissements à `relevance_first` isole leur apport propre. Les recherches d'entités
utilisent des expressions capitalisées et les extraits autorisés ; celles de dates utilisent
le calendrier local et les métadonnées synthétiques d'événements. L'historique reprend les
deux derniers messages, sauf changement de sujet explicite. Aucune facette attendue ni
étiquette d'évaluation n'intervient dans ces prototypes.
La langue de requête et le fuseau sont déclarés par les fixtures, comme les dates
d'événements des souvenirs. Cette campagne ne mesure pas leur détection automatique
ni leur disponibilité dans les conversations déployées.

Chaque monde contient volontairement **20 échéances imminentes**, plus que le budget de
huit éléments. Il s'agit d'un test de saturation du calendrier commun à toutes les familles,
pas d'une estimation de la fréquence réelle du défaut. Les observations de calibration
nommées `NOT-engine` ne sont jamais utilisées comme résultats du moteur.

## Calculer les scores

L'adaptateur écrit un JSONL dans `artifacts/memory-benchmark/observations.jsonl`.
Exemple de **format**, avec des identifiants à remplacer par ceux du corpus :

```json
{"query_id":"query-uuid","candidates":["memory-uuid-1","memory-uuid-2"],"retrieved":["memory-uuid-1","memory-uuid-2"],"injected":["memory-uuid-1"],"response_mode":"answer","latency_ms":42.5,"context_tokens":210}
```

Une étape au moins est nécessaire. Les mesures et `response_mode` sont facultatifs.
Les modes sont `answer`, `clarify`, `unknown`, `unavailable`. Ils décrivent le comportement
attendu, pas une phrase littérale à produire. Une réponse inconnue n'autorise pas à inventer
une relation ; un homonyme exige une clarification ; une note supprimée ou inaccessible
ne doit pas être révélée.

```bash
make memory-benchmark ARGS='score /output/corpus-v1 /output/observations.jsonl --output /output/run-baseline --label baseline --k 8 --stages retrieved injected'
make memory-benchmark ARGS='score /output/corpus-v1 /output/observations.jsonl --output /output/run-heldout --splits heldout --stages injected'
```

Le rapport comprend scores globaux et répartitions par domaine, contexte, famille,
langue, partition et forme de message, plus un fichier détaillé par message/étape.
Il conserve le libellé de campagne et les empreintes du manifeste et des observations.

La **facette** est l'unité de rappel : pour « C'est [personne fictive] qui me l'a offert
hier », retrouver la personne sans l'événement donne 50 % de rappel, pas une réussite.
Les traductions d'un même fait sont des alternatives ; une seule suffit. Les doublons
consomment leur rang sans augmenter le rappel. Les scores comprennent :

- Rappel des facettes et proportion de messages ayant toutes leurs facettes dans les `k` premiers résultats.
- Précision, MRR du premier fait pertinent et MRR du dernier fait nécessaire pour compléter le contexte.
- NDCG : gain 1 pour une nouvelle facette indispensable, 0,25 pour un souvenir facultatif distinct ; l'idéal place les indispensables en premier.
- Couverture du fichier d'observations : chaque message sélectionné reste au dénominateur, même absent du fichier.
- Souvenirs interdits dans **toute la liste**, au-delà de `k` compris : accès, oubli, ancien état interdit, autre monde ou identifiant inexistant.
- Messages sans fait exigible ayant tout de même des résultats, exactitude du mode de réponse lorsqu'il est fourni, latence et taille de contexte lorsqu'elles sont fournies.

Les messages sans fait exigible n'obtiennent pas artificiellement 100 % de rappel.
Le résultat doit être lu par famille, en particulier pour la clarification et l'isolation.
Un ancien horaire est interdit dans le cas de correction courante, mais requis pour
une question historique : ce sont des attentes différentes, pas une suppression du passé.

## Qualifier une amélioration

Comparer sous les mêmes conditions le moteur actuel et chaque proposition. Fixer les
objectifs sur la partition de développement puis les vérifier sur validation et réserve.
Examiner séparément le rappel complet, les fuites, les corrections et le budget de
contexte. Une moyenne élevée ne compense pas une fuite. Exiger zéro identifiant interdit
présenté au modèle et une couverture complète pour annoncer une campagne complète.

Ce corpus a un oracle contrôlé, mais son langage reste construit par gabarits. Une revue
humaine stratifiée des attentes et des réponses est nécessaire avant d'en faire un critère
de publication. Les identifiants seuls ne prouvent ni la suffisance des extraits, ni la
justesse de la réponse finale, ni la résistance aux instructions citées. Les assertions
et modes attendus sont fournis pour cette revue ; aucun jugement LLM automatique n'est
présenté comme vérité de référence. Ne pas extrapoler une latence par monde de 280
souvenirs à un index unique de 56 000 souvenirs.

## English usage summary

This is an entirely fictional, deterministic, engine-independent conversational recall
benchmark. The default build has 56,000 memories and 26,400 query messages, evenly
distributed across enterprise, independent practice, personal and nonprofit settings.
There are 40 authored settings, 200 isolated worlds and 33 scenario families in French
and English. Generation has no database or network access; outputs stay outside Git.

Run the commands above through `make memory-benchmark`. `/output` maps to the host's
`artifacts/memory-benchmark` directory. The generator never overwrites an existing
directory. Checksums and validation protect structural reproducibility, not engine quality.

An engine adapter must load each world's complete memory pool, enforce ACL/contact/state
rules and its fixed clock, and return corpus IDs at the available stages (`candidates`,
`retrieved`, `injected`). Do not expose the answer file or evaluation labels to the engine.
Reset engine state between queries. The opt-in Galaris adapter in `back/tests` uses only
the ephemeral test database and evaluates real lexical fallback, ACL, memory rendering
and the driver-neutral agent context capsule. It does not run embeddings or generate
LLM answers. Use the campaign and aggregation commands above; a zero world limit selects
all worlds, and optional database partitions must all complete before aggregation.

The six test-only variants are baseline, relevance-first calendar prioritization, history,
entities, relative time and their combination. All enrichments share relevance-first
prioritization, so compare them with that control to isolate search improvements. Every
world deliberately saturates upcoming calendar matches; scores describe this stress test.
Source fingerprints, coverage and shared budgets are checked. Partitioned concurrency
is reported and is not a single combined-index performance measurement.

Scoring uses required fact groups, with alternative IDs for translations. Missing selected
queries count as misses. No-fact queries are excluded from recall denominators. Forbidden
IDs are checked throughout full lists. Reports include coverage, complete/facet recall,
precision, first/complete MRR, graded NDCG, violations and optional response-mode/operational
measurements, broken down by setting, domain, family, language, split and message surface.

All variants of a setting remain in one 60/20/20 partition; scenario grammars are shared
across partitions. This measures controlled recall, not natural-language production
distribution, generated-answer correctness or instruction safety. Review a stratified
sample and actual answers before using this corpus as a release gate. Do not interpret
per-world latency as a measurement on a single combined 56,000-memory index.
