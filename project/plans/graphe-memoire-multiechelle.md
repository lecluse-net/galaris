# Graphe mémoire — hiérarchie et chargement spatial

- Statut : `partial`
- Revue des sources : 2026-10-08.

## Socle et limite actuelle

Le repli des feuilles exclusives, les positions conservées, le détail progressif et
les miniatures de fichiers/documents sont réalisés dans la fenêtre chargée :
[ADR 0157](../decisions/0157-stable-memory-leaf-branches.md),
[aperçus partagés](../decisions/0156-persistent-file-thumbnails.md) et
[contrat média](../../docs/fr/architecture/flows/media-resources.md).
Les compteurs globaux empêchent de déduire l'exclusivité d'une page partielle.

Le plafond de 3 000 nœuds et 8 000 liens conserve une fenêtre globale ; le navigateur
ne charge pas encore une carte serveur par région. Les paramètres internes du placement,
du cache et des miniatures appartiennent au code et aux tests, pas à ce plan.
Les anciennes mesures de la grille abandonnée ne qualifient pas le placement courant.

## Garantie recherchée

Dans Connaissances → Mémoire → Graphe, chaque item autorisé, même ancien ou isolé,
reste atteignable par une carte stable. Zoomer révèle groupes puis items ; dézoomer
replie les détails ; déplacer la vue charge les régions explorées. Le travail interactif,
le réseau et les caches restent bornés indépendamment du volume total.
Une région dense est subdivisée ou agrégée, sans omission définitive.

La hiérarchie est une projection reconstructible d'affichage ; elle ne modifie ni
Topics, liens métier, contenu, propriétaires ni droits. La
[piste 3D](cible.md#piste-optionnelle--visualisation-3d-de-la-mémoire) reste distincte.

## Lots restants

| Lot | Travail | Réception |
|---|---|---|
| Référence et budgets | Reprendre les mesures sur le moteur courant ; inventorier filtres, topologies, droits et consommateurs. | Baseline répétée, caches froid/chaud, objectifs de latence, octets, images et mémoire fixés avant optimisation. |
| Hiérarchie et carte serveur | Groupes récursifs, cycles, communautés denses, branches partagées et isolés ; positions, emprises et générations reprenables. | Chaque item représenté une fois et atteignable ; liens transversaux retrouvables ; reconstruction interrompue sans publication incohérente. |
| Chargement spatial | Contrat viewport/niveau de détail/génération, pagination régionale, préchargement, annulation, cache et éviction ; localisation d'un item et de son chemin. | Parcours au-delà de 3 000 nœuds sans chargement exhaustif initial ; retirer le plafond seulement après cette preuve. |
| Miniatures restantes | Réutiliser les dérivés/cache actuels pour les régions et les lignes visibles de la liste, jusqu'à 500 items par page ; lecture documentaire légère lorsque nécessaire. | Aperçu absent/lent sans blocage ; aucun original téléchargé pour un dérivé prêt ; arrivée sans déplacement, caméra et sélection conservées. |
| Actualisation | Invalidation websocket par région/révision, mutations locales, événements perdus/dupliqués/hors ordre et reconnexion. | Carte et compteurs convergents ; suppression/révocation prioritaire ; réponse ancienne incapable de ressusciter un item. |

Commencer avec ECharts et positions imposées ; comparer WebGL seulement si les mesures
justifient un changement. La suppression du plafond d'affichage ne modifie ni rappel,
limites MCP ni rétention Memory.

## Contraintes de conception

- Partir de la topologie canonique. Un hub partagé ne devient pas une feuille exclusive ;
  remapper les liens traversants sans les perdre ni les compter deux fois.
- Construire une projection versionnée, stable et isolée par périmètre ; préciser filtres,
  règles des liens suggérés, publication atomique et comportement si elle n'est pas prête.
- Borner les régions denses et les arêtes traversantes. Une génération expirée déclenche
  une resynchronisation explicite ; un repli provisoire ne se prétend pas exhaustif.
- Préserver repères locaux et sélection lors du raffinement, avec hystérésis par groupe.
  Localisation, zoom, tactile et clavier offrent des chemins équivalents.
- Vérifier ACL et filtres sur items, groupes, compteurs, caches et aperçus. Comparer les vues
  avec/sans données cachées ; proximité graphique n'accorde aucun accès.
- Annuler les demandes obsolètes et appliquer seulement le bon contexte/génération.
  Nettoyer requêtes, abonnements, timers et URL à la fermeture ; erreur récupérable avec retry.
- Charger les images selon emprise projetée, densité et viewport ; groupes repliés sans
  aperçus de leurs membres. Priorité à la sélection ; icône et titre utilisables sans image.
- Réutiliser les captures inertes et versionnées des domaines. Source multiple résolue
  de façon déterministe ; cache lié au contexte d'accès et à la version.
  Borner concurrence, générations, octets compressés, pixels décodés et images retenues.
- Invalider après mutation, révocation ou changement d'agent/session ; libérer réellement
  les images évincées. Aucun rendu de script documentaire dans un nœud.
- Conserver palette Solaire, i18n et séparation mobile/desktop à 1024 CSS px.

## Qualification

Reprendre `graphBranches.test.mjs`, les tests DB du graphe et les parcours existants du
[catalogue fonctionnel](../../docs/fr/dev/functional-tests.md), avec fixtures synthétiques.
Exercer ouverture, repli/expansion, détail, retour dans une région, erreur/retry,
réouverture, contexte changé, navigation clavier et petit viewport.

Comparer au moins 1 000, 10 000 et 100 000 items : étoile disproportionnée, branches
profondes, communauté dense, multi-appartenances, isolés et droits hétérogènes.
Ces volumes sont des objectifs de qualification, pas des capacités démontrées.

Mesurer première carte utilisable, expansions p50/p95, SQL/lignes, requêtes/octet,
frames pendant les gestes, mémoire/cache, préparation serveur et convergence après mutation.
Comparer avec/sans miniatures, présentes/absentes, à froid/chaud, ainsi que le nombre
d'actions pour retrouver puis ouvrir un item.
Une longue exploration doit revenir à des budgets stables ; le coût d'images ne doit
pas croître avec toute la mémoire à cadrage comparable.

Arbitrages à arrêter avant leur lot : algorithme de regroupement dense, isolation des
projections, filtres, stabilité entre générations, index spatial, readiness et budgets.
Publier les choix structurels en ADR et les résultats dans les guides/audits, avec
retour à la vue précédente pendant qualification. Retirer les lots réalisés sans
maintenir ici l'historique des essais de placement.
