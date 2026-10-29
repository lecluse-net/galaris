# ADR 0243 — Collections de répertoires documentaires partagés

- Statut : Accepted
- Date : 2026-10-26

## Contexte

Les répertoires personnels possèdent déjà un partage héritable. Leurs documents peuvent être
lus par les destinataires, mais le répertoire ne dispose pas de référence consultable ou joignable.

## Décision

`app.document` projette chaque répertoire autorisé comme collection en lecture seule sous
`document://folders/<uuid>/`, avec une page `/documents/folders/<uuid>`. Sa référence survit
aux renommages et déplacements. `document://folders/` découvre tous les répertoires lisibles,
y compris ceux dont les ancêtres ne sont pas explicitement partagés.

### Navigation par répertoires (2026-10-29)

La présence d’un document lisible rend ses répertoires et leurs ancêtres découvrables, dans les
classements de tous les utilisateurs. Le partage explicite d’un répertoire n’est pas requis
pour naviguer vers un document déjà autorisé. Les ACL de chaque document restent l’autorité
pour son contenu ; voir un répertoire n’accorde aucun accès aux autres documents.

`file_list("document://")` expose directement les répertoires contenant des documents lisibles
et les documents sans classement accessible. Dans un répertoire exact, la navigation liste
ses sous-répertoires immédiats et ses documents, sans aplatir les sous-répertoires. Un même
document peut apparaître dans plusieurs classements, avec son URI canonique inchangée.
Les listes fournissent les ancêtres nommés pour le fil d’Ariane, y compris à l’ouverture d’un
lien direct. La recherche de branche, la découverte exhaustive `document://folders/` et la
lecture JSON hiérarchique restent disponibles séparément.

La collection réutilise le partage effectif existant ; aucun nouveau grant ou stockage de contenu
n'est créé. Elle liste les sous-répertoires immédiats et les documents lisibles de toute la branche,
y compris les sous-documents. Les ACL documentaires filtrent avant comptage et pagination ;
un classement de document appartenant à autrui ne permet pas de contourner ses droits.

`file_read` sur un répertoire exact renvoie un JSON hiérarchique complet par page :
répertoires, documents et sous-documents avec leurs noms, types, URI et enfants. Chaque page
contient au plus 200 placements lisibles, racine exclue, dans l'ordre de parcours en profondeur.
Les offsets comptent les éléments (`offset_unit=item`), avec `next_offset` pour continuer.
Ce budget fixe remplace `max_chars` pour cette seule projection, afin de ne jamais découper
le JSON. Le contenu des documents et les images d'icônes ne sont pas inclus.

Les clés de placement distinguent un document classé dans plusieurs branches. Lorsqu'une page
commence au milieu d'une branche, `continuations` contient les enfants à rattacher aux
`parent_key` / `parent_uri` déjà lus ; ces ancêtres ne sont pas répétés dans le quota.
Un sous-document lisible sous un document parent interdit est rattaché au plus proche ancêtre
lisible, sans divulguer le document parent interdit. Les cycles sont exclus du parcours. Chaque requête relit
les droits et les placements courants ; reprendre à l'offset zéro après une réorganisation
concurrente. Le comptage et la pagination s'effectuent en SQL, sans charger toute la branche
dans le processus applicatif.

File Sharing traduit la projection publique en descripteurs génériques. L'API humaine utilise
l'identité authentifiée ; une consultation explicitement faite comme agent utilise ses propres
droits après contrôle du périmètre de gestion. Les pièces jointes et cartes conservent l'URI
source, ne copient pas les documents et n'accordent aucun accès. Leur miniature utilise l'icône
du répertoire. Chaque nouvelle requête réévalue les droits et l'état courant.

## Vérification

Les tests Document exercent découverte, pagination, sous-documents, renommage, droits de source,
révocation et rattachement indépendant. Le parcours E2E couvre l'insertion dans un Document,
la réouverture, la page dédiée et le partage dans Discussion sur bureau et mobile.
