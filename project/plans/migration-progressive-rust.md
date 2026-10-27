# Migration progressive du backend vers Rust — piste exploratoire

- Statut : `design`
- Revue des sources : 2026-10-27 ; approfondissement documentaire des alternatives à Pydantic AI.
- Portée : étude d'une migration ascendante par bibliothèque native PyO3.
- Réalisation : aucune migration engagée ; neuf sondes synthétiques Rig exécutées en Docker,
  sans driver Rust intégré, campagne LLM comparative ni benchmark de performance.

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
Aucun framework agentique Rust de remplacement n'est choisi. Rig est le premier candidat
sondé, sans priorité acquise sur ADK-Rust, AutoAgents et Swiftide ; le maintien hybride
reste la référence et une solution de repli.

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
6. Appliquer l'[étude comparative et ses expériences discriminantes](#alternative-à-pydantic-ai--étude-du-27-octobre-2026).
   La recherche et les sondes isolées ci-dessous amorcent R01 ; inventaire exhaustif,
   prototype intégré et qualification restent à réaliser. Un exemple upstream n'est pas
   une preuve Galaris.

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

## Alternative à Pydantic AI : étude du 27 octobre 2026

### Conclusion et niveau de preuve

**Rig reste un candidat à expérimenter ; un remplacement direct de Pydantic AI ne conserve
pas les garanties actuelles.** Neuf sondes exécutables ont confirmé des écarts de validation,
de retry et de reprise décrits ci-dessous. Les fonctions classiques
existent : modèles multiples, outils, historique, streaming, sorties typées et hooks.
L'intérêt supplémentaire est une machine d'exécution sérialisable que l'hôte peut piloter
par étapes. Cela rend le remplacement envisageable sans réécrire tout un SDK.
Voir l'[architecture Rig](https://rig.rs/docs/architecture) et ses
[runs persistables](https://rig.rs/docs/concepts/runs).

La recommandation est de **conserver Pydantic AI comme référence et de ne qualifier Rig
qu'avec une exigence explicite de non-régression**. Sa sélection comme candidat à une
expérience est une appréciation d'adéquation architecturale parmi
les solutions examinées, pas un classement exhaustif des frameworks Rust. Une amélioration
de qualité des réponses, de coût, de vitesse ou de fiabilité doit encore être mesurée.
Le langage ne rend pas le modèle plus compétent : changer le contexte, les schémas ou les
retries peut même dégrader ses résultats avec le même modèle et le même prompt apparent.

Références de version : le checkout verrouille `pydantic-ai` et `pydantic-ai-slim` en
**2.61.0** dans [uv.lock](../../back/uv.lock). La page des
[publications Rig](https://github.com/0xPlaygrounds/rig/releases) présente **0.45.0** comme
dernière version publiée hors préversion, et **0.46.0-rc.1** comme préversion.
L'[API publiée](https://docs.rs/rig/latest/rig/) confirme la façade 0.45.0. Les sondes utilisent
les crates publiées `rig-agent` et `rig-core` **0.45.0**, compilées avec Rust **1.97.1** ;
les fichiers critiques examinés correspondent à la révision
[`98ed06d7f1c911e6e4c7fdb5d690093bc964c514`](https://github.com/0xPlaygrounds/rig/tree/98ed06d7f1c911e6e4c7fdb5d690093bc964c514).
Les guides web évoluent indépendamment
et contiennent encore des exemples 0.44.0 : relever les signatures, features, dépendances
et formats sur la version figée avant tout prototype, sans copier les exemples tels quels.

### Ce que Galaris devrait effectivement remplacer

La dépendance actuelle comprend plusieurs couches, avec des difficultés différentes.
Les surfaces ci-dessous sont constatées dans le code ; cet échantillonnage ne clôt pas
l'inventaire exhaustif de R01.

| Couche | Usage actuel et source | Travail de remplacement |
|---|---|---|
| Boucle d'agent | `PydanticAgent`, hooks, `ToolSearch`, `ProcessHistory`, token d'annulation dans [runtime.py](../../back/app/harness/runtime.py). | Piloter modèles/outils, conserver gardes, budgets, compaction, interruption et sortie unique. Difficulté élevée, mais frontière `AgentDriver` déjà présente. |
| Validation et inférence structurée | `PromptedOutput`, `ModelRetry`, validateurs et contexte durable dans [structured_service.py](../../back/app/llm/structured_service.py) et [output_registry.py](../../back/app/llm/output_registry.py). | Reproduire modes tool/prompted, validation métier et feedback borné. Désérialiser un JSON dans une struct ne suffit pas. |
| Protocoles et profils fournisseurs | Construction Chat/Responses, profils et paramètres dans [pydantic_ai_utils.py](../../back/app/llm/pydantic_ai_utils.py), [protocol_inference.py](../../back/app/llm/protocol_inference.py), [provider_facade.py](../../back/app/llm/provider_facade.py) et les bridges. | Qualifier les requêtes réellement envoyées, authentification, raisonnement, refus, sorties incomplètes, coûts et annulation, pour chaque capacité et route. Risque transversal très élevé. |
| Historique et reprise | Messages SDK, `DeferredToolResults`, identités et versions 1 à 5 dans [checkpoint.py](../../back/app/harness/checkpoint.py). | Conserver l'existant, les parties opaques et les arguments approuvés ; rattacher les reçus au bon tour. Conversion à perte interdite. |
| Compétences et découverte | Capabilities chargées à la demande ou eager dans [skills.py](../../back/app/harness/skills.py), outils MCP filtrés dans le runtime. | Préserver instructions, catalogue autorisé, chargement et révocation. Une liste dynamique d'outils ne démontre pas cette sémantique. |

En revanche, Galaris possède déjà les contrats de driver, les droits, les tâches, les leases,
les décisions de routage et les journaux durables. Ces responsabilités restent dans leurs
domaines ; les fonctionnalités « multi-agent », « mémoire » ou « workflows » d'un framework
ne justifient pas de remplacer `app.task`, `app.memory` ou `app.process`.

Deux dépendances restent séparées : Pydantic validation des API/modèles n'est pas Pydantic AI ;
Monty n'est pas la boucle d'agent. Le [projet Monty](https://github.com/pydantic/monty) est
déjà écrit en Rust et sa [documentation Rust](https://pydantic.dev/docs/monty/quickstart/rust/)
décrit interpréteur et pool de workers. Le checkout l'utilise notamment pour
les computations Process. Étudier la conservation de ce moteur et le remplacement de son
binding hôte avant d'envisager un autre sandbox ; son intégration et ses limites doivent
être qualifiées séparément. Ne pas assimiler exécution de code Python dans ce sandbox et
dépendance du backend à CPython.

### Fournisseurs : partage réel entre Galaris et le SDK

La compatibilité fournisseur n'appartient pas entièrement à Pydantic AI. Le trajet actuel
compose construction SDK et adaptations Galaris :

```text
Agent / appel structuré
  -> modèle Pydantic AI : historique, schéma, construction et décodage
  -> transport interne Galaris
  -> gateway : droits, capacité, politique de paramètres, admission et comptabilité
  -> transport du bridge : authentification et protocole de l'endpoint
  -> fournisseur
```

| Responsabilité constatée | Propriétaire actuel | Conséquence pour Rust |
|---|---|---|
| Choix des paramètres, alias des plafonds, effort et protections des champs fonctionnels | [request_parameters.py](../../back/app/llm/request_parameters.py), appliqué par [proxy_service.py](../../back/app/llm/proxy_service.py). | Réutiliser ces règles et leur corpus ; ne pas les remplacer par les réglages par défaut de Rig. |
| Capacités sur lesquelles ces politiques sont fondées | Bridges, par exemple [OpenAI](../../back/bridge/openai/parameters.py) et [DeepSeek](../../back/bridge/deepseek/parameters.py), qui interrogent les profils Pydantic AI. | Le code d'adaptation est Galaris, mais sa source de capacités reste partiellement SDK. Ne pas supprimer ces imports sans une source qualifiée équivalente. |
| Négociation après rejet explicite d'un paramètre facultatif | `_send_best_effort` dans le proxy ; conservation des budgets/outils/schémas, retrait borné, aucun retry sur flux partiellement reçu. | Conserver la négociation existante ; ne pas ajouter une autre couche de retry payant. |
| Authentification, renouvellement et adaptation d'endpoint | Contrats de `provider_facade.py`, bridges et [transport Codex](../../back/bridge/openai/codex.py). | Garder leur propriétaire, avec le même endpoint et les mêmes droits pendant la comparaison. |
| Complétion des arguments fragmentés Responses | [responses_stream.py](../../back/app/llm/responses_stream.py), appelé par le proxy avant lecture SDK. | Réutiliser cette garantie ; un candidat doit refuser un suffixe terminal contradictoire avant effet. |
| Mappage des messages, schémas, parties natives et lecture des réponses | Modèles Pydantic AI reliés par [pydantic_ai_utils.py](../../back/app/llm/pydantic_ai_utils.py) et `protocol_inference.py`. | C'est cette couche SDK qu'un remplacement doit reproduire, même si le gateway reste inchangé. |

L'ADR 0095 ne transfère donc pas toute la compatibilité au SDK. Elle retire la copie locale
du constructeur/décodeur, tout en conservant le gateway et les bridges. Le test actuel
`test_sdk_inference_composes_with_provider_contract` vérifie justement cette composition.
Un essai Rig doit l'emprunter : remplacer uniquement le client et comparer son comportement
après les mêmes adaptations Galaris, avant d'élargir la migration.

### Options réellement différentes

| Option | Ce qu'elle apporte | Coût ou limite pour Galaris | Position proposée |
|---|---|---|---|
| Rust + Pydantic AI conservé | Migration des règles/runtime sans abandonner les adaptateurs et formats SDK actuels. | Deux runtimes et leur pont ; Python reste nécessaire. | Référence de comparaison ; destination A/B pleinement valable. |
| Rig + adaptateur Galaris | SDK fournisseurs et composants agentiques réutilisables, avec possibilité de piloter l'état par étapes. | Adaptation des contrats durables, profils et historique ; suivi des évolutions de dépendance. | Premier candidat sondé ; à comparer aux autres frameworks ci-dessous. |
| `rust-genai` + boucle Galaris | Client Rust multi-fournisseur, protocoles natifs, outils et streaming. | La bibliothèque se présente comme client ; la boucle, la reprise, les approbations et leurs politiques resteraient à posséder. | Candidat de comparaison si la couche fournisseurs de Rig échoue sur une route importante. |
| Distri | Framework Rust avec agents, skills, outils MCP et orchestration. | Recouvrement plus large avec Galaris ; extraire une simple couche SDK demande une étude spécifique. | Veille, sans l'adopter comme nouveau socle d'orchestration. |
| SDK propres à chaque fournisseur ou HTTP direct | Maîtrise du protocole et des fonctionnalités spécifiques. | Maintenir encodeurs, streaming, profils et compatibilités par fournisseur recrée le coût que l'ADR 0095 cherchait à retirer. | Adaptateur ciblé si nécessaire ; pas de SDK multi-fournisseur maison par défaut. |

Sources primaires pour les deux autres bibliothèques examinées :
[rust-genai](https://github.com/jeremychone/rust-genai) documente son rôle de client et
les réglages d'endpoint/authentification ; [Distri](https://github.com/distrihub/distri)
décrit sa propre orchestration et distingue les licences des composants communs et serveur.
Cette comparaison porte sur l'intégration au dépôt, pas sur leur valeur pour une application neuve.

### Autres frameworks Rust : élargissement de la sélection

La première étude était trop centrée sur Rig. Il existe d'autres frameworks agentiques
Rust, distincts des simples clients de modèles. La revue documentaire du 27 octobre élargit
la sélection ; seuls les neuf comportements Rig décrits plus bas ont été testés localement.
Les fonctionnalités des autres projets sont ici déclarées par leurs sources primaires,
sans preuve d'équivalence, de meilleure qualité ou de maturité suffisante pour Galaris.

| Framework | Périmètre documenté | Intérêt et vérification prioritaire pour Galaris |
|---|---|---|
| [ADK-Rust](https://github.com/zavora-ai/adk-rust/blob/v2.3.0/README.md) | Agents, outils, modèles multiples, sessions, callbacks, graphes avec checkpoints/approbations et voix temps réel. | Candidat à examiner pour la couverture des contrats et la reprise. Vérifier les capacités de la version publiée, l'exécution des validateurs et le feedback des erreurs, sans remplacer les domaines Task/Process de Galaris. |
| [AutoAgents](https://github.com/liquidos-ai/AutoAgents) | Exécuteurs Basic/ReAct, outils et sorties structurées, streaming, mémoire, hooks, orchestration par acteurs et outils WASM ; bindings Python. | Candidat pour une boucle agentique native et une transition Python/Rust. Vérifier validation locale, correction après erreur, états durables, annulation et coût ; les capacités diffèrent selon le fournisseur. |
| [Swiftide](https://github.com/bosun-ai/swiftide/blob/master/README.md) | Harnais agentique, historique, hooks, MCP, approbation humaine, suspension/reprise, graphes typés et pipelines RAG. | Candidat pour des composants adaptables à un hôte Galaris. Vérifier le contrat exact de validation/reprise et la frontière du contexte/exécuteur d'outils. Le projet annonce explicitement des API encore pré-1.0. |
| [Distri](https://github.com/distrihub/distri) | Framework agents/skills/outils/MCP avec son serveur et son orchestration. | Garder dans l'inventaire ; examiner l'extraction des composants sans créer un second propriétaire des tâches, des droits ou des sessions. |
| [LangChain Rust](https://github.com/Abraxas-365/langchain-rust) | Implémentation Rust de l'approche LangChain. | Alternative existante, sans priorité proposée compte tenu du retour utilisateur sur la migration passée. Ce retour Python ne démontre pas à lui seul la qualité de cette implémentation Rust. |

Les API publiées consultées affichent [ADK-Rust 2.3.0](https://docs.rs/adk-rust/2.3.0/adk_rust/),
[AutoAgents 0.4.0](https://docs.rs/autoagents/0.4.0/autoagents/) et
[Swiftide 0.33.0](https://docs.rs/swiftide/0.33.0/swiftide/). Le dépôt courant d'ADK-Rust
annonce déjà une 3.0 candidate non publiée : ne pas attribuer ses nouvelles garanties à la
2.3.0 sans vérification. Un numéro majeur, un nombre de téléchargements ou l'appellation
« production-ready » ne suffit pas à classer la maturité ou la qualité.

[Kalosm](https://github.com/floneum/kalosm) reste une piste distincte pour les modèles locaux,
les médias et la génération contrainte ; son périmètre documenté ne constitue pas une
preuve de remplacement de l'orchestration actuelle. `rust-genai` reste un client à combiner
avec une boucle possédée par Galaris, et non un framework agentique équivalent.

**Sélection proposée, sans vainqueur : Rig, ADK-Rust, AutoAgents et Swiftide.** Examiner
d'abord ADK-Rust sur la validation, le feedback d'erreur et la reprise, puis les contrats
d'AutoAgents et Swiftide, chaque fois sur une version publiée figée. Cette priorité est
un ordre d'investigation, pas un classement de maturité ou de qualité. Ensuite,
adapter les mêmes sondes de validation, feedback, effets et reprise. Comparer l'effort
d'intégration avant de retenir les candidats d'une campagne LLM réelle. Ne pas intégrer
quatre moteurs au produit et ne pas déduire qu'un framework plus large produit de meilleures
réponses. La référence reste Pydantic AI ; l'exigence de non-régression s'applique à tous.

### Rig face aux garanties utiles de Pydantic AI

« Documenté » signifie que l'amorce existe chez Rig, **aucune ligne n'est encore qualifiée
dans Galaris**. L'absence de preuve n'affirme pas qu'une fonctionnalité est impossible.

| Garantie | Point d'appui Rig documenté | Écart ou preuve Galaris nécessaire |
|---|---|---|
| Appel multi-fournisseur | Clients, modèles et transports remplaçables. | Même route, modèle/effort et restrictions ; pas seulement une réponse texte. Ne pas supposer que tous les endpoints compatibles OpenAI ont le même profil. |
| Résultat structuré | `Extractor` et `prompt_typed`, schémas et désérialisation. | Règles Pydantic et validateurs métier, différence absent/null, unions, champs supplémentaires, formats et modes sans outils. |
| Streaming | Événements texte, raisonnement, arguments, résultats d'outils et appels de modèle. | Projection `AgentEvent`, clôture normale, erreur après fragments, contenu provisoire rejeté et absence d'effet sur arguments partiels. |
| Outils et approbation | Hooks avant dispatch ; `AgentRun` peut conserver les appels en attente. | Autorisation durable Galaris, revalidation après accord, arguments inchangés et révocation. L'exemple d'accord en mémoire n'est pas suffisant. |
| Reprise | État sérialisable pilotable par étapes. | Journal avant effet et reçu après effet, leases, crash aux frontières et issue inconnue. Un snapshot ne prouve pas la non-répétition d'un effet. |
| Retry et erreurs | Hooks de retour au modèle, erreurs typées, retries d'extraction. | Budgets séparés outils/sortie, restitution des erreurs et attribution de tous les appels. Le guide des hooks demande un compteur propre pour les retries de réponse. |
| Compétences et grand catalogue | Outils dynamiques et modification de requête par hooks ; intégration MCP. | Reproduire chargement différé/eager et recherche autorisée, sans injecter tous les schémas à chaque tour. Pas d'équivalence établie avec les capabilities actuelles. |
| Historique et médias | Messages, historique et capacités média selon les fournisseurs. | Signatures de raisonnement, blocs opaques, compaction native, pièces jointes seules, références URI et voix interrompue. TTS/STT n'est pas une preuve de parité de la voix temps réel. |
| Tests et supervision | Modèles scriptés, erreurs/fragments simulés, inspection des requêtes ; spans via `tracing`. | Réemployer corpus synthétiques et garanties existantes, corrélation entre runtimes et comptabilité persistée. Une trace ne remplace pas `LLMCall`. |

Sources des capacités : [clients](https://rig.rs/docs/concepts/provider_clients),
[sorties structurées](https://rig.rs/docs/concepts/extractors),
[streaming](https://rig.rs/docs/concepts/streaming), [hooks](https://rig.rs/docs/concepts/hooks),
[MCP](https://rig.rs/docs/integrations/model_context_protocol),
[tests](https://rig.rs/docs/concepts/testing), [médias](https://rig.rs/docs/concepts/media_generation)
et [télémétrie](https://rig.rs/docs/concepts/observability).
Pour la référence Python, voir les [validateurs de sortie](https://github.com/pydantic/pydantic-ai/blob/main/docs/output.md)
et les [budgets de retry](https://github.com/pydantic/pydantic-ai/blob/main/docs/retries.md) ;
les comportements du checkout et de sa version verrouillée restent à relever par les tests.

### Maturité de Rig : constats sur le code et neuf sondes exécutées

La maturité ne se déduit ni du nombre de fournisseurs ni du langage. Le retour utilisateur
sur de meilleurs résultats après LangChain → Pydantic AI fixe une exigence de conservation
de la réussite métier ; il ne constitue pas une mesure comparative avec Rig.

**Indices positifs :** les sources de la révision examinée contiennent des tests de
streaming, de protocoles fournisseurs enregistrés, d'annulation, d'identifiants réutilisés
et de reprise. Les checks GitHub de cette révision indiquent notamment des succès pour les
tests, doctests, conformance et dépendances minimales ; cela atteste ces exécutions upstream,
pas leur adéquation à Galaris. Voir la [CI de la révision](https://github.com/0xPlaygrounds/rig/actions?query=98ed06d)
et sa [définition](https://github.com/0xPlaygrounds/rig/blob/98ed06d/.github/workflows/ci.yaml).

**Stabilité à qualifier :** le [changelog figé](https://github.com/0xPlaygrounds/rig/blob/98ed06d/CHANGELOG.md)
décrit des changements incompatibles des messages, hooks et reprises en 0.43, 0.44 et 0.45,
ainsi qu'une correction de la reprise des étapes en vol dans la dernière version. C'est
une activité de maintenance réelle, avec un coût d'adaptation encore élevé. Un correctif
récent n'est pas une preuve de défaut toujours présent. Le guide web de reprise annonce
encore `RUN_FORMAT=2`, alors que le code testé lit/écrit **5** : la source figée est impérative.

Neuf sondes entièrement synthétiques ont été exécutées contre les crates publiées, sans
réseau à l'exécution finale, sans clés et sans modèle réel. **9/9 réussissent leurs assertions ;
plusieurs assertions démontrent un écart, ce résultat n'est pas un certificat de conformité.**
Le code, le verrou et le résultat local sont conservés sous
`artifacts/rust-migration/2026-10-27/`, hors fichiers versionnés.

| Sonde | Résultat observé | Interprétation pour Galaris |
|---|---|---|
| Schéma avec `minLength=3`, outil `submit` renvoyant `"x"` | L'Extractor accepte `"x"` avec le type `String`, bien que le schéma expose la contrainte. | Schéma annoncé et désérialisation ne valent pas validation locale complète. Une désérialisation personnalisée peut refuser la valeur, mais doit être implémentée et qualifiée. |
| Réponse de mauvais type, puis réponse valide | Le retry typé renvoie le même historique, sans feedback de validation ajouté. | Écart avec la correction guidée actuelle ; la réussite avec réponse scriptée valide ne prouve aucune capacité de réparation du modèle. |
| Outil compteur, réponse finale invalide, retry puis réponse valide | Le compteur passe à **2** : le run recommence et exécute l'outil deux fois. Les messages et `completion_calls` retournés décrivent seulement la tentative acceptée ; le code conserve toutefois l'usage agrégé des tentatives. | Ne pas employer ces retries tels quels avec des effets ; garder aussi les appels et traces des tentatives rejetées dans le journal Galaris. |
| Appel modèle en attente sauvegardé puis restauré | `CallModel` est réémis avec le même numéro de tour. | L'hôte doit rattacher l'inférence durable et contrôler les réponses tardives, le budget et les coûts. |
| Snapshot outil avant effet, crash après effet sans acquittement | Le même appel est réémis ; un hôte naïf fait passer le compteur d'effets à **2**. | La sûreté dépend du journal externe et de la réconciliation. Ce n'est pas un bug propre à Rig : un snapshot seul ne résout pas cette fenêtre. |
| Appel acquitté, puis sauvegarde et restauration | Le run demande le modèle suivant, sans réémettre cet outil. | Protection utile après acquittement sauvegardé ; ne couvre pas le crash précédent. |
| Réponse d'un ancien tour avec identifiant fournisseur réutilisé | Réponse ancienne refusée ; réponse du tour courant acceptée. | Protection présente contre ce mélange de tours, à préserver dans l'adaptateur. |
| Réponse provenant d'un autre run avec mêmes tour, position et identifiant fournisseur | Acceptée si l'hôte la donne au mauvais run. | La corrélation Rig est locale au run ; l'hôte doit imposer identité d'opération, autorité et isolation des files. Ce n'est pas une frontière d'autorisation. |
| Chargement du format précédent | Refus explicite. | Bonne détection ; drainage, lecteur ancien ou migration nécessaires lors d'un changement de format. |

Sources vérifiées : [sorties typées](https://github.com/0xPlaygrounds/rig/blob/98ed06d/crates/rig-agent/src/agent/typed.rs),
[Extractor](https://github.com/0xPlaygrounds/rig/blob/98ed06d/crates/rig-agent/src/extractor.rs),
[contrôle partiel du schéma](https://github.com/0xPlaygrounds/rig/blob/98ed06d/crates/rig-core/src/structured_output.rs),
[état et réémission](https://github.com/0xPlaygrounds/rig/blob/98ed06d/crates/rig-agent/src/run/mod.rs)
et [tests de reprise upstream](https://github.com/0xPlaygrounds/rig/blob/98ed06d/crates/rig-agent/src/run/tests.rs).
Ces différences sont des politiques et responsabilités d'intégration ; elles ne permettent
pas de déclarer Rig inutilisable. Elles interdisent de le présenter comme un remplacement
équivalent sans travail supplémentaire. Aucun résultat comparatif de qualité LLM n'est acquis.

### Architecture candidate : réutiliser Rig et garder les effets dans leurs domaines

```text
app.agent : contrat AgentDriver et sélection d'un seul moteur
    |
adaptateur du harnais Rust : événements, contexte, arrêt et checkpoint versionné
    |
état agentique Rig piloté par un hôte Galaris
    |-- demande de modèle -> app.llm -> adaptateur fournisseur -> transport autorisé
    |-- demande d'outil  -> app.tools -> droits, autorisation, effet et reçu
    `-- état à sauver   -> propriétaire durable actuel -> PostgreSQL
```

Ce dessin est une proposition, pas un nouveau contrat public accepté. Les flèches traversent
PyO3 pour les domaines encore Python ; elles deviennent natives au fil de leur migration.
Le même principe peut être éprouvé dans un worker isolé si la durée de vie du pont devient
le problème dominant, mais cela ajoute protocole et déploiement : aucune nouvelle séparation
en service n'est requise à ce stade.

1. **Une seule boucle.** Choisir soit `AgentRunner` de Rig entouré de hooks, soit l'état
   `AgentRun` piloté par l'hôte. Pour Galaris, étudier d'abord le pilotage par étapes qui
   expose les points de persistance. Ne pas faire tourner simultanément cette boucle et
   celle de Pydantic AI ; R08 peut utiliser le SDK Python pour une inférence élémentaire.
2. **Un seul chemin d'inférence.** Le candidat passe par `app.llm`, avec autorité, échéance,
   admission, corrélation et coût par appel physique. Étudier le transport injectable Rig
   dans cette frontière. Appeler aujourd'hui une route Galaris qui utilise encore
   `protocol_inference.py` démontre l'intégration, pas la suppression de Pydantic AI.
   Un client Rig qui appelle directement Internet contournerait ces garanties.
3. **Des outils soumis au domaine.** Les appels natifs et MCP restent filtrés et exécutés
   par leurs façades ; l'intégration MCP de Rig est un moyen de transport éventuel.
   Elle ne doit pas devenir un deuxième catalogue de droits ni réexécuter les appels
   persistés automatiquement. Les lectures sûres peuvent être concurrentes ; les mutations
   exclusives conservent leur barrière. L'hôte contrôle la planification du lot.
4. **Un contexte explicite.** Autorité de run, agent, demandeur, échéance et jeton d'arrêt
   traversent la frontière comme données typées. Conserver l'injection de dépendances
   nécessaires sans envoyer de session SQLAlchemy ou de secret dans l'état sérialisé.
5. **Des données portables sans perdre le contenu natif.** Définir une enveloppe versionnée
   pour ordre des messages, appels/résultats, références média et blocs fournisseur opaques.
   Ne pas imposer le plus petit format commun texte/rôle. Les lecteurs historiques restent
   disponibles tant qu'un run ou une conversation en dépend.

Rig ne doit pas forcer le stockage Galaris à épouser ses structs internes. Son guide de reprise
demande de reprendre un état avec la même version Rig ; prévoir version de moteur et lecteur
compatibles, drainage ou migration explicitement qualifiée. Une mise à jour Cargo peut donc
avoir un coût opérationnel même si le code appelant compile.

Le [guide d'erreurs Rig](https://rig.rs/docs/concepts/error_handling) distingue les retries
de requête et les corrections de contenu ; il précise qu'un retry du prompt complet
redémarre le run, y compris ses outils. Cet exemple générique ne convient pas aux effets
durables Galaris. Réessayer seulement l'étape admissible sous l'autorité de son propriétaire,
avec les reçus acquis conservés et chaque appel physique compté. Désactiver ou intégrer
les retries implicites de chaque couche pour éviter multiplication des appels et des coûts.

### Les trois difficultés à résoudre avant de parler d'équivalence

**Validation :** `serde` lit/écrit des valeurs ; `schemars` décrit un schéma. Cela ne remplace
pas automatiquement les coercitions, contraintes, validateurs avec contexte et règles métier
Python. Les schémas d'outils MCP sont aussi dynamiques, ils ne deviennent pas tous des structs
compilées. Évaluer un validateur tel que [jsonschema](https://docs.rs/jsonschema/latest/jsonschema/)
pour ces schémas, avec draft, formats, nombres et résolution de références explicités ;
conserver des validateurs métier séparés et un feedback au modèle sous budget. La crate
documente des différences de conformité selon les drafts et des formats à activer :
l'étiquette « JSON Schema » ne garantit pas la parité avec le contrat courant.

**Providers :** conserver le partage de responsabilités décrit plus haut ; ne pas transformer
tous les appels en Chat compatible OpenAI pour faciliter
la migration. Raisonner par route et capacité : Chat, Responses, routage, authentification
avec renouvellement, raisonnement opaque, outils, cache, comptage et refus/incomplet.
L'ADR 0095 confie construction et décodage au SDK, en complément des adaptations Galaris.
Si Rig impose de recopier des
tables locales par famille/version de modèle pour retrouver les garanties, le coût évité
revient dans Galaris : contribuer upstream ou conserver Python est préférable à une parité
apparente. Les capacités officiellement documentées ne qualifient pas nos bridges spécifiques.

**Reprise :** conserver un checkpoint n'est pas savoir si un effet a eu lieu. Pour une écriture,
le moteur sauvegarde l'intention avant départ, puis le reçu après effet. Un crash entre les
deux exige la réconciliation du domaine, pas un nouvel appel aveugle. La clé d'appel tient
compte du tour et de la réponse : les fournisseurs peuvent réutiliser un identifiant d'outil.
Les tests actuels couvrent déjà ces cas, les résultats parallèles, les erreurs acquittées
et les arguments différés ; ils constituent les premiers scénarios à adapter.

### Reprise : protocole d'hôte à qualifier, au-delà de la sérialisation

Le code Rig précise qu'un appel modèle réémis porte le même tour, que ses réémissions
ne consomment pas de tour supplémentaire et qu'une réponse tardive de l'appel précédent
n'est pas distinguable par cet état seul. Les appels n'ayant pas atteint l'enregistrement
du résultat peuvent aussi manquer à l'usage Rig. `max_turns` ne remplace donc ni le budget
d'inférence ni la corrélation de Galaris.

| Point d'interruption | Reprise exigée du candidat Galaris |
|---|---|
| Modèle demandé, inférence déjà admise ou en vol | Rattacher l'identité durable existante et relire son journal ; ne pas créer une seconde inférence parce que Rig réémet `CallModel`. Toute nouvelle tentative suit le contrat LLM existant et conserve son coût. |
| Approbation en attente | Garder outil, arguments exacts et identité d'autorisation ; aucun effet avant décision durable. Au départ, revalider droits, portée et lease courants. |
| Intention d'outil sauvegardée, effet non commencé | Vérifier que le journal autorise encore le départ avant exécution ; le simple état `Execute` de Rig n'est pas une autorisation. |
| Effet possible, reçu absent | Réconcilier dans le domaine propriétaire. Réexécution limitée aux garanties de lecture/idempotence déjà déclarées ; sinon issue inconnue bloquante. |
| Reçu présent, réponse outil absente de l'état Rig | Réinjecter le résultat acquis sans réexécuter l'effet, puis sauvegarder l'avancement. |
| Ancienne autorité ou réponse tardive | Refuser son application au run courant ; conserver une preuve tardive via la réconciliation propriétaire sans réautoriser l'ancien worker. |
| Résultat terminal acquis, fermeture du stream retardée | Respecter la validation commune du driver et la fermeture bornée ; aucun deuxième succès ni événement post-terminal. |

Enveloppe d'hôte à concevoir : identité du run et de l'inférence/effet durable, génération
d'autorité, moteur/version, tour, position, identifiant fournisseur, empreinte des arguments
et révision du checkpoint. Les identités de tour de Rig complètent cette enveloppe sans
la remplacer. Les écritures qui appartiennent à une même transaction restent atomiques ;
un effet distant et son reçu ne sont pas rendus atomiques par PyO3 ou une struct Rust.

Les sondes sur le crash avant acquittement et sur les deux runs démontrent pourquoi ces
gardes sont nécessaires. Le protocole n'a pas été implémenté ni éprouvé sur deux workers,
sur des leases PostgreSQL ou sous arrêt brutal du backend Rust. Ces preuves restent des
conditions bloquantes de R08/R10.

### Non-régression : comportement, réussite métier et décision de bascule

La demande est **aucune régression**. Le plan n'autorise ni baisse de qualité compensée par
un gain de mémoire, ni retrait discret d'une fonctionnalité. Un écart volontaire devient
une décision produit séparée. Une campagne finie ne démontre pas l'absence de tout défaut ;
un résultat inconclusif ne permet pas la bascule.

1. **Référence actuelle vérifiée.** Les suites existantes de paramètres fournisseurs,
   d'inférence structurée, de checkpoints et d'annulation ont été exécutées : **1 032 tests
   réussis**, avec huit avertissements de dépréciation. Elles vérifient le backend actuel,
   pas Rig. Le scénario structuré `count=0 → 2 → 3` conserve le feedback métier, les trois
   appels et leur coût ; ce comportement devient une exigence du candidat.
2. **Conformité déterministe avant qualité.** Fournir les mêmes réponses externes scriptées
   aux deux moteurs, avec vrais validateurs, journaux et droits. Comparer acceptation et
   rejet, coercitions utiles, valeurs absentes/nulles, aliases, unions, nombres, contexte
   métier, arguments d'outils et erreurs. Une validation plus stricte qui rejette un ancien
   cas accepté peut aussi être une régression. Aucune sortie structurée invalide ni effet
   non autorisé, doublé ou attribué à un autre run n'est admissible.
3. **Réparation guidée à restaurer.** Une erreur doit revenir au modèle avec son contexte
   et son budget, sans redémarrer les effets acquis. Les hooks de Rig offrent des points
   d'extension ; l'équivalence de ces politiques n'est pas implémentée. Ne pas confondre
   `TypedRun.retries(n)` et ce contrat de correction.
4. **Campagne de qualité appariée.** Réutiliser le Lab et les cas synthétiques conversation,
   Dispatcher/Planner, Goal, outils, recherche, documents, médias et refus. Figer modèle,
   endpoint, effort, paramètres, capacités, données et budgets, puis alterner l'ordre des
   essais et répéter. Garder une réserve de cas indépendante pour éviter de qualifier les
   seuls exemples ayant servi à adapter le candidat.
5. **Résultats à examiner par famille.** Vérifier les effets et le livrable réel, les faux
   succès, omissions, capacité à corriger un outil, appels inutiles et coût par réussite.
   Conserver les paires où Pydantic AI réussit et Rig échoue ; une moyenne globale ou un
   juge LLM unique ne peut pas masquer ces pertes. Relecture à l'aveugle des sorties et
   désaccords, en séparant variation du candidat et variation du juge.
6. **Décision explicite sur les preuves.** Figer avant campagne un effectif et une analyse
   appariée adaptés aux écarts à détecter ; documenter l'incertitude et les cas discordants.
   Aucune marge de baisse de qualité n'est accordée par ce plan. Zéro nouvelle régression
   connue dans le corpus et absence de dégradation étayée sont nécessaires ; une absence de
   différence statistiquement détectée n'est pas une preuve d'équivalence. Tant que les
   conditions ne sont pas remplies, conserver Pydantic AI.

Les comparaisons réelles et les parcours assemblés du candidat restent à réaliser. Les
sondes hors réseau ne mesurent ni l'intelligence des agents ni la fidélité d'un fournisseur
réel. Le [plan Lab](lab-evaluation-mecanismes-ia.md) conserve les limites de comparabilité
et de jugement ; aucun benchmark upstream ne remplace cette qualification Galaris.

### Expériences R01 à plus forte valeur de décision

Ces expériences restent à réaliser dans un environnement Docker isolé après qualification
de l'outillage R02/R06 nécessaire ; on peut préparer leur corpus dès R01. Elles n'autorisent
ni bascule du harnais actuel ni campagne fournisseur payante.

| Étape | Expérience bornée | Preuve et conséquence attendues |
|---|---|---|
| R01-a — requêtes et validation | Figer Pydantic AI 2.61.0 et une version Rig ; utiliser vrais encodeurs/décodeurs avec transport externe simulé. Comparer Chat et Responses, noms de modèle opaques, effort retiré, outil, sortie structurée, 429, refus et flux tronqué. | Produire les différences sémantiques de requêtes/résultats et le nombre d'appels ; une bibliothèque qui répond « bonjour » ne passe pas cette porte. Conserver la route Python si un profil critique manque. |
| R01-b — effet et accord | Même scénario synthétique : lecture, écriture soumise à accord, refus/révocation, redémarrage après effet avant reçu, identifiants réutilisés. Vrais journaux et transactions Galaris, seule frontière externe remplacée. | Zéro écriture non autorisée ou doublée ; arguments exacts à la reprise, issue incertaine bloquée. Choisir pilotage par étapes ou runner sur cette preuve. |
| R01-c — contexte historique | Corpus de checkpoints versions 1 à 5, raisonnement signé synthétique, média seul, compaction et compétence eager/différée. Réouvrir conversation et run avec contexte/droits modifiés. | Chaque élément est conservé, transformé sans perte démontrée ou explicitement non reprenable ; aucun effacement silencieux. Mesurer la nécessité de conserver les lecteurs Python. |
| R01-d — parcours et coût total | Relier le candidat au testkit de driver, puis Task, texte et consommateurs structurés ; étendre ensuite à Goal, Process, Lab et voix. Comparaison scriptée puis campagne réelle distincte. | Vérifier succès métier et droits avant CPU/RSS, p95 et coût par réussite ; publier la couverture restante et l'effort d'adaptation/upstream. Choisir A/B/C sur ces résultats. |

Réutiliser notamment `test_checkpoint.py` (effets, identités et concurrence),
`test_runtime_cancellation.py` (reprise d'accord et interruption),
`test_structured_service.py` (modes et coût) et `test_driver_testkit.py` (contrat de stream).
Les suites checkpoint/annulation et l'intégration structurée ont été exécutées sur le
backend actuel ; le testkit de driver reste ici un point d'appui inspecté. Aucun de ces
résultats ne qualifie un driver Rig intégré.
À chaque nouvelle capacité, compléter la matrice ci-dessous et le registre des consommateurs.

### Peut-on faire aussi bien, voire mieux ?

| Axe | Conclusion raisonnable aujourd'hui | Condition pour revendiquer un progrès |
|---|---|---|
| Capacités d'un agent classique | Rig couvre les briques usuelles ; alternative crédible. | Qualification des capacités Galaris réellement utilisées, sans perte masquée. |
| Qualité des réponses et réussite | Aucun avantage du langage établi ; contexte et protocole peuvent changer le résultat. | Campagne appariée, même modèle, paramètres, budgets et cas, avec effets vérifiés. |
| Concurrence et ressources | Possibilité de mieux contrôler état, propriété des données et allocations côté Rust. | Mesures bout en bout, pont compris, saturation et endurance ; les races DB restent à traiter. |
| Reprise et contrôle | Machine par étapes intéressante pour exposer les décisions et points de sauvegarde. | Pannes injectées avec journal d'effets et autorité réels ; davantage qu'un état sérialisable. |
| Déploiement | Un backend sans CPython devient envisageable à C. | Toutes les dépendances et données qualifiées ; A/B gardent le coût du double runtime. |
| Maintenance | Réutiliser Rig évite de posséder tout un SDK ; coût d'adaptation encore inconnu. | Suivre au moins une mise à jour upstream, son diff de protocole et la reprise des états sauvegardés. |

La valeur la plus plausible est donc **un meilleur contrôle du runtime et des ressources**,
à confirmer. Accélérer le code local ne réduit pas le temps de génération chez le fournisseur ;
mesurer séparément attente réseau/modèle, outils, DB et orchestration avant de choisir les lots.
Sans bénéfice démontré ou si la parité impose trop de code de compatibilité, conserver
Pydantic AI avec un noyau Rust reste la conclusion technique recommandée.

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

Pour ce plan : revue des sources et de la cohérence, neuf sondes Rig isolées et suites
Galaris ciblées ci-dessus, préparation documentaire et diff.
Aucun comportement utilisateur/navigation ne change ; aucun nouveau parcours FR/EN à créer.
Les parcours et guides seront mis à jour avec chaque changement effectivement réalisé.

## Références externes et limites de l'étude

Sources primaires du plan initial revues les 25–27 octobre 2026 ; leurs pages courantes ne remplacent pas
la vérification des versions retenues lors d'une implémentation :

- [PyO3 — introduction](https://pyo3.rs/main/) : modules natifs Python et construction avec Maturin.
- [PyO3 — parallélisme](https://pyo3.rs/main/parallelism) : détachement de l'interpréteur et limites des accès Python depuis les threads Rust.
- [PyO3 — async](https://pyo3.rs/main/async-await) : interface native encore présentée comme expérimentale dans cette documentation.
- [pyo3-async-runtimes](https://docs.rs/pyo3-async-runtimes/latest/pyo3_async_runtimes/) : pont entre deux modèles de boucles, contexte et durées de vie à qualifier.
- [Pydantic AI — historique](https://pydantic.dev/docs/ai/core-concepts/message-history/) et
  [outils différés](https://pydantic.dev/docs/ai/tools-toolsets/deferred-tools/) : capacités à conserver, pas un format Rust déjà disponible.

Les sources Rig, rust-genai, Distri, Monty et validation sont liées directement dans
l'étude comparative du 27 octobre. Les capacités déclarées et exemples upstream servent
à sélectionner une expérience ; ils ne constituent pas des résultats sur Galaris.

La lecture du dépôt établit des couplages et des garanties recherchées. Elle ne démontre
ni un gain de performance, ni une compatibilité PyO3 avec toute la stack, ni l'existence
d'un remplacement Rust équivalent à Pydantic AI. Ces inconnues motivent les portes de
décision précoces et la possibilité de rester durablement hybride.
