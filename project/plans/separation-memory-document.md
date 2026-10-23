# Séparation définitive de Memory et Document

- Statut : `in-progress`
- Date : 2026-10-23
- Demande : souvenirs privés par agent, retrait de leur partage en base et dans le
  code, création du domaine `app.document`.
- Réalisation : séparation des modèles, services, routes et frontend implémentée ;
  migrations et consommateurs qualifiés. Revue des baselines d'architecture en
  attente avant clôture.

## Garanties recherchées

Un souvenir possède exactement un agent propriétaire. Aucun droit global, droit
d'équipe, grant individuel, classement documentaire ou privilège de partage ne
permet à un autre agent de lire ou modifier ce souvenir. Les humains autorisés à
administrer cet agent conservent leur accès de gestion ; cette capacité ne devient
pas un droit attribué à leurs autres agents.

`app.document` possède les documents éditoriaux, leurs contenus, versions,
propriétaires humains ou agents, classements personnels, dossiers, pièces jointes,
applications et droits. Un document existe sans souvenir obligatoire. Sa création,
sa lecture, son partage et sa suppression ne passent plus par le service Memory.
Un souvenir qui référence un document n'en devient ni le contenu de référence ni
une ressource partagée.

La séparation concerne les modèles, services, surfaces publiques, routes, outils,
frontend, tests et documentation. Un package de réexport au-dessus de
`app.memory` ne satisfait pas ce contrat.

## État établi dans le code

- `MemoryItem` hérite de `Shareable` et stocke encore `share_id` et `share_kind`.
  Les souvenirs autonomes refusent déjà les créations non privées et les grants
  dans les services ; la persistance conserve toutefois la capacité générique.
- `Document` possède sa table de contenu mais exige un `memory_item_id` unique,
  le même UUID et une identité de partage commune avec `MemoryItem`.
- `DocumentRevision` dépend d'une ligne de `memory_revisions` pour le snapshot.
- Les métadonnées, mots-clés, propriétaires et verrou optimiste nécessaires au
  document sont encore portés par le nœud mémoire.
- Les synthèses documentaires et leur historique `MemorySummaryRevision` sont
  communs aux lecteurs du document. `update_memory_content()` les autorise selon
  les droits documentaires, pas selon une propriété personnelle.
- Les projections de documents, Topics, dossiers et pièces jointes participent
  au graphe, à la recherche et aux index. Elles ne doivent pas être assimilées
  implicitement aux souvenirs privés d'un agent.
- Les routes documentaires sont sous `/memory/documents`, les composants et les
  appels frontend sous `front/app/memory`, et plusieurs consommateurs métier
  passent par la façade Memory pour accéder aux documents.

Sources : `back/app/memory/models.py`, `service.py`, `access.py`, `router.py`,
`semantic_index.py`, `retrieval.py`, `__init__.py`, `file_facade.py`, les suites
`test_document_split.py`, `test_document_sharing.py` et `test_document_structure.py`,
et la décision [0162](../decisions/0162-document-and-memory-synthesis.md).

## Choix retenus

1. **Synthèses partagées existantes.** Accord utilisateur : conserver leur contenu comme
   résumé documentaire, avec leur historique et leurs droits actuels, dans
   `app.document`. De nouveaux souvenirs à propos d'un document sont privés et
   indépendants. Une conversion des anciennes synthèses en souvenirs privés
   demande une règle explicite d'attribution ; le propriétaire du document,
   l'auteur de la dernière version et les agents lecteurs ne sont pas équivalents.
   Aucune attribution, duplication entre agents ou suppression implicite.
2. **Ressources du graphe.** Conserver les références aux documents
   et Topics autorisés, résolues par leurs domaines avec leurs droits courants.
   Leur représentation n'accorde aucun accès aux souvenirs d'un autre agent.
   Le retrait complet de ces références reste une autre portée possible.

Le contrat public de mémoire personnelle doit rester indépendant du modèle
Document et de son index : l'utilisateur souhaite pouvoir intégrer ultérieurement
un gestionnaire de mémoire tiers. Aucun moteur tiers n'est choisi par ce chantier.

## Répartition cible

| Domaine | Responsabilités |
|---|---|
| `app.memory` | Souvenirs personnels, acquisition, provenance, contacts propres à l'agent, rappel et contexte privé, oubli, maintenance et Dream sur ces souvenirs. |
| `app.document` | Contenu éditorial, titres, mots-clés documentaires, historique, droits, dossiers, classement, pièces jointes, vignettes, export, applications et recherche documentaire. |
| `app.topic` | Sujets canoniques ; Memory ou Document les référencent par un contrat public. |
| `app.dataset` | JSON, droits et versions Dataset ; seuls les adaptateurs historiques nécessaires subsistent. |
| `app.process` | BPMN, historique et exécutions Process ; aucun transfert de ces définitions vers Document. |
| `app.file_share` | Résolution et accès aux URI `memory://` et `document://` via leurs propriétaires respectifs. |

