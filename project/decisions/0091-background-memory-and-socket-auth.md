# 0091 — Calcul mémoire isolé et authentification WebSocket à la connexion

Date : 12 septembre 2026. Statut : accepté pour la correction de performances.

## Problème observé

La réconciliation des suggestions mémoire exécutait son calcul CPU dans la boucle
asyncio du backend, retardant HTTP et audio. Les transitions internes de Dream
déclenchaient chacune une notification et une authentification JWT par socket.

## Décision

Le calcul des suggestions utilise un unique processus à priorité réduite, créé avec
`spawn`. Il reçoit des vecteurs binaires et des appartenances déjà sélectionnés ; il
n'effectue aucun accès DB ou réseau. Les lectures et écritures restent dans la session
du backend. Les demandes sont sérialisées avant le chargement des vecteurs. Annulation
et arrêt terminent le calcul. La réconciliation ciblée attend aussi la fin du travail
interactif ; une maintenance Dream sans résultat ne déclenche pas de réconciliation.

La connexion WebSocket vérifie le JWT et conserve ses claims validés. Une émission
revérifie l'expiration, la révocation et les droits courants sans refaire la signature
ni l'authentification complète. Les contrôles identiques sont partagés entre sockets
pendant une même émission seulement ; aucun cache temporel d'autorisation n'est ajouté.
Les tokens API personnels conservent leur chemin de validation révocable existant.

Dream publie les changements aux frontières utiles de son état, avec une seule émission
en cours et un indicateur de changement en attente. Aucun intervalle supplémentaire
n'est introduit. L'instantané local conserve les phases intermédiaires.

Côté interface, les pages et widgets partagent la requête de liste des agents en cours
pour une même session. Une réponse d'une ancienne session ne peut plus effacer la
nouvelle liste. Le sélecteur attend cette requête même si le store charge aussi des
titres ou groupes. Les chargements de droits concurrents attendent la même réponse ;
changement d'identité, changement de rôle et déconnexion invalident les réponses
précédentes. Un échec ne provoque plus de nouvelles requêtes à chaque rendu ; un
rafraîchissement explicite reste possible. Aucun résultat n'est mis en cache avec un TTL.

## Garanties

Les tests couvrent les refus après révocation/expiration, trente émissions sans nouvelle
authentification JWT, les mises à jour arrivant pendant un envoi lent, les groupes
transitifs de mémoire et la disponibilité de la boucle avec un index de 768 dimensions.
Les tests frontend couvrent la requête partagée, la réouverture, l'erreur réseau,
la réponse tardive après changement de session et l'ouverture du sélecteur pendant
un autre chargement du store.
