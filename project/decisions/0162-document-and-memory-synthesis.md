# 0162 — Documents distincts et synthèses mémoire facultatives

- Statut : Accepted
- Date : 2026-10-07
- Remplace le contrat de titre et de partage des souvenirs de la décision 0161.

## Contrat

Le domaine Memory distingue désormais deux entités persistantes. `Document` possède
le titre, le contenu de référence, sa révision et les niveaux de partage. Il possède
exactement un `MemoryItem`, lié par une clé étrangère unique. Ce nœud porte une
synthèse HTML facultative et son historique indépendant, ainsi que la provenance,
les mots-clés, les dates et les relations du graphe. Le document et le nœud conservent
le même UUID pour préserver les URI et les références déjà publiées.

Un souvenir autonome reste privé à son agent. Son libellé d'affichage est une
projection du contenu, sans titre éditable ni partage indépendant. Les contacts,
sujets, fichiers, dossiers et pièces jointes conservent leurs règles structurelles.
La synthèse documentaire hérite des droits courants du document. Une révocation
s'applique aux lectures, au graphe et à la recherche. Une modification documentaire
ne réécrit pas la synthèse ; sa révision de référence permet de signaler son ancienneté.

La recherche lexicale et vectorielle exploite toujours le contenu documentaire
complet et la synthèse. Elle produit un seul résultat par couple. Les passages
sémantiques de la synthèse indiquent leur origine et ne portent pas de positions
de blocs dans le document. Les empreintes couvrent les deux ressources.

## Migration et compatibilité

L'apparition de la table `documents` déclenche d'abord l'action DbAdmin
`app.memory.document_split_backup` en phase `BEFORE_EXPAND`. Elle archive les lignes
complètes de `memory_items`, leurs révisions et leurs grants dans le schéma durable
`galaris_migration`, hors du périmètre Atlas. Un manifeste de comptages et des
empreintes SHA-256 vérifient cette sauvegarde immuable ; un rejeu ne la remplace pas.
Les tables documentaires déjà présentes sont aussi archivées pour qualifier une base
ayant déjà reçu l'expansion. Le retrait des anciennes colonnes déclenche cette voie
de rattrapage, même si la table `documents` existe déjà.

`app.memory.document_split`, en phase `AFTER_EXPAND`, crée les documents à partir de
la sauvegarde et refuse un changement des sources entre les deux phases. Elle vérifie les pointeurs avant
d'initialiser une synthèse vide. `DocumentRevision` attribue les snapshots immuables
existants au document, sans recopier les ressources ni changer leurs identités.
`MemorySummaryRevision` conserve séparément les versions de la synthèse.

Les documents historiques, révisions, URI, tombstones, classements, pièces jointes
et relations restent adressables. Un ancien souvenir partagé devient un document
en conservant ses destinataires et son verrouillage. Les anciens titres des souvenirs
privés sont incorporés à leur contenu ; les versions originales restent intactes.
Les ressources JSON non éditoriales et binaires d'anciens souvenirs partagés restent
lisibles dans leur format d'origine ; les nouvelles créations gardent le contrat HTML/Dataset.
L'action possède une postcondition et se rejoue sans effacer une synthèse créée
depuis sa première réussite. Une erreur annule la transaction. Le transfert incrémente
le verrou du nœud pour rejeter les écritures commencées avant la migration.

Après réussite de la postcondition, la contraction DbAdmin de cette même mise à jour
supprime de `memory_items` les colonnes `document_type`, `filename`, `visibility`,
`global_access` et `group_access`, devenues documentaires. Les noms d'export des
nœuds structurels restent dans leurs métadonnées ; leur visibilité dérive de leur
provenance et de leur propriétaire. Les champs du contenu mémoire, le libellé dérivé
et `read_only` restent nécessaires. Les tables de grants conservent leurs identités.
Les attributs ORM et services documentaires gardent leurs contrats, et le verrou
optimiste du nœud sérialise contenu documentaire, synthèse et droits. Un échec de
sauvegarde empêche l'expansion ; un échec de transfert conserve les anciennes colonnes
et la sauvegarde pour la reprise automatique au prochain démarrage.

La sauvegarde n'est jamais supprimée par la synchronisation. Les ressources auxquelles
elle fait référence, y compris les pièces jointes, sont protégées de l'oubli applicatif
et du nettoyage d'orphelins tant que l'archive est conservée. Les données restent
absentes des recherches et des lectures ordinaires après un oubli. Cette sauvegarde
SQL conserve des pointeurs : elle ne remplace pas une sauvegarde du stockage des
fichiers. Sa purge éventuelle est une opération administrative distincte et explicitement
validée. Aucun second module ni seconde liste d'activation n'est nécessaire.

Les routes `/memory/items/{id}` éditent la mémoire ou la synthèse ;
`/memory/documents/{id}` lit et modifie le contenu documentaire. Les outils de
fichiers gardent `document://` pour le contenu complet. Les alias de partage
historiques acceptent uniquement les documents. Le paramètre `title` des créations
mémoire reste accepté pour les anciens clients, mais le libellé est dérivé du contenu.

Les mots-clés courants du document et de sa synthèse sont une seule liste, stockée dans
`memory_items.keywords`. Les deux fiches peuvent la modifier avec les droits courants du
document, la même normalisation et le verrou optimiste commun. Modifier uniquement cette
liste ne crée ni révision documentaire ni révision de synthèse. Les snapshots historiques
conservent les mots-clés de leur époque. La séparation des anciens documents laisse la
colonne et ses valeurs en place ; un rejeu ne rétablit jamais les mots-clés d'une ancienne
révision. Les changements reçus à distance actualisent les champs restés intacts et
préservent les brouillons ; un conflit de mots-clés conserve le verrou d'origine pour
empêcher un écrasement silencieux.

## Interface et qualification

La durée de vie de la synthèse suit celle du document. Les commandes d'oubli mémoire
(HTTP et MCP), y compris administratives, et la fusion ne peuvent pas la supprimer
indépendamment. La suppression explicite du document utilise sa route dédiée, avec les
mêmes contrôles de propriété et de protection, puis efface la synthèse et ses versions.
Il existe une synthèse commune par document, visible selon les droits de chaque agent :
une révocation retire cette visibilité et invalide les vues ouvertes, sans supprimer les
données nécessaires au propriétaire ou aux autres lecteurs. Aucune nouvelle colonne ni
conversion de données n'est nécessaire pour appliquer cette protection aux anciens
documents transférés depuis `memory_items`.

La fiche mémoire sépare les champs, les liens et relations, et l'historique. Elle
n'affiche ni champ titre ni partage. La temporalité utilise des champs compacts.
Un document associé peut être ouvert depuis sa synthèse ; son éditeur conserve
titre, partage, autosave, applications et datasets. Les actions Dream précèdent
Enregistrer dans le pied ; Annuler et l'en-tête Contenu ont été retirés.

Les preuves vivent dans `test_document_split.py`, les suites documentaires,
les scénarios existants des composants et les parcours E2E. Elles couvrent la
conservation, le rollback et le rejeu, les droits, la recherche, les révisions,
les consommateurs Goal, les datasets, les ressources et les petits écrans.
Cette décision ne prouve aucun déploiement en production.
