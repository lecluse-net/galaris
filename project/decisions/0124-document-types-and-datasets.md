# 0124 — Types immuables de documents et Datasets JSON

- Statut : Accepted
- Date : 2026-09-19

## Décision

Un Dataset est un document, avec la même URI `document://`, le même `node_kind=document`,
les mêmes propriétaires, icônes personnelles, classements, ACL et révisions. Il apparaît
dans la bibliothèque Documents. Aucun schéma `dataset://` ni domaine parallèle n'est créé.

`MemoryItem.document_type` distingue `html` et `dataset`. Le défaut SQL `html` préserve les
ressources existantes ; cette propriété n'a de sens fonctionnel que pour les documents.
Le type est choisi lors de la création et absent des contrats de mise à jour, qui refusent
les champs inconnus. Les changements de MIME ne permettent pas de changer de type.
Une conversion éventuelle crée un autre document. Les futurs types nécessiteront chacun
leur contrat de contenu et leur éditeur ; aucun type image ou autre n'est activé ici.

Un Dataset stocke du JSON UTF-8 valide (`application/json`, sans profil éditorial versionné)
dans le stockage de ressources existant. Le texte source, y compris son indentation, est
conservé. La validation serveur rejette les entrées invalides et les nombres non finis avant
toute nouvelle ressource ou révision. La limite est 2 000 000 octets, sous réserve du quota
de stockage configuré. Le JSON peut contenir n'importe quelle valeur JSON racine.

CodeEditor, en langage JSON, remplace CKEditor pour ce type, en édition et dans l'historique.
L'autosauvegarde attend un JSON valide ; le brouillon reste récupérable. Les contenus JSON
ne passent pas par la conversion HTML, la projection de liens HTML ou les exports HTML/PDF.
Les exports de données utilisent les outils de fichiers et conservent le JSON.

`file_create(path="document://", document_type="dataset", content=...)` crée un Dataset.
L'absence du paramètre conserve HTML. Le paramètre est réservé à cette collection.
Les lectures sont paginées en caractères ; les éditions portent sur des lignes, contrairement
aux blocs des documents HTML. Toute mutation doit laisser un JSON complet valide.
Les écritures de fichiers exigent la révision observée. Copier une source `application/json`
vers la collection Documents crée un Dataset ; écrire vers un document existant conserve
son type et valide son contenu. Les ACL ne sont pas copiées.

## Garanties et consommateurs

Les parcours concernés sont la création HTTP humaine/agentique et MCP, les opérations
`file_*`, la bibliothèque (filtre/tri), l'éditeur partagé entre Documents et Chat,
l'inspection Memory, l'historique, les droits humains/agents/équipes et les projections
secondaires. Les documents HTML existants gardent leur comportement. Les révisions de
contenu restent séparées des changements de titre, classement, icône et partage.

Les tests DB couvrent la conservation exacte du JSON, les erreurs sans effet, les conflits,
les droits, la restauration et la copie ; les composants vérifient les brouillons invalides,
la réouverture, les conflits distants, la lecture seule, la création et le filtre/tri.
Un parcours E2E traverse la vraie API, PostgreSQL et CodeEditor.

L'exécution de JavaScript dans le corps HTML et les associations programmatiques entre
documents et datasets restent un chantier distinct. Cette décision ne leur accorde aucun
accès et ne modifie pas le profil HTML statique actuel.
