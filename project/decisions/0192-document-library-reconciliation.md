# 0192 — Réconciliation de la bibliothèque documentaire

Statut : accepté. Date : 2026-10-17.

## Garantie

Une suppression confirmée par l'utilisateur masque immédiatement ses occurrences dans la
bibliothèque, même si le serveur tarde. Un refus réaffiche les données les plus récentes.
Les sauvegardes confirmées se propagent dans l'arbre et la liste avant les relectures.
Recherche, pagination, classement personnel, droits et rafraîchissement restent gouvernés
par les réponses du serveur.

## Décision

Un store Pinia `memory.documentMutations` partage uniquement les commandes de suppression
en cours entre éditeurs et bibliothèques. Les vues filtrent leurs instantanés sans les
détruire : le rollback retire le filtre, sans restaurer une ancienne copie. Chaque commande
possède un numéro ; une réponse ancienne ne peut terminer une nouvelle commande. Le changement
d'identité efface cet état ; le renouvellement du jeton de la même session le conserve.

Les instantanés de liste et de branches restent propres à la bibliothèque montée. Une
projection indexée par UUID porte l'item courant de chaque document ; toutes ses occurrences
utilisent cette même valeur. Les réponses de versions antérieures ne remplacent pas les
versions récentes et les items sans occurrence sont retirés de cette projection. Une
sauvegarde reçue de l'éditeur actualise toutes les occurrences connues, avec contrôle de
`lock_version`, puis demande leur réconciliation serveur. Les lectures supplantées sont
annulées ; leurs générations restent contrôlées. Les notifications pendant une lecture
se regroupent dans une réconciliation suivante. Les changements d'accès et les reconnexions
continuent à déclencher une relecture immédiate des vues ouvertes.

Les propriétaires et mots-clés constituent des catalogues de filtres indépendants de la
page et de la recherche. Leur génération locale est invalidée par les notifications de
documents, les mutations, les changements d'accès, de session et les reconnexions. Les
changements de filtres et de page réutilisent les catalogues courants. Le contrat HTTP
conserve `include_owners` et ajoute `include_keywords`, vrai par défaut pour préserver
les consommateurs existants. Les branches et les recherches de liens n'en demandent pas.

Le contenu courant s'affiche avant le chargement des catalogues de l'éditeur et des pièces
jointes. Ces chargements possèdent leurs propres générations. Le brouillon de partage
dépend des grants du document, indépendamment de l'arrivée des options de propriétaires.
Une lecture de lien direct peut fournir son résultat initial à l'éditeur ; cette valeur
est consommée une fois. Une réouverture et un rafraîchissement relisent le serveur.

## Vérification

`document-flows.spec.mjs` retient les réponses HTTP pour vérifier ouverture, retrait et
restauration, propagation des titres et regroupement des rafraîchissements.
`document-classification.spec.mjs` conserve les garanties de placement et de réponses
tardives, y compris lorsque les lectures sont annulées. `test_library_performance.py`
compare les mêmes résultats avec et sans catalogues sur un corpus synthétique ; son
compteur couvre `SELECT` et `WITH`. Les diagnostics restent sous `artifacts/`.
