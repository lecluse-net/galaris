# 0106 — Structure documentaire déterministe et mémoire des pièces jointes

Statut : accepté — 17 septembre 2026. Référence : #168.

## État des lieux vérifié

| Surface | Existant conservé | Extension |
| --- | --- | --- |
| `memory.models.MemoryItem`, `service.list_graph_roots` | Chaque document est déjà un nœud ; inventaire paginé, sans seuil sémantique. | Aucun second nœud document. Types `attachment` et `folder` distincts. |
| `document_attachment_service` et `file_facade` | Manifeste, liste des PJ et URI `document://…/attachments/…` ; anciennes PJ conservées pour les révisions. | Table de correspondance `DocumentAttachment`, pointeur unique vers Memory, exposé dans les listes de ressources. |
| `document_tags`, `document_order` | Arborescences personnelles, identités UUID, plusieurs rattachements possibles ; supprimer une branche reclasse les documents sans les effacer. | Nœuds de dossiers et liens automatiques. |
| `retrieval` | Recherche lexicale/vectorielle ; les voisins seuls ne suffisaient pas à devenir candidats. | Les relations documentaires explicites peuvent fournir des candidats sans correspondance textuelle propre. |
| `image.mcp.image_read` | Lecture autorisée, matérialisation temporaire bornée et description par le modèle de vision. | Description enregistrée durablement avant de retourner un succès. |
| `memory.events` | Notifications limitées aux lecteurs actuels ; un ancien lecteur ne reçoit plus les événements du document. | Invalidation sans identifiant ni contenu, y compris après changements d'appartenance aux équipes. |

## Identités et autorité

Le manifeste documentaire reste la source des PJ actives et retenues. Chaque identité de PJ
possède exactement un compagnon Memory : clé primaire de `DocumentAttachment` et contrainte
unique sur `memory_item_id`. Son texte est initialement vide ; ses métadonnées identifient
l'URI, le MIME et la taille du binaire. Le texte n'est pas le binaire. Les synchronisations
préservent son contenu acquis et ses révisions. Toutes les catégories de PJ admises par
le contrat existant sont couvertes, sans extraction sémantique automatique.

Chaque `DocumentTag` pointe vers son propre nœud `folder`. Ni le nom, ni le chemin, ni le
partage d'un document ne changent cette identité. Les chemins historiques libres dans les
métadonnées d'un document ne créent pas de nouveaux dossiers sources.

`image_read` enregistre la description dans le texte HTML du compagnon de la PJ, avec une
révision portant la provenance agent/tâche. La description identique est idempotente. Le
document est reverrouillé et ses droits revérifiés avant l'écriture. Une PJ retenue, retirée
du manifeste actif, ne peut plus être enrichie. Une erreur de stockage fait échouer l'outil.
Pour les autres URI, la description devient une mémoire privée de l'agent, d'identité stable
par couple agent/URI ; elle n'introduit aucun nouveau partage de la ressource externe.

## Dossiers : aucun système de partage

Le classement reste personnel : seuls les créateurs listent et organisent leurs dossiers
dans la bibliothèque. Les agents voient dans Memory les dossiers directement rattachés à
un document lisible, et récursivement leurs ancêtres. Ils peuvent donc voir plusieurs
arborescences personnelles pour un même document, sans dupliquer celui-ci.

Cette visibilité est calculée depuis les droits actuels des documents, par une requête
récursive dédupliquée ; aucune ACL de dossier n'est copiée ou administrable. Un dossier
vide, ou ne contenant aucun descendant documentaire lisible, est absent du graphe de l'agent.
Voir un dossier ne donne accès ni aux documents interdits qu'il contient, ni aux branches
sœurs. Révoquer le dernier document justifiant un chemin masque immédiatement ce chemin.
Les nœuds restent distincts entre utilisateurs, même s'ils ont le même nom.

