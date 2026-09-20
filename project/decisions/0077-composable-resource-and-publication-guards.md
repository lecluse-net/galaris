# 0077 — Composer les réservations et protéger la publication

Statut : accepté — 7 septembre 2026.

Les garanties locales ne suffisent pas lorsqu'une opération appelle un adaptateur qui
réserve lui aussi de la mémoire, ou lorsqu'un worker termine après le remplacement de son
lease. Les contre-exemples sont décrits dans la revue A01–A18 du 7 septembre.

## Décision

- Le budget binaire réserve explicitement les octets propres et une allowance pour les
  adaptateurs enfants. Les enfants consomment cette allowance ; ils ne prennent pas un
  nouveau slot global. La réservation reste détenue jusqu'à leur libération, même si le
  parent est annulé. Sans allowance explicite, les réservations restent indépendantes.
- La génération multimédia et la livraison ont des réservations différentes. Le succès
  fournisseur, son identité et ses reçus sont persistés avant publication. Une observation
  tardive ne dégrade pas le succès ni sa comptabilité. La saturation locale avant appel
  fournisseur reporte l'admission sans consommer de tentative distante.
- Le Lab recharge son run sous verrou et compare le jeton après l'inférence. Publication,
  compteurs et clôture appartiennent à la même transaction. Un résultat terminé pendant une
  annulation est conservé avec son coût ; le run devient `cancelled`. Un worker remplacé
  ne modifie ni résultat, ni coût, ni lease courant. Les appels LLM restent auditables.
- Les écritures en thread sont drainées avant fermeture du descripteur et propagation de
  l'annulation. Une création non publiée est supprimée ; un commit dont l'accusé est perdu
  est vérifié en base avant toute suppression. L'inventaire d'orphelins protège les révisions
  historiques, impose au moins un jour d'ancienneté et exige une application quiescente
  pour appliquer une liste revue, avec revérification des références et du fichier.
- Les callbacks de démarrage/arrêt ont leurs délais. Un composant facultatif peut rester
  dégradé ; son opération encore vivante reste suivie et empêche une seconde instance.
- Les domaines Conversation et Process déclarent positivement les traces LLM libérées.
  Un consommateur absent, actif ou incertain conserve ses preuves. Les coûts et identités
  survivent à l'effacement des prompts/réponses bruts.
- La qualification de livraison contient les identités précédente/candidate, la provenance
  des tests, les résultats de convergence/restauration et les limites du jeu de données.
  La promotion vérifie l'image réellement installée. Un nouvel essai invalide la précédente
  qualification du bundle.

## Conséquences

Les tests portent sur les transactions concurrentes, les annulations aux frontières I/O,
la chaîne réelle de livraison d'un fichier de 100 Mo et les observations contradictoires.
Les catalogues PostgreSQL conservent les expressions CHECK/exclusion exactes à titre
d'observation ; aucune équivalence sémantique SQL ni transformation destructive n'est inférée.

La politique DbAdmin reste celle de 0073/0074 : expansion nullable, diagnostic non bloquant,
remplissage, puis resserrement au passage suivant. Les résultats locaux ne qualifient pas
automatiquement un volume, un ancien binaire ou un fournisseur externe différent.

## Séparation des phases et preuves de volume

Le worker Lab transporte désormais un `RunClaim` détaché entre claim et inférence, puis
un `CaseEvaluation` vers la publication. Les snapshots sont copiés ; aucune instance ORM
modifiable du run ne traverse l'inférence. Le DTO d'évaluation Memory appartient au contrat
public Dream, et son ancien chemin reste réexporté. La bibliothèque Memory et la projection
d'un item sont séparées des commandes ; les façades existantes restent compatibles.

Le composable Process possède le dialogue, les actions et la durée de vie du rafraîchissement.
Une génération de sélection distingue les actions tardives du rechargement qu'elles déclenchent
elles-mêmes ; fermer la fiche ou démonter la page invalide les notifications tardives.
Les privilèges sont revérifiés après confirmation d'une suppression.

La qualification locale ajoute une simulation de rétention sur douze semaines, une bibliothèque
avec 100 000 révisions et des mesures DbAdmin par phase avec écrivain concurrent. Le nombre
de requêtes, les allocations Python et les octets logiques sont distingués de la RSS et de
l'espace physique PostgreSQL. Ces preuves ne remplacent pas la qualification de l'installation.
