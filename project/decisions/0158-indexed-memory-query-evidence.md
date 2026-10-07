# 0158 — Preuves lexicales indexées et complémentarité du rappel mémoire

Statut : accepté. Date : 2026-10-04.

## Problème

Le classement normalisait les accents après la présélection SQL. Un souvenir dont
le nom comportait un accent pouvait donc manquer dès la génération de candidats,
même avec une requête équivalente sans accent. Découper les mots avant cette
normalisation coupait aussi certaines écritures Unicode décomposées.
Une concordance de mots isolés ne distinguait pas suffisamment une personne nommée
de plusieurs personnes portant séparément son prénom et son nom. Enfin, plusieurs
profils pouvaient consommer le budget au détriment d'un événement complémentaire.

## Décision

La recherche utilise une seconde projection FTS stockée, `search_vector_folded`,
avec un index GIN. PostgreSQL calcule la projection avec ses fonctions immuables
intégrées : minuscules, décomposition NFKD, retrait des caractères combinatoires,
et équivalences usuelles du sharp-s et du sigma final. Les poids titre/mots-clés/texte
restent ceux de la projection existante. Les plages combinatoires correspondent à
Unicode 16 utilisé par Python 3.14. La requête est normalisée avant son découpage
et transmise comme paramètre SQL. Aucun texte utilisateur n'entre dans l'expression
DDL. Le contenu original et la première projection sont conservés ; la nouvelle
colonne est différée dans les lectures ORM ordinaires.

Le rappel repère au plus deux groupes de mots explicitement capitalisés, de quatre
mots au maximum. Leur concordance exige la séquence complète, contrairement à
une simple concordance indépendante des mots. Le signal agit avant la limite SQL
des candidats et dans le classement fusionné. Les termes de ces groupes ont un
poids renforcé, et leur couverture manquante guide les premières sélections. La
priorité explicite supplémentaire est bornée aux deux premières places une fois
les groupes couverts, pour éviter d'écarter une information indirectement liée.
Les UUID, URI et titres exactement demandés conservent la priorité maximale.

La sélection couvre aussi les identités encore absentes dont le nom commence un
titre ; une simple mention dans un titre d'événement ne couvre pas cette facette.
La priorité cesse dès que l'identité est couverte, afin que plusieurs profils de
la même personne ne chassent pas un événement ou un rôle distinct. Les verbes
introductifs usuels, comme « Rappelle-moi », ne deviennent pas des noms. La sélection
récompense les termes et identités encore absents. Ce sont des
signaux bornés de classement, pas la preuve que deux souvenirs constituent deux
faits différents. Les scores exposés restent entre zéro et un. Les ensembles de
mots utilisés par la pénalité de similarité sont calculés une fois par candidat.

Une question visant une relation indirecte distingue la personne de référence de
la cible. Le nom doit être rattaché à une demande comme « le collègue de X » ou
« X's colleague » ; « mon collègue X » conserve X comme personne recherchée.
Des règles bornées français/anglais reconnaissent des assertions positives
entre deux noms complets dans les extraits accessibles, en exigeant la catégorie de
relation demandée. Les négations, citations et formulations incertaines sont écartées.
La proposition affirmative entière entre les noms doit correspondre à une forme
prise en charge ; la simple présence d'un prédicat ne suffit pas, notamment pour
les négations contractées et les hypothèses rapportées.
Si plusieurs noms différents satisfont la relation, aucune cible n'est promue.
Le classement conserve le rôle de la cible et une preuve de relation. Un voisin du
graphe déjà obtenu par un lien confirmé fort peut alors participer au rappel même
sans terme lexical commun, si son titre commence par le nom complet ainsi résolu.
Cette exception ne vaut pas pour les autres voisins et n'ajoute aucune traversée.
Les cibles textuelles sont limitées à seize groupes ; ce n'est ni une résolution
générale des identités ni une preuve d'absence d'homonymie.

Après la couverture de l'identité, un terme demandé encore absent reçoit une priorité
sur un profil répétant le nom. Une signature des mots de l'extrait conserve les
nombres et leurs signes, les accents, les négations, les questions et les différences
de formulation. Une répétition de cette
signature est rétrogradée, jamais fusionnée, supprimée ou interdite. Cette règle ne
prouve pas l'équivalence sémantique des paraphrases et traductions ; celles-ci restent
distinctes. Les chiffres, dates et contradictions ne deviennent pas des doublons
par une simple similarité vectorielle.

Le changement ne déclenche ni recherche supplémentaire ni appel de modèle.
Les ACL, la validité, l'isolation des contacts, l'admission finale et les budgets
restent ceux du rappel canonique. La branche temporelle conserve ses ancres
partielles, sa fenêtre et sa priorité ; « hier » n'est pas transformé en ancre.
La résolution des dates historiques et des pronoms reste un chantier distinct.

## Vérification et conséquences

Les tests DB couvrent les accents composés/décomposés, des équivalences Unicode,
les changements de contenu, les noms complets face aux faux rapprochements,
la coexistence profil/événement et les garanties existantes d'accès et de temps.
Les tests couvrent aussi la cible indirecte et sa preuve en rappel lexical et hybride,
les voisins privés, expirés, oubliés, d'un autre contact ou ancrés hors fenêtre,
les liens faibles/suggérés et les relations négatives, citées ou incertaines.
Un corpus entièrement synthétique permet de comparer le moteur courant à une
copie figée du précédent dans la même base éphémère. L'ordre est alterné et les
résultats retrouvés sont mesurés séparément du contexte injecté. Les deux versions
préservent la priorité temporelle. Les sources figées et les sorties restent sous
`artifacts/`, hors versionnement ; aucune donnée réelle n'alimente les fixtures.

La projection ajoute du stockage et du travail à l'écriture. DbAdmin l'ajoute et
calcule les valeurs pour les lignes existantes lors de la convergence du schéma ;
aucune migration manuelle ou extension PostgreSQL n'est nécessaire. La mesure
ancien/nouveau sur un schéma commun qualifie la lecture, pas le surcoût d'ingestion
ni la durée de construction initiale sur une très grande installation.

Cette heuristique ne résout pas les homonymes, les surnoms inconnus, les noms sans
capitales ou les références implicites de façon générale. Les mesures lexicales
ne qualifient ni un fournisseur d'embeddings réel ni une réponse finale du modèle.