Cette décision remplace, pour les dossiers, la proposition initiale du ticket d'ACL
indépendantes : l'utilisateur a explicitement choisi une visibilité dérivée des documents.

## Liens et recherche

La projection `memory.document_structure` produit :

- `references` : document vers document référencé ;
- `has_attachment` : document vers chacune de ses PJ actives ;
- `uses_attachment` : document vers une PJ explicitement incorporée ou liée ;
- `in_folder` : document vers chaque dossier de rattachement direct ;
- `parent_of` : dossier parent vers dossier enfant.

Le parseur reconnaît les attributs de liens HTML (`href`, `data-rich-reference`) et de
médias (`src`) contenant une URI documentaire canonique, ainsi que les liens locaux
`/memory/documents?document_id=…&attachment_id=…`. Un texte ressemblant à une URI, une URL
externe, une référence invalide ou une cible absente ne crée jamais de faux document.
Il n'y a aucun appel LLM ou embedding dans cette projection, même en réparation.

Le rappel part d'ancres lexicales ou vectorielles autorisées. Il parcourt au maximum quatre
liens, 500 liens visibles par niveau et le budget de candidats existant. Les références
sont directionnelles ; les liens de contenance sont parcourables dans les deux sens.
Chaque extrémité est filtrée avant les limites, aucun objet interdit ne sert de pont.
Le poids structurel décroît comme `1 / profondeur`, puis entre dans le classement existant.
La déduplication utilise l'identité Memory. Les résultats détaillés portent un chemin
structurel constitué uniquement de liens autorisés. Les autres mémoires gardent la règle
existante : un simple voisinage inféré ne suffit pas à rendre un résultat pertinent.

## Convergence, erreurs et durée de vie

Les écritures documentaires et de classement mettent à jour la projection dans leur propre
transaction. Le point de convergence normal est donc le commit, avant le succès de l'API,
sans attendre Dream. Les droits sont toujours évalués à la lecture, même si la projection
est en retard. Les erreurs de projection annulent l'écriture au lieu d'annoncer un succès.

DbAdmin initialise le corpus existant après sa normalisation éditoriale, avec deux parcours
par pages de 100 documents pour résoudre les références vers des PJ rencontrées plus tard.
Dream propose une réparation déterministe par sujet/version/jour, relit la source courante
sous verrou et utilise ses reçus/reprises habituels. Dream reste opportuniste : aucune borne
de durée réelle n'est promise pour réparer une modification hors des services applicatifs.
La garantie immédiate concerne toutes les mutations effectuées par les services pris en charge.

Les verrous, identités uniques et rapprochements des ensembles empêchent les doublons ;
le rejeu n'augmente pas les poids et ne réactive pas une ancienne référence retirée. La
projection ne modifie ni ne supprime les relations manuelles ou d'autres projections.

Retirer une PJ préserve son identité et son texte pour les anciennes révisions, mais masque
son nœud dans les lectures et recherches courantes. Oublier définitivement son document
efface aussi les descriptions et révisions de ses PJ. Supprimer un dossier suit le classement
personnel existant et retire ses liens, sans supprimer les documents.

Les vues Memory, le graphe et l'éditeur documentaire se réactualisent après une invalidation
sans données. Les listes et détails Memory rejettent les réponses antérieures à l'invalidation.
Une reconnexion revalide les données. Le retrait d'un accès ne retire jamais les accès restants.

## Vérifications

`test_document_structure.py` couvre les catégories de PJ, le texte acquis et sa conservation,
la lecture d'image réelle avec erreur de stockage, les dossiers dérivés récursivement et les
arborescences personnelles distinctes, les ponts interdits, l'inventaire paginé, l'absence
d'appels modèles, les liens manuels, l'effacement, les connexions concurrentes et le rejeu
Dream obsolète. Les suites existantes couvrent les classements, partages documentaires,
révisions, ressources, recherche et scheduler. Le test navigateur Memory couvre l'effacement
de la vue ouverte et le rejet d'une ancienne réponse après révocation.