Déclarer le nouveau module dans `back/modules.py` et `front/modules.ts`. Garder
des contrats publics explicites et des racines légères. Aucun import d'un service
ou modèle privé étranger pour remplacer les anciens imports internes de Memory.

## Contrat de persistance et de migration

- Conserver les UUID et URI documentaires, contenus, ressources binaires,
  révisions, auteurs, dates, tombstones, pièces jointes, classements et droits.
- Rendre le document indépendant d'une ligne `memory_items`. Transférer ses
  métadonnées et son verrou optimiste vers son propriétaire documentaire avant
  d'abandonner l'ancien verrou commun.
- Rendre les snapshots documentaires indépendants de `memory_revisions`.
  Conserver leurs numéros, pointeurs de ressources et provenance, sans réécriture
  des octets ni perte des versions historiques.
- Déplacer les clés étrangères des tables documentaires vers les identités de
  Document. Traiter séparément les références vers Dataset et Process ; ne pas
  perpétuer un `_id` sans clé étrangère vers le domaine propriétaire.
- Retirer des souvenirs les colonnes de partage, les anciennes tables de grants
  mémoire et le type `memory` du partage générique après transfert vérifié des
  politiques encore nécessaires aux documents et dossiers. Ne pas supprimer un
  grant documentaire sous prétexte qu'il provient d'une ancienne table Memory.
- Rendre obligatoire l'agent propriétaire d'un souvenir personnel. Les nœuds
  structurels ou publics existants doivent être transférés ou reconstruits selon
  leur nature avant le resserrement de cette contrainte.
- Conserver les archives historiques de la décision 0162 et les ressources
  auxquelles elles renvoient. Leur purge ne fait pas partie de ce chantier.

Les opérations passent exclusivement par des contributions `DbAdminAction`.
Préserver les obligations inachevées déjà enregistrées sous leurs clés stables,
même lorsque leur implémentation est déplacée vers le nouveau module.

Préparer une sauvegarde vérifiée hors de `public`, transférer avec des opérations
idempotentes, puis vérifier les postconditions avant toute contraction. L'échec
d'une préparation doit préserver les sources et empêcher le retrait correspondant.
Qualifier la reprise après chaque phase, le rollback et la conservation des
ressources externes à la transaction SQL. Aucune intervention en production n'est
autorisée par ce plan.

## Contrats et consommateurs à transférer

1. Modèles et schémas documentaires, droits et héritage des dossiers, classement,
   applications et pièces jointes.
2. Services CRUD, historique/restauration, recherche et indexation documentaires.
3. API documentaire indépendante ; conserver ou retirer explicitement les anciens
   chemins avec une politique de compatibilité documentée. Les anciennes routes
   de partage Memory ne doivent pas devenir une porte d'accès aux souvenirs.
4. Outils documentaires et provider `document://` ; le Tool Memory ne porte plus
   d'opération de partage de souvenirs. Préserver les politiques de fonctions et
   connexions existantes lors d'un transfert de catalogue.
5. Consommateurs File Share, Goal, Conversation, Dataset, Process, Dream,
   annotations de ressources et préparation du contexte des agents.
6. `front/app/document` : bibliothèque, éditeur, partage, classement, historique,
   services et types propres. `front/app/memory` garde le parcours des souvenirs.
   Préserver la navigation `/documents`, les liens publiés, l'i18n et les droits.
7. Conventions, guides FR/EN, skills Galaris concernés, décision structurelle et
   cartographies générées.

Inventorier les privilèges et leurs affectations avant de créer les privilèges
Document. Leur transfert ne doit ni supprimer les accès existants ni donner à
des lecteurs le droit d'administrer les documents.

## Réception et preuves

### Reprise après interruption

Les suites de bibliothèque et d'héritage déjà transférées sont regroupées sous
`app/document/tests` ; les deux garanties de liste des souvenirs récents restent
dans Memory. Les autres consommateurs documentaires sont transférés avec leurs
tests, sans maintenir une seconde implémentation documentaire dans Memory.

