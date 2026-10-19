# Campagne d’optimisation généralisée de Galaris

- Statut : `approved` — préparation demandée ; campagne non démarrée.
- Date de préparation : 2026-10-19.
- Démarrage envisagé : 2026-10-20, sur instruction de lancement de l’utilisateur.
- Nature : audit exhaustif du périmètre, qualification des pistes, corrections mesurées et bilan.
- La création de ce plan ne lance aucun benchmark, correctif, déploiement ou tâche programmée.

## Résultat attendu

Améliorer les performances et l’efficacité de Galaris sur l’ensemble de ses modules,
fichiers exécutables, parcours et infrastructures, en conservant ses garanties métier.
Une seule campagne porte la découverte, les corrections et leur qualification :
l’utilisateur ne doit pas avoir à demander une nouvelle recherche après chaque lot.

L’engagement d’exhaustivité porte sur un périmètre inventorié, des questions d’audit
explicites et des conditions de charge documentées. Il ne signifie pas qu’un optimum
universel existe pour tout matériel, toute donnée et tout usage futur.
Chaque piste reçoit une décision ; chaque surface possède un état et une preuve
adaptée. Une zone inaccessible ou non mesurée reste visible jusqu’au bilan.

Les optimisations retenues doivent produire un gain utile démontré. Une réduction du
temps local qui augmente excessivement la mémoire, le coût global ou les erreurs,
ou qui dégrade les résultats IA, ne constitue pas à elle seule une amélioration.

## Point de départ et sources

La [cartographie générée](../../docs/fr/architecture/generated/project-map.md) annonce
au moment de la préparation 77 modules backend déclarés, 39 frontend, 714 handlers
HTTP/WebSocket, 174 tables, 272 outils MCP natifs et 51 pages Vue. Ces nombres sont
des repères ; l’inventaire de lancement doit les recalculer et expliquer ses écarts.
Les modules déclarés ne couvrent pas à eux seuls toutes les infrastructures partagées.

Sources à consulter au lancement et dans chaque domaine :

- [Guide de développement](../../docs/fr/dev/README.md), contrats, modèles et tests réels.
- [Catalogue fonctionnel](../../docs/fr/dev/functional-tests.md) et
  [méthode de test](../../docs/fr/dev/testing.md).
- [Exploitation et volumétrie](../../docs/fr/dev/reliability-operations.md).
- [Audit SQL du 17 octobre](../audits/2026-10-17-sql-optimizations.md), à requalifier :
  douze chantiers recensés, quatre mesurés dans cet audit, sans preuve de livraison globale.
- [Revue des ressources](../audits/2026-09-07-resource-usage.md) et
  [matrice transversale](../audits/2026-09-19-fiabilisation-transversale.md), comme historique.
- [Index des plans](README.md) et [décisions](../decisions/README.md), pour éviter
  de transformer une optimisation en implémentation implicite d’une architecture future.

Un constat historique n’est ni une anomalie encore présente ni une preuve actuelle de gain.
Lire les skills applicables avant d’investiguer ou de modifier leur domaine, conformément
à `AGENTS.md`. Les lectures de code backend et frontend suivent aussi ces conventions.

## Garanties à conserver

| Domaine | Garanties obligatoires |
|---|---|
| Données | Contenu complet, révisions, historique, références, ordre et effets durables ; aucun écrasement ou effacement implicite. |
| Autorisation | RBAC, ACL, scopes, isolation entre comptes, équipes, agents et connexions ; refus après révocation. |
| Contrats publics | Réponses et sémantique HTTP, MCP, WebSocket et façades ; inventaire des consommateurs avant modification partagée. |
| Asynchronisme | Idempotence, annulation, réponses tardives, reprise, leases, absence de doublons et états terminaux immuables. |
| Streaming | Zéro ou plusieurs messages, exactement un résultat terminal et aucun événement après ce résultat. |
| Interface | Actions utilisables, brouillons conservés, chargement/erreur/retry, navigation et réouverture ; clavier et mobile lorsque concernés. |
| Ressources | Documents HTML dans Memory, Datasets JSON dans Dataset, BPMN dans Process ; URI et droits conservés. |
| IA | Qualité et réussite des tâches, capacités, provenance, livraison et vérification des effets ; coût par réussite plutôt que coût par appel seul. |
| Exploitation | Installation, mise à jour, reprise, diagnostic autonome et conservation de la cause primaire en cas d’échec. |

