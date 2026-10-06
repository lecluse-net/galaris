# 0159 — URL des nœuds mémoire et source principale

Statut : accepté. Date : 2026-10-06.

## Décision

`memory_urls(id, memory_node_id, url)` est l'unique association durable entre un nœud
mémoire et ses URL. `memory_node_id` référence `memory_items.id` ; `url` conserve la
référence complète. La colonne texte nullable `memory_items.primary_url` désigne la
source de visualisation privilégiée parmi ces URL. Elle reste `NULL` sans emplacement.
Une contrainte unique protège `(memory_node_id, url)` et une FK composite différée
vérifie l'appartenance de `primary_url`, sans ajouter de colonne à `memory_urls`.
Les URL ne sont plus enregistrées dans `metadata.resource_uri`, `metadata.resource_uris`
ou dans des lignes `MemorySource` de ressource. La provenance d'une Task ou d'un round
reste indépendante de ces emplacements.

`file_catalog_entries` possède les observations de transport : connexion, binding,
runtime, présence et version. Son `memory_url_id` référence une association d'URL ;
il ne possède plus de FK directe vers le nœud mémoire. L'identifiant du nœud est
dérivé de cette relation pour les requêtes et les contrôles d'accès. Une observation
retenue après suppression ne maintient pas une URL active vers le nœud ; les notes
et révisions du nœud demeurent conservées.

Le SHA-256 des octets complets est porté par `memory_items.file_sha256`, sans filtre
de format. Dream l'acquiert pour les fichiers externes ; les pièces jointes natives
immuables le reçoivent lors de leur projection. `content_hash` continue de désigner
le contenu éditorial de la fiche. Les copies externes identiques sont regroupées
par agent, avec transfert des associations d'URL vers le nœud canonique.
`file_media_type` et `file_size_bytes` sont des colonnes dédiées nullables pour le
MIME et la taille du fichier source. `media_type` et `size_bytes` décrivent le contenu
éditorial de la fiche ; ils ne servent pas à décrire les octets externes.

L'acquisition du SHA n'effectue aucune fusion et son index n'est pas unique.
Un SHA identique donne une similarité exacte de `1.0`, même sans embeddings.
`memory.maintain_findings` applique la politique de doublons de Dream : `off` ne
produit rien, `manual` conserve une proposition et `automatic` effectue la fusion.
Le premier nœud créé conserve son identité et sa source principale ; les notes,
URL, provenance, usages et relations des autres sont transférés. Le score ne
remplace pas les frontières de droits : les propriétaires et les accès doivent
être compatibles. Les pièces jointes identiques d'un même document peuvent
partager un compagnon ; celles de documents différents gardent leurs ACL distinctes.
Les historiques de descriptions des pièces jointes rejoignent le compagnon
survivant afin que l'oubli du document efface aussi les descriptions fusionnées.

`memory_usages.task_id` devient une véritable FK nullable vers `tasks.id`, avec
`ON DELETE SET NULL` pour conserver l'audit. Les autres provenances typées, dont
les rounds de conversation, conservent leurs FK existantes dans `memory_sources`.

La découverte d'une copie conserve l'URL principale existante. Un déplacement de
cette source met à jour la colonne ; sa suppression ou son changement d'octets
choisit une autre URL restante, puis `NULL` s'il n'en reste aucune. Les aperçus
privilégient la source principale accessible, avec contrôle des droits de chaque
source. Une URL ne donne jamais accès à elle seule.

## Transition et vérification

L'action DbAdmin `app.memory.url_associations`, en `AFTER_EXPAND`, transfère les
liens du catalogue et les URL des métadonnées/provenances avant contraction de
`file_catalog_entries.memory_item_id`. Elle conserve l'ancienne URL principale
lorsqu'elle appartient aux emplacements présents, puis retire les représentations
redondantes, y compris celles des révisions. Sa postcondition bloque la contraction
si un rattachement actif manque ; le rejeu ne crée pas de doublons.

L'action `app.memory.reference_integrity`, avant expansion, rassemble les URL
dupliquées en préservant les observations du catalogue. Les anciens UUID de Task
orphelins sont sauvegardés dans `galaris_migration.memory_usage_orphan_tasks`
avant que leur FK vive soit mise à `NULL` ; les usages demeurent en place.
`app.memory.file_attributes` récupère après expansion les attributs des anciennes
métadonnées et des descripteurs du catalogue. Les métadonnées des révisions
anciennes restent disponibles pour l'audit.

`test_memory_urls.py` vérifie le SHA de fichiers texte et binaires, l'association
unique, la stabilité de la source principale, les déplacements/suppressions et
la migration PostgreSQL avec rollback, rejeu et retrait de l'ancienne colonne.
Les suites catalogue, structure documentaire et aperçu frontend maintiennent
les garanties de regroupement, de droits et de conservation des contenus.
`test_file_identity.py` couvre les modes Dream, les matchs SHA sans embeddings,
les descriptions fusionnées, les usages, les contraintes en base et les actions
DbAdmin avec rollback et rejeu.
