# 0084 — Partage des documents et mémoires entre humains, agents et équipes

Statut : accepté. Date : 10 septembre 2026.

Les documents restent des textes HTML enrichis et privés à la création. Le partage distingue
les agents (`memory_item_grants`), les utilisateurs (`document_user_grants`) et les équipes
communes (`document_team_grants`). Les appartenances multiples de `agent_teams` et `team_users`
sont résolues à chaque lecture ou écriture, sans copier les membres dans les partages.
Les droits applicables se cumulent ; une révocation ne retire pas un autre partage explicite.

Un `HumanActor` explicite porte l’utilisateur authentifié quand aucun agent n’est sélectionné.
Il ne se convertit jamais en identifiant d’agent, y compris pour les sessions du navigateur.
Un partage humain ne bénéficie pas aux agents qu’il gère. Les routes documentaires conservent
leurs privilèges RBAC et les ressources héritent des droits du document.

Révision du 11 septembre 2026 : le partage avec des groupes repose sur une sélection explicite
d’un ou plusieurs groupes, chacun en lecture ou écriture. Il ne suit plus automatiquement
les groupes du propriétaire. Les anciens accès `group_access` sont présentés comme les groupes
actuellement concernés ; leur prochain enregistrement les convertit en grants explicites et
remet `group_access` à zéro. Aucun changement de schéma ni de droits n’est appliqué à la lecture.

L’accès global `0/1/2` correspond à aucun accès public, lecture et lecture/écriture pour les
utilisateurs actifs et les agents de l’application. Aucune route anonyme n’est ajoutée.
Le propriétaire ou un administrateur disposant de l’accès requis gère les partages ; un simple
rédacteur ne peut pas déléguer son droit. Les mutations vérifient la version du document.

L’interface est portée par le composant générique `SharingPanel`, exposé par `core/util`.
Il reçoit un état et un catalogue de destinataires, puis émet un brouillon complet à enregistrer.
Il ne connaît ni les documents, ni leurs API, ni leurs privilèges. Après validation de l’IHM,
`MemorySharingPanel` assure ce branchement pour l’éditeur de documents et pour les vues de
consultation et d’édition des items mémoire. Les anciennes boîtes d’accès agents et le sélecteur
de visibilité sont remplacés. Les nouveaux items sont créés privés puis ouverts pour permettre
leur partage. Les vues de simple aperçu et les autorisations générales ne sont pas des éditeurs
de partage.

Le service `item_sharing` applique la même transaction aux deux types de ressource. Les routes
documentaires conservent leur contrainte de type via `document_sharing`, et les items disposent
de `GET/PUT /memory/items/{id}/sharing`. Les tables de grants existantes portent déjà une FK
vers `memory_items` ; leurs noms historiques sont conservés. La contrainte réservant
`global_access` aux seuls documents est retirée par DbAdmin. Les restrictions de contenu des
documents et des projections gérées par une source restent applicables. Les projections sans
propriétaire affichent leur partage en lecture seule. Les routes de lecture et de modification
d’un item sans agent acceptent l’identité humaine authentifiée dans son propre périmètre.

Le champ porte un petit libellé « Partage », comme les autres inputs. Sur une même ligne,
les tags affichent le destinataire, une icône œil/crayon cliquable pour basculer Lecture/Écriture
et une croix de suppression. Une flèche de select indique l’ouverture du popover au clic sur
le champ ; les actions des tags n’ouvrent pas le popover. Les infobulles précisent les droits.
Sans partage accordé, le champ affiche « Privé ». Le propriétaire conserve toujours son accès.
Les agents et utilisateurs affichent toujours un avatar dans les tags et la recherche, avec
leurs initiales en repli. Le domaine fournit les composants d’avatar via un slot du partage
générique, sans introduire de dépendance de `core/util` vers `app/agent`.

Le popover s’ouvre au clic sur le champ ou au clavier. Les raccourcis Public et Groupes
proposent Lecture et Écriture en haut ; Groupes ajoute uniquement les groupes actuels du
propriétaire qui n’ont pas déjà accès, sans modifier ceux déjà partagés. Il disparaît quand
aucun groupe supplémentaire n’est disponible. Aucune règle implicite sur les futures
appartenances du propriétaire n’est créée.

Dessous, une recherche filtrée par Tous, Groupes, Personnes ou Agents affiche les destinataires
disponibles. Deux icônes œil/crayon accordent directement Lecture/Écriture, sans bouton « + »
ni sous-menu. Un droit déjà couvert est désactivé. Le propriétaire et les destinataires déjà
partagés directement sont exclus des résultats : leurs droits se modifient sur les tags.
Un membre couvert en lecture par un groupe reste proposé pour l’écriture, tandis qu’un membre
couvert en écriture est exclu. Les appartenances nécessaires au filtrage sont fournies par le
domaine. Ajouter un droit ne sert jamais à supprimer un partage : les tags portent ces actions.
La recherche pagine côté interface, avec 10 résultats par défaut et les tailles
`[10, 20, 50, 100, 500]`. Le catalogue reste chargé intégralement, mais seules les lignes de la
page courante et leurs avatars sont rendus. Recherche, catégorie et taille de page reviennent
à la première page ; l’ajout d’un partage recale une dernière page devenue vide.

Public/Lecture permet d’ajouter des groupes, agents et utilisateurs en écriture ; leurs tags
restent visibles à côté du tag Public. Les ajouts, modifications et suppressions de ces accès
préservent la lecture publique. Retirer Public conserve les accès explicites. Public/Écriture
ne propose aucun ajout et remplace les droits particuliers devenus redondants. Choisir
Public/Lecture conserve les rédacteurs explicites et retire les lectures devenues redondantes.
Basculer un rédacteur vers la lecture sous un accès public retire son grant devenu redondant.
Chaque clic enregistre directement l’ensemble des partages sous un verrou et une version,
dans une transaction unique. Le composant affiche uniquement le résultat persisté ; une erreur
laisse les droits affichés inchangés et propose leur rechargement.

Les tests sont maintenant activés à la demande de l’utilisateur. Les garanties d’accès,
de révocation et de conservation du contenu sont conservées dans
`back/app/memory/tests/test_document_sharing.py`, paramétrées pour les mémoires et documents.
L’ancienne attente de groupes suivant le propriétaire est remplacée par la sélection explicite,
y compris après transfert de propriété ; les appartenances des destinataires restent vivantes.
Les tests de composants réels de `front/browser-tests/document-sharing.spec.mjs` couvrent les
interactions, la pagination, les erreurs, les réponses obsolètes et l’intégration dans la page
mémoire. Les assertions sur les anciens menus et boutons sont remplacées par les actions
utilisables et leurs effets sur les droits.