Toute incompatibilité ou modification structurelle doit être identifiée comme telle,
avec ses consommateurs, son coût de transition et la décision requise. Elle ne peut
pas être dissimulée dans un lot de performance.

## Périmètre et comptabilité de couverture

### Inventaire de référence

Au lancement, inventorier les fichiers suivis par Git et les nouveaux fichiers de source
présents dans le worktree, sans parcourir les secrets, données locales, dépendances
installées ou sorties de build. Rapprocher cet inventaire des déclarations backend et
frontend, de la carte générée, des routes, modèles, outils, tâches et tests collectés.

Chaque fichier appartient à une unité de revue et reçoit une catégorie : source active,
source conditionnelle, infrastructure, test/outillage, documentation, généré, tiers ou
inactif à justifier. Les sources non référencées restent à examiner avant de proposer
leur suppression. Les fichiers générés et tiers sont examinés par leur générateur ou
leur usage ; leur exclusion de lecture détaillée est motivée et comptée séparément.

Inclure notamment `back/`, `front/`, `bin/`, `e2e/`, les exécuteurs, le gestionnaire de
harnais, les images, Compose, Make, manifestes, verrous, CI, assets et documentation
liée aux parcours. Confirmer les chemins présents au lancement, y compris les fichiers
de configuration à la racine. Tout fichier nouveau ou modifié durant la campagne
entre dans le suivi et peut invalider une revue précédente.

### Trois vues complémentaires

| Vue | Unité | Preuve recherchée |
|---|---|---|
| Structurelle | Chaque module et chaque fichier de source | Lecture contextualisée, contrats et consommateurs, questions applicables et constats reliés. |
| Fonctionnelle | Chaque famille de parcours | Chaîne complète interface/API/DB/runtime/frontière externe, coûts cumulés et résultat métier vérifié. |
| Transversale | Chaque mécanisme partagé | Variantes dans les consommateurs, isolation, cycle de vie, volume, concurrence et comportement dégradé. |

Un fichier lu n’est pas automatiquement mesuré. Une suite verte n’est pas une mesure
de performance. Un benchmark de service n’est pas une qualification de l’application
assemblée. Les trois niveaux restent distincts dans les registres et le bilan.

### Registres à créer au lancement

Conserver les synthèses durables dans `project/audits/optimisation-generalisee/`.
Ne créer ces fichiers qu’avec les premières données réelles de la campagne.
Les diagnostics bruts et résultats de machines restent sous
`artifacts/optimisation-generalisee/<campagne>/`, hors des sources versionnées.

| Registre | Champs minimaux |
|---|---|
| `README.md` | Référence examinée, périmètre, objectifs, progression avec dénominateurs, limites, prochaine action et emplacement des preuves locales. |
| `couverture-fichiers.csv` | Chemin relatif, empreinte, module, catégorie, unité de revue, état, preuve, pistes, motif d’exclusion éventuel. |
| `couverture-surfaces.csv` | Module, surface publique/boucle/stockage, activation, consommateurs, critères applicables, couverture statique et dynamique distinctes, preuve manquante. |
| `parcours.csv` | Scénario, acteurs/droits, données, charge, régime de cache, résultat attendu, mesures initiales/finales et statut. |
| `pistes.csv` | Identifiant stable, cause, manifestations, preuve, confiance, impact, risque, solution, dépendances, décision, lot et vérification. |
| `lots.csv` | Périmètre, référence avant/après, pistes couvertes, garanties, commandes génériques de vérification, résultats, limites et retour arrière. |

Les rapports versionnés ne contiennent que des données synthétiques, mesures agrégées
et conclusions techniques. Aucun secret, contenu de production, identifiant réel,
commande capturée sensible ou chemin propre à une installation. Vérifier les sorties
avant leur conservation ; ne pas remplacer le masquage des secrets par la perte de stderr.

