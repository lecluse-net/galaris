# 0236 — Répétabilité du juge sur sorties fixes dans le Lab

- Statut : accepté et implémenté (API et interface).
- Date : 2026-10-25.

Le rapport `GET /api/evaluation/{mechanism}/runs/{run_id}/judge-repeatability` lit
les campagnes et jugements persistés d'un run sous ses droits Lab de lecture ou
d'édition. Il ne relance ni candidat ni juge, ne modifie aucune note et ne lit pas
les corps des sorties. Les revues humaines et d'agents n'entrent pas dans la mesure.

Le résultat du benchmark présente ce rapport dans le panneau « Répétabilité du juge ».
Chargement, absence de mesure, configurations écartées, couverture et erreur récupérable
restent explicites. Les sources sont dépliables et la lecture peut être actualisée.
Les nouvelles publications du benchmark ouvert rechargent le rapport ; fermeture et
changement de contexte annulent la requête et écartent les réponses périmées. Le panneau
reste lisible avec les seuls droits de lecture du Lab, sur ordinateur et mobile.

Les campagnes sont regroupées uniquement lorsque leur configuration JSON enregistrée
est identique, avec digest SHA-256 et identifiants pour retrouver les preuves.
Le modèle avec son empreinte de liaison, la rubrique versionnée avec ses dimensions,
le seuil et l'effort doivent être renseignés
(l'effort peut être nul). Les campagnes historiquement incomplètes sont listées
à part. Un changement de poids, de modèle, de seuil ou d'effort crée un autre groupe.
Ce contrôle ne détecte pas une évolution fournisseur ou un changement de code absent
des snapshots : il décrit les configurations enregistrées, sans certifier leur équivalence réelle.

L'unité fixe est l'identifiant du résultat candidat, jamais une nouvelle génération
sur la même entrée. Un jugement exploitable exige un candidat terminé, un jugement
terminé sans erreur, un score fini entre 0 et 100, un verdict pass/fail et la version
de rubrique attendue. Les sorties sauvegardées déterminent le nombre de jugements
attendus par campagne ; absences et jugements inexploitables restent explicites.
Les campagnes partielles contribuent uniquement leurs jugements déjà publiés.

Sur chaque sortie jugée au moins deux fois, le rapport calcule la moyenne des écarts
absolus de score et le pourcentage de désaccord des verdicts sur toutes les paires de
campagnes. Il moyenne ensuite les sorties répétées d'un même cas, puis donne le même
poids à chaque cas regroupé par entrée/référence. Le nombre de paires ne devient pas
un effectif indépendant. Les calculs évitent l'énumération quadratique des paires et
s'exécutent hors de la boucle API.

Les deux métriques bornées utilisent les intervalles de Hoeffding par cas déjà
versionnés dans le Lab : aucun intervalle sous deux cas, insuffisance signalée sous
20 cas, incertitude non nulle malgré un accord parfait observé. `observations` compte
les sorties répétées ; `judgment_pairs` compte séparément les paires de jugements.
Sans répétition exploitable, les métriques restent inconnues, jamais égales à zéro
par défaut. Le rapport peut évoluer pendant une campagne active ; il conserve la
liste des campagnes lues et ignore toute campagne créée après cette lecture.

Ce lot prépare la séparation des variances mais n'est pas une décomposition de
variance candidat/juge. Les expériences fournisseurs, l'arbitrage
et les gardes décisionnelles restent distincts. Aucun corpus annoté réel ni résultat
fournisseur n'est fabriqué par les fixtures synthétiques.
