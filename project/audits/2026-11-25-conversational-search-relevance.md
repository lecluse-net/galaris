# Pertinence du contexte documentaire et mémoriel en conversation

## Observation

Sur six tours consécutifs examinés en lecture seule, le prompt contenait à chaque fois dix
références documentaires de continuité et six à huit références dans la mémoire longue.
Aucun appel d’outil de recherche n’a eu lieu. Des références à d’anciens travaux techniques
revenaient même lorsque le sujet avait changé. Certaines avaient pour titre un identifiant.

Un rejeu lexical hors ligne des correspondances de mots, avec les titres actuels et les
intitulés historiques des tâches, conserve quatre des soixante occurrences documentaires.
Elles appartiennent à un seul tour. Ce rejeu évalue la sélection parmi les anciens candidats.
Il ne reconstruit ni l’index ni les réponses du modèle à la date des échanges.

## Mesures sur corpus synthétiques

| Épreuve | Mesure | Référence | Correction |
|---|---|---:|---:|
| 17 tours, souvenirs | Précision des éléments injectés | 6,6 % | 100 % |
| 17 tours, continuité documentaire | Précision des éléments injectés | 5,9 % | 100 % |
| 17 tours, chaque canal | Rappel des sources attendues | 100 % | 100 % |
| 17 tours, chaque canal | Abstention quand aucune source n’est attendue | 0 % | 100 % |
| 528 questions, mémoire ordinaire | Précision moyenne dans les huit premières places | 26,26 % | 26,58 % |
| 528 questions, mémoire ordinaire | Rappel des faits attendus | 82,94 % | 82,94 % |
| 528 questions, mémoire ordinaire | Questions avec tous les faits attendus | 77,16 % | 77,16 % |
| 64 questions sans fait attendu dans la campagne large | Contextes vides | 8 | 8 |

La première épreuve impose un voisinage vectoriel artificiellement homogène, une
paraphrase, des titres de collection répétés et des demandes hors sujet. Les deux versions
utilisent les mêmes jugements de pertinence et les mêmes vecteurs contrôlés. La deuxième
compare les versions question par question sur 1 128 items, avec 132 questions par domaine
(entreprise, indépendant, vie personnelle et association). Elle utilise PostgreSQL et le
repli lexical. Aucun résultat interdit ni erreur de fournisseur de contexte n’a été observé
dans les deux bras. Les valeurs de précision des deux épreuves ont des dénominateurs différents.

Un filtre initial plus strict portait la précision de la campagne large à 29,39 % et
abaissait le rappel des faits à 79,17 %. La version retenue conserve les appuis lexicaux
distinctifs et les cibles dont une relation est établie. Sur ce corpus large, le gain de
précision reste faible et 56 des 64 questions sans fait attendu reçoivent encore du contexte.
Les mesures portent sur les éléments fournis au modèle. Une tentative de mesure des
embeddings configurés en développement a échoué à la connexion.

## Reproduire le contrôle ciblé

```bash
make tests ARGS='app/memory/tests/test_turn_relevance_benchmark.py -q -s'
make tests ARGS='app/memory/tests/test_recall_evaluation.py app/file_share/tests/test_resource_search_qualification.py -q -s'
```

La campagne appariée emploie quatre mondes, quatre workers et les variantes `previous,baseline`
du harnais existant. Les rapports distinguent les candidats retrouvés des éléments injectés.
[Protocole du benchmark](../../back/scripts/memory_benchmark/README.md)