États de couverture : `à examiner`, `en cours`, `examiné`, `à mesurer`, `qualifié`,
`bloqué`, `exclu avec justification`. Une surface qualifiée indique précisément
pour quels scénarios et quelles charges. Un blocage indique sa cause, la preuve
manquante et la condition de reprise ; les autres unités continuent.

## Dimensions et mesures

| Dimension | Mesures et questions |
|---|---|
| Latence | Temps jusqu’au premier contenu utile, premier token, réponse complète et effet durable ; médiane et percentiles si l’échantillon le permet. |
| Débit et capacité | Opérations réussies par unité de temps, concurrence supportée, longueur/âge des files, temps d’attente et saturation. |
| Base de données | Nombre et durée des requêtes, lignes et colonnes chargées, plans, blocs, tris temporaires, verrous, pool et durée des transactions. |
| CPU | Temps CPU et chemins dominants, calculs et sérialisations répétés, blocages de l’event loop, coût des conversions. |
| Mémoire | RSS des processus, allocations, pic, état après fermeture et plateau après cycles ; distinguer allocations Python et mémoire totale. |
| Réseau | Nombre d’appels, taille transférée réelle, contenu utile, retries, amplification des événements et reconnexions. |
| Frontend | Ressources initiales et différées, rendu, interactions, longues tâches, croissance du DOM, abonnements et mémoire après navigation. |
| Stockage | Croissance logique/physique, index, historiques, journaux, fichiers temporaires, rétention et coût du nettoyage. |
| IA | Appels, tokens, contexte, temps local/fournisseur, retries, coût monétaire disponible, qualité et coût par tâche réellement réussie. |
| Repos et exploitation | CPU/requêtes/réseau sans utilisateur, démarrage, build, installation, mise à jour, santé et coût du diagnostic. |

Définir au jalon initial des budgets par famille et par volume à partir du besoin
observable et de la référence mesurée. Consigner unité, charge, tolérance au bruit et
garanties préservées. Éviter un seuil unique en millisecondes pour tous les parcours.
Quand le besoin maximal est inconnu, présenter une courbe et une limite de capacité
mesurée ; ne pas inventer une cible ou extrapoler sans preuve.

## Déroulement de la campagne

### Phase 0 État de référence et environnement

1. Lire `git status --short`, les instructions et les sources actuelles. Préserver les
   changements existants ; aucune remise à zéro ou création de commit implicite.
2. Identifier la révision, les changements non committés et les empreintes des sources.
   Décrire les versions d’images, ressources allouées, configuration utile non secrète,
   jeux de données et activation des modules.
3. Vérifier la disponibilité des conteneurs, bases éphémères et bancs navigateur.
   Séparer l’instrumentation de diagnostic du coût normal du produit.
4. Recenser les benchmarks, budgets et preuves déjà disponibles. Rejouer les scénarios
   retenus sur l’état courant ; distinguer échec préexistant et régression introduite.
5. Fixer les enveloppes d’essai : tailles, concurrence, durée, espace disque et appels
   externes. Les essais payants respectent une enveloppe explicite avant exécution ;
   à défaut, garder ces qualifications ouvertes et poursuivre les mesures locales.

**Sortie :** référence reproductible, matrice de couverture initiale, budgets d’essai,
contrôles disponibles et limites connues. Aucun gain annoncé à ce stade.

### Phase 1 Inventaire et premier parcours complet

Construire les registres puis exercer un parcours synthétique complet avant de
généraliser le dispositif : authentification, ouverture d’une conversation, envoi,
traitement agentique, outil contrôlé, persistance, résultat terminal, affichage et
réouverture. Séparer transport externe simulé et qualification avec fournisseur réel.

Découper le temps entre navigateur, transport, serveur, SQL, files, orchestration,
fournisseur et affichage. Vérifier le contenu et l’effet final, pas seulement le statut
HTTP. Corriger les lacunes du protocole de mesure avant d’étendre les essais.

**Sortie :** inventaire réconcilié et méthode de mesure éprouvée de bout en bout.

### Phase 2 Revue exhaustive par familles

Examiner tous les fichiers de chaque famille avec les contrats et tests associés,
appliquer les grilles ci-dessous et alimenter les pistes sans commencer les corrections
applicatives. Les prototypes nécessaires aux mesures restent isolés et réversibles.
La découverte continue après les premiers résultats intéressants.

