# Mémoire conversationnelle — seconde qualification du 29 octobre 2026

## Problème et changement

Une relance courte perdait son sujet lors du repli lexical : l'historique alimentait
la graine sémantique mais pas les termes lexicaux. Deux reproductions FR/EN, passant
par la composition réelle du contexte et le stockage PostgreSQL, échouaient avant
correction avec zéro souvenir pertinent injecté. Elles passent après correction.

La requête peut reprendre le dernier message humain distinct parmi six messages
récents pour les références conversationnelles FR/EN. Elle reste limitée à 18 mots et
240 caractères ; le message sélectionné est limité à 600 caractères. Les réponses de
la machine ne fournissent pas ce sujet lexical. Un changement explicite de sujet écarte
l'ancien historique des graines lexicale et sémantique. Le titre d'une tâche nommée et
le titre structuré d'un Goal conservent leur priorité lexicale. Aucun appel modèle,
paramètre, schéma ou droit supplémentaire n'est introduit.

La détection est déterministe et bornée : elle ne constitue pas une résolution linguistique
générale, notamment pour les longues chaînes de pronoms ou les changements de sujet implicites.
Les paroles humaines servent d'indice de recherche et ne deviennent pas une preuve factuelle.

## Comparaison initiale

La référence est la version après le premier lot d'améliorations, y compris sa réservation
de places ordinaires sous saturation du calendrier. Elle est figée avant ce changement.
Chaque bras utilise désormais ses propres constructeurs de requêtes : partager le constructeur
courant aurait contaminé la référence avant même le rappel. Deux tests couvrent les signatures
anciennes/récentes et 16 constructions entrelacées par cas.

Les mêmes 396 requêtes synthétiques, 360 souvenirs et trois mondes sont comparés avec
les mêmes droits, horloges, budgets et ordre alterné. Les 348 questions répondables portent
les scores de rappel ; les questions inconnues ne gonflent pas leur dénominateur.

| Mesure | Avant cette modification | Après |
|---|---:|---:|
| Rappel des faits retrouvés, @8 | 84,6 % | 89,9 % |
| Rappel des faits injectés, @8 | 76,4 % | 81,0 % |
| Questions avec toutes leurs preuves injectées | 68,4 % | 74,1 % |
| Références pronominales : faits injectés | 25,0 % | 100 % |
| Relances : faits injectés | 33,3 % | 83,3 % |
| Questions avec résultat interdit | 0 | 0 |

Ces scores portent sur le repli lexical réel et un calendrier volontairement saturé.
Les traductions et reformulations d'une famille ne sont pas des situations indépendantes.
Une présence dans le contexte ne prouve pas une réponse correcte du modèle.

## Campagne élargie sans ajustement sur les profils réservés

Le même changement est mesuré sur 1 584 requêtes, 3 360 souvenirs chargés dans un même
index et 12 mondes isolés. Quatre domaines ont chacun 396 requêtes ; les partitions
développement, validation et heldout ont chacune 528 requêtes. Les 1 392 questions
répondables portent les scores. Les 33 familles, deux langues, reformulations et cinq
régimes calendaires sont conservés, avec 200 distracteurs par monde et quatre workers.
Les profils d'évaluation n'ont pas servi à ajuster le moteur après observation.

| Mesure | Avant cette modification | Après |
|---|---:|---:|
| Rappel des faits retrouvés, @8 | 82,0 % | 87,2 % |
| Rappel des faits injectés, @8 | 75,3 % | 80,0 % |
| Questions avec toutes leurs preuves injectées | 66,5 % | 72,3 % |
| Références pronominales : faits injectés | 25,0 % | 100 % |
| Relances : faits injectés | 27,1 % | 83,3 % |
| Profils heldout : faits injectés | 75,7 % | 80,6 % |
| Questions avec résultat interdit | 0 | 0 |

Aucun échec de fournisseur du contexte n'est masqué dans cette campagne. Le fournisseur
vectoriel est remplacé uniquement à sa frontière par son erreur de non-configuration,
pour exercer le repli réel. La plus grande taille de brief observée est de 4 147 caractères,
sous le budget de 12 000. La moyenne SQL passe de 33,40 à 33,76 instructions par requête :
le gain de qualité n'est pas présenté comme une réduction du travail de recherche.

## Réponses réelles et limite d'attention

Le contrôle opt-in prépare 40 contextes appariés et conserve leurs empreintes, y compris
celles des sources de référence. Une capture exploratoire de 40 réponses est suivie d'un
contrôle final ciblé de 12 réponses : quatre relances répondables et deux inconnues, par
bras, avec le même modèle de conversation configuré et un ordre alterné. Le sujet humain
ne fournit jamais la valeur attendue. Les attendus restent extérieurs à l'inférence.

