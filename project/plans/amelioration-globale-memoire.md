# Plan — Qualification de la mémoire et expériences restantes

> **Statut :** `partial` — socle documentaire réalisé ; qualification et extensions ouvertes.
> **Revue documentaire :** 19 septembre 2026.

Le contrat réalisé appartient à la [décision 0108](../decisions/0108-memory-document-retrieval.md).
Les lots d'admission MEM-017, d'indexation MEM-016, de recherche commune MEM-008 et le premier
découpage documentaire MEM-018 ne sont plus des implémentations à reprendre dans ce plan.

Les preuves et limites restent dans les audits de
[validité](../audits/2026-09-11-memory-multimedia-qualification.md),
[recherche documentaire](../audits/2026-09-17-memory-document-retrieval.md),
[classement](../audits/2026-09-17-memory-ranking-v8.md) et de
[rappel vide](../audits/2026-09-17-memory-empty-round.md).
Le contrat courant restitue les meilleurs candidats sans seuil de pertinence, avec droits,
validité et révisions préservés. Une présence dans les résultats ne prouve pas une réponse.

Restent : qualification multilingue et sur d'autres corpus, paraphrases/alias, pertinence
des passages et utilité aval, extraction nouvelle des pièces jointes, observation et
expériences Memory/Dream/Topics ci-dessous. Les résultats locaux ne qualifient pas la production.

## 1. Objectif

Améliorer la capacité de Galaris à retenir, organiser, retrouver, présenter, corriger et oublier
les informations utiles, sans optimiser une étape au détriment de l’ensemble du cycle mémoire.
Les documents sont des éléments mémoire centraux : leur contenu complet et actuel doit être
recherchable, et les agents doivent recevoir les passages utiles avec leurs URI et leur provenance.
Le modèle d'embeddings est exclusivement celui du paramètre configuré ; le plan ne choisit,
ne compare et ne remplace aucun modèle.

Chaque changement doit répondre à quatre questions avant son implémentation :

1. quel défaut observable cherche-t-il à corriger ?
2. quelle hypothèse explique qu’il améliorera la situation ?
3. quel benchmark avant/après peut réfuter cette hypothèse ?
4. quelles portes de non-régression et quel rollback empêchent une dégradation silencieuse ?

Le plan ne cherche donc pas un « meilleur système de mémoire » abstrait. Il organise une suite
d’expériences comparables, chacune reliée à un défaut utilisateur ou opérationnel précis.

## 2. Autorités et périmètre

Les contrats, modèles, implémentations et tests restent autoritaires. Ce plan s’inscrit notamment
dans les décisions suivantes sans les remplacer :