L'ancien `test_document_split.py` vérifiait une étape intermédiaire où Document
dépendait encore de Memory et où les souvenirs portaient des grants. Cette
représentation est retirée. La conservation des identités, contenus, pointeurs,
révisions, synthèses, URL et droits est désormais vérifiée par
`test_independence_upgrade.py` et `test_migration_preservation.py`, via le vrai
pipeline PostgreSQL/Atlas, avec interruption et rejeu. Les contrats privés et le
refus d'écrire un résumé documentaire par Memory sont dans `test_boundary.py`.
La qualification des consommateurs et de l'application assemblée est effectuée.
Les parcours de création dans les dossiers, navigation entre bibliothèque et Chat,
et rafraîchissement distant des contenus et des droits passent dans une pile
isolée. La reprise de développement a transféré les documents et révisions puis
retiré l'ancienne colonne d'identité, avec une archive vérifiée conservée. Les
baselines d'architecture restent en attente de revue explicite (ADR 0223) ; ce
point empêche encore la clôture du chantier et le succès de `docs-prepare`.

Les scénarios d'HTML éditorial sont transférés vers
`app/document/tests/test_editorial_content.py`. L'indisponibilité d'une projection
est qualifiée dans `test_projection_failure.py`, avec des erreurs de provider et
de PostgreSQL dans une session isolée. Les anciens scénarios qui ajoutaient une
provenance personnelle à un Document vérifient maintenant le refus de cette
mutation et la création d'un souvenir privé indépendant. Une proposition de
fusion vers un Document lisible crée ou retrouve le souvenir privé de l'agent ;
sa provenance personnelle n'est pas ajoutée au Document. Les droits
documentaires restent couverts par les suites de partage. Les assertions de
grants dans les réponses Memory et de titre éditable d'un souvenir personnel
sont retirées avec ces anciens contrats. Les versions du corps documentaire
utilisent `DocumentRevision` ; les marqueurs historiques de reprise restent
qualifiés sur leur ancienne table avant contraction.

Les vérifications de reprise ont révélé deux écarts supplémentaires : le champ
hérité `documents.memory_item_id` doit rester fourni dans les INSERT pendant
l'expansion, même pour un `ON CONFLICT`, et l'inventaire des fichiers doit lire
les manifestes Document courants/historiques sans dépendre d'une référence
Memory. Les fixtures de migration couvrent désormais la colonne obligatoire.
Les diagnostics DbAdmin longs conservent leur cause initiale et leur fin après
masquage du mot de passe.

| Garantie | Vérification |
|---|---|
| Un agent ne lit, rappelle, recherche, modifie ni ne partage les souvenirs d'un autre. | Scénarios DB/API/MCP avec deux agents, même équipe et même gestionnaire humain, grants historiques et modes globaux. |
| Aucun partage mémoire ne subsiste en persistance. | Inspection des métadonnées cibles et de la base isolée après contraction ; absence des colonnes et types retirés. |
| Un document existe et fonctionne sans souvenir. | Scénario de création, lecture, édition, partage, historique et suppression sans ligne personnelle Memory. |
| Les données historiques sont conservées. | Migration PostgreSQL synthétique avant/après : identités, pointeurs, contenus, versions, auteurs, tombstones, droits et pièces jointes. |
| La migration reprend sans duplication ni perte. | Rejeu, interruption entre phases, erreur injectée et postconditions sur les données réelles. |
| Les droits documentaires restent effectifs. | Équipes vivantes, héritage, révocation, accès humains distincts des agents, refus après révocation et réponses tardives. |
| Les domaines Dataset et Process restent autonomes. | Tests de persistance/API et tests d'architecture existants adaptés aux nouveaux contrats. |
| Les consommateurs fonctionnent après séparation. | Parcours File Share, Goal, Conversation, Dream et recherche avec ressources existantes. |
| L'interface reste utilisable. | Application assemblée : création/ouverture/réouverture, sauvegarde et conflits, partage et retrait, historique, erreurs/retry, navigation, clavier et petit écran. |
| La séparation est réelle. | Contrôles d'architecture et inventaire des imports ; aucun réexport documentaire permanent depuis Memory ni dépendance obligatoire Document → souvenir. |

Réutiliser les scénarios existants au lieu de dupliquer les suites. Une attente
historique de synthèse commune doit être déplacée vers Document ou remplacée par
la nouvelle garantie de propriété explicitement retenue, pas simplement supprimée.

Lancer les tests ciblés par `make tests`, les contrôles de typage et d'architecture,
`make docs-prepare` et `git diff --check`. Appliquer et inspecter la synchronisation
en développement une fois le transfert qualifié sur base isolée. `make validate`
reste réservé à l'utilisateur. Ne déclarer le plan réalisé qu'après ces preuves ;
une extraction de fichiers seule reste incomplète.