Dans ce contrôle final, les quatre preuves utiles passent de zéro à quatre présences
dans le contexte. Les réponses factuellement correctes et correctement citées passent
de zéro à trois sur quatre. Une réponse reste nulle malgré la présence de la preuve.
Les deux inconnues conservent une abstention dans chaque bras. Les montants avec leur
unité source sont distingués de l'égalité stricte de chaînes. La capture exploratoire
avait obtenu quatre réponses correctes sur ces mêmes quatre formulations : ces petits
échantillons montrent une variabilité, pas un taux de réussite généralisable.
Ce contrôle ne mesure pas l'initiative de recherche d'un agent autonome ni un transport Messenger.

## Vérifications supplémentaires

Les 69 tests ciblés passent. Ils couvrent les limites et les changements de sujet,
360 historiques générés de manière déterministe, des messages non humains et mal formés,
la priorité des tâches nommées et des titres de Goal. Ils conservent la couverture existante
des corrections, suppressions et retraits d'accès pendant un rappel en cours.

Le test concurrent ouvre quatre vraies sessions indépendantes pour deux agents et deux
contacts distincts par agent. Les appels sont synchronisés à la frontière du fournisseur,
puis chaque capsule est rouverte dans une nouvelle transaction : chaque contexte conserve
sa propre preuve et exclut celles des trois autres interlocuteurs.

## Défaut supplémentaire révélé par la suite complète

Le premier passage étendu obtient 684 succès, cinq échecs et un scénario opt-in ignoré.
Deux échecs sont une vraie panne de recherche filtrée par sujet : le prédicat d'appartenance
réutilise `MemoryLink` à l'intérieur d'une requête qui joint déjà cette table. SQLAlchemy
autocorrèle alors ses deux tables et produit un `EXISTS` sans clause `FROM`.
L'analyse des variantes retrouve le même contexte dans l'expansion du graphe et les compteurs
d'enfants. Les requêtes de simple lecture et les filtres isolés n'exerçaient pas cette combinaison.

La correction borne explicitement la corrélation à `MemoryItem` dans le prédicat partagé.
Les contradictions, voisins et compteurs conservent leur propre lien d'appartenance.
Le test de contradiction ajoute un filtre de sujet et une preuve hors sujet du même agent ;
le test de navigation ajoute expansion, enfants et voisins d'autres contacts/sujets.
Ces reproductions échouent avant correction. Ce renforcement vérifie l'absence de fuite et
le résultat réel, au-delà d'une simple compilation de SQL ou d'une assertion de source.

Les trois autres échecs venaient d'un champ retiré des révisions Document dans une fixture
legacy, des anciens privilèges Params à la place de Dream et d'un attribut calculé expiré
lu implicitement dans une fixture async. Les attentes et le chargement synthétique sont
actualisés ; aucun droit produit n'est assoupli. Leur sélection de 75 tests passe.

La grande comparaison précède ce dernier correctif SQL indépendant de la continuité ;
le rejeu des 396 requêtes sur le code final conserve exactement 81,0 % de rappel injecté
et 74,1 % de preuves complètes, sans résultat interdit. Les empreintes des trois fichiers
de production modifiés correspondent au manifeste de ce rejeu.

La dernière sélection du domaine mémoire et des outils de mesure obtient **689 succès
et deux scénarios opt-in ignorés**. Ces deux chemins ont été exécutés séparément :
préparation configurée des contextes et campagne complète. Les 38 tests ciblant le
correctif SQL, ses variantes et le second consommateur de la fixture legacy passent.
Le contrôle strict de types passe, ainsi que les 459 tests unitaires frontend et la
parité des traductions. Les 33 tests de contrats et d'outillage d'architecture passent
également. Cela ne constitue pas la validation complète de l'application ;
aucun parcours navigateur, Task autonome ou environnement de production n'a été exercé.

Les contrôles documentaires FR/EN et les contrats d'architecture passent sur les snapshots
de préparation. La publication des cartes et le rafraîchissement de l'index documentaire
restent refusés par la garde : d'autres modifications frontend changent les sources pendant
la génération. Aucun index ou fichier généré n'est forcé à partir d'un snapshot devenu périmé.

Le fournisseur d'embeddings configuré reste injoignable après une nouvelle requête sur
une phrase synthétique. Les vecteurs prescrits ne sont pas présentés comme une mesure
de pertinence sémantique. Aucun gain de latence n'est revendiqué sous la charge partagée
des contrôles. Les journaux, données synthétiques et sources figées restent dans les
artefacts locaux ; ce compte rendu conserve des agrégats sans données d'installation.
