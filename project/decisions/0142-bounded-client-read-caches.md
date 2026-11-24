# 0142 — Caches de lecture client bornés et séparés par autorisation

Statut : accepté. Date : 2026-09-27.

## Garantie

Réduire les lectures répétées entre composants et écrans sans mélanger les réponses
d’endpoints dont les autorisations diffèrent. Une session révoquée, une mutation connue
ou une réponse tardive ne doit pas repeupler le cache d’un nouveau contexte.

## Décision

`core.util.sessionReadCache`, exposé par la façade légère de `core.util`, conserve en mémoire
des lectures avec des limites définies pour chaque usage. Il mutualise les requêtes concurrentes et
isole l’annulation de chaque lecteur. La dernière annulation abandonne le transport. Les erreurs
de transport restent réessayables. Un changement de session ou de rôle vide les caches et invalide
les requêtes en cours. Le renouvellement du jeton dans une même session conserve les lectures,
y compris celle qui déclenche ce renouvellement. Chaque lecture vérifie aussi la génération
de session, notamment après un changement dans un autre onglet. Le signal et la génération
sont injectés par les services : cet utilitaire ne dépend pas du client API.
Les groupes d’invalidation relient les mutations aux caches concernés.

Les avatars Chat et administration conservent des entrées distinctes par endpoint et génération
de session. Les images reçues sont réutilisées pendant la session, même après un rechargement,
grâce à IndexedDB. Chaque cache mémoire reste limité à 64 entrées et 16 Mio. Le stockage
partagé est limité à 512 entrées et 64 Mio. Une réponse 404 reste en mémoire pendant 60 secondes.
Une mutation locale d’agent ou d’avatar invalide les deux endpoints. Une révision connue
différente, fournie par `updated_at`, déclenche une nouvelle lecture. Un changement externe
devient visible lorsque le consommateur reçoit la nouvelle révision ou à la session suivante.
Seuls les accès réseau passent par la file secondaire des aperçus.

Le cache contient des blobs, pas les URL objets appartenant aux vues : chaque ancien
appelant de `getAvatarBlobUrl` conserve la responsabilité de sa propre URL. La discussion
peut partager une URL tant que plusieurs bulles restent montées. Les composants d’avatar
réagissent aux invalidations et aux changements de session.

Les sélecteurs d’agents conservent une fraîcheur nulle : ils partagent uniquement les
lectures simultanées par périmètre et rendent des copies indépendantes. Aucun résultat
d’autorisation n’est ajouté à un cache durable.

Les services alimentant les stores d’agents, titres, groupes et paramètres réutilisent aussi
leurs réponses : 60 secondes pour la liste complète des agents, cinq minutes pour les trois
autres catalogues. Chaque catalogue conserve au plus une réponse de 16 Mio ; les résultats
plus volumineux restent utilisables mais ne sont pas retenus. Les services parcourent toutes
les pages d’agents avant de mettre la liste en cache, et rendent des copies JSON indépendantes
pour que les brouillons locaux ne modifient pas le cache. Une liste vide est un résultat valide.

Les mutations réussies de ces services invalident leurs catalogues et les projections connues
(titres intégrés, suppression de groupe, avatars et appartenances aux équipes d’agents).
Le paramètre `force=true` des lectures de service et actions de store abandonne une ancienne
lecture au profit d’une lecture réseau. Les stores ignorent les réponses supplantées et
effacent les listes sur un refus de lecture. F5 recrée les caches des catalogues. Les changements
faits ailleurs deviennent visibles à la prochaine lecture après expiration ou immédiatement
après F5. Les activités temps réel suivent leur propre politique.

## Validation

Tests unitaires d’expiration, éviction, poids, échecs, annulation et invalidation ; parcours
navigateur des avatars et sélecteurs, puis agents, équipes, tableau de bord, tâches et Chat.
Parcours d’ouverture/réouverture/rechargement des agents ; tests des stores avec les vrais
services pour les modifications, listes vides, réponses tardives, erreurs, expiration et session.
