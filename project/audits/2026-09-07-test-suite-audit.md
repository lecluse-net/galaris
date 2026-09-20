# Audit de la pertinence de la suite de tests — 7 septembre 2026

Suite à la demande de mise en œuvre : [changements, traçabilité et validations](2026-09-07-test-suite-improvements.md).
Le présent audit conserve ses constats et résultats historiques.

La suite possède un socle utile, notamment sur les permissions, la persistance, les reprises après incident et les courses concurrentes. Le principal investissement à faire concerne les tests frontend qui inspectent du texte source pour prétendre vérifier une interaction ou un rendu. Leur faiblesse a été reproduite par mutation : certains acceptent une régression, d'autres refusent un changement équivalent.

Les suppressions immédiatement justifiables restent modestes : **un test automatisé vide de comportement et trois copies redondantes**. Les tests de bridges avec transports simulés restent utiles à leur niveau. Ils ne constituent toutefois pas une preuve de fonctionnement avec un service distant réel.

## Périmètre et méthode

Le **Lab est exclu du périmètre sur demande de l'utilisateur**, car il est en cours de réécriture. Ses résultats n'entrent pas dans les recommandations ou les bilans ci-dessous.

L'inventaire initial hors Lab couvre **501 fichiers candidats, dont 496 contenant des définitions de tests**, et **3 284 définitions** : 2 884 Python et 400 JavaScript, avant expansion des paramètres. Deux définitions Python sont des diagnostics manuels exclus de pytest. Le frontend représente 367 définitions ; les autres tests JavaScript concernent le browser-executor et les scénarios E2E.

L'analyse combine inventaire AST de toutes les définitions, recherche de doublons et d'oracles suspects, lecture ciblée des tests et du code exercé, vérification des fixtures et de la découverte CI, exécution des principales suites et expériences de mutation. L'« oracle » désigne ce qui permet au test de distinguer un résultat correct d'une régression.

**L'inventaire est exhaustif pour la copie de référence ; la revue sémantique approfondie est ciblée.** Les lignes « conserver provisoirement » ne sont pas des certifications individuelles. Une classification fondée sur le nombre d'assertions, le nombre de mocks ou le seul résultat vert serait trompeuse. Les cas suffisamment examinés et les défauts démontrés sont distingués dans les colonnes `profondeur`, `motif` et `constat`.

Livrables :