L’ordre suivant organise le travail ; il ne retire aucun module du périmètre.
Réconcilier toutes les familles avec l’inventaire réel au lancement.

| Famille | Surfaces à examiner | Risques et mesures privilégiés |
|---|---|---|
| Socle backend | API, auth, utilisateurs, équipes, autorisations, paramètres, sessions, i18n, démarrage et supervision | Coût par requête, contrôles de droits, sessions/pools, démarrage, tâches au repos. |
| Persistance et stockage | Database, DbAdmin, storage, modèles de tous les domaines, fichiers et historiques | Plans et N+1, lectures larges, index, écritures, verrous, convergence, purge et croissance. |
| Socle frontend | Bootstrap, shell, API, navigation, routage, stores, i18n, composants communs, assets et PWA | Graphe initial, chargement différé, requêtes partagées, changement de compte, abonnements et réouverture. |
| Agents et tâches | Agent, Harness, Harnesses, Task, Goal et tous les drivers/gestionnaires de harnais | Préparation, dispatch, planning, files, leases, streaming, supervision, reprise et coût de coordination. |
| LLM et multimédia | LLM, providers conditionnels, Image, Audio, Voice, Multimedia | Résolution, catalogue, quotas, contexte, chunks, transferts, retries, rétention et qualité/coût. |
| Conversations | Messenger, Conversation, Chat et bridges Matrix, Nextcloud, OneBot, Telegram, WhatsApp | Journal entrant, déduplication, historique, pagination, fan-out, réactions, reconnexion, médias et audio. |
| Outils et connexions | Tools, MCP, Connection, Skill, File Share, Browser, Console, Code et bridges associés | Découverte, catalogues, chargements répétés, pools, matérialisation bornée, callbacks et arrêt. |
| Ressources et mémoire | Memory, Dataset, Contact, Topic, Dream, Share | Bibliothèques, recherche, ACL, indexation, embeddings, graphe, révisions, résolution et rétention. |
| Processus | Process, bridge n8n, BPMN natif, workers de calcul et activités | Catalogue, sérialisation, état, transitions, événements, callbacks, concurrence et reprise. |
| Administration et évaluation | Dashboard, Lab, Incident, Documentation, Onboarding et écrans de configuration | Agrégations, compteurs, qualification, import/export, recherche documentaire et gros historiques. |
| Adaptateurs externes restants | Mail, Calendar, Samba et tout bridge présent non couvert ci-dessus | Connexions, pagination distante, synchronisation, erreurs, quotas, retries et nettoyage. |
| Livraison et outillage | Compose, images, exécuteurs, Make, bin, CI, documentation et tests | Taille/build, démarrage, opérations au repos, duplications, isolation, diagnostics et preuves d’échec. |

Une petite taille de fichier, une faible couverture de tests ou une faible fréquence
d’usage n’autorisent pas une exclusion automatique. Les modules désactivés sont revus
statiquement et qualifiés dynamiquement lorsque leur environnement est disponible.

**Sortie :** tous les fichiers classés, toutes les unités revues ou explicitement
bloquées, pistes reliées à leurs manifestations, lacunes de mesure identifiées.

### Phase 3 Qualification dynamique et recherche transversale

Exercer les familles de parcours ci-dessous et les chemins coûteux relevés par la revue.
Mesurer les causes dominantes, les attentes et les limites ; une recherche textuelle
de motifs suspects ne démontre pas à elle seule un problème.

Pour chaque cause confirmée, chercher ses variantes dans tout le dépôt, examiner
chaque occurrence dans son contexte et inventorier les consommateurs. Rassembler
les occurrences dans une même piste lorsque la correction et le contrat sont communs.

**Sortie :** pistes confirmées, infirmées ou encore incertaines ; mesures comparables,
risques fonctionnels et familles de consommateurs. Les blocages n’interrompent pas
l’exploration indépendante. Le passage aux corrections intervient après la consolidation
du périmètre global et l’enregistrement de toutes les zones non qualifiées.

### Phase 4 Arbitrage et construction des lots

