# Migration progressive du backend vers Rust — piste exploratoire

- Statut : `design`
- Revue des sources : 2026-10-25.
- Portée : étude d'une migration ascendante par bibliothèque native PyO3.
- Réalisation : non engagée ; aucun prototype ni benchmark Rust réalisé pour ce plan.

## Résultat recherché et décisions encore ouvertes

Évaluer si un noyau Rust améliore la fiabilité de la concurrence, la consommation de
ressources et la maintenance de Galaris, en conservant les comportements existants.
Porter progressivement les dépendances autonomes, puis leurs consommateurs. Chaque
tranche doit pouvoir être qualifiée et conservée sans engager une réécriture totale.

Ce document est une piste de travail, pas une autorisation d'implémentation, de déploiement
ou d'appels fournisseurs payants. Il ne change ni les priorités ni l'architecture acceptée.
Les lots ci-dessous sont tous à réaliser ; leurs critères sont des preuves attendues.

Trois destinations doivent rester distinctes :

| Destination | Python restant | Condition de choix |
|---|---|---|
| A — Backend hybride | API, ORM, Pydantic AI et adaptateurs autour d'un noyau Rust. | Les gains utiles sont acquis sans remplacer les bibliothèques structurantes. |
| B — Runtime métier Rust | Hôte Python pour Pydantic AI, certains providers et la compatibilité historique. | Le runtime natif apporte un gain démontré et la frontière Python reste maîtrisable. |
| C — Backend entièrement Rust | Aucun interpréteur Python nécessaire au fonctionnement du backend. | Tous les consommateurs, protocoles, données et opérations d'administration ont un remplacement qualifié. |

Conserver A ou B est une issue valable. Un binaire Rust qui embarque CPython et Pydantic AI
reste hybride. Retirer Pydantic AI est une décision indépendante, tardive et facultative.
Aucun framework agentique Rust de remplacement n'est choisi.

## Sources et contraintes établies

Consulter à nouveau ces sources au démarrage de chaque lot : le checkout évolue.

- [Modules activés](../../back/modules.py), [cartographie générée](../../docs/fr/architecture/generated/project-map.md)
  et [invariants](../../docs/fr/architecture/invariants.md) : les couches sont `core/app/bridge` ;
  les cycles existants interdisent de supposer un ordre topologique module par module.
- [Contrats agentiques](../../back/app/agent/contracts.py) et
  [driver interne](../../back/app/harness/driver.py) : une frontière de driver existe déjà,
  indépendante du runtime concret ; son implémentation actuelle est Python.
