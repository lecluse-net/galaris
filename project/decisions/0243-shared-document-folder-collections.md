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
y compris ceux dont les ancêtres sont privés, sans exposer ces ancêtres.

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
Un descendant lisible sous un parent interdit est rattaché au plus proche ancêtre lisible,
sans divulguer le parent interdit. Les cycles sont exclus du parcours. Chaque requête relit
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