Ordonner les pistes par gain utile, fréquence/volume, croissance, confiance, risque et
coût de réalisation. Distinguer améliorations dominantes, croissance non bornée,
gaspillage au repos, gains locaux et recherches architecturales.

| Décision d’une piste | Justification attendue |
|---|---|
| À réaliser | Gain démontré ou réduction mesurée d’une croissance, garanties et vérification définies. |
| À expérimenter | Hypothèse précise, expérience discriminante et enveloppe bornée. |
| Écartée | Hypothèse infirmée, gain négligeable ou compromis défavorable démontré. |
| Différée | Dépendance ou décision externe précise ; conséquence et condition de reprise documentées. |
| Bloquée | Preuve nécessaire inaccessible ; aucun succès déclaré pour cette qualification. |

Une priorité faible ne supprime pas une piste du registre. Ne pas multiplier les
micro-optimisations pour augmenter artificiellement le nombre de corrections.
Une expérience s’arrête lorsque son hypothèse est tranchée ou son enveloppe atteinte ;
consigner l’incertitude restante et poursuivre les autres unités.

**Sortie :** liste globale des décisions, lots ordonnés et garanties par consommateur.
Les choix structurels suivent les décisions du dépôt ; aucun déploiement ni changement
de produit n’est déduit du seul objectif de performance.

### Phase 5 Réalisation et preuve par lot

Pour chaque lot :

1. Confirmer que la référence et les consommateurs n’ont pas changé depuis la mesure.
2. Reproduire le défaut ou exécuter le benchmark initial avec le comportement attendu.
3. Renforcer la couverture existante de la garantie durable lorsque nécessaire.
4. Appliquer la correction la plus directe ; garder les refactorings connexes séparés.
5. Vérifier le même scénario après correction : égalité métier, gain, dispersion,
   coût déplacé et risques de concurrence/erreur selon le changement.
6. Exercer un parcours assemblé, puis étendre aux autres familles de consommateurs.
7. Relire le diff pour perte de données, accès indu, état bloqué, ressources non bornées
   et régressions. Résoudre les constats avant de fermer le lot.
8. Revenir sur une expérience défavorable en préservant les changements étrangers au lot.
9. Mettre à jour registres, documentation et mesures ; invalider les preuves dépendantes
   lorsqu’une autre correction modifie leurs conditions.

Une réussite ciblée qualifie le lot dans son périmètre ; elle ne qualifie pas encore
la combinaison de tous les changements.

### Phase 6 Qualification combinée et clôture

Comparer le système initial au système final sur les mêmes parcours et distributions.
Vérifier les interactions entre lots, les nouvelles causes dominantes, les consommations
déplacées et la capacité sous charge. Refaire les seules mesures invalidées ou nécessaires
à cette comparaison ; ne pas répéter les suites larges sans raison.

Toute nouvelle manifestation alimente le registre et suit le même circuit. Une nouvelle
cause prioritaire révélée par la suppression d’un premier goulot doit être qualifiée.
Une recherche sans gain utile supplémentaire peut être close avec ses preuves et limites.

## Grilles techniques à appliquer

### Backend et base de données

- Travail réellement nécessaire : calculs, conversions, validation, résolution et
  sérialisation répétés ; appels internes redondants et réponses trop larges.
- Requêtes par élément, chargements de relations, rafraîchissements, comptages,
  agrégations avant pagination, transactions longues et attentes de connexion.
- Index utiles ou redondants selon les filtres, tris et écritures réels ; plans avec
  distributions représentatives, sélectivité des ACL, historiques et suppressions logiques.
- Pagination stable, bornes et taille de 500 acceptée côté API ; coût des gros contenus
  exclus des projections de liste quand le contrat le permet.
- Sections synchrones dans les chemins async, fan-out non borné, timeouts aux bonnes
  frontières, backpressure, interruption et récupération.
- Rétention, tombstones, MVCC, taille des journaux/index et durée de nettoyage ;
  réessai sans perte ni double effet. Toute modification de schéma passe par DbAdmin.

### Frontend et cycles de navigation

- Imports initiaux/différés, éditeurs et bibliothèques lourdes, fontes, images et
  précache PWA ; mesurer séparément graphe initial et téléchargements hors ligne.