- [Flux agentique](../../docs/fr/architecture/flows/agent-execution.md) et
  [machines d'état](../../docs/fr/architecture/state-machines.md) : les leases, commandes,
  checkpoints et journaux PostgreSQL portent la reprise, pas la mémoire du processus.
- [Runtime du harnais](../../back/app/harness/runtime.py),
  [checkpoints](../../back/app/harness/checkpoint.py),
  [inférence structurée](../../back/app/llm/structured_service.py) et
  [façade providers](../../back/app/llm/provider_facade.py) : Pydantic AI est utilisé au-delà
  de `app.harness`. `ModelProfile` apparaît même dans une interface publique de providers.
- [ADR 0095](../decisions/0095-pydantic-ai-request-ownership.md) : la construction des requêtes
  et la lecture des réponses ont été confiées au SDK pour éviter de maintenir localement
  les particularités des modèles. Les contrats actuels et le verrou de dépendances font foi.
- [Catalogue des tests](../../docs/fr/dev/functional-tests.md),
  [tests du driver](../../back/app/agent/tests/test_driver_testkit.py),
  [tests de checkpoints](../../back/app/harness/tests/test_checkpoint.py) et
  [tests d'annulation](../../back/app/harness/tests/test_runtime_cancellation.py) : réutiliser
  les garanties existantes avant d'ajouter de la couverture.
- [Dockerfile](../../back/Dockerfile) et [manifest Python](../../back/pyproject.toml) : le
  backend utilise Python 3.14 ; l'intégration Cargo/PyO3/Maturin reste à concevoir.

La lecture de ces fichiers ne constitue pas une validation de leur comportement actuel.
Les changements locaux d'autres travaux doivent être conservés ; figer une référence
isolée avant toute comparaison ou expérience.

## Architecture de transition proposée

```text
API, orchestration et dépendances Python conservées
                      |
           interfaces Python publiques existantes
                      |
          adaptateurs PyO3 minces et typés
                      |
     bibliothèques Rust autonomes par responsabilité
```

1. Le noyau Rust ne dépend pas de PyO3, de Pydantic ou d'objets SQLAlchemy. Ses données,
   erreurs et règles se testent sans initialiser Python.
2. L'adaptateur convertit les entrées, erreurs et résultats ; il ne devient pas un second
   service métier. Fournir des annotations Python vérifiées par Pyright.
3. Les appels Rust vers Rust deviennent directs lorsque les deux responsabilités sont
   migrées. Préserver `core` indépendant de `app/bridge`, y compris entre crates.
4. Une opération cohérente traverse la frontière en une fois lorsque possible. Mesurer
   conversions, copies et allocations ; ne pas imposer JSON comme format interne universel.
5. Les threads Rust possèdent leurs données. Les callbacks Python et leurs `ContextVar`
   restent attachés à l'hôte approprié ; aucune session SQLAlchemy partagée avec un worker.
6. Libérer l'interpréteur pendant une fonction longue ne suffit pas à préserver la
   réactivité du thread `asyncio` : prévoir une exécution déportée ou un pont async qualifié.
7. Le code natif partage le processus Python. Un crash natif peut arrêter tout le backend ;
   PyO3 n'est pas un mécanisme d'isolation ni une garantie de reprise après arrêt brutal.

Un workspace candidat serait `back/native/`, avec des bibliothèques de domaine et une
crate de liaison Python. Ce chemin et ce découpage sont à confirmer au lot R02 ; ne pas
créer une crate par fichier ni un nouveau système d'activation concurrent à `modules.py`.

## Ordre des lots et points de décision

```text
R00 référence -> R01 risque Pydantic AI -> décision sur l'expérience native
R02 outillage -> R03 première règle -> R04 dépendances pures -> R05 état métier
R06 pont async -> R07 premier worker -> R08 pilote du harnais
R09 extension des domaines -> destination A ou B possible
R10 remplacement facultatif de Pydantic AI -> R11 persistance et socle HTTP
R12 retrait final de Python, seulement pour la destination C
```

R01 étudie tôt le risque principal ; il ne remplace pas Pydantic AI. R08 démontre un
parcours agentique borné avant de généraliser la migration du runtime. R09 peut porter
des parties indépendantes sans attendre R08, mais aucun consommateur ne dépend d'une
capacité expérimentale non qualifiée. Chaque lot peut être subdivisé en livraisons.

### R00 — Figer les contrats, consommateurs et mesures de départ

1. Établir un inventaire à partir de `back/modules.py` et des imports réels : module,
   interface publique, dépendances, consommateurs, tables, jobs, HTTP/MCP et tests.
2. Classer chaque responsabilité : règle pure, état en mémoire, I/O, persistance,
   orchestration ou dépendance Python. Repérer les cycles et les ensembles transactionnels.
3. Pour chaque candidat, écrire la garantie observable et les comportements à conserver :
   droits, données existantes, erreurs, annulation, reprise, événements et terminalité.
4. Mesurer sur infrastructure Docker isolée : CPU, RSS, allocations si pertinentes,
   débit, latences p50/p95/p99, retard de boucle async, requêtes SQL et coût des conversions.
5. Inclure repos, charge représentative, saturation et récupération ; figer corpus,
   version, matériel, concurrence, budgets CPU/RAM, caches et bibliothèques natives.

**Sortie :** registre de couverture pour tous les modules, graphe et référence reproductible.
Les mesures brutes restent sous `artifacts/` ; les conclusions versionnées sont agrégées.
**Arrêt :** aucun premier lot de performance choisi sur une intuition seule.

### R01 — Qualifier tôt la dépendance à Pydantic AI

1. Inventorier les imports et usages directs, différés, réexportés et persistés dans tout
   le backend : `app.harness`, `app.llm`, Lab, Tools, voix et bridges providers notamment.
2. Compléter la matrice ci-dessous avec les symboles, consommateurs, versions verrouillées,
   tests disponibles et trous de couverture. Distinguer Pydantic validation, Pydantic AI,
   les SDK fournisseurs et Monty ; ce sont des remplacements différents.
3. Relever le format et les versions acceptées des historiques/checkpoints, y compris
   les éléments opaques propres aux fournisseurs et les appels différés en attente.
4. Décrire deux contrats candidats : appel d'un run Pydantic AI complet depuis Rust ;
   appel élémentaire de modèle depuis une boucle Rust. Le premier prouve l'interopérabilité,
   il ne prouve pas le remplacement de la boucle agentique.
5. Préparer la recette minimale R08 : texte, appel d'un outil de lecture, résultat final,
   annulation et reprise. Identifier ce qui restera réellement Python dans chaque variante.

**Sortie :** étude de faisabilité, contraintes et coût de maintenance, avant une extension
du runtime Rust. Décider si l'on poursuit vers A, explore B ou étudie C ; une difficulté
sur C ne bloque pas les lots utiles de A. Aucune promesse de suppression du SDK.

### R02 — Construire une extension native reproductible

1. Choisir et verrouiller Rust, PyO3, Maturin et les dépendances ; vérifier Python 3.14,
   les plateformes effectivement prises en charge et les licences. Évaluer l'ABI retenue.
2. Ajouter un workspace minimal et une liaison Python typée, puis construire les wheels
   en étapes Docker dédiées. Garder les compilateurs hors de l'image de production.
3. Intégrer des cibles Make ciblées pour formatage, analyse Rust, tests et construction.
   Ces cibles sont à créer ; elles n'existent pas à la date de ce plan. Ne rien installer
   sur l'hôte et ne pas modifier l'orchestration de `make validate` pour la reproduire.
4. Vérifier import et exécution de la vraie extension dans les images dev, tests et prod ;
   exercer wheel absente, version incompatible et erreur de chargement avec diagnostic utile.
5. Définir reconstruction native en dev, cache de compilation et association exacte entre
   code Python et binaire. Le hot reload Python ne recompile pas spontanément Rust.

**Sortie :** une image construite à neuf charge l'extension exacte, Pyright voit ses types,
les erreurs natives prévues deviennent des erreurs Python identifiables. Les défaillances
de build/install conservent commande, étape, cause et statut sans dépendre de la télémétrie.
**Retour :** ancienne image cohérente ; aucun changement de données.

### R03 — Porter une première règle déterministe d'incidents

1. Examiner `app.incident.sanitizer.fingerprint_failure` et ses consommateurs. Extraire
   précisément le traitement déterministe, en conservant la conversion des objets Python
   côté adaptateur. La catégorisation et la suppression de secrets restent hors du premier lot.
2. Écrire un corpus entièrement synthétique : Unicode, nombres, UUID, références d'erreur,
   espaces, valeurs absentes et limites de taille. Relever les empreintes Python de référence.
3. Implémenter les mêmes règles en Rust et vérifier normalisation, expressions régulières,
   sérialisation canonique et empreintes octet pour octet. Une différence peut changer les
   regroupements d'incidents existants : aucun changement implicite d'algorithme/version.
4. Conserver l'interface Python et remplacer son implémentation par l'adaptateur. Réutiliser
   les scénarios de persistance/groupement ; tester la vraie extension, pas un faux module.
5. Mesurer appel isolé, lot d'incidents et workflow complet, conversions incluses.

**Sortie :** parité des empreintes et regroupements, échec explicite sur entrée invalide,
coût d'intégration connu. Ce lot peut servir à éprouver l'outillage sans gain de vitesse.
**Retour :** restauration de l'implémentation Python ; empreintes persistées compatibles.

### R04 — Remonter les dépendances pures sélectionnées

1. Classer les candidats après R03 par coût mesuré, couplage et risque. Examiner les règles
   d'incidents restantes, codecs de valeurs et traitements de texte ; confirmer les propriétaires.
2. Pour chaque candidat, inventorier tous les consommateurs avant extraction ; établir
   formats, erreurs, limites, ordre, Unicode, nombres, dates et stabilité des identifiants.
3. Porter une opération complète à la fois avec son corpus de parité. Pour les structures
   aux entrées variées, évaluer les tests de propriétés et lire le skill correspondant.
4. Vérifier les données déjà persistées. Une nouvelle normalisation HTML, empreinte,
   interprétation d'URI ou de valeur JSON exige une décision explicite de compatibilité.
5. Retirer le doublon Python après qualification et période de retour définie pour le lot.

**Sortie par extraction :** consommateurs recensés, corpus compatible, coût total mesuré,
implémentation de référence et échéance de retrait identifiées.
**Limites :** le chiffrement, le hachage standard et une partie du traitement média/HTML
utilisent déjà des bibliothèques natives ; leur réécriture n'est pas un gain présumé.

### R05 — Porter l'état et les règles métier sans déplacer les effets

1. Choisir une machine d'état bornée après inventaire, par exemple une règle de transition
   ou de reprise ; utiliser les constantes et tests réels, pas uniquement la documentation.
2. Définir des valeurs natives : état lu, commande, révision, autorité et décision produite.
   Garder les appels réseau et les écritures PostgreSQL dans leur propriétaire actuel.
3. Porter les règles ; vérifier transition interdite, terminalité et données historiques.
4. Persister la décision seulement après une revalidation atomique dans la transaction.
   Le compilateur Rust ne garantit ni fraîcheur du lease ni absence d'écrivain concurrent.
5. Comparer les décisions Python/Rust sur des snapshots synthétiques sans appliquer deux
   fois les effets. Couvrir concurrence réelle par des transactions DB indépendantes.

**Sortie :** décisions équivalentes, écriture périmée refusée, aucun second propriétaire du
workflow. **Retour :** décision Python sur le même état durable, sans modification du schéma.

### R06 — Qualifier le pont async et le multithread avant tout worker

1. Comparer l'exécution CPU déportée depuis Python et un pont asyncio/Tokio maintenu.
   Choisir sur un prototype isolé ; ne pas imposer Tokio aux règles synchrones.
2. Définir propriétaire et durée de vie des runtimes, threads, tâches, buffers et clients.
   Borner concurrence, files et volume d'octets, avec ralentissement des producteurs.
3. Définir la propagation explicite des identités et échéances ; vérifier `ContextVar`,
   boucle d'origine et absence de session SQLAlchemy dans une branche native concurrente.
4. Exercer annulation avant départ, pendant calcul, I/O et callback Python, puis shutdown
   et réouverture. Un thread de calcul n'est pas arrêté de force par l'annulation de son attente.
5. Injecter erreur Python, erreur Rust, panic contrôlable et arrêt brutal dans un processus
   de test isolé. Conserver la cause initiale si le nettoyage échoue aussi ; aucun cleanup
   en mémoire ne constitue une preuve de reprise après crash.

**Sortie :** heartbeat Python réactif sous charge, ressources libérées après drainage,
arrêt borné et absence de croissance non bornée sur endurance. Mesurer threads et RSS.
**Arrêt :** aucune extraction de worker si annulation, autorité ou cycle de vie sont ambigus.

### R07 — Migrer un premier worker durable borné

1. Auditer comme candidat le suivi des générations de `app.multimedia` : admission,
   autorisation différée, polling fournisseur, checkpoint et livraison sont liés. Confirmer
   la frontière avant choix ; une petite taille de fichier ne prouve pas l'isolement.
2. Séparer décision native et effets hôtes via un protocole typé de commandes/résultats.
   Les fonctions Python propriétaires des permissions, fichiers et appels LLM restent utilisées.
3. Désigner un seul exécuteur actif pour chaque opération et un seul propriétaire des
   transactions. Ne pas traiter un appel PyO3 et deux connexions DB comme une transaction unique.
4. Tester doublon, deux workers, réponse inversée/tardive, lease expiré, arrêt après effet
   avant reçu, callback répété, révocation et reprise. Une issue inconnue non idempotente
   reste bloquée jusqu'à réconciliation ; aucune promesse d'effet exactement une fois.
5. Basculer un groupe défini d'opérations en développement. Le choix d'implémentation est
   figé pour leur durée ; le retour ne lance pas un second worker sur un run actif.

**Sortie :** parcours complet avec résultats et reçus durables, pannes injectées et mesure
comparative. **Retour :** drainer ou réconcilier les runs selon leur version, puis nouvelles
admissions Python. Conserver les formats et lecteurs nécessaires aux opérations en cours.

### R08 — Démontrer un harnais Rust en conservant Pydantic AI

1. Utiliser le contrat `AgentDriver` existant pour un candidat distinct, expérimental et
   explicitement sélectionné. Garder l'identité et les checkpoints du driver interne actuel.
2. Première expérience : un run Rust appelle un run complet Pydantic AI hébergé en Python.
   Vérifier événements, annulation et ressources ; comptabiliser cette étape comme un pont,
   pas comme une boucle d'agent migrée ou un gain de performance acquis.
3. Deuxième expérience, seulement si utile : une boucle Rust demande des inférences
   élémentaires à un adaptateur Python qui conserve Pydantic AI pour les messages, profils
   et protocoles. Désigner une seule boucle propriétaire des appels d'outils et des retries.
4. Exécuter texte -> outil de lecture -> suite -> résultat unique, puis erreur d'outil,
   JSON invalide, réponse incomplète, interruption, reprise et autorisation différée.
5. Conserver les façades `app.agent`, `app.llm`, `app.tools` et le journal des effets.
   Chaque appel physique reste comptabilisé ; aucune route fournisseur directe de contournement.
6. Réutiliser le testkit de driver. Qualifier d'abord la compatibilité déterministe puis
   un parcours assemblé avec de vrais services et, dans une campagne distincte, fournisseurs.

**Sortie :** faisabilité mesurée de B et liste précise de ce qui reste fourni par Python.
Une expérience texte simple ne qualifie ni les médias, ni la voix, ni les anciens checkpoints.
**Retour :** nouvelles opérations sur le driver Python ; opérations existantes attachées à
leur moteur, version et autorité, sans conversion implicite d'un checkpoint actif.

### R09 — Étendre par groupes de consommateurs

Le registre R00 fixe l'ordre réel après chaque extraction. Ce tableau est une proposition
de vagues ; il couvre aussi les modules qui peuvent rester Python à la destination A/B.

| Vague candidate | Surfaces à inventorier et traiter séparément |
|---|---|
| Infrastructure autonome | Utilitaires purs de `core`, budgets, erreurs et contrats ; adaptateurs Python conservés. |
| Ressources et référentiels | `incident`, `share`, `document`, `dataset`, `memory`, `contact`, `topic`, `storage`, `file_share` ; droits et formats de chaque propriétaire. |
| Outils et intégrations techniques | `tools`, `connection`, `mcp`, `console`, `code`, `browser`, `skill`, `documentation`, `bridge.samba`, `bridge.code_server`, `bridge.harness` ; exécution et autorisations restent dans leurs domaines. |
| Médias et fournisseurs | `multimedia`, `image`, `audio`, `llm` et toutes les entrées de `LLM_PROVIDER_MODULES`, avec profil, auth, transport et comptabilité qualifiés par capacité. |
| Agent et tâches | `agent`, `task`, `goal`, `harness`, `harnesses`, `dream`, `process`, puis les bridges de harnais Hermes/Claude/Codex/DeepSeek et `bridge.n8n`. |
| Conversations et bridges | `messenger`, `conversation`, `chat`, `voice`, Mail/Calendar, Matrix/OneBot/Nextcloud/Telegram/WhatsApp ; journal canonique, médias et curseurs conservés. |
| Composition et administration | `user`, `team`, `authorize`, `params`, `dbadmin`, API/websocket/runtime, `dashboard`, `lab`, `onboarding`, `main.py`, déclarations et surfaces historiques comme `webhook`. |

Pour chaque module : sélectionner une responsabilité, recenser entrants/sortants,
relever la transaction, reprendre les contrats/tests, migrer ses dépendances admissibles,
exercer un parcours complet, mesurer puis retirer l'adaptateur devenu inutile. Un module
peut traverser plusieurs vagues. Les cycles se résolvent par ports ou extraction d'un
ensemble cohérent ; ne pas augmenter les baselines pour forcer la progression.

**Sortie par module :** état `Python`, `mixte`, `Rust avec adaptateur` ou `Rust autonome`,
preuves et dépendances restantes. Aucun pourcentage fondé seulement sur les lignes portées.

### R10 — Remplacer Pydantic AI seulement après une décision séparée

1. Refaire l'inventaire R01 ; vérifier l'ensemble des consommateurs, pas seulement le
   driver expérimental. Évaluer conserver Python, adopter une bibliothèque Rust maintenue
   ou posséder les composants nécessaires ; comparer contrats et coût de suivi upstream.
2. Définir la matrice des capacités réellement prises en charge. Un retrait de capacité
   ou de provider est une évolution produit explicite, jamais une réussite de migration.
3. Remplacer un élément à la fois : représentation portable et historique, validation
   structurée, outils/différés, boucle d'agent, puis adaptation des protocoles/providers.
   Conserver le SDK en Python pour les éléments non encore qualifiés ; ajuster cet ordre
   aux dépendances démontrées, sans double boucle ni doubles retries.
4. Exécuter la matrice de conformité ci-dessous sur chaque capacité, puis sur les parcours
   Task, Goal, texte, voix par tours, Process et Lab qui la consomment.
5. Qualifier l'ancien historique et les checkpoints dans les deux sens si un retour est
   annoncé possible. Garder les versions opaques et leurs lecteurs ; bloquer explicitement
   une reprise incompatible. Ne pas réinterpréter un checkpoint comme une nouvelle mission.
6. Comparer qualité, effets réels, coûts/appels, latences et stabilité. Les essais simulés
   couvrent les branches ; les essais réels qualifient les providers et la qualité sémantique.
7. Retirer `pydantic-ai` du manifest/verrou uniquement après disparition des imports,
   réexports, callbacks et formats encore dépendants, avec recette de l'image finale.

**Sortie :** chaque ligne de la matrice est démontrée ou la dépendance reste maintenue.
Une ADR acceptée doit précéder le changement structurel ; le présent plan n'en tient pas lieu.

### R11 — Porter la persistance et le socle applicatif restant

1. Choisir une stratégie DB qualifiée : accès natifs par domaines, transactions, niveaux
   d'isolation, contraintes, JSONB, vecteurs, notifications, pools et annulation des requêtes.
2. Maintenir d'abord DbAdmin comme unique autorité du schéma public. Si les modèles Python
   sont retirés, concevoir leur source déclarative de remplacement avec `database` et
   `core-dbadmin` ; aucune seconde autorité ni migration SQL manuelle parallèle.
3. Qualifier convergence sur base vide et synthétique existante, datasets, reconcilers,
   grants, historisation, reprise et échecs d'update/install. Ne supprimer les descriptions
   Python qu'après prise en charge de tous leurs objets et données.
4. Porter authentification/RBAC, paramètres, i18n, HTTP, Socket.IO/WebSocket et MCP en
   conservant leurs protocoles : un WebSocket générique ne remplace pas Socket.IO.
5. Rebrancher bootstrap, superviseur, readiness, arrêt et commandes d'exploitation.
   Vérifier les preuves locales d'échec, le rollback et les erreurs de diagnostic elles-mêmes.

**Sortie :** installation et mise à jour réelles sur environnement isolé, mêmes données et
droits, transports compatibles avec le frontend existant. **Retour :** compatibilité de
schéma démontrée ; une ancienne image ne suffit pas à annuler des transformations de données.

### R12 — Retirer Python si la destination C reste justifiée

1. Vérifier que le registre couvre tous les modules actifs, imports différés, scripts,
   outils CLI, contributions d'installation, plugins/skills et formats historiques.
2. Construire une image candidate sans Python. Exercer démarrage, update, index documentaire,
   administration et tous les groupes de consommateurs concernés, avec pannes et reprise.
3. Vérifier les intégrations externes qui peuvent conserver leur runtime propre : les
   inventorier séparément du backend, sans prétendre réécrire Hermes ou n8n dans ce chantier.
4. Faire une qualification combinée des changements cumulés et une répétition du retour
   arrière sur données synthétiques. Les seuls tests ciblés de chaque lot ne suffisent pas.
5. Retirer adaptateurs, descriptions et dépendances Python devenus inutiles, puis actualiser
   ADR, documentation FR/EN, cartes, installation et exploitation.

**Sortie :** backend fonctionnel sans CPython, sans lecteur historique nécessaire manquant,
avec preuve de compatibilité, exploitation et mesure globale. Si cette preuve manque,
conserver A/B et documenter les dépendances restantes.

## Pydantic AI : matrice de remplacement à compléter dès R01

Les liens ci-dessous pointent vers des couvertures existantes à examiner et paramétrer ;
ils ne signifient pas que ces tests sont suffisants ni qu'ils ont été exécutés ici.

| Capacité et risque | Preuve requise avant remplacement | Points d'appui existants |
|---|---|---|
| Construction Chat/Responses et profils | Même sémantique de messages/outils/effort, paramètres retirés ou envoyés, erreurs HTTP, limites et auth ; requêtes réelles des bibliothèques candidates. | `back/app/llm/tests/test_pydantic_ai_utils.py`, `back/tests/test_provider_parameters.py`, bridges providers. |
| Historique et compaction | Rôles, ordre, instructions, fragments, résultats d'outils, références médias, contenu natif et signatures opaques conservés ; aller-retour de l'existant. | `test_agent_history_compaction.py`, `test_local_executor_history.py`, `test_checkpoint.py` dans `app/harness/tests`. |
| Sorties structurées | Schémas et validation métier équivalents : absents/null, unions, nombres, champs supplémentaires, refus/incomplet et retry borné ; aucune sortie invalide acceptée. | `back/app/llm/tests/test_structured_service.py`, `structured_service.py`, `decision_service.py`. |
| Streaming et terminalité | Fragments corrélés, un seul terminal et rien après, absence de faux succès à la fermeture, sortie partielle conservée. | `back/app/agent/tests/test_driver_testkit.py`, `test_executor_streaming.py`, `test_runtime_guards.py`. |
| Outils natifs et MCP | Noms/arguments/résultats/erreurs, contexte et droits réévalués ; découverte filtrée ; identités réutilisées entre tours sans mélange. | `test_tool_discovery.py`, `test_checkpoint.py`, suites `app/tools/tests`. |
| Autorisations différées et compétences | Suspendre avant effet, conserver les arguments exacts, reprendre l'appel approuvé après revalidation ; découverte à la demande et politique eager conservées. | `test_runtime_cancellation.py`, `test_skills.py`, `checkpoint.py`, `skills.py`. |
| Concurrence des outils | Lectures sûres concurrentes, mutations exclusives comme barrière, ordre/résultats stables, aucune session DB partagée. | `test_checkpoint.py` : concurrence sûre, appels en attente et snapshots immuables. |
| Effets, checkpoints et reprise | Journal avant effet, reçu après effet, aucun rejeu aveugle, issue inconnue bloquante, vieux formats traités explicitement. | `test_checkpoint.py`, `test_ssh_checkpoint_recovery.py`, `test_execution_evidence.py`. |
| Annulation et récupération d'appel | Demande distincte de l'arrêt confirmé, transport fermé, effets engagés drainés, budget original conservé et checkpoint durable. | `test_runtime_cancellation.py`, `test_call_recovery.py`, `test_run_control.py`. |
| Budgets, gardes et coûts | Compter tous les appels physiques et retries, plafonds/échéances conservés, détection des boucles, cache et consommation renseignés sans double compte. | `test_runtime_budget_wrapup.py`, `test_runtime_guards.py`, suites usage/inférence de `app.llm`. |
| Multimodal et voix | Pièce jointe seule, historique avec média, octets temporaires bornés, URI canonique, interruption/reprise par tour et priorité voix. | `test_native_media.py`, `test_media_resource_policy.py`, suites `app/voice/tests`. |
| Consommateurs hors harnais | Décisions Dispatcher/Planner, Lab, Tools, providers et façades publiques continuent de fonctionner sans types SDK qui s'échappent. | Imports réels de `app/llm`, `app/lab`, `app/tools`, `bridge/*` et tests de leurs consommateurs. |

La compatibilité du harnais ne suffit pas à retirer Pydantic validation des contrats/API.
Monty et les moteurs externes sont aussi inventoriés séparément ; les remplacer n'est pas
un prérequis implicite de R03–R09.

## Recette minimale de conformité du harnais

Construire cette recette en réutilisant les suites existantes, avec état synthétique et
vérification des effets persistés. Les doubles remplacent les fournisseurs/serveurs externes,
pas le journal, le moteur ou les transactions que l'expérience prétend qualifier.

1. Texte sans outil ; outil de lecture ; deux outils sûrs ; mutation entre deux lectures.
2. Argument invalide puis correction bornée ; erreur d'outil rendue au modèle ; réponse
   fournisseur malformée, tronquée ou interrompue sans succès fictif.
3. Approbation et refus ; révocation avant exécution ; reprise avec les mêmes arguments.
4. Coupure avant effet, après effet avant reçu, après reçu avant événement, puis redémarrage.
5. Annulation pendant inférence, outil, persistance et nettoyage ; réponse tardive d'un
   ancien run ; reprise avec checkpoint historique et version inconnue.
6. Tours réutilisant le même identifiant d'appel ; raisonnement opaque et média conservés ;
   découverte de compétence et d'outil sous droits différents.
7. Conversation simultanée avec Task/Goal/Process ; tour vocal interrompu ; changement
   de contexte ou de droits ; saturation puis récupération des ressources.

Comparer d'abord des réponses externes scriptées identiques pour isoler l'orchestration.
Ensuite apparier et répéter les parcours avec fournisseurs réels, paramètres et budgets
figés. Mesurer réussite métier, effets, coûts et incertitude ; une prose identique ou un
juge LLM seul ne prouve pas la compatibilité. Ne jamais jouer deux fois une mutation réelle
pour comparer les moteurs : clones isolés, réponses enregistrées synthétiques ou simulation
sans effet pour le candidat. Les campagnes réelles sont à planifier séparément.

## Réception, retour arrière et suivi par tranche

Chaque fiche de lot devra contenir : propriétaire métier, hypothèse, interfaces et
consommateurs, dépendances entrantes/sortantes, données et transactions, critères chiffrés
choisis avant mesure, vérification directe, implémentation de retour et formats supportés.

Conditions communes :

- Zéro régression connue sur droits, perte de données, doublon d'effet ou terminalité.
  Toute divergence critique suspend la bascule et exige un diagnostic.
- Parité exacte pour les formats/hashes contractuels ; équivalence métier documentée pour
  les réponses non déterministes, avec limites et couverture explicitement publiées.
- Performance mesurée en build Rust optimisé, conversion et workflow complet inclus,
  conditions identiques, distributions et dispersion ; aucune vitesse présumée du langage.
- Choix du moteur figé par opération ; retour après drainage/réconciliation. Les nouveaux
  checkpoints restent lisibles par le moteur de retour ou leurs runs gardent leur moteur.
- Repli uniquement sur un échec de sélection avant effet démontré. Une exception après
  démarrage natif ne déclenche jamais automatiquement la même opération en Python.
- Réduire les anciennes dépendances et les baselines lorsqu'elles disparaissent ; ne pas
  conserver indéfiniment deux moteurs par commodité. Aucun délai global fiable avant R01–R03.

Exemples de contrôles existants à sélectionner selon le lot :

```bash
make tests ARGS='app/incident/tests'
make tests ARGS='app/harness/tests/test_checkpoint.py app/harness/tests/test_runtime_cancellation.py app/harness/tests/test_call_recovery.py'
make tests ARGS='app/agent/tests/test_driver_testkit.py app/agent/tests/test_driver_boundary.py'
make tests ARGS='app/llm/tests/test_pydantic_ai_utils.py app/llm/tests/test_structured_service.py'
make typecheck
make architecture-check
make docs-prepare
git diff --check
```

Ces commandes sont des exemples ciblés, pas une orchestration à exécuter intégralement
pour chaque lot. Les tests Rust et de liaison doivent être intégrés aux cibles Make à R02.
La validation complète reste réservée à l'utilisateur ; ne pas lancer `make validate`.

Pour ce plan uniquement : revue des liens et cohérence, préparation documentaire et diff.
Aucun comportement utilisateur/navigation ne change ; aucun nouveau parcours FR/EN à créer.
Les parcours et guides seront mis à jour avec chaque changement effectivement réalisé.

## Références externes et limites de l'étude

Sources primaires consultées le 25 octobre 2026 ; leurs pages courantes ne remplacent pas
la vérification des versions retenues lors d'une implémentation :

- [PyO3 — introduction](https://pyo3.rs/main/) : modules natifs Python et construction avec Maturin.
- [PyO3 — parallélisme](https://pyo3.rs/main/parallelism) : détachement de l'interpréteur et limites des accès Python depuis les threads Rust.
- [PyO3 — async](https://pyo3.rs/main/async-await) : interface native encore présentée comme expérimentale dans cette documentation.
- [pyo3-async-runtimes](https://docs.rs/pyo3-async-runtimes/latest/pyo3_async_runtimes/) : pont entre deux modèles de boucles, contexte et durées de vie à qualifier.
- [Pydantic AI — historique](https://pydantic.dev/docs/ai/core-concepts/message-history/) et
  [outils différés](https://pydantic.dev/docs/ai/tools-toolsets/deferred-tools/) : capacités à conserver, pas un format Rust déjà disponible.

La lecture du dépôt établit des couplages et des garanties recherchées. Elle ne démontre
ni un gain de performance, ni une compatibilité PyO3 avec toute la stack, ni l'existence
d'un remplacement Rust équivalent à Pydantic AI. Ces inconnues motivent les portes de
décision précoces et la possibilité de rester durablement hybride.