La recherche de termes dans un même bloc d’Obsidian a guidé le contrôle du passage cité.
Graphiti combine signaux lexicaux, sémantiques et relationnels. LongMemEval évalue aussi
l’abstention, ce qui motive ici de compter les contextes vides sur les cas sans preuve.
[Obsidian Search](https://obsidian.md/help/plugins/search) · [Graphiti](https://github.com/getzep/graphiti) · [LongMemEval](https://arxiv.org/abs/2410.10813)

## Deuxième comparaison — sujet et renseignement demandé

La référence de cette comparaison est la correction du tableau précédent. Une nouvelle
épreuve de régression emploie deux maisons fictives au nom proche. Une question sur le
code d'entrée de l'une ramenait la note de l'autre, y compris lorsque le code figurait
dans une note et le nom recherché dans une autre. Le test vérifie le cas en minuscules,
une demande d'identité, une réponse dans l'autre langue et une question à deux volets.
Le classement entre fichiers et souvenirs vérifie aussi que le nom et le détail
apparaissent dans le titre et un même passage.

Le moteur reconnaît certaines demandes de détail en français et en anglais, dont un
lieu, une quantité, une décision et une procédure. Il privilégie les passages qui
rattachent ce détail au sujet. Une question d'identité explicite peut rester sans
contexte si le nom complet manque. Quand une question comporte plusieurs demandes,
une source qui ne répond qu'à une partie peut rester utile. Les contrôles de portée et
de révision précèdent la sélection du passage.

Les deux campagnes comparent les versions sur les mêmes requêtes, avec quatre workers
par campagne et PostgreSQL en repli lexical. Le corpus initial et le corpus réservé
partagent 33 familles de formulations. Le second change de graine, de profils et de
faits et double le nombre de distracteurs, de 200 à 400 par monde. Ses quatre domaines
sont la restauration, la photographie, la garde d'animaux et le jardin associatif.
Les jugements du benchmark restent extérieurs au moteur. Les statistiques portent
sur la liste ordonnée de huit éléments au maximum que le modèle reçoit. Une question
sans fait requis peut avoir un contexte auxiliaire autorisé.

Le corpus réservé se régénère avec cette commande, dans un répertoire de sortie neuf.

```bash
make memory-benchmark ARGS='generate --output /output/detail-relevance-heldout --profiles catering photography pets community_garden --seed 59047 --repetitions 1 --distractors 400'
```

Pour comparer deux implémentations, conserver les sources de référence avant modification
et utiliser les variantes `previous,baseline` sur les quatre mondes avec le
[harnais de mesure](../../back/scripts/memory_benchmark/README.md). Le manifeste du
harnais contient les empreintes, le budget, le nombre de workers et les modes réellement
utilisés. Les fichiers de traces contiennent les extraits effectivement transmis.

| Mesure du contexte injecté | Initial, avant | Initial, après | Réservé, avant | Réservé, après |
|---|---:|---:|---:|---:|
| Précision moyenne, huit places maximum | 26,58 % | 33,07 % | 27,75 % | 34,88 % |
| Rappel des faits requis | 82,94 % | 84,45 % | 83,19 % | 84,27 % |
| Questions dont tous les faits requis sont présents | 77,16 % | 78,88 % | 76,51 % | 77,59 % |
| Rang réciproque moyen du premier fait requis | 0,659 | 0,753 | 0,660 | 0,754 |
| Contextes vides sur 64 questions sans fait requis | 8 | 24 | 8 | 24 |

Avant la sélection du contexte, la précision des résultats de recherche passe de 26,26 %
à 27,23 % sur le corpus initial et de 27,06 % à 28,22 % sur le corpus réservé.
Dans le contexte injecté, la précision individuelle augmente pour 65 questions et baisse
pour quatre sur le premier corpus. Sur le second, elle augmente pour 60 et baisse pour
quatre. Deux questions de procédure perdent un fait complémentaire sur le corpus réservé.
Aucun résultat interdit ni erreur d'assemblage du contexte dans les deux campagnes.

Le premier essai sur le corpus initial atteignait 35,27 % de précision. La version
livrée conserve davantage de contexte pour les formulations composées et les paraphrases.
Les 40 contextes encore non vides sur 64 se répartissent entre demandes visant des notes
d'un autre agent, éléments oubliés et documents dont le partage a été retiré. Tous les
cas d'identité inconnue de ces deux campagnes donnent un contexte vide. Le fournisseur
d'embeddings configuré en développement a échoué sur les entrées synthétiques. Les
résultats ci-dessus mesurent le repli lexical et s'arrêtent avant la génération de réponse.

## Troisième comparaison — événements passés et procédures

Deux défauts se reproduisaient sur des souvenirs synthétiques. Une date en tête du fait
personnel échappait au rappel « la semaine dernière » quand le souvenir n’avait aucune
ancre de calendrier. Une recherche de procédure pouvait fournir les étapes seules, alors
qu’un autre souvenir décrivait le matériel obligatoire.

Le rappel par période peut maintenant utiliser la date explicite en tête d’un souvenir
personnel de 800 caractères au maximum. Les énoncés courts en français et en anglais
acceptent le format ISO et les dates avec mois en lettres. La présence de plusieurs
années datées exclut cette interprétation. La date de l’événement accompagne le passage
jusqu’au contexte et à la recherche de fichiers. Les questions sur la date de rédaction
gardent leur propre critère. Le test passe une frontière d’année et vérifie une note
privée, un homonyme, une date impossible, une date seulement citée et la borne de fin.

Sur une question qui demande la teneur d’un échange pendant une période, le classement
cherche un passage qui décrit un échange sur le sujet. Cela permet à une discussion
plus ancienne de passer devant des opérations plus récentes de la même personne.
Pour les procédures, les étapes et les prérequis constituent deux aspects complémentaires.
Le classement favorise l’aspect manquant lorsque les premières notes répètent le même.

La référence est la version livrée à la deuxième comparaison. Les deux bras emploient
l’horloge du scénario, y compris dans l’interprétation des périodes relatives. La mesure
supplémentaire sur le corpus réservé active `--memory-benchmark-derived-titles`. Chaque
titre de souvenir y est dérivé des premiers caractères du texte visible comme dans le
chemin de création natif. Les questions, les faits attendus et les distracteurs restent
identiques à ceux de l’épreuve avec titres rédigés.

| Campagne de 528 questions | Précision avant → après | Rappel des faits avant → après | Questions avec tous les faits avant → après |
|---|---:|---:|---:|
| Corpus initial, titres rédigés, 1 128 éléments | 33,07 % → 35,76 % | 84,45 % → 90,63 % | 78,88 % → 85,78 % |
| Corpus réservé, titres rédigés, 1 928 éléments | 34,88 % → 37,42 % | 84,27 % → 90,12 % | 77,59 % → 84,27 % |
| Même corpus réservé, titres natifs | 23,25 % → 26,73 % | 70,04 % → 76,54 % | 59,05 % → 65,73 % |

Les 32 questions distinctes sur les échanges de la semaine précédente retrouvent
la source attendue au premier rang, contre aucune auparavant. Sur les 16 questions
de procédure du corpus réservé avec titres natifs, le rappel moyen des faits attendus
passe de 31,25 % à 100 %. Dans cette même campagne, 39 questions gagnent au moins
un fait requis, aucune n’en perd et une question baisse en précision. Le modèle reçoit
encore du contexte pour 40 des 64 questions sans fait requis dans chaque campagne.
Aucun résultat interdit ni erreur d’assemblage n’a été observé.

Ces mesures évaluent le contexte injecté avec le repli lexical. La nouvelle tentative
sur les phrases synthétiques auprès du fournisseur d’embeddings de développement a
renvoyé `EmbeddingError`. Les réponses finales d’un modèle et la latence en production
n’ont pas été mesurées. Le passage des titres rédigés aux titres natifs est une
réévaluation des mêmes questions, et non un troisième corpus indépendant.

## Quantités, durées et périmètre dans les passages

Une question sur une quantité peut trouver un document qui annonce la quantité comme
encore inconnue, alors que le document qui donne le chiffre ne contient pas le mot
« quantité ». Un scénario PostgreSQL reproduit ce cas avec deux documents partagés,
un document privé et un souvenir personnel. Avant la correction de l’index documentaire,
le contexte retenait le document d’attente et le souvenir. Après correction, il cite
le document contenant la mesure et son unité. Le retrait du partage supprime cette
preuve dès le tour suivant.

Le classement vérifie si une phrase rattache la mesure, la durée ou la restriction au
sujet demandé. Un titre constitué uniquement du sujet peut qualifier le passage qui
le suit. Une date ou un horaire isolé compte parmi les leurres. Pour un sujet explicite
de deux à six termes, l’index documentaire peut aussi proposer des passages qui
contiennent tous les termes du sujet. Cette recherche conserve les contrôles d’accès,
la fenêtre bornée de candidats et le budget du contexte. Un passage trouvé uniquement
par le sujet doit apporter le détail demandé pour être transmis.

Les trois campagnes appariées comparent la même version figée avant cette correction
au classement final. Chacune évalue 528 questions, dont 464 avec au moins un fait
requis, réparties entre 33 familles en français et en anglais. La troisième utilise
les titres natifs et quatre profils supplémentaires (logistique, architecture, voyage
et bibliothèque), avec la graine 34289 et 400 distracteurs par monde. Elle a été
générée après la dernière modification du moteur. Elle réemploie les familles de
formulations du générateur. Les scores portent sur les résultats effectivement injectés
par le canal mémoire ordinaire en repli lexical, dans la limite de huit éléments.

| Campagne | Précision avant → après | Rappel des faits avant → après | Questions couvertes intégralement avant → après |
|---|---:|---:|---:|
| Initiale, titres rédigés, 1 128 éléments | 35,76 % → 38,17 % | 90,63 % → 91,27 % | 85,78 % → 86,42 % |
| Réserve, titres natifs, 1 928 éléments | 26,73 % → 30,25 % | 76,54 % → 78,05 % | 65,73 % → 67,24 % |
| Quatre profils supplémentaires, titres natifs, 1 928 éléments | 25,96 % → 29,27 % | 73,64 % → 76,22 % | 63,36 % → 65,95 % |

Sur les 16 demandes de quantité de la troisième campagne, le rappel passe de
37,5 % à 100 % et la précision de 20,31 % à 87,5 %. Sur les 16 demandes de périmètre,
le rappel passe de 81,25 % à 93,75 % et la précision de 15,63 % à 57,81 %.
Au total 22 questions gagnent au moins un fait attendu et aucune n’en perd.
Deux formulations de la campagne initiale baissent en précision, car une procédure
mentionne un nombre de pièces à contrôler alors que la question vise la taille du lot.
Dans chaque campagne, 40 des 64 demandes sans fait requis reçoivent encore du contexte.
Aucun identifiant interdit n’apparaît dans les résultats injectés. La qualité des réponses
générées et la latence en production restent hors du périmètre de ces mesures.

## Attribution des rôles et des surnoms

Sur le corpus de quatre profils supplémentaires, les 16 demandes de rôle utilisant
un prénom ambigu recevaient un contexte vide avec les titres natifs. En PostgreSQL
isolé, deux notes attribuant des rôles à deux personnes de même prénom reproduisent
ce défaut. Une note sur la visite de l’une d’elles peut également être très proche
de la question dans l’index vectoriel.

Le classement privilégie les passages qui attribuent la responsabilité à la personne
nommée. Une fois un homonyme représenté, un passage concernant un second homonyme
peut occuper la prochaine place. Pour une demande explicite de surnom, le contexte
vérifie le sujet de la dénomination. Le surnom d’une personne mentionnée dans un
projet et le nom de code du projet conduisent ainsi à des sélections différentes.
Les tests exercent aussi un document, les champs de profil, le discours rapporté,
une demande composée et un nom de projet antérieur.

Chaque campagne compare les deux versions sur les mêmes 528 questions synthétiques
en français et en anglais, réparties en 33 familles. Les mesures portent sur les
passages effectivement transmis à l’agent.

| Corpus | Précision avant → après | Rappel des faits avant → après | Questions couvertes intégralement avant → après |
|---|---:|---:|---:|
| Titres rédigés, 1 128 éléments | 38,17 % → 39,08 % | 91,27 % → 91,27 % | 86,42 % → 86,42 % |
| Titres natifs, 1 928 éléments | 29,27 % → 31,69 % | 76,22 % → 79,67 % | 65,95 % → 69,40 % |
| Nouveau corpus de contrôle, titres natifs, 1 928 éléments | 30,31 % → 32,73 % | 77,62 % → 81,07 % | 68,53 % → 71,98 % |

Sur chacun des deux corpus à titres natifs, le rappel des faits pour les 16 questions
de rôle avec homonymie passe de 0 % à 100 % et leur précision atteint 80 %. Sur les trois
campagnes, aucune question ne recule en précision ou en rappel. Le corpus de contrôle
change les profils, les contenus et la graine de génération, tout en conservant les
familles et les modèles de questions.

Dans chaque corpus, les demandes sans fait attendu qui reçoivent tout de même du
contexte passent de 40 à 32 sur 64. Les 32 restantes concernent l’isolation entre
agents (16), des accès révoqués (8) ou des souvenirs effacés (8). Le contexte injecté
contient d’autres éléments autorisés et aucun identifiant interdit.

Le fournisseur d’embeddings de développement a renvoyé une erreur sur les phrases de
contrôle. Les trois campagnes mesurent donc le repli lexical. Un test PostgreSQL
distinct utilise des vecteurs contrôlés en français et en anglais et vérifie que le
document attribuant le rôle est injecté tandis qu’une note de visite, même au-dessus
de 0,95 de similarité, est écartée. La qualité des réponses générées et le gain en
production restent à mesurer.

## Contact d’un projet et demandes visant une source privée

Dans les observations de départ, la recherche lexicale trouvait l’affectation d’un
contact à un projet, mais le contexte pouvait être vide pour une question comme
« À qui en parler ? ». Le nom du projet était commun aux titres des résultats et
le verbe de la question ne figurait pas dans l’affectation. À l’inverse, demander
expressément la note privée d’un autre agent pouvait faire entrer jusqu’à huit
passages autorisés qui mentionnaient simplement le même sujet.

Le classement reconnaît désormais une affectation portant sur le projet demandé ou
une instruction qui désigne son interlocuteur. L’index peut retrouver un passage
français à partir du nom propre dans une question anglaise. Le contexte automatique
s’abstient lorsqu’une demande vise exclusivement la mémoire privée d’un autre agent.
Les tests exercent les droits sur un document indexé avant et après révocation.

Chaque ligne compare la version précédente à la correction sur 528 questions FR/EN,
33 familles et 1 928 éléments à titres natifs. Le nouveau contrôle utilise quatre
autres profils (énergie, formation, animaux, bénévolat) et la même grammaire de
génération. Les mesures concernent le contexte effectivement transmis.

| Corpus | Précision | Rappel des faits | Questions avec tous les faits | Contexte non vide sans fait attendu |
|---|---:|---:|---:|---:|
| Corpus de la comparaison précédente | 32,73 % → 34,91 % | 81,07 % → 82,79 % | 71,98 % → 73,71 % | 32/64 → 16/64 |
| Nouveau contrôle | 31,96 % → 34,19 % | 79,45 % → 81,18 % | 69,18 % → 70,91 % | 32/64 → 16/64 |

Sur les 16 questions de contact de projet par corpus, le rappel passe de 50 % à
100 %. La précision atteint 100 %, contre 25 % et 21,88 % respectivement.
Aucune question ayant un fait attendu ne perd en précision ou en rappel. Le scoreur
accordait un crédit facultatif à quelques passages de questions sans réponse. Leur
suppression explique les seules baisses individuelles de précision (4 et 6 questions).
Les 16 demandes qui reçoivent encore du contexte sans fait attendu concernent le
partage retiré (8) et l’effacement (8). Aucun identifiant interdit n’a été injecté.
Les deux campagnes utilisent le repli lexical. Elles ne mesurent pas les réponses
générées ni l’effet du changement en production.

## Langue de la source et versions contradictoires

La question peut être posée en français tout en visant une consigne écrite en
anglais. Dans la reproduction synthétique, deux notices donnent des lieux de
stockage différents pour le même matériel. Avant correction, les deux lieux
entraient dans le contexte, celui de la mauvaise notice en premier.

Quand la demande identifie une source française ou anglaise, la recherche tient
compte du sujet et de la langue du passage. Un titre qui désigne précisément le
sujet peut servir d’appui à une valeur donnée dans le corps du texte. Deux
documents ayant le même contenu indexé conservent leurs titres et leurs droits
respectifs. Le test bilingue vérifie le passage cité et repose la question après
révocation du partage. Les contrôles hybrides couvrent aussi une traduction du
sujet sans mot commun et un voisin vectoriel rédigé dans l’autre langue.

Azure AI Search documente le ciblage d’un champ linguistique lors d’une recherche
multilingue. Galaris conserve ici son index existant et qualifie l’extrait envoyé
à l’agent. Pour les passages courts, la langue déclarée du souvenir peut
compléter les indices présents dans le texte. La reconnaissance est limitée aux
sources explicitement demandées en français ou en anglais. [Recherche multilingue dans Azure AI Search](https://learn.microsoft.com/fr-fr/azure/search/search-language-support)

Les deux campagnes comparent les mêmes questions et les mêmes droits avant et
après correction. Chacune comporte 528 questions en français et en anglais, 33
familles et 1 928 éléments à titres natifs. Le second corpus change les profils
(qualité, conseil, déménagement et jardin partagé), les contenus et la graine.
Les modèles de questions restent communs.

| Corpus | Précision globale | Rappel global des faits | Questions avec tous les faits et une précision de 100 %, sur 464 ayant une réponse |
|---|---:|---:|---:|
| Corpus précédent | 34,19 % → 36,42 % | 81,18 % → 81,61 % | 70 → 82 |
| Nouveau contrôle | 33,93 % → 36,39 % | 79,89 % → 79,89 % | 74 → 90 |

Sur les 32 questions qui désignent la langue de la source, la bonne version passe
de 0 à 32 premières places. La version qui donne la valeur contradictoire apparaît
dans 30 contextes avant correction et dans aucun après. La précision de cette
famille passe de 13,96 % à 87,50 % sur le premier corpus et de 18,75 % à 100 % sur
le second. Quatre contextes contiennent encore une note dans la bonne langue
qui emploie un mot du sujet avec un autre sens. Aucune question ne perd en
précision ou en rappel et aucun identifiant interdit n’est transmis.

Sur chaque corpus, 16 des 64 questions sans fait attendu reçoivent encore du
contexte. Les campagnes mesurent le repli lexical. Le fournisseur d’embeddings
de développement a renvoyé une erreur lors du contrôle synthétique. Les tests
hybrides utilisent des vecteurs contrôlés. L’exactitude des réponses générées et
le gain en production restent à mesurer.

## Attribution du lieu à l’objet demandé

Une consigne de classement et une règle d’autorisation peuvent parler des mêmes
confirmations. La version précédente renvoyait les deux notes pour quatre questions.
Le parcours conversationnel recherche désormais une phrase qui associe un emplacement
à l’objet demandé, y compris lorsque la question précise la langue du document. Le
classement tient compte de cette preuve avant de remplir le budget de résultats.
Quand aucune attribution explicite n’est reconnue, le rappel conserve ses candidats
ordinaires ou ceux dans la langue demandée. Cette règle couvre des formulations
délimitées en français et en anglais.

Le benchmark ciblé utilise neuf formulations et trois inventaires fictifs. Il lit
le contexte rendu, y compris les titres dérivés du texte des souvenirs. Pour réussir
une question, il faut retrouver la bonne source et citer le lieu attendu. Le contrôle
de précision exige aussi que le lieu d’un autre objet, présent dans cette même source,
soit absent du contexte et qu’aucune source superflue ne soit citée. Cette distinction
entre présence du fait et bruit au sein d’un passage pertinent s’inspire de la méthode
d’évaluation par assertion de [RAGChecker](https://proceedings.neurips.cc/paper_files/paper/2024/file/27245589131d17368cccdfa990cbf16e-Paper-Datasets_and_Benchmarks_Track.pdf).

| Contexte effectivement transmis | Version précédente | Version avec attribution |
|---|---:|---:|
| Bon lieu cité, benchmark ciblé | 6/9 | 9/9 |
| Bon lieu cité sans lieu ni source parasite, benchmark ciblé | 0/9 | 9/9 |
| Questions de langue avec tous les faits et aucun résultat superflu, deux corpus | 28/32 | 32/32 |
| Précision globale, corpus de référence | 36,42 % | 36,79 % |
| Précision globale, corpus de contrôle | 36,39 % | 36,39 % |

Les deux campagnes générales reprennent chacune 528 requêtes et 1 928 éléments.
Le rappel global reste à 81,61 % et 79,89 % respectivement. Les quatre corrections
sont des reformulations d’un même cas de bénévolat. Le benchmark ciblé élargit
les formulations et les objets, mais reste construit. Ces campagnes portent sur
le repli lexical sur PostgreSQL. Le fournisseur d’embeddings configuré en
développement a renvoyé une erreur lors d’un nouvel essai sur trois phrases
synthétiques. Les résultats concernent le contexte envoyé à l’agent et laissent
ouverte la qualité des réponses générées en production.
