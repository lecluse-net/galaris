# 0165 — Positions et présentation personnelles du graphe mémoire

- Statut : Accepted
- Date : 2026-10-09

## Contrat

Le graphe 2D conserve son placement entre ouvertures. Chaque utilisateur possède son
état pour un agent et un contexte de recherche/Topic/contact. Les choix d'un utilisateur
ne modifient jamais ceux d'un autre. La caméra, les natures masquées et les branches
dépliées sont restaurées avant l'affichage ; les coordonnées reviennent avec les pages
de nœuds autorisées. Les nouveaux nœuds d'une nature masquée héritent de ce choix.

`memory_graph_views` contient la clé de contexte, les préférences JSONB et une révision.
`memory_graph_positions` conserve une ligne par nœud et vue. Ajouter des nœuds ou changer
un filtre de nature ne réécrit pas un gros JSON de coordonnées. Les écritures ajoutent
au plus 500 positions par requête, sans plafond global de nœuds. Les nœuds masqués et
les feuilles repliées gardent leurs coordonnées ; une page partielle ne les supprime pas.
La suppression de l'utilisateur ou de l'agent supprime ces états par cascade.

Les positions connues deviennent des ancres et les nouvelles positions sont calculées
à proximité des branches ou du placement existant. Les petits graphes sans cache gardent
leur placement initial animé ; ses coordonnées sont capturées après stabilisation ou
lors d'une interaction. Une vue restaurée utilise le placement explicite public du
renderer, qui évite de réinitialiser la simulation et ses caches internes.

Le serveur choisit l'utilisateur à partir de la session et contrôle le périmètre agent,
les filtres et les droits courants des sources. Une coordonnée ou préférence enregistrée
ne donne aucun accès supplémentaire. La révision et le verrou de vue empêchent un onglet
ancien d'écraser silencieusement les choix d'un autre. Après conflit, le client relit la
révision et renvoie uniquement les champs effectivement modifiés. Deux placements
initiaux concurrents ne remplacent pas des coordonnées déjà enregistrées.

Les sauvegardes sont différées, regroupées et incrémentales. Les échecs conservent les
modifications en attente et proposent une reprise sans bloquer le graphe. Un changement
de session invalide les requêtes en attente. Ce socle ne précalcule pas encore de carte
3D et ne transforme pas le transfert exhaustif actuel en lecture régionale.

## Vérification

Les tests DB couvrent deux utilisateurs du même agent, les contextes distincts,
l'accès refusé, les coordonnées masquées, la révocation et les conflits de révision.
Les tests du client couvrent les lots, les échecs, les changements pendant une sauvegarde
et la fusion après conflit. Les parcours du renderer réel vérifient réouverture,
nouveaux nœuds, masquage par nature et reprise, sur desktop et mobile. Le parcours E2E
utilise l'API réelle pour vérifier les positions et préférences après navigation complète.
