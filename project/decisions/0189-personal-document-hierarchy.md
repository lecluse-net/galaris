# 0189 — Sous-documents dans le classement personnel

- Date : 2026-10-15.
- Statut : accepté.

La bibliothèque étend le classement personnel des dossiers aux documents. Chaque
utilisateur peut placer un document sous un autre, sans modifier leurs contenus,
révisions, propriétaires ou grants. Lire le parent ne donne aucun accès à ses enfants.
Le classement d'un autre utilisateur demeure indépendant.

`document_nesting` conserve un parent documentaire unique par utilisateur/document,
avec une position parmi ses frères. Les références pointent vers les vrais Documents.
Un déplacement sous un document retire seulement les affectations aux dossiers du même
utilisateur ; un déplacement vers un dossier ou les non-classés retire le parent personnel.
Déplacer le parent déplace visuellement sa branche sans réécrire les descendants.
Les anciennes affectations à plusieurs dossiers restent lisibles.

Le verrou transactionnel existant de l'arbre personnel sérialise aussi ces opérations.
Le serveur vérifie l'accès aux deux documents et rejette les cycles, y compris à travers
un ancêtre devenu illisible. L'ancre de réordonnancement est validée avant toute mutation.
Le classement reste possible avec le seul accès en lecture au document.

La lecture filtre séparément les enfants et les parents selon le périmètre actuel.
Un enfant lisible dont le parent est supprimé ou illisible reparaît parmi les non-classés ;
l'identité du parent n'est alors pas exposée. Supprimer un parent ne supprime jamais
ses enfants. Les compteurs ne comptent que les enfants lisibles. La recherche plate
conserve les sous-documents ; les branches chargent leurs enfants directs par pages,
indépendamment des filtres de recherche. Les caches sont invalidés lors d'un changement
de session ou de droits et ignorent les réponses périmées.

L'interface ajoute une action de création sous chaque document, le dépliage récursif,
le glisser-déposer dans un document, un dossier ou parmi les non-classés.
La création et le classement utilisent les opérations existantes séparées : si le
classement échoue après création, le document est conservé et un message le signale.
Cette structure de navigation n'ajoute pas de grants ni de liens métier dans le graphe Memory.