- Appels à l’ouverture/réouverture, doublons, waterfalls, polling, surchargement,
  pagination, sélection des champs et cohérence des indicateurs de chargement.
- Stores et caches : déduplication, fraîcheur, invalidation, clé de contexte,
  changement de compte/droits et rejet des réponses obsolètes.
- Rendu et réactivité : listes/graphes, coût des watchers et transformations,
  DOM, longues tâches, écouteurs, timers, sockets et libération après démontage.
- Parcours vide/existant/erreur/retry, navigation rapide, fermeture avant réponse,
  réouverture, conservation du brouillon ; viewport inférieur puis supérieur ou égal
  à 1024 CSS px lorsque concerné, clavier et absence d’action inaccessible.
- Aucun plafond HTTP navigateur global réintroduit comme raccourci de performance.
  Les assertions permanentes protègent les usages et budgets utiles, pas un layout local.

### Agents, IA, outils et flux externes

- Décomposer préparation locale, file, fournisseur, outil, persistance et affichage ;
  distinguer premier token, premier résultat utile et réussite complète.
- Mesurer prompts, catalogues, mémoire injectée, duplication du contexte, résolutions
  de modèle/connexion et coût de coordination entre étapes.
- Comparer qualité et effets sur corpus synthétique figé ; répétitions pour la variance,
  versions/réglages identifiés et coût de toute la trajectoire, échecs inclus.
- Examiner streaming, nombre/taille des chunks, écritures et événements, journal,
  reprise, reçus tardifs, retries et quotas ; préserver les résultats terminaux.
- Vérifier les outils actifs/inactifs, configuration fraîche, capacités et droits,
  connexions partagées, téléchargements et matérialisations temporaires bornées.
- Les propositions de changement de modèle, supervision ou ordonnanceur restent
  reliées aux plans existants ; aucune dégradation de qualité acceptée implicitement.

### Infrastructure, observabilité et outillage

- Mesurer au repos puis sous activité : boucles, healthchecks, scans, indexations,
  synchronisations, caches, pools, volumes et services conditionnels.
- Examiner limites de ressources, files, concurrence, proxies, compression et coûts
  de conteneurisation selon les goulots observés ; éviter le réglage sans hypothèse.
- Mesurer le coût des logs/traces/métriques et leur volume sans perdre les preuves utiles.
  Toute évolution d’observabilité suit le skill correspondant.
- Préserver les preuves locales d’échec d’installation/mise à jour, cause primaire,
  échec secondaire et échec de stockage du diagnostic ; injecter les défaillances utiles.
- Optimiser builds et tests avec leurs garanties : dépendances reproductibles,
  collecte réelle, isolation des bases et détection des régressions.

## Parcours minimums à qualifier

Chaque ligne décrit une famille à détailler en scénarios. La matrice issue des surfaces
réelles doit compléter cette liste, notamment pour les pages et outils moins fréquents.

| Famille | Chaîne et variantes nécessaires |
|---|---|
| Session et shell | Connexion, première page, navigation, déconnexion/changement de compte, réponse ancienne et droits révoqués. |
| Administration | Listes/recherche/détail/modification, pagination, grands catalogues, retour à la liste et réouverture. |
| Chat | Historique, envoi, streaming long, annulation, reconnexion, pièce jointe et retour dans une conversation existante. |
| Task/Goal | Création, plan/arbre, outil, progression, pause/reprise/annulation, terminal et persistance après réouverture. |
| Outils/connexions | Catalogue, configuration, découverte, appel, refus, erreur externe et configuration modifiée durant l’usage. |
| Mémoire/Documents | Liste, recherche, lecture/édition/sauvegarde, révisions, partage/révocation, pièces jointes, indexation et graphe. |
| Datasets | Liste/détail, grands JSON, lecture/écriture, révisions, références depuis Document/Process et isolation des droits. |
| Process | Catalogue, lancement, activités, attente/callback, doublon, interruption/reprise et supervision. |
| Messenger/bridges | Entrée, journal, dispatch, livraison, doublon, reçu tardif, fichier/média et reconnexion. |
| LLM/multimédia | Catalogue/profil, appel texte et flux, média, quota/erreur, coûts, historique et rétention. |
| Topic/Contact/Dream/Dashboard | Recherche/résolution, agrégations historiques, traitement périodique et affichage sous croissance. |
| Lab/Documentation/Onboarding | Lecture et recherche, campagne bornée, résultat/erreur, progression et réouverture. |
| Exploitation | Démarrage/repos, concurrence, croissance prolongée, purge, mise à jour/reprise et diagnostic en échec, dans un environnement isolé. |