- [0010 — Mémoire agentique gouvernée et commune aux drivers](../decisions/0010-governed-agent-memory.md) ;
- [0020 — Dossiers thématiques globaux comme pivot de la mémoire](../decisions/0020-global-thematic-dossiers.md) ;
- [0024 — Création gouvernée et réemploi prioritaire des dossiers thématiques](../decisions/0024-governed-topic-creation.md) ;
- [0026 — Mémoire conversationnelle scellée par interlocuteur puis classée par Topic](../decisions/0026-topic-contact-conversation-memory.md) ;
- [0027 — Extraction mémoire en une passe, conditionnée par le Topic](../decisions/0027-topic-gated-single-pass-memory-extraction.md) ;
- [0041 — Signalements déterministes de maintenance mémoire](../decisions/0041-deterministic-memory-maintenance-findings.md) ;
- [0104 — Documents comme pivot de l'information](../decisions/0104-documents-information-hub.md) ;
- [0106 — Structure documentaire et mémoire des pièces jointes](../decisions/0106-document-structure-memory.md) ;
- [0107 — Dossiers personnels des objectifs](../decisions/0107-personal-goal-folders.md).

Le [plan du Lab](lab-evaluation-mecanismes-ia.md) possède l’infrastructure transversale de
benchmark. Le présent document définit les questions et métriques propres à Memory ; il ne crée
pas un second système d’évaluation.

Le plan couvre le cycle complet :

```text
source observée
      ↓
éligibilité et extraction
      ↓
acquisition, déduplication et provenance
      ↓
organisation par Topics et graphe
      ↓
recherche, ranking et sélection bornée
      ↓
injection ou lecture volontaire
      ↓
usage réel dans une décision
      ↓
correction, consolidation, vieillissement et oubli
```


### 2.1 Sources vérifiées pour le remaniement du 17 septembre 2026

Ce fichier reste le plan unique. La demande porte sur son remaniement, pas sur une activation,
une migration, un déploiement ou une réécriture de la mémoire en production.

- **Code local courant** : cartographie générée, `memory/{models,semantic_index,embedding,
  retrieval,service,file_facade,context,attachment_description}.py`, projection des résultats dans
  `file_share/resource_service.py`, tests Memory et contrats du Lab. Le worktree évolue pendant
  l'analyse ; les constats ci-dessous désignent les fonctions, pas une prétendue release figée.
- **Diagnostic local du 17 septembre, vers 11 h Paris** : 26 documents dont 24 avec texte,
  508 souvenirs avec texte, 18 compagnons de PJ sans texte ; aucun embedding courant.
  Les 535 chunks présents ont le bon modèle configuré mais aucune empreinte courante.
  La file contient alors 1 753 jobs en attente et 197 en erreur ; les dernières erreurs indiquent
  un fournisseur injoignable. Ce sont des compteurs de jobs, pas de documents distincts.
  Ces observations sont celles du développement, **pas un audit de santé de la production**.
- **Validation locale déjà exécutée** : 40 tests de `test_semantic_search.py` et
  `test_recall_evaluation.py` réussis. Les embeddings de ces tests sont substitués ou indisponibles ;
  ce résultat ne mesure ni le fournisseur réel, ni la pertinence sur le corpus documentaire.
- **Rapport privé lu en production, en lecture seule** :
  lecture paginée avec vérification d'une même révision sur toutes les pages.
  Son titre, son identifiant et son empreinte ne sont pas publiés.
  Ses résultats sont des **preuves rapportées**, non des campagnes réexécutées lors de ce remaniement.
  Les branches, bundles et artefacts `console://work/…` cités ne sont pas réputés intégrés ou
  accessibles dans le dépôt courant. Les fichiers d'observation et d'évaluation contrefactuelle
  cités dans ce rapport n'ont pas été retrouvés aux chemins correspondants dans le backend local.

| Constat de code actuel | Conséquence | Lot |
|---|---|---|
| `file_facade.search_file_resources` filtre `memory://` sur `node_kinds=["memory"]` ; `document://` utilise `service.search_items` | Un document n'est pas directement candidat à la recherche mémoire explicite ; le parcours documentaire reste lexical | MEM-008 |
| `resource_service.resource_search` construit l'URI depuis le schéma demandé | Élargir les résultats sans adapter ce consommateur fabriquerait des URI et capacités erronées | MEM-008 |
| La mise en file sémantique intervient après le commit de certaines écritures ; `record_attachment_description` ne l'appelle pas | Fenêtre de perte de programmation et descriptions acquises non réindexées immédiatement | MEM-016 |
| Réconciliation : existence d'au moins un chunk courant ; disponibilité : existence d'au moins un item courant | Une couverture partielle ne peut pas être résumée par « index disponible » | MEM-016 |
| Découpage à 360 mots, recouvrement 60, plafond 256 fragments ; texte de recherche limité à 2 millions de caractères | Structure et fin des grands documents potentiellement perdues sans état partiel explicite | MEM-018 |
| `_semantic_candidates` lit les chunks puis les objets ORM ; `_hydrate_hits` calcule l'accès sans en faire une condition de retrait | Frontières de révision et d'autorisation à corriger sur toutes les voies | MEM-017 |
| Replis utilisant une page lexicale calculée avant l'appel au fournisseur | Risque de réintroduire un extrait invalidé pendant l'attente | MEM-017 |
| Le brief peut rechercher plusieurs natures, mais présente surtout des UUID ; le résultat fichier perd les diagnostics détaillés | Découverte, lecture et compréhension des limites inégales selon le consommateur | MEM-007/008 |

### 2.2 Analyse et arbitrages sur les réflexions du rapport privé

| Apport du document | Ce que le plan retient | Limite ou correction |
|---|---|---|
| Cycles 1–2, instrumentation : candidat, exposé, injecté, utile | Événements distincts, traces par source, aucun renforcement fondé sur la seule exposition | La proposition initiale de petit bonus pour l'injection est abandonnée au profit de la correction ultérieure du rapport privé : aucun crédit d'utilité sans preuve attribuable |
| MEM-013/MEM-014 du rapport privé : writer, observation et ablations | Réutiliser les contrats et tests pertinents après récupération et revue du delta ; observer sans modifier le ranking | Résultats historiques de branches expérimentales, pas fonctionnalités livrées ; aucun portage global aveugle |
| Cycles 19–34 : propensions, cohortes et censure | Séparer probabilité d'action et échantillonnage de traces ; mission racine, horizon fixé et inconnues explicites | Une attestation de bras sans changement exécuté ne démontre aucun effet ; pas d'IPS/SNIPS depuis un score ou un taux de logging |
| Cycles 38–40 : support de concept | Dépendances de provenance, rareté, exceptions et stabilité ; un cluster propose, il ne prouve pas un concept | Plusieurs fragments ou replays d'une source ne deviennent pas plusieurs observations indépendantes |
| Cycle 45 : SciFact | Conserver un canal global indépendant du Topic ; mesurer séparément fidélité au top-k exact et pertinence annotée | Le banc TF-IDF rapporté passe de Recall@10 0,7735 en exhaustif à 0,3681 avec le seul centroïde ; les bornes complètes ne réduisent pas les comparaisons. Ce n'est ni le modèle configuré ni une mesure de Galaris |
| Cycle 46 : génération cohérente | Manifestes, révisions, espace vectoriel, publication atomique et état incomplet explicite | Cohérence, fraîcheur, couverture et autorisation sont des garanties différentes ; aucune nouvelle partition technique imposée |
| Cycle 47 : frontières ORM et replis | Priorité à une projection cohérente et à une admission commune des sorties ; reproduire ses ordonnancements dans la suite actuelle | Le rapport privé rapporte des défauts reproduits dans les vraies fonctions, mais pas le parcours HTTP complet ni un incident de production ; `refresh` seul ne suffit pas |
| Cycle 48 : origine et activation | L'origine d'un fait reste attachée à sa version ; un chemin de rappel ne la réécrit pas | Une origine correcte ne prouve pas la pertinence ; les fixtures avec provenance fournie ne démontrent pas son extraction automatique |
| Cycle 49 : support par fragment | Ancrages source/version et dépendances ; distinguer source citée, support attesté et vérité | Ne pas inférer des circuits ET/OU depuis une liste de citations ; `MemorySource.content_hash` n'est pas un digest général des octets de la source externe |

Les analogies cognitives motivent des expériences, pas des constantes de production. L'activation
adaptative, les nouveaux états de dormance et les circuits de preuve restent exploratoires.
Les anciennes références à Alembic, à des révisions d'arêtes inexistantes ou à des FK empêchant
l'oubli ne sont pas reprises : SQLAlchemy/DbAdmin, snapshots d'attributs réellement disponibles
et effacement gouverné restent les contrats du dépôt.

**Correspondance des identifiants :** conserver les MEM-001 à MEM-015 de ce fichier. Le MEM-011
« cycle de vie Topic » du rapport privé rejoint ici MEM-010 ; son MEM-012 « métriques causales » rejoint
MEM-009 ; son MEM-013 « observation » précise notre MEM-013 ; son MEM-014 « ablations » précise
MEM-006 et MEM-009. Notre MEM-014 reste l'UX d'administration. Les nouveaux MEM-016 à MEM-018
portent respectivement l'indexation, l'admission et la représentation documentaire.

## 3. Invariants communs

Les lots ajoutés à ce plan respectent par défaut les invariants suivants :

- `app.memory` reste l’unique façade métier de la mémoire gouvernée ;
- documents et textes acquis de PJ sont des sources de premier rang, sans bonus aveugle de nature ;
- l'usage vectoriel du profil configuré dans `app.llm` fait autorité : aucun modèle automatique,
  secondaire, de secours ou choisi après benchmark ; les paramètres de ranking restent globaux ;
- un changement du modèle configuré invalide les projections incompatibles et programme leur
  reconstruction ; aucune conversion ou comparaison implicite entre espaces vectoriels ;
- index présent, index complet, contenu actuel et remise autorisée sont des propriétés distinctes ;
- les données du document sont des sources à consulter, jamais des instructions capables de
  modifier la politique d'outils, les droits ou les consignes supérieures ;
- PostgreSQL conserve l’identité, les droits, les sources, les révisions, les liens et l’audit ;
- les ACL et le scellement par interlocuteur sont appliqués avant ranking ou expansion du graphe ;
- une panne des embeddings ou du provider vectoriel reste fail-open vers un chemin lexical
  fraîchement admis, avec dégradation visible ; elle n'assouplit jamais les ACL ni l'effacement ;
- les projections source-managed restent distinctes de leur autorité métier ;
- aucune proximité sémantique ou graphique n’accorde un droit d’accès ;
- provenance, oubli physique, révision et idempotence ne sont jamais sacrifiés à la qualité perçue ;
- l’évaluation utilise des copies bornées ou des snapshots et ne modifie jamais la mémoire de
  production ;
- une amélioration n’est pas déduite d’un score global seul : les dimensions antagonistes restent
  visibles séparément ;
- le dataset de holdout n’est ni lu ni modifié pendant le réglage ;
- les seuils d’acceptation sont écrits avant l’ouverture du holdout ;
- un changement qui échoue à ses portes de non-régression n’est pas promu.

Pour le premier lot Topic, une contrainte supplémentaire est ferme : **aucun nouveau type de
mémoire, aucun nouveau type de lien et aucune modification du modèle de données**. Le travail doit
rendre plus pertinent le système existant. Cette contrainte de MEM-001 n'interdit pas les schémas
justifiés des lots d'indexation/observation distincts, à concevoir via SQLAlchemy et DbAdmin.

## 4. Modèle de qualité global

La qualité mémoire ne peut pas être réduite au nombre de souvenirs ni à la similarité vectorielle.
Chaque lot doit indiquer les dimensions qu’il affecte et celles qu’il ne doit pas dégrader.

| Dimension | Question | Exemples de mesures |
|---|---|---|
| Couverture et fraîcheur | Chaque contenu et passage éligible est-il indexé à la version attendue ? | fragments attendus/publiés, retards, lacunes explicites, erreurs par cause |
| Fidélité de restitution | L'extrait, sa révision, ses sources et ses droits décrivent-ils le même état admis ? | mélanges de versions, réintroductions par repli, localisations erronées |
| Sélectivité de capture | Galaris retient-il ce qui sera utile sans conserver le bruit ? | précision/rappel de `CREATE`, `LINK`, `IGNORE`, taux de faits ponctuels retenus |
| Fidélité | Le souvenir reste-t-il soutenu par la source ? | hallucinations, couverture des preuves, contradictions introduites |
| Déduplication | Une même connaissance garde-t-elle une identité stable ? | faux `LINK`, doublons, provenances par UUID, fusions manuelles ultérieures |
| Organisation | Les souvenirs sont-ils regroupés selon des sujets durables et utiles ? | cohésion, séparation, fragmentation des Topics, qualité des liens existants |
| Rappel | Les bons éléments remontent-ils avant les éléments seulement proches ? | Recall@k, MRR, nDCG, précision@k, succès lexical/vectoriel/graphe |
| Diversité | Le contexte évite-t-il paraphrases et répétitions ? | taux de quasi-doublons dans le top-k, couverture de sous-sujets |
| Utilité en exécution | La mémoire présentée améliore-t-elle réellement la décision ? | taux d’usage, gain aval sur la Task, faux appuis sur un souvenir |
| Fraîcheur et autorité | Les faits valides dominent-ils les faits périmés ou faibles ? | erreurs de temporalité, contradictions non signalées, sources dominantes |
| Gouvernance | Peut-on comprendre, corriger, partager et oublier ? | couverture de provenance, succès d’oubli, délais de correction, incidents ACL |
| Coût opérationnel | Le gain justifie-t-il coût, latence et volume de contexte ? | coût par source, latence p50/p95, tokens injectés, taille des index |

## 5. Fiche d'expérience et preuve attendue

Avant de promouvoir une idée en lot, consigner son identifiant `MEM-XXX`, le défaut observable,
la population concernée, la baseline, l'hypothèse réfutable et l'unique variable candidate.
Préciser les dimensions à améliorer et à protéger, les datasets, les métriques déterministes,
la rubrique sémantique éventuelle, les seuils préenregistrés, le canari et le rollback.

Après l'expérience, publier dans un rapport lié les snapshots baseline/candidat, les résultats
par sous-population, couverture, coût, durée, incertitude, régressions et signaux du canari.
Conclure par promouvoir, poursuivre, rejeter ou rollback, avec justification. Une hypothèse
réfutée peut être abandonnée sans implémentation ; le registre conserve ce choix.

## 6. Protocole commun de benchmark

Le [Lab](lab-evaluation-mecanismes-ia.md) porte l'infrastructure et ses qualifications restantes.
Ses rôles natifs `purpose=work|validation|holdout` existent ; ils ne garantissent pas seuls
le gel du corpus ni l'étanchéité des partitions.

1. Expurger et revoir les cas importés de production ; une sortie historique n'est pas sa référence.
2. Figer corpus, catalogue, révisions, modèle d'embeddings configuré et paramètres hors variable
   testée ; pour les mécanismes génératifs seulement, figer aussi leur modèle configuré et le juge.
3. Mesurer la baseline, travailler sur `work`, sélectionner sur `validation`, puis figer les
   seuils avant l'ouverture unique du `holdout` pour la décision finale.
4. Comparer baseline et candidat par cas, avec plusieurs répétitions si le mécanisme varie.
   L'unité statistique reste l'épisode ou la conversation, jamais ses messages corrélés.
5. Publier moyenne, médiane, dispersion, couverture et intervalles de confiance lorsque le volume
   le permet. Un score global ne compense pas une régression critique.
6. Préférer les mesures déterministes pour les décisions fermées. Réserver le juge aux dimensions
   ouvertes ; son échec ne reçoit aucun score de remplacement.
7. Annoter ou revoir humainement les gardes fortes, arbitrer les cas ambigus et mesurer l'accord
   en aveugle lorsqu'il y a plusieurs annotateurs.

Ce protocole s'applique à tous les lots ci-dessous ; chaque lot ne précise que ses particularités.


## 7. Programme prioritaire — documents, indexation et pertinence du rappel

Le socle documentaire est décrit par 0108. Les extensions ci-dessous le réutilisent ;
elles ne remettent pas en chantier l'admission commune, l'indexation durable, les lecteurs
canoniques ou les passages déjà implémentés.

### 7.1 MEM-018 — Extensions de pièces jointes et provenance par passage

- Concevoir l'extraction déterministe des binaires pris en charge après évolution explicite
  de l'ADR 0106, qui ne prévoit actuellement pas d'extraction automatique.
- Pour une acquisition multimodale, définir déclenchement, budgets, modèles configurés et
  provenance ; aucune analyse générative systématique implicite.
- Séparer texte extrait, description interprétée et binaire. Réutiliser le compagnon Memory
  et l'URI canonique ; retrait d'une PJ et révision du corps gardent leurs contrats distincts.
- Compléter les ancrages par passage lorsque la source les fournit : origine, version attestée,
  chemin de rappel et support interprétatif distincts. Ne pas attribuer toutes les sources
  d'un item à chacune de ses phrases, ni assimiler citations copiées et corroboration indépendante.
- Évaluer séparément représentation extractive globale et circuits de preuve ET/OU sur
  annotations indépendantes ; ils ne deviennent pas des prérequis au rappel courant.

**Preuve :** extraction partielle, PJ renommée/retirée, provenance multi-source et restauration
du fournisseur, avec mesure de couverture et de fidélité des localisations. Préserver les
tests existants de documents longs, de tableaux, d'ACL et d'admission.

### 7.2 MEM-006/007 — Pertinence des candidats, classement et contexte utile

**Garantie observable :** la recherche sélectionne les passages qui répondent à la demande,
tout en conservant les exceptions, les sources rares et les contraintes de contexte.

Pipeline candidat : requête et contraintes explicites → voies lexicales/vectorielles globales et
thématiques → fusion → expansion documentaire bornée → classement → diversité des passages →
admission → assemblage du budget de contexte.

Conserver une voie globale indépendante du Topic, conformément aux contre-exemples du rapport privé.
Un Topic/concept n'est pas une partition d'index. Ne pas filtrer tout le corpus par le seul
centroïde le plus proche, ni ajouter un index ANN ou des bornes géométriques sans besoin de
capacité mesuré. L'exact pgvector actuel sert d'oracle de fidélité des optimisations ; sa fidélité
ne remplace pas les jugements de pertinence documentaire.

Travaux à comparer séparément, à **modèle d'embeddings configuré constant** :
- lexical : langue, accents, variantes morphologiques, titres, sections, noms exacts, références
  et termes courts significatifs ; préserver une voie littérale pour les identifiants techniques ;
- passages : présélection lexicale et vectorielle au niveau du fragment ; comparer aux passages actuels, puis regrouper les passages complémentaires par document ;
- fusion : comparer la politique actuelle à une fusion des rangs explicitement définie, en
  évitant qu'une normalisation d'un petit lot transforme un faible signal en preuve forte ;
- classement : pertinence directe d'abord, portée projet/Goal/contact ensuite ; autorité,
  actualité et structure comme signaux bornés, jamais popularité ou fraîcheur comme vérité ;
- graphe : mesurer séparément références, contenance, dossiers et liens sémantiques ; pénaliser
  les hubs, borner profondeur/largeur/coût, garder les chemins explicables et les cycles neutres ;
- diversité : plusieurs passages d'un document si complémentaires, un seul si redondants ;
  ne pas confondre déduplication de résultats et fusion durable de deux documents ;
- rappel sans seuil : restituer les meilleurs candidats disponibles dans la limite demandée ;
  mesurer leur utilité sans confondre présence d'un souvenir et preuve d'une réponse.

Ne pas diluer la requête dans tout l'historique de la tâche. Extraire le contexte pertinent depuis
les contrats existants ; une contrainte exacte d'épisode, date ou source ne devient pas un simple
bonus. Distinguer recherche ciblée et synthèse multi-sources. Une reformulation ou décomposition
en sous-requêtes reste une expérience bornée, avec preuve que son gain justifie coût et latence.

Le brief remet URI, titre, section, extrait fidèle et révision. Le budget couvre l'ensemble du
contexte ; les extraits lexicaux sont centrés sur la correspondance, pas systématiquement sur le
début du document. Un extrait coupé doit permettre une lecture complémentaire au bon endroit.
Conserver la politique sélective de recherche : l'agent consulte le brief, cherche si nécessaire
et lit les sources avant d'en faire une affirmation importante.

Le socle reste sans appel génératif pour classer. Un reclasseur spécialisé est une expérience
ultérieure isolée, uniquement avec une capacité explicitement configurée et un gain hors
échantillon ; aucun modèle caché ou choisi automatiquement. Il n'est pas un prérequis à la
correction et ne change pas le modèle d'embeddings.

**Preuve :** ablations par canal et par type de lien, précision/rappel/nDCG, passages utiles
déplacés hors du top-k, redondance, coût et utilité après lecture. Ne promouvoir aucun poids
graphique parce qu'il augmente seulement les chemins visités.

### 7.3 MEM-013/014 — Observation et diagnostic sans renforcer la popularité

Commencer par un socle opérationnel léger : couverture courante par nature de contenu,
fragments attendus/publiés, retard p50/p95/max, jobs utiles en attente, échecs par cause,
disponibilité du fournisseur, latence et état du rappel. Réutiliser les métriques existantes.
Le tableau d'administration montre aussi les contenus bloqués et leur action de réparation,
sans nécessiter les traces expérimentales détaillées.

Puis instrumenter un rappel par identité d'exécution avec versions de code/politique/configuration,
budgets, sources des candidats, contributions réellement utilisées, chemins et raisons d'exclusion
non sensibles. Une liste servie n'est pas tout le vivier de candidats. Enregistrer l'injection
après les coupes du brief ; une ouverture, une citation, une correction et un résultat de tâche
sont des événements différents. Le taux d'accès reste une exposition, pas un score d'utilité.

Une réussite de tâche ne crédite pas tous les souvenirs injectés ; un échec ne les pénalise pas
tous ; l'absence de citation ou d'exposition ne prouve aucune inutilité. Les signaux collectifs
restent collectifs. Aucun apprentissage des forces pendant cette première instrumentation.

L'observation est indépendante du classement : panne de télémétrie sans effet sur les résultats,
trace échouée/incomplète jamais annoncée comme complète. Coût borné et mesuré, échantillonnage
explicite, aucun texte brut de requête ou extrait dans les traces générales. Si une corrélation
pseudonymisée est nécessaire, HMAC versionné avec clé hors DB ; le taux de collecte n'est pas
une propension d'action. Rétention proposée à qualifier : détails 90 jours, agrégats réellement
anonymisés 400 jours ; cohortes Lab gouvernées séparément. Un oubli purge les références
identifiantes et peut invalider un rapport, sans FK qui bloque l'effacement.

**Preuve :** flags désactivés, panne d'écriture, rejouage, fermeture concurrente, non-exposition
des attributs privés, purge et coût. Reprendre les invariants du rapport privé sans importer automatiquement
ses tables/triggers, sa branche divergente ou ses anciennes conventions de colonnes.

### 7.4 MEM-006/009 — Corpus de pertinence et mesure aval dans le Lab

Créer une extension du Lab existant pour le rappel réel : fixtures et corpus isolés, aucune
écriture de production. Les métriques de pertinence utilisent des labels revus ; elles ne doivent
pas dépendre d'un juge génératif. Adapter explicitement le contrat de run du Lab si ce parcours
déterministe diffère de ses mécanismes actuels à jugement LLM, sans modifier ces derniers.

**Dataset initial proposé :** 200 cas répartis 100 work / 50 validation / 50 holdout,
dimensionnement final avant confirmation. Répartir par familles de documents/provenance, tâche
ou conversation et période ; deux fragments, paraphrases ou révisions de la même origine ne
traversent pas les partitions. Séparer cas réalistes annotés et tests adversariaux construits.
Tout corpus déjà exploré, dont SciFact dans le rapport privé, est un jeu de développement, pas un nouveau
holdout. Les copies de production doivent être bornées, autorisées et expurgées.

Chaque cas conserve : snapshot et date de coupe, requête, langue, contraintes, agent de test et
ACL, documents/révisions/fragments pertinents avec grades 0..3, interdits, budgets et origine
du label. Aucun résultat historique n'est automatiquement la bonne réponse. Inclure noms exacts,
reformulations sans vocabulaire partagé, français/anglais, termes techniques courts, passage
profond/tableau/PJ, corrections contradictoires, sources dépendantes, contact exact, recherche
transversale, document rare/ancien, absence de réponse et fournisseur indisponible.

Deux baselines distinctes :
1. **service dégradé observé**, pour mesurer la réparation opérationnelle ;
2. **hybride sain avec le même modèle configuré**, pour évaluer les gains d'algorithme.
Restaurer les embeddings ne constitue pas à lui seul une preuve d'amélioration du ranking.

Bras offline minimaux : CURRENT exact, lexical seul, vectoriel seul, lexical+vectoriel,
+Topics, +structure documentaire, +liens sémantiques. G1/G2 et normalisation du degré sont
des variantes expérimentales, pas une réduction implicite des quatre sauts documentaires
actuels. Placebos de graphe à degrés/types/portées compatibles et fenêtres temporelles conservées :
un gain similaire au placebo ne valide pas l'apport sémantique du graphe. Ces ablations ne
deviennent pas des options permettant aux agents de dégrader la stratégie canonique.

Mesurer Recall@10 des candidats, nDCG@8/MRR/Precision@8 des résultats, rappel par passage,
taux de faux résultats sur questions sans réponse, utilité et redondance du brief. Rapporter
aussi les pertinents ajoutés **et chassés** par chaque canal, coût SQL, p95/p99, tokens/caractères,
lacunes d'indexation et troncatures. Un arrêt budgété ou un domaine incomplet ne signifie pas
top-k exact ; ne jamais convertir `has_more=false` en certificat d'exhaustivité.

Comparaison appariée par cas, intervalles par grappes de provenance/tâche, pires régressions et
résultats par strate. Aucun taux sur résultats admis sans taux d'abstention/couverture. Les
tests synthétiques démontrent des invariants ; les labels documentaires mesurent la pertinence ;
les tâches réelles mesurent l'utilité aval. Aucun de ces étages ne remplace les autres.

**Expérimentation aval ultérieure :** shadow sans modification des réponses, puis A/A et canari
borné après qualification. Enrôlement des missions racines avant traitement, affectation stable
sur leurs descendants selon le port public Task, horizon H et succès métier préenregistrés,
attestation du comportement réellement exécuté. Conserver en intention de traiter toutes les
racines incluses ; histoire perdue = issue inconnue, pas échec ni exclusion du dénominateur.
Publier succès à H, activité à H, échec terminal, coût et bornes pour les inconnues séparément.
Un enfant tardif, un reparentage ou une suppression ne peut réécrire silencieusement le passé.

Les parcours de lignée doivent diagnostiquer cycles, limites de profondeur, largeur, lignes,
temps et octets ; ne pas traiter un préfixe visible comme une lignée complète. Corriger les
anciennes hypothèses du rapport privé sur parenté/racine depuis les contrats Task actuels avant portage.
IPS/SNIPS reste hors du chemin critique et inutilisable sans vraies probabilités d'action,
support suffisant et plan statistique préenregistré. Le logging seul ne rend rien causal.

### 7.5 Portes de qualification et limites des promesses

| Dimension | Porte proposée avant implémentation |
|---|---|
| Intention durable | 100 % des mutations prises en charge couvertes ; aucun succès sans intention persistée |
| Couverture après rattrapage | 100 % des fragments éligibles pour les formats pris en charge ; chaque exclusion/erreur explicite |
| Fraîcheur | Cible initiale : 99 % des petits documents/PJ textuelles indexés en moins de 60 s, sous charge nominale définie et fournisseur disponible |
| Grands documents | Progression et reprise bornées ; délai cible publié après mesure du volume, jamais de fin silencieusement ignorée |
| Cohérence et droits | Zéro mélange de versions, réintroduction invalide ou résultat refusé à l'admission dans la matrice adverse |
| Génération de candidats | Recall@10 ≥ 95 % sur les cas positifs du corpus validé ; écart par strate publié |
| Classement | Gain nDCG@8 proposé ≥ 5 points sur hybride sain, borne basse du gain apparié positive ; aucune strate critique en recul > 2 points |
| Questions sans réponse | Mesurer le bruit et les réponses non étayées de l'agent ; une liste de candidats non vide est attendue avec le rappel sans seuil, pas une preuve de réponse |
| Graphe | Gain utile supérieur aux placebos, sans hausse non maîtrisée des hubs ni perte de sources rares |
| Coût | Surcoût p95 de l'observation ≤ 10 % proposé ; budget absolu du rappel, SQL et contexte fixé sur validation selon l'infrastructure |
| Effacement | Purge des chunks, générations, caches et traces identifiantes ; aucun job ne ressuscite le contenu |
| Utilité aval | Gain sur le critère métier préenregistré, à horizon et population identiques ; sans données suffisantes, aucune conclusion causale |

Les seuils de qualité et de performance sont des **cibles à qualifier**, ajustables sur work et
validation puis gelées avant holdout ; aucune précision universelle n'est promise. Une cible non
atteinte reste un résultat négatif explicite. Les garanties d'ACL, d'effacement et de fidélité
version/extrait ne peuvent être assouplies pour gagner un score. Le délai de 60 s ne couvre pas
une panne fournisseur ; sa durée et le temps de rattrapage sont mesurés séparément.

### 7.6 Surfaces et garanties de non-régression à reprendre

| Lot | Surfaces principales du dépôt | Scénarios existants à renforcer |
|---|---|---|
| MEM-017 | `retrieval.py`, `access.py`, `service.py`, `context.py`, contrats de sortie fichiers/API | `test_semantic_search.py`, `test_document_sharing.py`, `test_document_grants.py`, `test_document_structure.py` : concurrence, droits frais, révisions et replis |
| MEM-016 | `semantic_index.py`, `automation.py`, `embedding.py`, `models.py`, `dbadmin.py`, tous les writers | `test_semantic_search.py`, `test_acquisition_automation.py`, `test_creation_cancellation.py`, `test_document_structure.py` : durabilité, jobs, rattrapage et descriptions |
| MEM-018 | `semantic_index.py`, `document_structure.py`, `attachment_description.py`, contrats de contenu et de source | `test_editorial_html.py`, `test_document_resources.py`, `test_document_structure.py`, `test_source_associations.py` : fidélité, couverture, PJ et provenance |
| MEM-008 | `file_facade.py`, `facade.py`, `schemas.py`, `app.file_share.resource_service`, MCP, voix, brief et drivers | `test_facade.py`, `test_mcp.py`, `app/file_share/tests/test_resource_service.py`, tests de contexte et navigateur : recherche puis lecture réelles |
| MEM-006/007/009 | `retrieval.py`, `context.py`, `evaluation.py`, contrats/datasets/runs du Lab | `test_recall_evaluation.py`, `test_context.py`, `test_search_performance.py`, `test_agent_correction_eval.py`, tests de publication du Lab |
| MEM-013/014 | `metrics.py`, journal d'usage, état d'index, routes d'administration, interface Memory | `test_metrics.py`, `test_document_library.py`, tests navigateur Memory ; nouveaux scénarios d'observation seulement pour les garanties manquantes |

Les fichiers non préfixés appartiennent à `back/app/memory/`, les tests à son répertoire `tests/`.
Cette matrice désigne des points de départ, pas une liste suffisante de tests de publication.
Tout import inter-module utilise la façade publique ; les changements Task passent par son port
et ceux de fichiers par `app.file_share`. Les contrats/frontend changés devront être qualifiés
sur leurs consommateurs réels, avec i18n et contrôle des droits.

## 8. Lot MEM-001 — Granularité et création pertinente des Topics

### 8.1 Hypothèse et périmètre

La politique historique fragmentait les activités ; sa correction par réemploi peut désormais
absorber un projet durable dans une catégorie trop large. L'hypothèse est de privilégier le
**sujet durable à granularité comparable** : « Refonte de site web », « Site web Machin » et
« Site web Truc » restent des Topics homogènes reliables par les relations existantes.
« Audit du site web Machin » ou « Correction du menu mobile de Machin » restent des activités.

Le candidat reformule les prompts Task/Message pour distinguer équivalence, proximité et
inclusion, conserve le réemploi d'un Topic de même portée et resserre la déduplication : un
recouvrement lexical ne suffit pas à rabattre un projet sur un thème général.

Aucun nouveau modèle, colonne, type de mémoire, type de lien, statut concret/générique,
hiérarchie obligatoire ou reclassement massif. Conserver `DREAM_TOPIC_CREATION_MODE=propose`
pendant la qualification et le canari.

### 8.2 Corpus et métriques

| Dataset proposé | Taille initiale | Usage |
|---|---:|---|
| `topics-granularite-work` | 60 conversations | Développement et erreurs |
| `topics-granularite-validation` | 30 conversations | Sélection du candidat |
| `topics-granularite-holdout` | 30 conversations | Décision finale aveugle |

Chaque conversation comporte 5 à 20 messages, un catalogue figé et une séquence attendue.
Couvrir projets voisins sous un thème, plusieurs activités d'un projet, détail ponctuel,
nouveau sujet, retour A → B → A, pronoms/réponses courtes, pause longue/changement immédiat,
français/anglais, noms propres admissibles, identités privées ou contenus sensibles interdits,
et incidents réels transformés en non-régressions.

Pour toutes les paires de messages d'une conversation :

- précision de regroupement = paires regroupées à raison / paires regroupées ;
- rappel de regroupement = paires regroupées à raison / paires attendues ensemble ;
- F1 = moyenne harmonique de précision et rappel.

Ces mesures pénalisent généralisation et fragmentation sans dépendre du nom exact des Topics.
Ajouter ratio Topics prédits/attendus, singletons, précision/rappel des créations et des
frontières, retours A → B → A, réemploi, créations pour 1 000 messages, coût, durée et erreurs.
La rubrique sémantique du Lab qualifie le nom et le sujet ; elle ne remplace pas ces métriques.

### 8.3 Portes proposées et déploiement

Appliquer le protocole commun, avec au moins cinq répétitions de la politique courante.
Les seuils suivants restent proposés, ajustables sur `work`/`validation` puis gelés avant holdout :

| Dimension | Porte initiale |
|---|---|
| F1 de regroupement | Gain ≥ 5 points ; borne basse de l'IC à 95 % strictement positive |
| Précision et rappel de regroupement | Aucune baisse > 2 points |
| Créations justifiées | Précision ≥ 90 %, rappel ≥ 80 % |
| Réemploi après première occurrence | ≥ 95 % |
| Topics singleton | ≤ 5 % |
| Confidentialité | Aucune nouvelle violation critique |
| Score sémantique | Aucune baisse > 2 points |
| Coût et durée | Hausse < 15 % |
| Couverture et erreurs | Run complet, aucune hausse des erreurs candidat |

Une amélioration moyenne ne compense ni fuite ni retour au « Topic par souvenir ».
Après holdout réussi, conserver un canari en mode `propose`, comparer propositions acceptées,
refusées, corrigées, fusions ultérieures, croissance du catalogue et qualité du rappel.
Le suivi prévu dure deux à quatre semaines : créations pour 1 000 messages, singletons à
30 jours, médiane d'activités par Topic, fusions/scissions/réaffectations, coût, latence,
erreurs et couverture Dream. Les incidents revus enrichissent les non-régressions.

Le rollback restaure le prompt antérieur et son snapshot. Le passage éventuel en mode `auto`
reste une décision ultérieure fondée sur le canari ; ce plan ne l'autorise pas.

Livrer corpus portables, annotations, baseline/candidat, prompts et règle de déduplication
retenus, rapport avant/après, mesures du canari et procédure de rollback. Un prompt modifié
seul ne clôture pas ce lot.

## 9. Cible transversale — Dream crée, Memory organise et fait converger

### 9.1 Frontière de responsabilité

La cible globale sépare les opérations qui exigent une compréhension ou une synthèse ouverte de
celles qui peuvent être reproduites à partir de preuves persistées :

```text
source durable
      │
      ├──► Dream + LLM borné ──► création ou reformulation de contenu
      │                             Topic, souvenir, résumé, proposition structurée
      │
      └──► Memory déterministe ──► provenance, embeddings, déduplication,
                                    associations, réorganisation, vieillissement,
                                    oubli, ACL et rappel
```

Le LLM peut proposer le contenu d’un nouveau Topic ou d’un nouveau souvenir parce que cette
opération demande une abstraction sémantique. Il ne possède jamais directement les liens du graphe
et ne redessine pas les associations existantes. La création d’un Topic pour une source peut
produire son premier rattachement comme effet déterministe du reçu qui a créé ce Topic ; les
rattachements et déplacements ultérieurs reposent sur les données canoniques, les embeddings et une
politique versionnée.

Le RAG reste un chemin de rappel pour présenter du contexte à un LLM. L’entretien du graphe n’est
pas lui-même un RAG et ne requiert aucune génération : un index vectoriel, des requêtes k-NN et un
réconciliateur d’état désiré suffisent. Le fournisseur d'embeddings est celui qui est configuré,
local ou distant ; ses coûts et limites sont mesurés sans en choisir un autre.

### 9.2 Matrice cible des mécanismes

| Opération | Signal principal | LLM autorisé | Autorité d’application |
|---|---|---:|---|
| Éligibilité d’une source | état, type, longueur, provenance | non | service du domaine source |
| Extraction d’un fait durable | contenu et contexte bornés | oui, sortie structurée | `app.memory` |
| Création ou reformulation d’un Topic | sujet durable à nommer | oui, sortie structurée | `app.topic` |
| Rattachement initial au Topic nouvellement créé | reçu et source ayant motivé la création | non | `app.topic` puis projection Memory |
| Détection de doublons | similarité, scope et provenance | non | `app.memory` |
| Association et réorganisation du graphe | embeddings et structure canonique | non | réconciliateur `app.memory` |
| Fusion ou scission suggérée | cohésion, séparation et densité | non | proposition gouvernée |
| Contradiction sémantique | candidats vectoriels et preuves textuelles | exceptionnel et borné | maintenance gouvernée |
| Vieillissement et oubli | dates, usage réel, autorité et politique | non | `app.memory` |
| Rappel pour une exécution | lexical, vectoriel, graphe et ACL | non dans le socle ; reclasseur spécialisé seulement en expérience séparée | `app.memory` |

Une ambiguïté ne doit pas provoquer un appel LLM automatique pour « sauver » une association.
Elle laisse l’affectation inchangée, produit au besoin une suggestion explicable ou attend une
correction humaine. Un LLM éventuellement employé pour qualifier une contradiction ne reçoit
qu’une paire de candidats déjà autorisés et ne peut pas modifier directement le graphe.

### 9.3 Quatre couches à ne plus confondre

La cible distingue :

1. **la provenance**, immuable et auditable : Task, round, tour Voice, Goal ou autre source ayant
   produit ou confirmé un souvenir ;
2. **le contenu durable**, révisionnel : texte, type, dates et ressources du
   `MemoryItem` ;
3. **l’organisation courante**, évolutive : Topic principal ou secondaire, voisins sémantiques,
   confiance et version de politique ;
4. **les décisions explicites**, prioritaires : lien manuel, affectation épinglée, correction,
   partage et oubli.

Le Topic porté par la Task ou le round d’origine reste une preuve historique. Il ne doit pas
imposer à perpétuité l’emplacement courant du souvenir. Inversement, déplacer un souvenir dans un
Topic plus précis ne réécrit pas l’activité historique qui l’a produit.

Avant toute réorganisation automatique, une décision d’architecture devra donc choisir et tester
une représentation explicite de l’organisation courante : relation distincte de la provenance ou
override persistant que le réconciliateur canonique respecte. Modifier seulement une arête
`topic_contains` existante est insuffisant, car sa reconstruction depuis les sources pourrait
annuler le déplacement au sweep suivant. Cette décision devra mettre à jour les ADR 0020 et 0026.

### 9.4 Propriété et durée de vie des liens

Chaque arête doit avoir un propriétaire et une politique de suppression non ambigus :

| Famille | Exemple | Peut être remplacée automatiquement | Priorité |
|---|---|---:|---:|
| Canonique | provenance, contact exact, cycle de Goal | seulement depuis sa source d’autorité | maximale |
| Manuelle/épinglée | affectation ou relation choisie explicitement | non | maximale |
| Organisationnelle gérée | appartenance Topic courante | oui, par sa seule politique versionnée | moyenne |
| Sémantique dérivée | voisin, candidat de fusion ou de scission | oui, entièrement reconstructible | faible |

Une projection automatique ne prend jamais possession d’un lien manuel de même triplet. Une
association de co-présentation ou de co-rappel n’est pas une preuve métier : l’utiliser pour
tisser des liens créerait une boucle auto-renforçante où les souvenirs déjà injectés deviennent
artificiellement centraux.

### 9.5 Entretien incrémental et borné

La convergence globale ne doit pas recalculer naïvement le produit cartésien de tous les Topics
et souvenirs :

- création ou modification d’un souvenir : k-NN borné vers les Topics et voisins accessibles ;
- création ou modification d’un Topic : k-NN inverse vers les souvenirs potentiellement mieux
  classés ;
- fin d’une opération Dream : réconciliation ciblée des UUID effectivement touchés ;
- changement de modèle d’embedding ou de politique : rebuild versionné et reprenable ;
- sweep global à faible charge : correction de la dérive et suppression des projections
  obsolètes ;
- recalcul d’embedding uniquement lorsque l’empreinte sémantique du nœud a changé.

Les jobs restent idempotents, coalescés, observables et préemptibles par le travail interactif.
Une panne du fournisseur vectoriel conserve les liens organisationnels courants et ne les efface
pas sous prétexte que l’état désiré n’a pas pu être calculé.

### 9.6 Dream comme producteur de deltas sémantiques

L’amélioration continue ne doit pas transformer Dream en boucle générative permanente. Chaque
mécanisme déclare séparément :

- son éligibilité déterministe et les raisons fermées d’ignorer une source ;
- l’unique étape qui exige éventuellement un LLM ;
- l’empreinte de l’entrée qui rend un ancien résultat encore valide ;
- la version du prompt, du schéma, du modèle et de la politique ;
- les UUID créés, modifiés, fusionnés ou oubliés ;
- les jobs déterministes ciblés que ce delta doit déclencher ;
- son coût, sa durée et la preuve que son effet a réellement été appliqué.

```text
source nouvelle ou modifiée
        │
        ├── empreinte déjà traitée ──► aucun appel
        └── besoin de synthèse ouvert ──► un appel structuré borné
                                             │
                                             └──► delta d’UUID
                                                     ├─ indexation ciblée
                                                     ├─ déduplication
                                                     └─ réconciliation du graphe
```

Un résultat vide admissible conserve un reçu versionné afin que Dream ne paie pas de nouveau la
même conclusion. Une reprise réapplique l’effet checkpointé sans réinterroger le modèle. Les
mécanismes sont ordonnés selon leurs dépendances de preuve et leur utilité attendue, avec budgets
par période, backpressure pendant le travail interactif et observabilité du backlog.

Le coût pertinent n’est pas seulement le nombre de tokens Dream : il doit être rapporté au nombre
de souvenirs utiles effectivement appliqués, de doublons évités, de corrections détectées et de
gains aval mesurés. Un mécanisme qui produit beaucoup de contenu inutilisé doit pouvoir être
ralenti, désactivé ou remplacé par une règle déterministe, même si sa sortie semble plausible.

## 10. Lot MEM-010 — Réorganisation continue des Topics et du graphe

### 10.1 Problème observé

Les détections actuelles savent signaler une mémoire orpheline, un membre éloigné, deux Topics
proches ou des groupes pouvant justifier une scission. Elles ne convergent pas encore vers une
meilleure organisation des items lorsque le catalogue de Topics évolue.

Cas cible : un Topic générique contient des souvenirs SQLAlchemy, FastAPI, Vue et Quasar. Deux
Topics plus précis, « Python backend » et « Vue frontend », sont créés plus tard. Les souvenirs
qui correspondent nettement mieux à l’un de ces Topics doivent y être déplacés sans appel LLM,
sans perdre leur provenance et sans attendre une correction manuelle item par item.

### 10.2 Hypothèse

Une affectation vectorielle relative au catalogue courant, protégée par une marge, une hystérésis
et des pins manuels, doit augmenter la cohésion des Topics et la qualité du rappel tout en évitant
les oscillations et les déplacements plausibles mais faux.

La proximité absolue ne suffit pas. Un déplacement n’est admissible que si le candidat est assez
proche **et** sensiblement meilleur que l’affectation actuelle. Les valeurs sont évaluées avec le
modèle configuré, sans seuil universel supposé entre modèles.

Complément du rapport privé retenu : avant fusion ou subdivision, compter les origines dépendantes plutôt
que les chunks ou replays ; une origine inconnue ne devient pas une preuve indépendante.
Préserver les exceptions et les requêtes rares. Les propositions géométriques restent des
candidats ; elles ne créent pas automatiquement un concept ou un nouveau type de lien. Séparer
organisation conceptuelle, partitions techniques de l'index et chemins d'activation. Dormance,
redirections et forces adaptatives restent des sous-lots expérimentaux, après qualification du
rappel documentaire et de l'observation, sans effacement automatique dû à une faible exposition.

### 10.3 État désiré d’une affectation

Pour chaque souvenir admissible, le plan de réconciliation conserve :

- le ou les Topics d’origine provenant des sources ;
- le Topic organisationnel courant ;
- le meilleur Topic candidat et les `k` suivants ;
- les similarités courante et candidate ;
- la marge observée ;
- le modèle, l’empreinte sémantique et la version de politique ;
- le nombre d’observations stables et la date du dernier changement ;
- l’origine `manual`, `source_default` ou `semantic` et un éventuel pin ;
- la raison expliquant un maintien, une proposition, un déplacement ou une suppression.

Une relation candidate peut rester une projection reconstructible. L’affectation courante doit en
revanche avoir une autorité persistante que le réconciliateur des provenances ne remplace pas.

### 10.4 Politique de réaffectation candidate

Les valeurs suivantes sont des points de départ à qualifier sur `work` et `validation`, pas des
constantes acceptées :

```text
créer une proposition si :
    similarité_cible >= 0,65
    ET similarité_cible - similarité_actuelle >= 0,10

appliquer automatiquement si :
    la proposition reste identique pendant au moins 2 sweeps
    OU la marge dépasse un seuil fort préenregistré

conserver l’affectation courante si :
    le candidat reste dans la bande d’hystérésis

retirer un lien dérivé si :
    il sort du top-k ou reste sous le seuil bas pendant N sweeps
```

La sélection doit être déterministe à snapshot identique, y compris en cas d’égalité. Elle ne
compare que des nœuds autorisés dans le même périmètre de propriétaire. Un souvenir scellé à un
contact peut changer de Topic, jamais de contact. Un document de travail, une projection
source-managed ou un type de mémoire particulier peut être exclu par politique explicite plutôt
que par effet secondaire.

### 10.5 Application d’un déplacement

Un déplacement automatique validé doit former une seule transition idempotente :

1. verrouiller l’item et ses affectations organisationnelles ;
2. revérifier les empreintes et la politique ayant produit la proposition ;
3. créer ou mettre à jour l’affectation cible ;
4. retirer uniquement l’ancienne affectation possédée par la même politique ;
5. déplacer le scope Topic/contact organisationnel sans toucher au scellement du contact ;
6. conserver toutes les `MemorySource` et les Topics historiques des activités ;
7. journaliser source, cible, scores, politique, snapshot et cause ;
8. relancer l’indexation ou le rappel seulement pour les nœuds affectés.

Une affectation manuelle ou épinglée bloque l’étape 3 et produit un diagnostic, jamais une
mutation. Une correction manuelle ultérieure doit pouvoir déplacer l’item et poser le pin dans la
même transaction logique.

### 10.6 Topics génériques et Topics précis

Les embeddings peuvent montrer qu’un souvenir est plus proche d’un Topic précis que de son Topic
générique. Ils ne prouvent pas à eux seuls le sens orienté « est une spécialisation de ». Deux
stratégies devront donc être comparées :

- **classement plat** : l’item quitte le Topic générique et rejoint le Topic précis ;
- **navigation hiérarchique** : l’item appartient au Topic précis et un lien Topic→Topic permet
  au générique de l’exposer indirectement.

Une hiérarchie ne doit pas être inférée depuis le seul cosinus. Elle demanderait au minimum une
preuve structurelle supplémentaire — ensemble de membres, cohésion, couverture et stabilité — ou
une validation explicite. Elle constitue un sous-lot ultérieur et ne bloque pas le classement plat.

### 10.7 Dataset et cas obligatoires

Le benchmark de réorganisation doit rejouer des snapshots successifs, pas seulement classer des
paires isolées. Chaque cas fournit un graphe initial, une séquence de créations ou modifications et
le graphe final attendu.

Il couvre au minimum :

- un Topic générique puis deux Topics plus précis créés ultérieurement ;
- un item qui doit rester dans le Topic générique ;
- un candidat proche sans marge suffisante ;
- une affectation manuelle épinglée ;
- un souvenir issu de plusieurs sources ou Topics historiques ;
- un souvenir conversationnel dont le contact doit rester inchangé ;
- la modification puis la suppression d’un Topic cible ;
- une fusion et une scission administratives concurrentes avec un sweep ;
- un changement de modèle ou de dimension d’embedding ;
- un fournisseur d’embeddings indisponible ;
- un job interrompu puis repris ;
- une seconde exécution strictement idempotente ;
- un volume représentatif permettant de mesurer latence et amplification d’écritures.

### 10.8 Métriques et portes initiales

Mesures principales :

- précision et rappel des items à déplacer ;
- exactitude de la cible parmi les déplacements justifiés ;
- cohésion intra-Topic et séparation inter-Topics avant/après ;
- taux d’items orphelins ou maintenus dans un Topic trop générique ;
- taux de churn des affectations par sweep et temps jusqu’à convergence ;
- impact sur Recall@k, précision@k et diversité du brief ;
- nombre d’embeddings recalculés et requêtes vectorielles par nœud modifié ;
- latence p50/p95, écritures DB et durée du sweep global ;
- nombre d’appels et coût LLM consacrés aux associations, qui doivent rester nuls.

Portes proposées avant baseline :

- précision des déplacements automatiques au moins égale à 95 % ;
- exactitude de cible au moins égale à 95 % ;
- aucun déplacement d’une affectation épinglée ;
- aucune modification de contact, ACL, provenance, contenu ou révision d’un souvenir ;
- zéro suppression de lien canonique ou manuel non possédé par la politique ;
- après convergence, churn inférieur à 1 % des affectations par sweep ;
- aucune baisse de Recall@5 ou de précision@5 supérieure à 2 points ;
- aucune fuite inter-agent ou inter-contact sur les suites adversariales ;
- zéro appel LLM sur le calcul et l’application des associations ;
- exécution interrompue puis reprise donnant le même graphe final qu’une exécution continue.

### 10.9 Déploiement progressif et rollback

1. **simulation** : calculer les mouvements sans persister de candidats ;
2. **shadow** : persister les propositions et leur explication sans influencer rappel ni graphe ;
3. **suggestion** : les exposer à l’administration et mesurer acceptations/corrections ;
4. **canari automatique** : appliquer seulement les marges fortes à une population bornée ;
5. **généralisation** : élargir après holdout et canari positifs.

Chaque mutation conserve assez d’audit pour reconstruire l’ancienne affectation. Le rollback
désactive d’abord l’application automatique, restaure le dernier snapshot organisationnel validé
et relance le réconciliateur en excluant la politique fautive. Il ne restaure ni ne réécrit les
contenus, provenances ou ACL, puisqu’ils n’ont jamais été modifiés par ce lot.

### 10.10 Livrables envisagés

- ADR séparant provenance thématique et organisation courante ;
- représentation et contrat public des affectations gérées et pins manuels ;
- planificateur k-NN ciblé et sweep global reprenable ;
- mode simulation/shadow et explications de chaque candidat ;
- datasets temporels `work`, `validation` et `holdout` ;
- benchmark de qualité, stabilité, coût et impact sur le rappel ;
- tests DB de concurrence, idempotence, ACL, contacts, fusion, scission et rollback ;
- observabilité des candidats, mouvements, refus, churn et coûts ;
- interface de diagnostic et correction proportionnée au mode de déploiement.

## 11. Registre extensible des axes d’amélioration

Ce registre est l’entrée principale pour ajouter de nouvelles idées. Une ligne ne constitue ni une
solution retenue ni une autorisation d’implémenter.

| ID | Axe ou problème | Statut | Première question de benchmark |
|---|---|---|---|
| `MEM-001` | Granularité et création pertinente des Topics | cadré ci-dessus | Le F1 de regroupement progresse-t-il sans hausse des singletons ? |
| `MEM-002` | Sélectivité de l’extraction automatique | à cadrer | Quels faits utiles sont ignorés et quels détails ponctuels sont retenus ? |
| `MEM-003` | Déduplication et identité logique des faits | campagne à cadrer | Combien de doublons et de faux `LINK` apparaissent par source ? |
| `MEM-004` | Contradictions, autorité et temporalité | campagne à cadrer | Le rappel présente-t-il le fait valide et signale-t-il les désaccords utiles ? |
| `MEM-005` | Vieillissement, consolidation et oubli | à cadrer | Quels souvenirs périmés restent influents et lesquels sont oubliés trop tôt ? |
| `MEM-006` | Classement par passages, canaux et ablations | cadré §7.2 et §7.4 | Recall@k et précision@k progressent-ils sous ACL et scopes réels ? |
| `MEM-007` | Passages complémentaires, URI et budget du brief | cadré §7.2 | Chaque token injecté ajoute-t-il une information utile non redondante ? |
| `MEM-009` | Utilité aval, horizon et cohortes gouvernées | cadré §7.4 | Une mémoire pertinente améliore-t-elle le résultat par rapport à une exécution sans rappel ? |
| `MEM-010` | Réorganisation continue des Topics et du graphe | cadré ci-dessus | Les items convergent-ils vers le meilleur Topic sans faux déplacements, oscillations ni appel LLM ? |
| `MEM-011` | Provenance par passage et correction opérateur | cadré avec MEM-018 §7.1 | Un humain peut-il expliquer et corriger rapidement chaque souvenir présenté ? |
| `MEM-012` | Confidentialité, partage et oubli vérifiable | transverse à tous les lots | Les suites adversariales prouvent-elles zéro fuite et un oubli physique complet ? |
| `MEM-013` | Santé de l'index et observation distincte de l'utilité | cadré §7.3 | Où se situent les dégradations de qualité, latence, volume et coût ? |
| `MEM-014` | Diagnostic, couverture et réparation opérateur | cadré §7.3 | L’interface permet-elle de diagnostiquer sans exposer ni encourager de mauvaises mutations ? |
| `MEM-015` | Orchestration, utilité marginale et budget de Dream | cadré transversalement | Quel effet durable et quel gain aval chaque appel LLM produit-il par euro, seconde et source traitée ? |
| `MEM-018` | Extraction nouvelle des PJ et provenance fine | cadré §7.1 | Un détail nouvellement acquis reste-t-il retrouvable, localisable et fidèlement sourcé ? |

Toute nouvelle observation entre dans ce registre avec sa preuve, sa question de benchmark et
son prochain travail d'instruction. Les comptes rendus d'expériences terminées vont dans
`project/audits/` et sont liés depuis le lot concerné.

## 12. Ordonnancement, dépendances et livraison

Le socle documentaire est un acquis. La baseline des expériences utilise le moteur courant,
ses générations d'index et son admission ; elle ne reproduit pas les lots déjà livrés.

| Lot restant | Contenu et dépendances | Preuve de sortie | Retour arrière |
|---|---|---|---|
| A — Classement mesuré | MEM-006 et campagnes Lab §7.4 ; modèle configuré constant | Holdout, ablations, gain utile et coût mesuré ; alias, langues et négatifs documentés | Politique de classement précédente, index et admission conservés |
| B — Extensions de PJ | Extraction nouvelle et provenance fine de MEM-018/MEM-011 | Couverture, localisations, droits et révisions préservés | Désactiver l'acquisition nouvelle, conserver les textes déjà acquis |
| C — Observation et utilité aval | MEM-013 détaillé et MEM-009 ; shadow avant canari | Traces bornées, A/A et horizon préenregistré | Désactiver l'expérience sans changer le moteur sain |
| D — Capture et organisation | MEM-001/002/003, MEM-010 en simulation, MEM-004/005 sur erreurs observées | Gains de capture/rappel, pins, provenance et oubli préservés | Affectations restaurables sans réécrire les sources |

MEM-012 (droits/oubli), MEM-014 (diagnostic) et MEM-015 (budgets Dream) accompagnent chaque
expérience. Une extraction nouvelle n'est pas requise pour indexer un texte déjà disponible.

Avant chaque lot : inventaire des consommateurs, garantie observable, scénario reproduisant le
défaut ou baseline, seuils, limites et rollback. Développer un premier parcours complet, puis
étendre par groupes de consommateurs. Les modifications de schéma passent par les modèles
SQLAlchemy et DbAdmin ; pas de DDL/Alembic recopié depuis les prototypes du rapport privé. Les choix
structurels (générations, admission, extraction, traces) donnent lieu aux ADR concernés.

Toute future publication requiert la qualification du snapshot courant par `make validate`,
lecture de son rapport et revue des résultats. Une édition ultérieure invalide cette qualification.
Les autorisations reçues couvrent la lecture du document de production, le remaniement du plan,
l'implémentation et les essais en développement. Elles n'autorisent pas la réparation,
l'activation de traces ou un canari en production.

## 13. Critères de réussite et clôture

Les améliorations préservent les garanties documentaires et d'admission de 0108.
Le travail restant produit une amélioration crédible lorsque :

- la pertinence documentaire progresse face à un hybride sain utilisant le même modèle configuré ;
- les résultats du rapport privé repris sont reproduits sur le code actuel et distingués des preuves encore
  expérimentales, sans transformer leurs nombres de tests en gains de production ;
- chaque mécanisme Memory important possède une baseline et un holdout revu ;
- les métriques couvrent capture, organisation, rappel, utilité aval, gouvernance et coût ;
- Dream réserve les appels LLM aux créations et interprétations qui en ont besoin, tandis que
  l’entretien courant des associations converge sans appel génératif ;
- une source inchangée et déjà checkpointée ne provoque pas un nouvel appel LLM, et chaque effet
  Dream expose les UUID touchés aux traitements déterministes ciblés ;
- l’organisation courante peut évoluer sans réécrire les sources historiques et sans qu’un sweep
  canonique annule silencieusement un déplacement validé ;
- les changements promus franchissent des gates préenregistrés et restent positifs en canari ;
- les incidents réels enrichissent les non-régressions au lieu de rester des anecdotes ;
- une dégradation peut être attribuée à une variable, détectée rapidement et rollbackée ;
- aucune amélioration moyenne ne masque une fuite ACL, un faux lien critique ou un oubli incomplet ;
- le plan reste assez lisible pour accueillir de nouveaux constats sans les transformer trop tôt
  en solutions techniques.

## 14. Validation attendue pour les futures implémentations

Selon le lot concerné :

- tests unitaires des règles pures et métriques déterministes ;
- tests d’intégration DB pour acquisition, provenance, liens, ACL, révision et oubli ;
- exécution side-effect-free du vrai mécanisme dans le Lab ;
- tests ciblés, puis `make typecheck` et `make architecture-check` ;
- `make project-context` si les surfaces, modèles, routes, outils ou settings changent ;
- tests de contrats fichiers, composants/UI et quelques E2E pour recherche → lecture → injection ;
- revue des migrations déclaratives, rétention et invalidations si les schémas évoluent ;
- `make validate` avant publication, lecture de `artifacts/validation/*/summary.txt` ;
- `git diff --check` et revue du diff sans écraser les modifications en cours.

Le remaniement documentaire seul ne réexécute pas les benchmarks, ne régénère pas la cartographie
et ne vaut pas qualification du runtime. Sa validation porte sur les sources, les liens, la
cohérence des statuts, l'ordonnancement et le diff.
