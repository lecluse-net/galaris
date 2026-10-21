<p align="right"><strong>Français</strong> · <a href="../../en/dev/datasets.md">English</a></p>

# Jeux de données et contrats de données

`app.dataset` possède le codec commun, les jeux de données et leurs opérations JSON.
La façade publique est `app.dataset.facade` ; les imports
historiques `app.process.values` conservent les restrictions du profil BPMN v2.

Le codec de variables représente chaque valeur avec son type :

```json
{
  "approved": {"type": "bool", "value": false},
  "report": {"type": "File", "value": "file://00000000-0000-4000-8000-000000000001"},
  "note": {"type": "string", "value": null}
}
```

Les types sont `int`, `float`, `string`, `bool`, `Agent`, `User`, `File`, `Document`,
`Dataset`, `array` et `object`. Les conteneurs imbriquent des valeurs typées.
Les entiers sont exacts et transportables en JavaScript ; les nombres non finis,
les clés JSON dupliquées et les charges dépassant les limites sont refusés.
Le typage vérifie la forme d'une référence ; sa résolution vérifie séparément les droits.

Les jeux de données acceptent toutes les racines JSON, sans schéma associé. Leur contenu
et celui des révisions sont conservés exactement. Le codec typé reste disponible pour les
variables des processus ; leur définition et leur validation appartiennent à Process.
Les applications documentaires utilisent le pont Dataset avec les droits du lecteur et
son consentement personnel. Les écritures libres et les restaurations vérifient le JSON,
les droits et la révision, sans imposer de structure métier.
La bibliothèque Documents exclut les Datasets, y compris les projections historiques,
avant comptage, pagination et calcul des filtres. `POST /memory/documents` refuse le type
`dataset` ; la création passe par `POST /datasets` ou `file_create(path="data://", ...)`.
La lecture d'un ancien Dataset par `GET /memory/documents/{id}` renvoie uniquement
`{resource_type: "dataset", resource_uri: "data://…"}` après contrôle des droits,
sans contenu documentaire. Les anciens liens ouvrent l'éditeur Dataset. La recherche
Memory et son graphe excluent ces anciennes projections des Documents courants.
Les liens HTML `data://` restent des références Dataset et se recherchent dans son domaine.

Un Document peut joindre des références Dataset vivantes via ses `dataset-attachments`.
Le manifeste documentaire conserve uniquement des URI ; ni copie JSON, ni droits Dataset
ne sont créés. Les mutations vérifient l'écriture du Document et sa version de verrouillage,
ainsi que la lecture indépendante du Dataset à l'ajout. Les références devenues inaccessibles
n'exposent plus leur titre. La suppression du lien conserve le Dataset. `file_list` sur les
PJ renvoie les URI `data://` lisibles, sans proposer de suppression de la ressource jointe.
Les utilisations Dataset incluent ces références après filtrage des droits du Document.
Les écritures utilisent `expected_revision` ; le partage utilise `expected_lock_version`.
Le provider `data://` enregistré dans File Sharing utilise les mêmes services.

Le classement personnel utilise exclusivement `dataset_tags`, `dataset_tag_assignments` et
`dataset_appearances`, sans partager les dossiers Memory. Les routes `/datasets/tags` et
`/datasets/library/move` exigent la lecture Dataset ; organiser une ressource lisible ne donne
aucun droit d'écriture. Les mutations d'une même arborescence sont sérialisées et refusent
les cycles. Supprimer une branche retire les classements de son utilisateur, jamais le JSON.
`GET /datasets` combine recherche titre/JSON, classement, propriétaire utilisateur/agent,
mot-clé, bornes temporelles inclusives/exclusives et tri. La bibliothèque demande les non
classés et l'ordre manuel par défaut ; les autres consommateurs conservent la liste complète.
`/datasets/library/facets` ne propose que les propriétaires et mots-clés de ressources lisibles.

Les lectures MCP gardent le JSON exact et leurs offsets en caractères. Elles donnent aussi
`start_line`, `end_line` et `total_lines` (lignes à partir de 1), ainsi que
`start_line_complete` et `end_line_complete`. Ces indicateurs signalent les lignes coupées
par la pagination : relire leur partie manquante avant de les remplacer avec `file_edit`.
Une page vide ne porte pas de coordonnées de ligne. Les éditions restent soumises à
`expected_revision` ; ces repères évitent de relire tout l'inventaire pour compter ses lignes.