## Protocole expérimental

1. Utiliser des fixtures entièrement synthétiques et des environnements isolés.
   Figer paramètres, volumes, distribution des données, droits, versions et état initial.
2. Commencer par un cas représentatif, puis augmenter cardinalité, profondeur,
   taille des contenus et concurrence séparément avant leurs combinaisons utiles.
   Inclure données vides, usuelles, grandes, historiques et fortement partagées.
3. Distinguer cache froid, cache chaud et invalidation ; définir ce que « froid »
   signifie réellement sans purger les caches globaux de la machine ou des services actifs.
4. Réinitialiser l’état comparable, effectuer les échauffements nécessaires,
   alterner l’ordre référence/candidat et répéter les essais. Enregistrer les échecs,
   la dispersion et la concurrence étrangère ; ne pas sélectionner le meilleur passage.
5. Vérifier résultats, droits et effets pour chaque variante. Comparer également
   les requêtes/octets, ressources et coûts déplacés, au-delà du temps total.
6. Publier médianes et intervalles ou distributions adaptés. Les percentiles élevés
   exigent un nombre d’échantillons suffisant ; trois essais ne qualifient pas un p99.
7. Distinguer mesure sous instrumentation, benchmark isolé, navigateur et essai assemblé
   avec des images représentatives de la livraison ; ne pas extrapoler depuis le hot reload.
8. Pour concurrence et endurance, observer file, erreurs, verrous, mémoire après cycles,
   récupération et plateau. Une fin d’essai sans crash ne démontre pas l’absence de fuite.
9. Les doubles couvrent les frontières externes ; garder les vrais services internes,
   transactions et permissions du workflow. Signaler séparément l’absence d’essai réel
   d’un bridge ou fournisseur ; ne pas attribuer son attente à un coût local.

## Vérification et commandes

Utiliser les cibles Make réelles et les conteneurs ; ne pas lancer les toolchains sur
l’hôte ni pytest dans le backend de développement. Choisir les suites après inspection
des tests existants et de la panne durable à protéger.

| Besoin | Contrôle à sélectionner selon le lot |
|---|---|
| Persistance/règle/SQL | `make tests ARGS='…'`, avec la base éphémère et les scénarios concernés. |
| Composant/réactivité/cache | `make tests-front-components ARGS='…'` et unités existantes selon leur collecte réelle. |
| Parcours assemblé | `make tests-e2e ARGS='…'` et inspection des erreurs navigateur/requêtes échouées. |
| Typage et catalogues | `make typecheck`, après un ensemble cohérent de changements. |
| Lint | `make lint`, selon les sources modifiées. |
| Frontières et carte | `make architecture-check` ; réduire la dette supprimée sans augmenter la baseline. |
| Documentation | `make docs-prepare` ; mettre à jour les parcours FR/EN si le comportement ou la navigation change. |
| Volume spécifique | Benchmarks existants, dont rétention LLM, bibliothèques Memory, listes Process/Dataset, streaming et charge DbAdmin. |
| Hygiène finale | Relecture du diff, registres et `git diff --check`. |

Les commandes avec `…` sont des patrons à remplacer par des chemins effectivement
présents ; elles ne sont pas des commandes de lancement littérales.
Ne créer ni une batterie miroir de l’implémentation ni un test par fichier. Préférer
budgets de requêtes, conservation des résultats, isolation et bornes de croissance.
Les assertions de temps tiennent compte du bruit et sont complétées par des mesures
structurelles pertinentes. Justifier le retrait éventuel d’une assertion existante.