- [Index de tous les fichiers et décisions](2026-09-07-test-suite-evidence/inventaire-fichiers.md).
- [Inventaire par test, avec oracle et résultat](2026-09-07-test-suite-evidence/inventaire-tests.csv).
- [Inventaire des fichiers et empreintes](2026-09-07-test-suite-evidence/inventaire-fichiers.csv).
- [Résultats détaillés des exécutions](2026-09-07-test-suite-evidence/resultats.json).
- [Preuves des mutations](2026-09-07-test-suite-evidence/mutations.json).
- [Dispositifs opérationnels et diagnostics hors inventaire des définitions](2026-09-07-test-suite-evidence/dispositifs-hors-inventaire.md).
- [Delta intervenu pendant l'audit](2026-09-07-test-suite-evidence/delta-fin-audit.md).

La référence initiale est une copie du répertoire de travail, incluant ses modifications non commitées, sur HEAD `15881f3c9368c55744db22486dd1022d81504bbb`. Les essais utilisent des conteneurs, des données synthétiques et des bases éphémères. Les mutations sont faites dans des copies jetables. Aucun test ni code applicatif n'a été modifié par cet audit. Le second inventaire hors Lab porte sur **503 fichiers candidats et 3 293 définitions**, soit neuf définitions supplémentaires ; elles sont détaillées dans le delta.

Le dépôt a évolué pendant l'analyse. Les résultats ci-dessous appartiennent à la copie initiale ; le delta est examiné séparément. Les nouveaux tests frontend et de conversion réussissent, ainsi que le scénario DbAdmin à 100 000 lignes.

## Résultats exécutés sur la référence initiale

| Suite | Résultat | Durée de la suite, hors préparation |
|---|---|---:|
| Backend, PostgreSQL éphémère, hors Lab | 3 308 réussis, 1 échec, 1 ignoré | 158 s |
| Frontend Node, hors Lab | 391 réussis | 43,7 s |
| Browser-executor | 17 réussis | 24,1 s |
| SSH executor | 9 réussis | 0,55 s |
| Harness manager | 26 réussis | 4,2 s |
| E2E, Chromium / Firefox / WebKit | 48 réussis : 16 scénarios × 3 navigateurs | environ 2,9 min |
| Mutations backend existantes | Référence valide ; 4 mutations détectées sur 4 | — |

Soit **3 801 cas exécutés dans les six suites principales hors Lab**, sans compter les relectures ciblées et les mutations. Le nombre de cas diffère du nombre de définitions à cause du paramétrage et des navigateurs. Les durées correspondent aux commandes complètes ; les cas Lab ont été retirés du bilan. Les scénarios E2E partagés restent comptés, mais leurs éventuelles sous-étapes Lab ne font pas l'objet d'une conclusion.

L'échec backend hors Lab concerne un test dépendant du fuseau local. Il échoue avec `TZ=UTC`, puis réussit avec `make TZ=Europe/Paris tests ...`. Le cas ignoré est la qualification DbAdmin explicitement activée par `DBADMIN_LOAD_TEST`, ensuite exécutée avec succès sur la deuxième copie.

Le premier essai frontend utilisait un ancien `node_modules` de l'hôte, incomplet. Il a été écarté et remplacé par une exécution avec les dépendances du frontend actif montées en lecture seule. Les quatre erreurs de cet essai de préparation ne sont pas des anomalies applicatives.

Les répétitions E2E `--repeat-each=3` configurées en CI n'ont pas été reproduites ici. Les qualifications upgrade/release et les contrôles statiques indépendants n'ont pas été exécutés dans cet audit ; leurs scripts et leurs déclenchements ont été examinés. Les résultats complémentaires de restauration et de charge figurent dans le delta. Aucun taux global de couverture ni taux global de résistance aux mutations n'a été mesuré.

## Constats et décisions

### A01 — Un test ne vérifie aucun comportement

[`test_closed_choice_ignores_non_matching_text`](../../back/app/messenger/tests/test_interactions.py), ligne 275 dans la référence, appelle seulement `await _reset_for_tests()`. Il ne crée aucun choix, n'envoie aucun texte et n'appelle pas le mécanisme de résolution.

**Décision : réécrire ce test.** Créer un choix fermé, soumettre un texte non reconnu, puis vérifier que le choix reste en attente et qu'aucune résolution n'est émise. Si ce scénario est abandonné, supprimer cette définition vide. Ajouter simplement `assert True` ne lui donnerait aucune valeur.

Les 17 autres définitions Python sans assertion directement repérée ne sont pas assimilées à ce cas : deux sont manuelles, et les autres vérifient notamment qu'une entrée autorisée ne déclenche pas d'exception. Les helpers E2E contiennent aussi des assertions que le corps appelant ne répète pas.

### A02 — Priorité élevée : remplacer les preuves d'interface fondées sur des regex

**201 des 367 définitions frontend sont des candidates à contrôle de sources seules**, repérées par leurs appels. Ce nombre inclut des conventions statiques légitimes : ce n'est pas un compte de tests inutiles. Après distinction des conventions et de quelques tests mixtes, l'inventaire recommande de renforcer ou remplacer l'oracle de **191 définitions frontend**.

Trois expériences donnent une preuve concrète :

| Test | Modification dans une copie | Résultat | Ce que cela établit |
|---|---|---|---|
| [`themePageBackground.test.mjs`](../../front/core/themePageBackground.test.mjs) | `rgb(250, 250, 250)` devient `#fafafa` | Échec | Faux signal pour une couleur équivalente |
| [`skillActionLayout.test.mjs`](../../front/app/skill/skillActionLayout.test.mjs) | Une règle finale impose `flex-wrap: wrap !important` | Réussite | Le contrôle ne détecte pas la régression de CSS |
| Test « home cards are hidden… » de [`homePage.test.mjs`](../../front/app/index/homePage.test.mjs) | Déplacement du `v-if="canReadChat"` dans un commentaire ; carte sans directive | Réussite | Une présence textuelle ne prouve pas la condition d'affichage |

Pour le deuxième cas, Chromium confirme sur un élément de test utilisant ces styles que les valeurs calculées passent de `nowrap/nowrap` à `wrap/normal`. Cette vérification porte sur le CSS effectif, pas sur le montage complet de la page Vue. Le troisième cas concerne la visibilité d'une carte ; il ne démontre pas un contournement de l'autorisation backend.

Autres concentrations à traiter :

- [`pageScroll.test.mjs`](../../front/app/chat/pageScroll.test.mjs) : 13 définitions, dont une exige le texte exact d'un commentaire. Aucun navigateur ne calcule ici le défilement.
- [`documentEditorReuse.test.mjs`](../../front/app/memory/documentEditorReuse.test.mjs), [`goalHierarchy.test.mjs`](../../front/app/goal/goalHierarchy.test.mjs) et [`scheduleOwnership.test.mjs`](../../front/app/goal/scheduleOwnership.test.mjs) : de nombreuses assertions de structure ne démontrent pas les interactions annoncées.
- [`unreadNotifications.test.mjs`](../../front/app/chat/unreadNotifications.test.mjs) : la présence d'un abonnement dans le code ne prouve pas la réception d'une notification en arrière-plan.
- Tests de modales, de tableaux et de présentation : les noms de classes, couleurs et enchaînements de lignes figent souvent l'implémentation.

**Décision : remplacer progressivement les oracles, en commençant par les droits visibles, les réponses asynchrones périmées, les dialogues et la pagination.** Exécuter les fonctions ou composables pour l'état ; monter le composant pour les événements et le DOM ; utiliser le navigateur pour les styles calculés, le défilement et le responsive. Ne pas transférer chaque assertion regex dans un scénario E2E coûteux.

Les fichiers mixtes doivent être traités test par test. Par exemple, les tests qui exécutent `compactStreamingTail`, `currentAIResponse` ou `shouldAnimateTaskStatus` restent pertinents, même si leurs fichiers contiennent aussi des inspections de sources. Le chargement d'un module TypeScript complet avec dépendances substituées constitue un véritable test unitaire ; l'extraction d'une expression par regex est plus fragile.

### A03 — Trois doublons exacts peuvent être fusionnés

Les corps AST sont identiques hors docstring ; les fixtures et contextes de classe ont été relus :

| Fichier | Paire | Décision |
|---|---|---|
| [`core/params/tests/test_router.py`](../../back/core/params/tests/test_router.py) | `test_read_params_logic` / `test_read_params_list_logic` | Garder un seul scénario `read_params()` |
| [`core/params/tests/test_services.py`](../../back/core/params/tests/test_services.py) | `test_get_triggers_load` / `test_get_existing_param` | Fusionner ou différencier explicitement chargement initial et lecture du cache |
| [`core/util/tests/test_yaml.py`](../../back/core/util/tests/test_yaml.py) | `test_load_empty_file` / `test_empty_yaml_file` | Garder un seul test de fichier vide |

Supprimer trois copies réduit peu le temps total. Le gain est surtout de rendre l'intention et la maintenance plus claires. Les tests voisins de valeurs par défaut, de masquage des secrets et de cache ont une utilité distincte.

### A04 — Des oracles ou scénarios à préciser

Dans [`test_yaml.py`](../../back/core/util/tests/test_yaml.py), `test_substitute_nested_braces_not_supported` annonce des accolades imbriquées mais utilise uniquement `${VAR}`. Introduire une entrée réellement imbriquée et le résultat attendu, ou fusionner avec le scénario d'interpolation ordinaire.

Dans [`test_multimedia.py`](../../back/app/multimedia/tests/test_multimedia.py), `test_live_mcp_catalog_and_execution_follow_profile_and_connection` accepte une `Exception` correspondant à plusieurs motifs (`not authorized`, `not found`, `Unknown tool`). Le scénario de refus est pertinent, mais peut réussir pour une mauvaise raison. Préciser le type ou code attendu et vérifier l'absence d'appel au fournisseur.

Dans [`test_run_control.py`](../../back/app/harness/tests/test_run_control.py), `test_cancel_is_idempotent_after_run_completion` appelle une seule fois `cancel(uuid4())`. Cela vérifie la tolérance à un identifiant absent, mais ne crée ni exécution terminée ni double annulation. Renommer ce petit contrat ou compléter le scénario annoncé, en vérifiant notamment que le nettoyage n'est pas rejoué.

Les petits tests de constructeurs, tags de route et attributs constants ont une priorité de consolidation faible. Les supprimer systématiquement serait excessif : certains protègent un contrat de compatibilité ou une valeur de sécurité par défaut.

### A05 — Un test pertinent est dépendant de l'environnement

[`test_linked_work_filters_and_orders_tasks_by_operational_recency`](../../back/app/conversation/tests/test_service.py) vérifie un ordre et une borne de longueur utiles, mais impose `2026-08-20T14:00+02:00` alors que le code sérialise dans le fuseau du processus. `.env.example` définit `TZ=UTC`.

**Décision : conserver et rendre déterministe.** Tester séparément l'ordre et la présentation des dates ; fixer explicitement le fuseau pour le contrat de présentation, ou comparer des instants normalisés si l'offset n'est pas une exigence. La commande de reproduction Paris doit passer `TZ` comme variable Make, car le `.env` est inclus par le Makefile.

### A06 — Un test d'outillage concentre presque toute la durée frontend

[`typecheck-gate.test.mjs`](../../front/scripts/typecheck-gate.test.mjs) prend environ **43,07 s sur 43,72 s**. Il injecte des erreurs TypeScript et relance les outils pour vérifier qu'ils les rejettent. C'est un garde-fou utile sur le périmètre de compilation.

**Décision : le conserver dans la validation de l'outillage, en dehors de la boucle unitaire rapide si son coût gêne le développement.** Il ne remplace pas le typecheck normal du produit. Même logique pour éviter les doublons d'exécution entre build, typecheck et couverture : mutualiser quand les mêmes preuves peuvent être conservées.

Les tests backend les plus lents vérifient notamment WebRTC réel, saturation, recherches SQL volumineuses et transitions DDL. Leur durée seule ne justifie pas leur retrait.

### A07 — Les tests de bridges prouvent surtout le contrat local

Les tests de Matrix, Telegram, WhatsApp, Nextcloud, OneBot, mail, n8n, des harnais et des fournisseurs LLM/médias exercent des niveaux différents : traduction de messages, payloads et erreurs HTTP, routage, autorisation, configuration, retries ou cycle d'exécution.

**Décision : conserver ces contrôles lorsqu'ils exercent l'adaptateur réel et vérifient ses entrées/sorties.** Un `httpx.MockTransport` n'est pas un test vide : il peut détecter une mauvaise URL, un en-tête manquant, un payload incorrect ou un mauvais traitement d'erreur. À l'inverse, il ne détectera pas une incompatibilité avec un serveur distant que la réponse simulée ne représente pas.

La suite locale ne certifie donc ni l'inscription d'un compte réel, ni une session durable auprès du fournisseur, ni l'ensemble des interactions disponibles chez lui. L'audit n'a utilisé aucun compte externe et n'a envoyé aucun message. L'inventaire marque explicitement cette frontière ; aucun dispositif supplémentaire de comptes ou de plateforme de qualification n'est installé ici.

### A08 — Les évaluations déterministes ne mesurent pas toute la qualité IA

[`test_agentic_evals.py`](../../back/app/agent/tests/test_agentic_evals.py) utilise des réponses contrôlées. Les évaluations de mémoire et de rappel comprennent aussi des données ou représentations synthétiques. Elles vérifient utilement le pipeline, les contrats de sortie, les règles de sélection et l'isolation.

**Décision : conserver en précisant leur portée.** Un score parfait sur ces scénarios ne mesure pas la pertinence générale des décisions, résumés ou réponses d'un modèle réel. Les tests de prompts protègent certaines instructions, mais leur présence textuelle ne démontre pas que le modèle les suivra.

### A09 — Les fixtures définissent la portée réelle des tests de persistance

Les fixtures backend usuelles partagent souvent une connexion avec transaction de test et savepoints. Elles conviennent aux services et API isolées, mais ne prouvent pas à elles seules les courses entre transactions. Les fixtures dédiées de concurrence utilisent des connexions indépendantes : elles doivent rester distinctes.

Le client ASGI ordinaire ne prouve pas non plus le démarrage complet avec lifespan et workers ; les E2E réels apportent cette couche sur les parcours qu'ils exercent. Une fixture historique complète automatiquement le manager humain de certains objets `Agent`. Elle simplifie les anciens tests mais peut masquer une construction ORM incomplète ; les tests explicites du manager requis et du chemin public restent nécessaires.

**Décision : conserver les différentes couches en nommant leur portée.** Ne pas attribuer à un appel direct de service la garantie d'un parcours HTTP autorisé, ni à une transaction partagée la garantie de concurrence entre deux processus.

### A10 — Les contrats statiques restent utiles quand la structure est l'exigence

Les frontières de modules, l'enregistrement des routes, la cohérence des catalogues, les contraintes de déploiement et les règles d'autorisation peuvent légitimement être vérifiés statiquement. Les tests d'outillage qui injectent une faute et exigent son rejet ont aussi un oracle utile.

**Décision : conserver ces contrats et privilégier AST, configuration parsée ou modèle compilé lorsque cela évite la dépendance aux commentaires et au formatage.** Le seuil de couverture de `coverage-critical.ini` est de 70 % sur un sous-ensemble agrégé, avec branches activées. Ce n'est ni une couverture globale de l'application, ni un minimum garanti par bridge ou par module. Les quatre mutations backend couvrent quatre garde-fous choisis ; elles ne constituent pas un score général de mutation.

### A11 — Séparer diagnostics manuels et garanties automatisées

`back/tests/manual/test_message_history.py` contient deux essais avec affichage de résultats ; `back/tests/manual/test1.py` ne contient qu'un `main()` vide. Les contrôles de connexion des managers sont des diagnostics opérationnels. `front/core/util/model3d.browser.mjs` comporte une vraie vérification navigateur, mais n'est pas collecté par `node --test` ni par les specs E2E habituelles.

**Décision : supprimer éventuellement le squelette manuel vide, conserver les diagnostics utiles sous une désignation explicite et raccorder le scénario 3D à l'E2E ou à une cible dédiée si sa protection automatisée est attendue.** Sa commande manuelle est déjà documentée en tête de fichier. Ne pas compter sa présence dans le dépôt comme un succès de CI.

## Ce qui mérite d'être préservé et ce qui manque

| Domaine | Preuves fortes observées | Limite ou suite à donner |
|---|---|---|
| Autorisations, sessions, secrets | Refus, redaction, rotation et courses de rafraîchissement ; connexions DB indépendantes | Préserver les tests de refus ; les regex de boutons ne remplacent pas les contrôles API |
| Tâches, goals, conversations, process | Transitions, leases, idempotence, reprise, double démarrage, effets persistés | Conserver les scénarios de panne et d'expiration ; élargir les mutations seulement sur les invariants critiques |
| Mémoire et fichiers | Isolation, stockage, réconciliation, pagination et bornes de requêtes/volume | Les embeddings simulés ne qualifient pas la qualité sémantique d'un moteur réel |
| Chat frontend | État réellement exécuté, résultats tardifs, multi-onglets, reprise HTTP après perte d'événement, E2E trois navigateurs | Ajouter les interactions aujourd'hui couvertes uniquement par inspection de sources |
| Autres écrans | Tests de stores/composables et chargement de pages | Le scénario E2E multi-pages ne démontre pas les CRUD complets de goals, documents, process et réglages |
| Exécuteurs | Chromium réel et reprise après crash ; permissions Unix réelles ; API et protections de chemins du manager | Les opérations Docker du manager sont en partie simulées ; ne pas les confondre avec une qualification d'un harnais distant |
| Exploitation | Scripts restore/upgrade/release avec données, fichiers et clés ; déclenchements CI existants | Qualification liée aux scénarios et images sélectionnés, pas à toute combinaison de versions |

## Ordre de travail recommandé

1. **Assainir les preuves trompeuses déjà établies** : réécrire le choix fermé, fusionner les trois doublons, corriger le scénario YAML et stabiliser le fuseau. Pas de suppression en masse.
2. **Remplacer un premier groupe de tests UI à risque** : permissions visibles, sélection asynchrone, fermeture de modales et pagination. Partir des composables et stores existants ; ajouter quelques interactions DOM ou navigateur ciblées.
3. **Conserver les scénarios de panne et les contrats backend** ; ajouter pour chaque correctif important un cas qui échoue avant le correctif et réussit après. Éviter de remplacer ces scénarios par des vérifications de présence de code.
4. **Clarifier la portée des suites** : contrat local, composant, navigateur, diagnostic externe, qualification de release. Un résultat doit indiquer ce qui a été réellement exécuté.
5. **Optimiser l'outillage après consolidation des preuves** : isoler le canari TypeScript coûteux et mutualiser la mesure de couverture lorsque cela ne réduit pas la sélection de tests.

Le critère de pertinence à appliquer lors des prochaines revues : **quel défaut observable ce test détecte-t-il, et une modification incorrecte représentative le fait-elle réellement échouer ?** Une suppression est justifiée quand elle retire une preuve nulle ou déjà fournie à l'identique ; un remplacement est préférable quand l'intention produit reste importante.
