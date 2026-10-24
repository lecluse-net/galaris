# Campagne d'optimisation globale

Campagne lancée le 24 octobre 2026 conformément au
[plan d'optimisation](../../plans/optimisation-generalisee.md). Les corrections doivent
conserver les résultats métier, droits, révisions, reprises, annulations et effets durables.
L'inventaire et les premiers contrôles de référence sont établis. Quinze lots indépendants
sont intégrés au worktree : onze optimisations ciblées des catalogues Tools, du retrait
des références de fichiers, des résumés Process, des recherches Contact, des métriques
Topics, des pointeurs natifs Document et du démarrage frontend ; quatre corrections de stabilisation préservent
l'ouverture des pièces jointes Memory, la langue initiale, les liens directs Activité
et la génération du contrat frontend des paramètres.
La revue exhaustive reste ouverte ; aucun gain global
sur l'ensemble de la plateforme n'est établi.

## Référence et périmètre

La référence de lancement est `5e26ce7771cc176dc5224d4dd4f2d62be04317bf`, avec
des changements locaux préexistants conservés. Chaque fichier inventorié possède une
empreinte SHA-256 ; toute modification ultérieure exige une requalification des preuves
qui en dépendent. La cartographie au lancement compte 78 modules backend et 40 frontend,
contre 77 et 39 lors de la préparation du plan.

L'instantané d'inventaire réconcilié à cette reprise comprend 5 647 fichiers
(68 848 372 octets) et 478 surfaces de modules : 1 941 sources actives,
69 conditionnelles, 1 137 fichiers de test/outillage, 648 d'infrastructure,
1 837 documentaires et 15 générés. Dix-huit opérations qualifiées et une référence au repos
complètent les surfaces conventionnelles dans le registre. Les modèles publics
`.env.example` sont inclus, contrairement aux configurations privées. La classification est un premier
tri automatique à confirmer par la revue contextualisée. Les secrets, données locales,
artifacts et dépendances installées sont exclus ; aucun lien symbolique n'est suivi.

## Registres et preuves

- [Fichiers](couverture-fichiers.csv) : empreintes, unités et état de revue.
- [Surfaces](couverture-surfaces.csv) : activation, consommateurs et preuves manquantes.
- [Parcours](parcours.csv) : scénarios synthétiques et qualification dynamique.
- [Pistes](pistes.csv) : hypothèses, mesures, décisions et garanties.
- [Lots](lots.csv) : corrections acceptées et preuves avant/après.

Les diagnostics locaux sont conservés sous
`artifacts/optimisation-generalisee/2026-10-24-lancement/` : état Git initial,
diff de sauvegarde, archive des sources autorisées, inventaire, signaux statiques non confirmés et sorties complètes des
contrôles. Les rapports versionnés ne conservent que les agrégats et conclusions techniques.

## Progression et limites

La reprise a ajusté le séquencement du plan : les lots indépendants ayant leurs
consommateurs et preuves peuvent être livrés pendant que la revue des autres familles
continue. Les mesures du lancement ci-dessous restent des références historiques ;
les résultats des corrections réelles sont détaillés dans la section suivante.

Les fichiers recensés ne sont pas tous examinés. Les signaux AST de lectures attendues
dans des boucles sont des pistes non confirmées, conservées dans le diagnostic local.
La revue classe séparément les
fichiers examinés complètement et ceux dont seule une surface a été étudiée.
Le relevé distingue lectures complètes, revues partielles et opérations qualifiées : ces états
ne constituent pas une revue exhaustive des 118 modules.
Les six registres de campagne sont des sorties générées/synthétisées suivies séparément
de ce dénominateur ; leurs empreintes ne sont pas incluses dans leur propre manifeste.

| Contrôle de référence | Résultat | Portée |
|---|---|---|
| Listes Process/Dataset/Document, lecture File Share, arbre Task, traces et stream LLM | 24 tests réussis | PostgreSQL éphémère ; Dataset de 30 éléments lu en 2 requêtes, pause/reprise d'un arbre de 42 Tasks en 3 requêtes chacune. |
| Recherche Memory, lecture/ordre Document, onboarding, rétention LLM et cycle de vie Storage | 26 tests réussis | Corpus synthétiques, droits, croissance et rollback. |
| Chat et première mission assemblés | 17 tests réussis | Chromium, transport HTTP/WebSocket réel et modèle scripté : streaming, outil, Task durable, erreur fournisseur, pause/reprise/arrêt, reconnexion et réouverture ; vérifications mobiles présentes dans les scénarios. |
| Documentation préparée | Réussi | Cartes générées et contrats documentaires. |
| Typage et unités frontend | Réussi | Pyright strict, vue-tsc, 439 tests frontend et parité des catalogues. |

Le build de production utilisé par ces E2E mesure 484 976 octets gzip d'imports statiques
initiaux en anglais, et 620 186 avec le catalogue français. Tous les chunks JS/CSS
représentent 4 232 539 octets gzip ; le précache annonce 614 entrées et 14 817,98 Kio.
Ces périmètres sont distincts : fontes, API, médias et temps de rendu ne sont pas inclus
dans le graphe initial. Aucun gain de chargement n'est déduit de cette seule référence.

## Première expérience Process

Une liste de résumés relit chaque run, sa définition et son agent. Un prototype local
regroupe ces lectures tout en conservant un rafraîchissement des runs sélectionnés.
Les réponses JSON complètes sont comparées à chaque passage. Un échauffement est exclu,
puis six paires sont exécutées en alternant l'ordre référence/candidat.

| Runs synthétiques | Lectures référence | Lectures prototype | Médiane référence | Médiane prototype |
|---|---:|---:|---:|---:|
| 10 | 32 | 5 | 11,371 ms | 2,619 ms |
| 50 | 152 | 5 | 47,400 ms | 4,532 ms |
| 500 | 1 502 | 5 | 455,872 ms | 25,830 ms |

Le premier prototype échouait sur une suppression logique tardive : sa relecture
excluait le run sélectionné, contrairement au rafraîchissement unitaire. Ce contre-cas
a échoué avant la correction locale, puis réussi en conservant les lignes historisées
dans cette relecture interne. Les six sondes finales réussissent : trois volumes,
définition historisée, résultat terminal tardif et suppression logique tardive.

Ces résultats qualifient une expérience de service, pas une correction livrée. Les
sources applicatives suivies n'ont pas changé pendant les premiers contrôles. Les
coûts mémoire/gros JSON, les sessions concurrentes indépendantes, les droits sur tous
les consommateurs HTTP/MCP et le parcours assemblé Process restent à qualifier. Les
autres activités locales concurrentes peuvent influencer les durées ; les nombres de
lectures et l'égalité des résultats constituent les preuves structurelles principales.

Après ces contrôles, des changements indépendants sont apparus dans les composants Chat,
un nouveau CSS de conversation et un test Goal. Ils sont conservés et repris dans le
manifeste courant. Les E2E et tailles de build ci-dessus portent sur leur référence de
lancement, pas sur la version ultérieure de ces écrans. Les preuves SQL Process/Tools/
Storage ne sont pas affectées par ces fichiers ; toute modification de leurs propres
sources impose une nouvelle comparaison.

## Expériences Tools et Storage

Deux autres frontières ont été comparées sans changer leur implémentation applicative,
avec un échauffement puis six paires alternées. Les quatre sondes réussissent.

| Scénario synthétique | Lectures référence | Lectures prototype | Médiane référence | Médiane prototype |
|---|---:|---:|---:|---:|
| Catalogue de 10 Tools | 11 | 2 | 3,210 ms | 1,421 ms |
| Catalogue de 50 Tools | 51 | 2 | 13,593 ms | 2,378 ms |
| Retrait des références de 10 fichiers | 22 | 4 | 8,828 ms | 3,207 ms |
| Retrait des références de 100 fichiers | 202 | 4 | 88,945 ms | 16,147 ms |

Le prototype Tools conserve une relecture groupée fraîche et la projection publique,
avec comparaison des pages partielles, recherches vides et recherche Unicode `STRASSE` /
`Straße`. Il ne déplace pas la recherche vers SQL et ne crée aucun cache de droits.
Les modifications concurrentes et consommateurs administratifs restent à exercer.

Le prototype Storage conserve le verrou d'identité de volume, les tombstones et
`soft_delete`. Un fichier partagé reste vivant, aucun octet n'est supprimé pendant le
retrait, et le rollback restaure toutes les références et tous les fichiers à chaque
passage. Les sessions d'enregistrement concurrentes, le commit réel et la reprise du
purgeur avec le prototype restent à qualifier avant intégration.

L'audit SQL du 17 octobre doit être requalifié : la résolution Console recherche déjà le
Tool puis sa connexion. Les lectures Process par élément ont été qualifiées puis corrigées
dans le lot L03 ci-dessous. Les sous-requêtes corrélées d'attribution Topic restent
présentes dans les sources inspectées ; leur gain actuel et les cas de droits/historique
restent à vérifier.

Les essais utilisent exclusivement des fixtures synthétiques et des transports externes
simulés. Aucune enveloppe d'appels payants n'est définie : les qualifications fournisseurs
réels restent ouvertes. La campagne ne modifie pas l'installation en production et ne
lance pas `make validate`, réservé à l'utilisateur.

## Corrections intégrées et qualification

Les preuves locales de reprise sont dans
`artifacts/optimisation-generalisee/2026-10-24-qualification/`. Les comparaisons chargent
la source initiale sauvegardée et la réalisation courante dans le même test ; un
échauffement précède six paires alternées. Les allocations sont mesurées séparément
des temps, sur des sessions dont l'identity map est vidée. Elles ne représentent pas le RSS.

| Cas synthétique | Lectures avant → après | Médiane avant → après | Pic Python avant → après |
|---|---:|---:|---:|
| 50 Tools, schéma simple | 51 → 2 | 14,550 → 2,808 ms | 526 503 → 575 262 octets |
| 500 Tools, schéma simple | 501 → 2 | 143,393 → 18,445 ms | 2 604 862 → 3 358 900 octets |
| 500 Tools, 20 paramètres descriptifs | 501 → 2 | 211,556 → 68,804 ms | 12 544 850 → 19 237 926 octets |
| Retrait de 10 fichiers | 22 → 4 | 10,133 → 3,955 ms | 309 424 → 341 130 octets |
| Retrait de 100 fichiers | 202 → 4 | 101,388 → 19,343 ms | 407 301 → 702 905 octets |
| Retrait de 1 001 fichiers | 2 004 → 6 | 1 015,752 → 181,768 ms | 707 690 → 2 785 940 octets |

Le lot **L01 / SQL05** remplace les relectures par Tool dans
`app.connection.agent_admin_service.list_tools` par une relecture groupée existante.
Il garde la recherche Python Unicode, le total, l'ordre, les droits de délégation,
le masquage et la fraîcheur des configurations. Les DTO internes sont libérés avant la
construction de la réponse publique. Le compromis mémoire est explicite : au maximum
de page testé avec des descriptions longues, le gain de temps s'accompagne d'environ
6,7 Mo d'allocations Python supplémentaires. Le catalogue complet reste chargé avant
pagination ; sa projection metadata et son coût sous concurrence restent à étudier.

Le lot **L02 / SQL04** sélectionne les fichiers devenus orphelins par `NOT EXISTS` dans
des lots bornés. Il conserve le verrou transactionnel, les fichiers encore partagés,
l'ordre des identités, les tombstones et le purgeur existant. Les lots évitent une
croissance sans borne des paramètres SQL et de l'état ORM chargé. Les octets restent
intacts avant le commit ; les tests réels de deux sessions montrent qu'un enregistrement
concurrent attend, réussit après rollback et refuse la résurrection après commit.

Les nouveaux budgets SQL échouaient avant les corrections (11/51/501 lectures Tools,
22/202 pour le retrait) puis réussissent après. Les 53 tests ciblés AgentAdmin/Tools/
fonctions/portées passent. La qualification Storage et de ses consommateurs a détecté
un test HTTP périmé : il utilisait `/api/memory/documents`, retiré lors de la séparation
Document/Memory, et échouait avant d'atteindre la suppression. Le même échec a été
reproduit avec l'ancien stockage. Le scénario utilise maintenant les routes, privilèges
et profil éditorial Document actuels, sans retirer ses assertions de droits ou d'effets.
Les 10 contrôles complémentaires de ce consommateur et des frontières Document/Process
passent. Ce parcours manquait à la sélection initiale ; il fait désormais partie de la
qualification du lot, au lieu de déduire la couverture HTTP des seules sondes de service.

Les cinq parcours Chromium AgentAdmin et Files passent avec l'application assemblée :
appel du catalogue et révocation réelle, suppression/refus de suppression d'un fichier,
navigation et réouverture sur ordinateur/mobile. Pyright, vue-tsc, les 439 unités
frontend et les contrôles de traduction passent. Les 16 contrôles finaux communs aux
deux lots, la préparation documentaire et les 33 tests du contrôle d'architecture
passent aussi. La relecture du diff conserve les garanties et les changements
indépendants du worktree. La validation globale demeure réservée à l'utilisateur.

### Résumés Process — L03 / SQL01

Le lot conserve les sélections et les contrôles de droits HTTP/MCP, puis projette les
champs publics des runs sélectionnés en une lecture groupée par lot de 500. Les pages
liées à un périmètre de Tasks/runs ne chargent plus les gros JSON d'exécution internes.
Les détails et réponses de mutation gardent leur rafraîchissement unitaire existant.
Les définitions archivées restent lisibles ; une suppression logique tardive conserve
la réponse de la lecture détaillée et une suppression physique reste une erreur explicite.
Aucun cache de droits ou de résultats n'est ajouté.

La comparaison charge la source sauvegardée au début de ce lot et le correctif réel
dans la même base synthétique : un échauffement, six paires alternées avec identity map
vidée avant chaque appel, égalité des réponses JSON complètes. Les allocations Python
sont mesurées séparément sur quatre passages ; elles ne représentent pas le RSS.

| Résumés synthétiques | Lectures avant → après | Médiane avant → après | Pic Python avant → après |
|---|---:|---:|---:|
| 10, historique court | 32 → 3 | 10,094 → 1,934 ms | 392 028 → 295 300 octets |
| 50, historique court | 152 → 3 | 43,205 → 3,247 ms | 765 368 → 403 976 octets |
| 500, historique court | 1 502 → 3 | 457,349 → 18,694 ms | 4 947 053 → 2 605 132 octets |
| 500, historique interne volumineux | 1 502 → 3 | 520,960 → 18,482 ms | 25 918 329 → 2 597 040 octets |

Les budgets de 10/50/500 résumés échouaient avant le correctif et passent après.
Les 121 tests ciblés Process et les 34 contrôles complémentaires HTTP/MCP/conversation
passent : JSON métier complet, ordre, pagination, droits et révocation, états terminaux,
changement tardif et résultat relu après commit d'une session indépendante. Pyright,
vue-tsc, les 439 unités frontend et la parité i18n passent aussi.

Le premier parcours Chromium a vérifié les résumés puis échoué sur une fixture externe
qui supposait l'existence du Tool n8n. La trace montre que la base isolée n'exposait que
le moteur natif dans ce catalogue. Le test crée désormais son Tool externe via l'API
administrative réelle, en conservant toutes ses assertions. Le parcours Chromium
complet passe : résumés, réouverture, édition native et externe sur ordinateur/mobile.
Les 33 contrôles d'architecture et la préparation documentaire passent aussi.

La sélection ORM initiale des listes générales HTTP/MCP charge encore leurs colonnes
internes, et les contrôles de droits MCP restent par élément : le budget de trois
lectures qualifie les pages de résumés par périmètre, pas tout appel MCP. La charge
concurrente généralisée, le RSS et les fournisseurs réels restent ouverts. Les preuves
complètes de ce lot sont locales sous `artifacts/optimisation-generalisee/2026-10-24-process/`.

### Recherche Contact sans route — L04 / SQL06

La recherche canonique est désormais évitée quand la recherche Messenger n'a trouvé
aucune route. Les autres branches gardent le regroupement multicanal, les noms, l'ordre,
le filtrage des bots et les routes exactes. La recherche Messenger est toujours exécutée
à chaque appel ; aucun résultat vide n'est conservé en cache. Les contacts persistés ne
sont ni modifiés ni supprimés.

La référence sauvegardée et les deux lignes du correctif sont comparées sur les mêmes
données synthétiques : un échauffement, six paires alternées avec identity map vidée,
égalité des réponses, puis quatre mesures d'allocations séparées.

| Contacts canoniques sans route joignable | Lectures avant → après | Médiane avant → après | Pic Python avant → après |
|---|---:|---:|---:|
| 0 | 3 → 1 | 1,412 → 0,435 ms | 291 095 → 279 873 octets |
| 501 | 13 → 1 | 35,363 → 0,544 ms | 3 640 397 → 279 873 octets |

Les deux budgets SQL échouent avant le correctif puis passent. Les 49 tests ciblés
Contact, Memory, Messenger et consommateurs Process/Goal passent. Le scénario DB
conserve les 501 contacts puis active réellement le Chat et retrouve son humain à
l'appel suivant. Le parcours Chromium crée une activité humaine dans un processus,
attend sa réponse et reprend après une seule soumission. Pyright, vue-tsc, les 439 unités
frontend, la parité i18n et la préparation documentaire passent. Les preuves locales
sont sous `artifacts/optimisation-generalisee/2026-10-24-contact/`.

Ce gain concerne la branche sans route ; les recherches non vides continuent à charger
l'index canonique complet. Les transports externes, leur latence réseau, la charge
généralisée et le RSS ne sont pas qualifiés par cette mesure.

### Attribution des métriques Topics — L05 / SQL02

Les métriques mensuelles et les mois disponibles utilisent désormais une construction
de jointures commune, au lieu des sous-requêtes corrélées répétées. Les priorités du
sujet restent Task directe, Task du Process, conversation du Process puis conversation
directe. Le filtre d'agent garde son ordre indépendant : agent enregistré sur l'appel,
Task directe, connexion de la conversation directe puis lanceur du Process.
La jointure de provenance conversationnelle part de l'identité du run enregistrée sur
l'appel : archiver le run ne retire pas ce lien. L'unicité du lien empêche de multiplier
les coûts. Les jointures de connexion ne sont ajoutées que pour un périmètre d'agents.
Aucun cache, index, schéma, droit ou contrat HTTP/MCP n'est modifié.

Les comparaisons chargent la source sauvegardée et le service réellement intégré sur
les mêmes données synthétiques. Elles excluent un échauffement puis alternent six paires,
avec identity map vidée. L'égalité porte sur la réponse JSON complète. Les statistiques
PostgreSQL sont actualisées dans la base isolée ; JIT reste activé. Les blocs sont les
accès partagés déjà en cache du dernier `EXPLAIN ANALYZE`, additionnés pour les deux
requêtes LLM. Ils ne désignent pas des blocs distincts ni un volume transféré.

| Appels | Tasks sans rapport | Périmètre | Médiane service avant → après | Accès aux blocs avant → après |
|---|---:|---|---:|---:|
| 6 | 0 | global | 10,923 → 11,708 ms | 45 → 17 |
| 6 | 0 | un agent | 11,806 → 12,847 ms | 51 → 21 |
| 1 200 | 1 000 | global | 16,371 → 14,113 ms | 7 305 → 83 |
| 1 200 | 1 000 | un agent | 17,099 → 15,749 ms | 9 105 → 87 |
| 12 000 | 10 000 | global | 87,728 → 25,575 ms | 73 079 → 671 |
| 12 000 | 10 000 | un agent | 64,474 → 28,682 ms | 91 079 → 675 |
| 6 | 10 000 | global | 11,173 → 11,502 ms | 679 → 347 |
| 6 | 10 000 | un agent | 13,235 → 13,368 ms | 688 → 351 |

Les deux requêtes LLM par page sont conservées ; le gain porte sur leur travail interne.
Les allocations Python sont mesurées séparément sur quatre passages : à 12 000 appels,
le pic médian global passe de 1 174 141 à 1 188 414 octets et celui par agent de
1 220 402 à 1 204 270 octets. Ces mesures ne représentent ni le RSS ni la mémoire serveur.
Le compromis est explicite : avec six appels, le service coûte environ une milliseconde
de plus. La première construction expérimentale ajoutait davantage de coût Python ;
la version retenue évite sa sous-requête de projection et les jointures d'agent inutiles.

Les douze scénarios de priorité, scope et cycle de vie passent avant et après. Ils couvrent
les sujets absents d'une Task, les Tasks/runs/rooms/Topics archivés, les rounds supprimés,
les connexions désactivées et les mois disponibles. Les deux budgets PostgreSQL à
1 201 appels échouaient avant (7 308 et 9 208 blocs) puis passent. Les contrôles élargis
Topics et sélecteurs ont réussi pour 77 scénarios ; le dernier était bloqué avant la
requête par une fixture créant encore un Document dans Memory. Le même échec a été
reproduit avec la source initiale. Le scénario utilise maintenant le contrat Document
HTML et son affectation publique au sujet, en conservant les assertions de participants,
équipes, documents et scopes. Les 16 contrôles finaux incluant ce scénario passent.

Le parcours Chromium conserve l'affectation Document/Dataset, puis vérifie les coûts et
appels de juillet/août, leurs infobulles et la relecture après rechargement. Pyright,
vue-tsc, les 439 unités frontend et la parité i18n passent. Les preuves locales complètes
sont sous `artifacts/optimisation-generalisee/2026-10-24-topic/`.

La recherche des variantes du constructeur périmé a trouvé une autre fixture E2E réelle,
un alias Document valide et un test de rejet intentionnel. La fixture réelle utilise
maintenant Document ; son aperçu 3D et sa réouverture passent dans Chromium. Un garde
AST central échoue sur cette fixture avant correction puis passe, en distinguant les
imports Memory, les alias Document et les rejets explicites. Les 21 contrôles des
frontières et associations de ressources passent aussi. Ces fixtures étaient hors du
typage strict et les parcours correspondants n'avaient pas été sélectionnés auparavant ;
la préparation seule de la base ne pouvait pas détecter leur contrat de création périmé.
Le garde est limité aux appels littéraux directement importés : il ne remplace pas les
tests de persistance et de droits.

L'agrégation mensuelle précède toujours la pagination et le choix des mois parcourt
l'historique pertinent. La charge généralisée, les distributions très différentes,
le RSS et les fournisseurs réels restent ouverts. Aucun gain global de plateforme n'est
déduit de ces mesures de service.

### Pagination des métriques Topics — SQL07, prototypes écartés

Deux prototypes locaux limitent l'agrégation mensuelle aux identités de la page via une
CTE, d'abord par filtre puis par jointure. Ils conservent une seule requête pour sélectionner
la page et ses métriques ; le calcul des mois disponibles reste complet. Chaque prototype
réussit huit sondes : réponses JSON complètes, provenances riches et historique, scopes,
recherches sélectives/vides et pages de 10, 50 et 500 éléments. Les temps portent sur un
échauffement exclu puis six paires alternées, jusqu'à 2 000 sujets et 40 000 appels.

Le gain ne justifie pas leur intégration. Avec la variante de jointure, une page globale
de 50 sujets passe de 44,192 à 41,685 ms, mais une page de 500 passe de 62,237 à
64,698 ms. Pour cette dernière en scope d'agent, des passages du candidat dépassent
700 ms et atteignent 1 014 ms, contre moins de 72 ms pour la référence. La cause de ces
pointes n'est pas qualifiée ; les derniers plans `EXPLAIN` seuls ne les expliquent pas.
Le choix des mois conserve une part importante du coût global. Aucun de ces prototypes
n'est copié dans l'application ; la source du lot L05 reste inchangée.
Les preuves locales sont dans `artifacts/optimisation-generalisee/2026-10-24-topic-pages/`.

### Contacts joignables ciblés — L06 / SQL08

L'annuaire des destinataires ne charge désormais que les contacts canoniques correspondant
aux identités joignables. Les filtres Memory optionnels sélectionnent l'union des adresses
exactes et des utilisateurs Galaris, dans le périmètre du propriétaire. Sans filtre, la liste
administrative conserve son contrat. Une collection explicitement vide ne charge rien.
Les identités sont interrogées par groupes bornés ; toutes les identités du contact retenu
restent chargées afin de conserver son nom canonique, ses alias et son regroupement.
Les bots sont écartés avant cette résolution ; la recherche Messenger reste exécutée à
chaque appel. Aucun cache applicatif, schéma, index ou droit n'est ajouté ou modifié.

La référence charge les deux sources sauvegardées Contact et Memory ; elle est comparée
au correctif réel sur les mêmes annuaires synthétiques, avec une seule personne joignable.
Un échauffement est exclu puis six paires alternées comparent les réponses complètes.
L'identity map est vidée avant chaque appel ; les allocations sont mesurées séparément
sur quatre passages. Les contacts sans rapport contiennent des métadonnées privées
entièrement synthétiques ; une identité identique chez un autre propriétaire vérifie l'isolation.

| Contacts sans rapport | Lectures totales avant → après | Dont lectures canoniques | Médiane avant → après | Pic Python avant → après |
|---|---:|---:|---:|---:|
| 0 | 17 → 17 | 5 → 5 | 8,824 → 10,095 ms | 342 255 → 357 961 octets |
| 501 | 23 → 17 | 10 → 5 | 46,314 → 10,422 ms | 7 826 286 → 358 080 octets |
| 2 001 | 41 → 17 | 25 → 5 | 231,699 → 12,155 ms | 9 284 086 → 358 177 octets |

Le compromis minimal est d'environ 1,3 ms et 16 Ko supplémentaires avec un seul contact
canonique. Les pics Python ne mesurent pas le RSS. Le filtrage SQL peut encore parcourir
les métadonnées parentes selon le plan choisi ; la charge réseau des bridges et les très
grands nombres de destinataires ne sont pas qualifiés par ces mesures.

Le premier filtre testé avait déjà réduit les SELECT, mais produisait un mauvais plan :
les identités du propriétaire étaient relues 2 002 fois dans chacune des deux requêtes
principales. À 2 001 contacts, il atteignait environ 717 ms malgré ses 17 lectures et son
petit pic mémoire. La sélection distincte des identités supprime ces relectures du grand
ensemble : le dernier plan passe de 84 232 à 229 blocs en cache pour chacune de ces
requêtes. Le test de régression couvre maintenant le travail PostgreSQL, pas seulement
le nombre de SELECT : il échoue sur la variante sauvegardée à 168 471 blocs puis passe
sur la version retenue. Cette expérience confirme pourquoi un budget de requêtes seul
ne qualifie pas une optimisation ; le contrôle de plans fait désormais partie du scénario.

Les 55 tests ciblés passent : réouverture après renommage, noms canoniques, champs conservés,
routes et propriétaire, filtres exacts et union sans doublon, appels sans résultat et
administration sans filtre. Les cas unitaires de 501/1 001 routes conservent chaque
destinataire après découpage. Le parcours Chromium fait sélectionner un humain, attend sa
réponse et reprend le processus avec le filtre final. Pyright, vue-tsc, les 439 unités
frontend et la parité i18n passent. Les preuves sont dans
`artifacts/optimisation-generalisee/2026-10-24-contact-index/`.
La branche vide du lot L04 est requalifiée dans ces tests ; ses mesures initiales restent
des références historiques. Les sources et changements indépendants du worktree sont conservés,
y compris une suppression Git de source, distinguée d'une erreur de lecture dans l'inventaire.

### Configurations Tools hors page — L07 / SQL09

Le catalogue délégué charge d'abord uniquement les identifiants, codes et libellés.
La recherche Python `casefold`, l'ordre du catalogue et la pagination restent identiques.
La page conserve sa relecture complète groupée et fraîche, sa validation et le masquage
des secrets. Les appels sans projection gardent leur configuration complète : seul
AgentAdmin demande explicitement cette première passe légère. Aucun cache, droit ou
schéma de stockage n'est modifié. Les autres consommateurs recensés sont le chargement
MCP, Messenger, la liste HTTP Tools et `get_all_tools`.

Le budget de régression utilise dix Tools affichés et 0 ou 500 configurations volumineuses
hors page. Avant correction, ce dernier cas atteint 69,5 Mo Python et dépasse le budget
de 6 Mo ; après correction les deux cas passent. La même session peut ensuite relire
la configuration complète des Tools sélectionnés et non sélectionnés.

Les deux sources de référence sauvegardées après L01 sont comparées au correctif réel
sur les mêmes catalogues synthétiques. Chaque appel vide l'identity map ; un échauffement
est exclu puis six paires alternent les versions. Les réponses JSON complètes sont égales,
y compris la recherche Unicode, une page décalée, une recherche vide et une page hors
catalogue. Les allocations sont mesurées séparément sur quatre passages. Le ramasse-miettes
reste actif ; une seconde série mesure aussi ses pauses, sans les retirer des temps.

| Tools / taille de page | SELECT avant → après | Médiane avant → après | Étendue avant → après | Pic Python avant → après |
|---|---:|---:|---:|---:|
| 10 / 10 | 2 → 2 | 3,927 → 4,977 ms | 2,851–7,809 → 1,954–9,921 ms | 1,036 → 0,796 Mo |
| 510 / 10 | 2 → 2 | 21,395 → 8,293 ms | 21,068–25,317 → 7,079–9,307 ms | 19,178 → 1,681 Mo |
| 2 010 / 10 | 2 → 2 | 79,153 → 25,267 ms | 78,534–79,910 → 23,962–323,286 ms | 73,321 → 4,534 Mo |
| 2 010 / 500 | 2 → 2 | 301,651 → 83,037 ms | 133,017–469,381 → 80,813–401,452 ms | 90,882 → 29,587 Mo |

Ces médianes incluent les pauses observées. Dans le cas 2 010/10, la pointe du candidat
à 323,286 ms contient 298,632 ms de collecte Python. À 2 010/500, plusieurs appels de
référence comprennent 331 à 340 ms de collecte, et un appel candidat 331 ms. Le gain de
mémoire est établi ; ces six passages ne qualifient pas les percentiles de latence d'un
service durable. Le petit catalogue ne présente pas de gain temporel répétable : la
première série donnait 2,316 → 1,854 ms, la seconde environ 1,05 ms de plus. Les pics
Python ne sont pas le RSS. Les métadonnées de tout le catalogue restent chargées et les
configurations de la page restent intégralement lues et validées.

Les 80 contrôles applicatifs catalogue/AgentAdmin/secrets/ToolAdmin réussissent, puis
les 14 contrôles finaux catalogue/Messenger, les quatre comparaisons et le parcours
Chromium de création, consultation et refus après révocation. La première invocation
du diagnostic hors du backend ne chargeait pas sa fixture DB ; elle a été relancée
avec les fixtures isolées explicites. Le typage des deux sources modifiées passe.
Le premier contrôle global était bloqué par deux erreurs dans un changement RBAC
indépendant. Ce fichier a été corrigé dans le worktree pendant les vérifications ;
le nouveau `make typecheck` réussit : Pyright, vue-tsc, 439 unités frontend et parité
i18n. Ce lot ne constitue pas une validation complète du système.
Les preuves locales sont dans `artifacts/optimisation-generalisee/2026-10-24-tool-projection/`.
Les mesures et empreintes de L01 restent historiques ; ses garanties concernées sont
requalifiées par ce lot.

### Métadonnées ToolAdmin — L08 / SQL10

La liste administrative MCP ne charge désormais que les colonnes correspondant à ses
métadonnées publiques. La requête de comptage, les filtres de type et de capacité,
l'ordre, les limites et les contrôles d'accès sont conservés. La page ne lit ni ne
valide les configurations d'exécution ; celles-ci restent dans le détail, relu par son
contrat habituel. Le parcours vérifie cette ouverture dans la même session après la liste,
avec sa description complète, sa configuration et le masquage des secrets.

Le budget automatisé couvre 10 et 500 Tools contenant des descriptions privées
volumineuses. À 500, la référence atteint 69,8 Mo Python et dépasse le budget de 6 Mo ;
les deux cas corrigés passent. Les comparaisons de la source sauvegardée et du correctif
réel utilisent un échauffement exclu, six paires alternées et une identity map vidée
avant chaque appel ; les quatre mesures d'allocations sont séparées. Le GC reste actif
et ses pauses sont enregistrées. Les réponses JSON complètes sont égales pour les pages,
les décalages et les filtres exercés.

| Tools / taille de page | SELECT avant → après | Médiane avant → après | Pic Python avant → après |
|---|---:|---:|---:|
| 10 / 10 | 2 → 2 | 1,672 → 1,506 ms | 0,417 → 0,295 Mo |
| 500 / 500 | 2 → 2 | 8,366 → 5,205 ms | 10,303 → 1,084 Mo |
| 2 000 / 50 | 2 → 2 | 5,818 → 6,360 ms | 1,560 → 0,297 Mo |
| 2 000 / 500 | 2 → 2 | 15,314 → 12,314 ms | 10,215 → 1,051 Mo |

Le gain principal est la mémoire. Le cas 2 000/50 coûte environ 0,54 ms de plus dans
cette série ; aucune amélioration universelle de latence n'est annoncée. Les pics Python
ne mesurent pas le RSS. La charge concurrente, l'endurance, les autres opérations du
service et les distributions générales restent ouvertes.

Les 78 tests finaux catalogue/ToolAdmin/AgentAdmin/accès passent, ainsi que les quatre
comparaisons et les deux parcours Chromium ToolAdmin sur ordinateur et mobile. Ils
préservent notamment les filtres de capacité, les secrets, la réouverture et les refus
après révocation. Pyright, vue-tsc, les 439 unités frontend et la parité i18n passent
avec cette dernière source applicative. Les preuves locales sont dans
`artifacts/optimisation-generalisee/2026-10-24-tool-admin-list/`.

Les deux lots ont aussi passé les 33 contrôles d'architecture. La préparation documentaire
FR/EN vérifie les cartes générées et le corpus actif ; les journaux restent avec leurs preuves.

### Démarrage frontend — L09 / WEB01

Le graphe des imports du build montre que les consommateurs de bootstrap importaient
le catalogue complet de `core.util`, avec ses lecteurs et composants différés. La façade
publique existante expose désormais les primitives dont ils ont besoin : les 17
consommateurs changent leur chemin d'import, sans dupliquer de composant, symbole
d'injection, cache ou fonction. Le chargement de la palette reste effectué au démarrage.
Les références métier, menus, avatars, aide contextuelle, Memory, aperçu Agent et partage
sont les consommateurs inventoriés ; le point d'entrée complet reste disponible.

La comparaison utilise deux builds issus des mêmes sources gelées et du même verrou de
dépendances. Seuls les exports de façade et les imports des consommateurs diffèrent.
Les options expérimentales de Vite/i18n restent dans les diagnostics ; aucune n'est
portée dans la configuration applicative.

| Taille statique, octets gzip par fichier | Avant | Après |
|---|---:|---:|
| Démarrage EN, catalogue sélectionné inclus | 485 196 | 445 008 |
| Démarrage FR, catalogue sélectionné inclus | 620 367 | 580 179 |
| Démarrage ZH, catalogue sélectionné inclus | 613 314 | 573 126 |
| Ensemble des fichiers mesurés du manifeste | 4 233 426 | 4 245 449 |

Le démarrage économise 40 188 octets gzip, soit 8,3 % en anglais ; les catalogues de
langues secondaires sont inchangés. Les fichiers initiaux passent de 56 à 53. L'ensemble
compilé comporte sept chunks supplémentaires et coûte 12 023 octets gzip de plus.
Le précache reste complet : 614 entrées / 14 822,22 Kio deviennent 621 / 14 846,25 Kio.
Le gain initial ne constitue donc pas une réduction du téléchargement complet lors de
l'installation PWA.

Le rapport de build conserve ses mesures avant de refuser un dépassement. Les nouveaux
budgets sont de 460 000 octets gzip en EN et 600 000 en FR/ZH, avec le catalogue
sélectionné et sans polices, trafic API ni précache. La référence réelle échoue au
budget EN ; le build optimisé passe. Le test central provoque aussi un dépassement
indépendant de chaque langue. Le build assemblé avec les autres changements courants
mesure 445 870 / 581 470 / 574 417 octets gzip et passe ces trois budgets ; il est
distinct de la paire gelée utilisée pour attribuer le gain.

Le rendu est comparé dans le même Chromium avec un échauffement exclu, puis six paires
alternées par langue. Chaque passage utilise un contexte neuf, le cache réseau
désactivé, les service workers bloqués, un CPU ralenti quatre fois, 40 ms de latence,
700 000 octets/s et gzip niveau 1. Les API invité sont synthétiques. La mesure s'arrête
au bouton de connexion traduit visible, après les réponses de session et d'inscription.

| Langue | Médiane bouton prêt, avant → après | Ressources transférées, avant → après | Requêtes, avant → après |
|---|---:|---:|---:|
| EN | 1 255,15 → 1 173,50 ms | 553 517 → 508 742 octets | 63 → 60 |
| FR | 1 584,90 → 1 524,75 ms | 713 941 → 669 166 octets | 64 → 61 |
| ZH | 1 613,70 → 1 570,15 ms | 698 560 → 653 785 octets | 64 → 61 |

Ces ressources incluent les polices/images terminées et la route de connexion, mais pas
la réponse HTML de navigation. Le résultat ne mesure ni une authentification réelle,
ni les latences backend, ni les percentiles sous charge. Les captures avant/après du
premier écran sont identiques octet pour octet et ont été inspectées. La mesure gelée
précède la correction indépendante de langue HTML du lot L11.

Les essais de suppression des composants/directives i18n inutilisés ne gagnaient que
964 octets gzip ; deux corrections d'imports internes d'icônes avaient un effet négligeable.
Ils sont écartés. Une première façade incomplète laissait encore des importeurs avides ;
seule la variante sans importeur initial du catalogue complet est intégrée.

### Disponibilité du lecteur Memory — L10 / WEB02

La qualification a révélé un défaut préexistant : un `nextTick` ne garantit pas qu'un
composant importé de manière asynchrone expose déjà sa méthode d'ouverture. Le premier
clic Memory pouvait finir sans ouvrir le média. Les échecs Office et audio ont été
reproduits avec les sources originales dans une copie isolée, sans retirer les changements
du worktree. Le scénario renforcé de première ouverture échoue aussi avec l'ancien
composant ; le scénario distinct de changement de contexte passe déjà sur cette référence.

Une seule ouverture en attente est conservée par composant. Elle attend la disponibilité
effective du lecteur ; une génération invalide les réponses tardives et annule l'attente
lors d'un changement de Memory ou d'un démontage. Une erreur d'import est capturée et
rejoint la notification existante, en libérant le chargement du bouton. URI, contenu,
droits et téléchargement ne changent pas. Un échec de téléchargement ES peut rester
mémorisé par le navigateur : le lot garantit une erreur visible et un nouvel essai qui
libère le bouton, sans promettre une récupération réseau sans rechargement.

Les 65 contrôles de prévisualisation/renommage des pièces jointes passent : Office,
audio/vidéo, lecteur réellement retardé, changement de contexte, fermeture/réouverture,
téléchargement et deux essais avec import interrompu. Le test attend le chargement du
module réel ; il ne remplace pas le lecteur interne. La recherche de variantes identifie
AgentFileBrowser et DocumentEditor comme faux positifs, leurs lecteurs étant statiques.
La couverture initiale ne retardait pas l'import réel et pouvait masquer ce défaut.

### Langue du bootstrap assemblé — L11 / WEB03

Le profil initial a aussi montré un libellé FR/ZH traduit avec une langue HTML anglaise.
Le contrat de la version Quasar installée confirme la cause : sa première installation
applique son pack par défaut après le chargement de la langue applicative. Les tests de
locale existants ne traversaient pas cette installation dans l'application assemblée.

Le bootstrap réapplique maintenant la langue déjà chargée après l'installation Quasar,
avant le montage. Le catalogue présent est réutilisé et le repli anglais est conservé.
Trois E2E de production, avec contextes EN/FR/ZH neufs, vérifient le libellé traduit et
la langue HTML, puis sa conservation pendant la saisie. Ils passent sans erreur de page.
Les mesures de gain du lot L09 portent sur les builds gelés sans ce correctif séparé.

### Liens Activité et disponibilité des droits — L12 / WEB04

Une refonte RBAC indépendante, présente pendant cette qualification, a ajouté des droits
par domaine. Le parcours E2E existant a alors reproduit la perte de `tab=tasks` pendant
le chargement des privilèges, avec sélection de Conversations à la place. La cause est
la normalisation du lien avant la disponibilité des droits.

Les panneaux attendent désormais le chargement des privilèges et le lien demandé reste
intact pendant cette attente. Le détail `task_id` est ouvert quand le droit Task devient
disponible. Les contrôles de domaine existants sont conservés ; aucun accès API n'est
élargi. Le parcours complet des références métier passe, renforcé par l'ouverture directe
du détail Task, sa fermeture, puis la navigation par onglet et les références après
rechargement. Les six contrôles de refus/révocation passent et vérifient l'absence de
requêtes d'historique interdites. Cette qualification ne couvre pas la refonte RBAC entière.

La requalification suivante a retrouvé un second défaut sur ce lien : Quasar ferme
automatiquement un dialogue quand l'URL change. L'ajout de `tab=tasks` après l'ouverture
pouvait donc refermer le détail, selon l'ordre de chargement. Le dialogue conserve
désormais sa référence pendant la normalisation ; le retrait de `task_id` le ferme
explicitement. Échap, le fond et la révocation du droit conservent leur effet.
Le parcours assemblé a révélé cette régression. Le premier contrôle de composant la
manquait en vérifiant la visibilité pendant l'animation de sortie ; sa reprise attend
la fin des animations et échoue alors avant correction. Cette attente protège le
comportement stabilisé, sans figer la durée ou l'apparence de la transition.

### Vérifications de cette reprise

Pyright, vue-tsc, les 444 unités frontend et les catalogues i18n passent. Les groupes
de composants vérifiés comprennent 41 contrôles présentation/références/aide contextuelle,
65 contrôles pièces jointes et six contrôles d'accès par domaine. Le premier passage
avait révélé les défauts décrits ci-dessus ; ses échecs sont conservés avec leurs reprises.
Les E2E couvrent les trois langues initiales, les références métier, Files ordinateur/mobile
et la PWA. Le dernier parcours PWA vérifie le remplacement automatique A→B, le maintien
de la conversation/session et le fonctionnement hors ligne FR/ZH avec le bootstrap corrigé.

Les preuves locales sont regroupées sous `artifacts/optimisation-generalisee/`, dans les
dossiers `2026-10-24-frontend-profile`, `2026-10-24-memory-view-readiness`,
`2026-10-24-bootstrap-locale` et `2026-10-24-activity-readiness`. Leurs empreintes
qualifient 26 fichiers pour ces seuls contrats ; aucune revue complète de ces modules
n'est annoncée. Les changements concurrents indépendants sont conservés.

La préparation documentaire finale a régénéré les cartes et vérifié le corpus FR/EN.
Les 33 contrôles ciblés de `make architecture-check` passent. Plusieurs tentatives
précédentes de préparation documentaire avaient vérifié le corpus FR/EN et les
contrats d'architecture sur leur instantané, puis refusé de publier les cartes parce que
des sources avaient changé pendant l'exécution. Ces refus sont conservés dans les
journaux ; une réussite sur un instantané ne qualifie pas les modifications ultérieures.
Le garde-fou de publication n'a pas été contourné. L'inventaire a ensuite été réconcilié
avec les nouvelles cartes : 473 surfaces conventionnelles et 15 opérations qualifiées.

### Pointeurs natifs Document — L13 / SQL11

Le lecteur enregistré par Document cherchait successivement dans le contenu courant,
les révisions, les révisions de résumé, puis le résumé courant. Un résumé ou un pointeur
absent entraînait quatre allers-retours SQL dans ce domaine. Les consommateurs recensés
sont le stockage natif, les lectures et révisions Document, les résumés, les restaurations,
les projections Memory et la recherche documentaire. Les contrôles de droits restent
dans leurs consommateurs ; le registre Core conserve l'indépendance des domaines.

Le lot remplace ces quatre lectures par un `COALESCE` de sous-requêtes scalaires dans le
même ordre, chacune limitée à une ligne. L'expression SQL est construite une fois et
reçoit un paramètre à chaque appel ; elle ne conserve ni texte, ni résultat, ni droits.
Un texte vide est une valeur présente ; seul `NULL` poursuit la recherche. La visibilité
des propriétaires non flushés, l'absence d'autoflush et l'inclusion des archives restent
inchangées. Aucun schéma ni index n'est modifié.

Les budgets ont d'abord échoué sur la source initiale : sept cas atteignaient deux à
quatre lectures, avec des octets déjà corrects. Les neuf cas de précédence, providers,
valeurs vides/nulles et archivage, plus un parcours de transactions, passent après
correction. Ce dernier lit un propriétaire nouveau puis modifié sans SQL, observe le
commit d'une autre connexion malgré son objet ORM périmé, retrouve ce commit après
rollback et lit deux pointeurs en parallèle dans des sessions distinctes.

La source sauvegardée et le code réel sont comparés avec 1 et 2 000 lignes par source.
Les pointeurs recherchés se trouvent en fin du corpus synthétique ; leurs octets sont
comparés à chaque appel. Un échauffement précède six paires alternées par scénario ;
l'identity map est vidée et les allocations sont mesurées séparément sur quatre passages.
Ces temps locaux incluent l'instrumentation et d'autres vérifications ont tourné sur
l'hôte pendant la qualification ; ils ne constituent pas un budget de latence API.

| Source recherchée, corpus de 2 000 lignes | SELECT Document avant → après | Médiane avant → après |
|---|---:|---:|
| Contenu courant | 1 → 1 | 0,720 → 0,587 ms |
| Révision du contenu | 2 → 1 | 0,861 → 0,514 ms |
| Révision du résumé | 3 → 1 | 1,098 → 0,662 ms |
| Résumé courant | 4 → 1 | 1,711 → 0,914 ms |
| Pointeur absent | 4 → 1 | 1,936 → 1,037 ms |

Sur le petit corpus, le résumé passe de 0,789 à 0,210 ms. Les pics Python mesurés restent
voisins : environ 279–280 Ko avant et 276 Ko après. Le gain porte sur les allers-retours
du lecteur Document ; les lectures d'autres domaines du registre, l'autorisation et les
autres requêtes d'une réponse complète restent hors de ce budget. Le RSS, l'endurance,
les latences extrêmes et la charge globale ne sont pas qualifiés.

La première variante reconstruisait toutes les expressions à chaque appel : elle
réduisait les lectures mais ralentissait le contenu courant d'environ 0,3 ms et ajoutait
environ 12 Ko d'allocations. Elle est écartée ; la variante retenue réutilise uniquement
la structure SQL immuable. Le lecteur Memory possède déjà une requête union unique et
n'est pas modifié. Les boucles du registre Core composent des domaines distincts et ne
sont pas une variante à fusionner dans Document.

Les 83 tests de budgets et de consommateurs passent : actions Document, historique,
partage/révocation, ressources, classification, migrations de texte et stockage natif.
Les 49 contrôles de référence comprennent aussi 26 tests de supervision et de timeouts.
Pyright, vue-tsc, les 446 unités frontend et les 7 381 paires de messages passent dans le
worktree courant. Une annotation du paramètre SQL a corrigé le premier refus de typage ;
elle ne modifie pas l'expression exécutée. Les premières données du diagnostic tentaient
d'insérer une colonne calculée : ce montage invalide a été corrigé avant toute mesure
retenue. Les preuves locales sont dans
`artifacts/optimisation-generalisee/2026-10-24-document-inline/`.

Les dix scénarios ciblés ont aussi repassé sur la source finale annotée. Le parcours
Chromium de partage Document passe avec l'application assemblée : refus initial,
lecture, réouverture mobile, modification sans repartage puis révocation. Le premier
filtre de sélection Playwright n'avait sélectionné aucun test ; il a été corrigé avant
ce parcours réussi. Ces vérifications restent ciblées ; elles ne qualifient pas la
combinaison complète des changements du worktree.

### Travail Document au repos — IDLE01

Le worker réel a aussi été observé dans une base clonée, sans autre racine applicative,
avec une file vide puis 20 000 travaux terminés et des statistiques PostgreSQL actualisées.
Chaque observation de 6,25 secondes contient quatre lectures espacées d'environ deux
secondes. Le temps SQL cumulé vaut 2,207 puis 2,396 ms ; la médiane par lecture vaut
0,526 puis 0,559 ms. Il s'agit du temps d'exécution SQL, sans prétendre mesurer le coût
complet des sessions, le CPU ou la consommation globale au repos.

La cadence reste inchangée : aucun goulot dominant n'est démontré dans ces deux cas,
et l'allonger changerait la réactivité et la reprise des leases. La file active, la
concurrence et une observation prolongée restent ouvertes. Le superviseur Core a été
relu séparément : sa boucle de maintien ne lance pas elle-même les sondes de readiness,
qui sont exécutées à la demande. Ses callbacks applicatifs restent à profiler comme tels.

### Sélection des pages générales Process — L14 / SQL12

La liste HTTP générale sélectionnait tous les champs ORM de chaque exécution, puis
transmettait seulement leurs identifiants au sérialiseur de résumés L03. Cette première
lecture chargeait donc cinq JSON privés sans les consommer : données du processus,
état d'exécution, instantané moteur, analyse et instantané de lancement.

Le mode explicite `summary_only` de `paginate_runs` omet désormais ces colonnes pour
ce handler. Le comptage, les filtres, le tri, le périmètre natif et les droits ne changent
pas. Les entrées/sorties et métadonnées publiques restent entières ; la projection L03
relit ses champs et les deux libellés utiles de l'instantané. Le défaut conserve les
objets complets. Les listes MCP n'activent pas ce mode : leurs contrôles par élément et
leurs chargements restent à qualifier séparément. Aucun cache ni schéma n'est ajouté.

La comparaison exécute la sélection suivie de la sérialisation réelles, avec une source
sauvegardée après L03. Chaque cas exclut un échauffement puis alterne six paires ;
l'identity map est vidée avant chaque appel. Les réponses JSON complètes sont égales,
y compris page suivante, recherche vide et tri par statut. Quatre passages d'allocations
sont séparés des temps. D'autres vérifications ont tourné sur l'hôte pendant ces essais.

| Corpus / page / état privé | SELECT avant → après | Médiane avant → après | Étendue avant → après | Pic Python avant → après |
|---|---:|---:|---:|---:|
| 10 / 10 / petit | 3 → 3 | 2,406 → 2,439 ms | 1,996–3,851 → 2,339–3,186 ms | 0,342 → 0,325 Mo |
| 500 / 500 / petit | 3 → 3 | 29,408 → 25,597 ms | 26,279–32,838 → 23,980–30,131 ms | 6,029 → 5,133 Mo |
| 500 / 50 / volumineux | 3 → 3 | 10,539 → 6,323 ms | 8,883–14,197 → 5,018–7,099 ms | 4,468 → 0,578 Mo |
| 500 / 500 / volumineux | 3 → 3 | 62,693 → 28,015 ms | 60,387–67,696 → 25,878–29,910 ms | 40,409 → 5,128 Mo |

Le petit cas coûte environ 0,03 ms de plus dans cette série. Le gain principal porte
sur les allocations évitées quand l'état privé est volumineux ; il ne mesure pas le RSS
et ne qualifie ni un p99, ni la concurrence ou l'endurance. Les champs publics peuvent
eux-mêmes être volumineux et restent hors de cette réduction.

Le budget existant a été étendu au vrai handler de liste, en conservant les services
internes réels : les trois tailles 10/50/500 échouaient avant le changement parce que
les colonnes privées étaient chargées. Les cas par périmètre passaient déjà. Après
correction, les 164 contrôles Process réussissent. Les neuf filtres sont exercés avec
et sans projection ; un lanceur hors périmètre est exclu. La lecture détaillée puis le
retour au mode complet dans la même session retrouvent les données persistées et le
même objet ORM. Les 22 contrôles finaux du handler et de ses droits passent aussi,
avec les refus HTTP sans session ou sans privilège, après des modifications de droits
indépendantes dans d'autres routes du même fichier.

Les quatre comparaisons du code réel et le parcours Chromium du catalogue passent.
Ce dernier relit les résumés de cinq runs via l'API générale avant/après réouverture,
puis exerce l'éditeur natif et l'éditeur externe sur petit écran. Le typage ciblé des
deux fichiers Process passe. Les premiers contrôles globaux ont rencontré des sources
en cours de modification et des fixtures de tests frontend indépendantes ; les sorties
et reprises sont conservées séparément, sans les assimiler à une validation globale.

Les preuves locales sont dans
`artifacts/optimisation-generalisee/2026-10-24-process-selection/`. L03 est requalifié
pour ses résumés et consommateurs concernés ; ses mesures initiales restent historiques.
Les doubles frontend de disponibilité Mail et de lecture Goal ont aussi été alignés
sur les imports et codes d'autorisation courants, sans retirer leurs assertions de
révocation, de sélection ou de réponse tardive. Les premiers échecs de ces contrôles
étaient distincts des tests du chemin Process et restent dans les diagnostics locaux.

### Génération du contrat des paramètres en développement — L15 / DEV01

Le build frontend a révélé un import de `generatedAccess.ts` sans fichier correspondant,
dans une modification RBAC indépendante. Le générateur existait et écrivait dans
`/app-front/core/params`, mais Compose ne montait que le répertoire `authorize` : une
génération dans le backend ne devenait pas visible dans le dépôt.

Le montage ciblé du répertoire Params est ajouté en développement et le contrat est
produit par le générateur existant, à partir des noms de paramètres déclarés. Il ne
contient aucune valeur de paramètre. Un conteneur ponctuel utilisant la configuration
Compose corrigée a réellement régénéré le fichier du dépôt. Le backend actif n'a pas
été redémarré, aucune synchronisation DB n'a été nécessaire et les huit contrôles
existants de configuration Compose passent. Le montage devient actif pour le backend
à sa prochaine création normale. Le test central de câblage protège cette destination.

Une erreur indépendante de construction de `frozenset` depuis un générateur asynchrone
a également été signalée par le typage dans le handler Topics. Sa correction est arrivée
dans le worktree pendant la qualification et n'est pas attribuée à ces lots. Le nouveau
parcours HTTP traverse les vraies vérifications de droits et rouvre le sujet ; les
26 tests Topics, dont les attributions mensuelles L05, passent. Le premier montage de
ce diagnostic utilisait une adresse synthétique refusée par le validateur et n'avait
pas atteint le handler ; ce journal reste distinct de la vérification réussie.

La dernière reprise confirme le typage Pyright/vue-tsc, 448 unités frontend, les
catalogues i18n et les neuf composants ciblés, dont le scénario L12 après la fin des
transitions. Le parcours E2E des références métier passe de nouveau avec le lien direct
Task ; celui du catalogue Process passe aussi après réouverture et sur petit écran.
Une préparation documentaire a réussi ; les 33 contrôles de `make architecture-check`
passent également. Les deux reprises documentaires après consolidation du bilan ont
ensuite vérifié corpus et contrats sur leur instantané, mais refusé la publication à
cause de nouvelles modifications concurrentes. La préparation finale reste donc à
reprendre sur des sources stabilisées ; le garde-fou n'a pas été contourné.
Ces résultats ciblés ne valent pas validation complète de la plateforme.

Prochaine étape : poursuivre la revue des familles et fichiers signalés, des fortes
cardinalités de destinataires et des coûts au repos. Ces quinze lots ne closent pas la
campagne ; `make validate`, réservé à l'utilisateur, n'a pas été exécuté.