`make validate` reste réservé exclusivement à l’utilisateur. L’agent ne l’exécute
pas, ne lance pas ses scripts et ne reproduit pas son orchestration complète.
Quand l’utilisateur le lance, lire la synthèse et les échecs de l’instantané concerné ;
toute édition suivante invalide cette qualification du code courant.
La campagne fournit ses preuves ciblées et le bilan nécessaire à cette étape.

## Pilotage et reprise entre sessions

À chaque session, lire d’abord ce plan, le résumé de campagne et les registres ; comparer
les empreintes aux sources courantes. Reprendre la prochaine unité inachevée, sans
repartir d’une recherche générale ni répéter les découvertes déjà tranchées.

À chaque unité terminée, enregistrer l’état, les preuves, les nouvelles pistes et les
consommateurs à revoir. Une référence changée déclenche une requalification ciblée et
un suivi des dépendances ; les preuves non affectées restent utilisables.

Communiquer des progrès concrets : surfaces examinées sur total, mesures réalisées sur
prévues, gains confirmés, limites et prochaine étape. Ne pas attendre que l’utilisateur
redemande une recherche après chaque lot. L’autonomie de la campagne commence à son
lancement explicite ; ce plan ne programme aucune exécution pour le lendemain.

Les actions de production, publication et commits restent soumises aux autorisations
du dépôt. Aucun nettoyage global, suppression de volumes ou modification directe sur
un serveur de production ne constitue une étape implicite de cette campagne.

## Critères de réception et bilan

- [ ] L’inventaire est réconcilié avec les déclarations et les fichiers réels ; les ajouts
  de la campagne sont inclus. Chaque fichier possède une catégorie et un état justifié.
- [ ] Toutes les sources du périmètre ont une revue contextualisée ou un blocage identifié.
  Les exclusions générées/tiers/inactives restent distinctes du taux de revue.
- [ ] Les surfaces publiques, boucles, stockages et consommateurs sont reliés aux unités
  revues ; aucune famille de modules n’a disparu entre inventaire et bilan.
- [ ] Les parcours et charges convenus ont été mesurés, ou les preuves manquantes sont
  décrites avec leur conséquence. Les couvertures statique et dynamique sont séparées.
- [ ] Chaque piste possède une décision étayée ; les causes confirmées ont fait l’objet
  d’une recherche de variantes et les occurrences connues sont comptabilisées.
- [ ] Les lots retenus ont leurs preuves avant/après, garanties, consommateurs et
  vérifications de concurrence/erreur/reprise adaptées.
- [ ] Les parcours combinés ont été comparés à la référence initiale ; les régressions
  introduites sont résolues et les nouvelles causes prioritaires sont qualifiées.
- [ ] Les contrôles pertinents, essais assemblés et limites sont rapportés séparément.
  Aucun résultat ciblé n’est présenté comme une validation complète du système.
- [ ] Le bilan agrège les gains sans additionner des pourcentages incompatibles, indique
  les coûts déplacés et publie les dénominateurs de couverture.
- [ ] Les risques, pistes différées et blocages résiduels ont un impact et une condition
  de reprise. Une preuve indispensable manquante maintient la qualification concernée
  ouverte ; elle n’est pas transformée en réussite pour clôturer le plan.
- [ ] La documentation utile est préparée, les modifications étrangères préservées,
  les preuves expurgées et `git diff --check` réussi.

Le bilan final sera conservé dans `project/audits/optimisation-generalisee/README.md`.
Il distinguera réalisation, audit terminé, qualification partielle et blocages.
Une fois les travaux réalisés ou transférés explicitement, mettre à jour l’index des
plans et conserver contrats et preuves dans leurs sources canoniques.

## Instruction de lancement

> Lance la campagne décrite dans `project/plans/optimisation-generalisee.md`.
> Commence par figer l’état, inventorier tout le périmètre et établir les mesures.
> Poursuis la revue de toutes les unités et la consolidation des pistes avant les
> corrections applicatives, puis réalise et qualifie les lots retenus.
> Tiens les registres à jour pour reprendre entre sessions et continue sans attendre
> une nouvelle demande après les premières découvertes. Signale les limites sans
> présenter une zone non examinée comme optimisée. Respecte les critères de réception,
> les changements existants et les restrictions de production, commits et validation.