Les inventaires de collections du planner se créent directement avec
`file_create(path="data://", name=..., content=...)`. Le reçu conserve l'URI exacte retournée
et doit correspondre à une opération réussie de l'étape de découverte. Le planner relit le
JSON complet sous les droits de l'agent avant de figer la liste ; les anciens reçus en
`document://` restent utilisables uniquement via un alias Dataset vérifié. Un Document HTML
ne peut pas servir d'inventaire JSON. L'inventaire interne n'est pas un livrable à transmettre.
Omettre le JSON dans `content` est un refus avant effet, avec une indication du paramètre à
corriger, et ne crée aucune ressource.

La migration DbAdmin `app.dataset.legacy_documents` conserve les sources et crée
des alias vérifiés. Les anciens accès Memory délèguent au nouveau domaine.
Le pont HTML conserve le consentement personnel par révision documentaire et le
budget SQL partagé de 30 écritures / 4 Mo par minute et par utilisateur/jeu de données.

Le partage reprend `DocumentSharingLevelUpdate` et le même catalogue de destinataires que
Memory. `PUT /datasets/{id}/sharing-level` remplace atomiquement le niveau et les grants,
sous verrou et `expected_lock_version`, sans réécrire le JSON ni ses révisions. Le composant
frontend commun `SharingPanel` gère lecture/écriture et héritage des groupes. Un éditeur
ne devient pas propriétaire ; les ressources en lecture seule ne peuvent pas être repartagées.

`GET /datasets/{id}/owner` affiche le propriétaire et les cibles autorisées.
`PATCH /datasets/{id}/owner` exige l'écriture, la gestion de la ressource et
`expected_lock_version`. Les cibles sont les agents gérés et l'utilisateur courant ;
`DATASET_ADMIN` autorise aussi les autres utilisateurs actifs. Le transfert garde l'ancien
propriétaire en écriture, retire le grant redondant du nouveau propriétaire et actualise
la projection historique, sans modifier le contenu ni sa révision. Les jeux en lecture seule
sont exclus. Le frontend indente le JSON chargé sans réencoder
les nombres ni les chaînes ; cette présentation ne rend pas le brouillon modifié.

`GET /datasets/{id}/usages` pagine les catégories `documents`, `processes` et `agents`.
Le point de composition enregistre les fournisseurs publics de Memory, Process et LLM ;
Dataset n'importe pas leurs modèles. Les requêtes portent sur les contenus documentaires
natifs courants, les références de runs et snapshots, et les traces d'outils conservées.
Les permissions du module source et ses ACL s'appliquent avant comptage et pagination.
Ce relevé décrit des références observées et ne constitue pas un graphe exhaustif de dépendances.
La suppression reste logique, sous verrou et version attendue.

Les runs Process stockent leurs variables dans `process_runs.data` et leurs fichiers
via `process_run_files`, sans Dataset. Les données, liens et reçus d'exécution sont
atomiques ; les droits sont ceux du processus parent. Dataset ne fournit que le codec
typé partagé, sans posséder le stockage des runs.
Les anciens marqueurs de métadonnées `engine_dataset`, `engine_managed` et `engine_agent`
n'accordent aucun statut particulier. Les permissions ordinaires gouvernent lecture, écriture,
pièces jointes, propriétaire et suppression, y compris via les alias Memory. La suppression
logique exige toujours la gestion et la version attendue, sans supprimer l'historique ni les runs.

## Projection historique et conditions de retrait

Dataset est l'unique autorité de contenu, historique et droits. Une création native
`data://` ne crée pas de Document Memory. Seul un alias de migration vérifié reçoit
une projection `DatasetDocumentProjection`, définie dans `app.memory.contracts` :
métadonnées, version, empreinte et grants, sans contenu ni historique. La suppression
retire la projection des lecteurs courants, en conservant les sources et l'alias comme
preuves de migration. La lecture de cet état passe par une requête async explicite.

Les anciens appels métier Memory restent des adaptateurs vers Dataset pour les consommateurs historiques,
applications HTML, pièces jointes et Process encore raccordés. Les nouveaux consommateurs
utilisent `app.dataset.facade` ou File Sharing avec `data://`.

Le retrait de la projection exige que ces consommateurs aient migré, que les clés étrangères
Process ne ciblent plus le Document historique, et que les parcours de contenu, révisions,
partage/révocation, PJ, consentements et budgets passent sur les URI canoniques. Les alias
vérifiés restent un contrat de lecture des anciennes références, indépendant de la projection.
Leur conservation et celle des preuves ne doivent pas être confondues avec le maintien d'un
second chemin d'écriture. Aucun retrait de ligne source n'est prévu par cette consolidation.
