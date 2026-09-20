# Audit de qualité et de fiabilité — 6 septembre 2026

Galaris dispose déjà d'une infrastructure de qualité substantielle : typage strict,
tests PostgreSQL isolés, contrats de transitions, supervision, contrôle des frontières,
CI de sécurité et exercice de restauration. La priorité est maintenant de renforcer les
frontières de confiance, les garanties sous concurrence et la fidélité des tests au runtime.

**À traiter en premier : l'accès au socket de gestion root de l'exécuteur SSH,
les erreurs de chargement absorbées, les barrières DbAdmin et les écritures interrompues.**

## Périmètre et méthode

Audit du dépôt local, basé sur le commit `a25228b76a54eb61a81eaf82b7eed7fcbba2714a`
et les fichiers présents pendant la revue. Inventaire transversal de `back/core`,
`back/app`, `back/bridge`, `front`, des deux exécuteurs, de `harness_manager`, des scripts,
de Compose, des Dockerfiles, de la CI, des tests et de la documentation d'architecture.
La cartographie annonce 65 modules backend, 33 frontend, 94 tables et 123 outils MCP.

La méthode combine inventaire statique, lecture approfondie des surfaces citées,
lecture des tests, exécution des portes existantes et contre-exemples isolés. Ce rapport
ne prétend pas que chacune des quelque 400 000 lignes inventoriées dans les grands
répertoires applicatifs a reçu une lecture humaine ligne par ligne, ni que les intégrations
externes ont été validées en conditions réelles. Une surface sans nouveau constat n'est
pas certifiée exempte de défaut.

Les vingt constats du 5 septembre ont leur propre suivi. Ils ne sont pas présentés ici
comme de nouveaux problèmes. Aucun code de production n'a été modifié par cet audit,
aucun commit créé, aucune synchronisation de la base de développement lancée.

**Travail concurrent :** le fichier de suivi du précédent audit était déjà modifié au
départ. Pendant l'audit, des modifications sont apparues dans les contrats et la façade
d'agents, le garde de raisonnement, l'exécuteur Hermès, les tests, l'affichage des résultats
de tâches et la documentation associée. Elles sont
préservées. Les validations ci-dessous portent sur les fichiers disponibles au moment
de chaque exécution, pas sur un snapshot final immuable de ces changements.

Niveaux : **P0** frontière de sécurité à fermer immédiatement ; **P1** perte de données,
indisponibilité ou comportement erroné significatif ; **P2** consolidation et passage à
l'échelle ; **P3** entretien. Les propositions structurelles sont distinguées des défauts.

## Vérifications exécutées

| Vérification | Résultat observé |
|---|---|
| `make tests` | **3 105 succès**, 12 avertissements, environ 85 s de pytest |
| `make typecheck` | Pyright : **0 erreur** ; vue-tsc réussi ; **327 tests frontend** réussis ; catalogues vérifiés |
| `make architecture-check` | Cartographies à jour, contrôle des frontières réussi, **27 tests** réussis |
| `make tests-browser` | **7 tests** réussis |
| `make tests-harness-manager` | **10 tests** réussis, 1 avertissement |
| `make tests-e2e` | **9 parcours Chat Chromium** réussis, environ 26 s ; une exécution, sans répétition triple |
| `make tests-restore` | Restauration PostgreSQL, fichiers canaris et clés validée |
| `make security-check` | Réussi avec sa politique et ses exclusions ; Semgrep : **79 règles, 1 057 fichiers, 0 constat** |
| `git diff --check` | Réussi en fin de revue |

Les tests utilisant PostgreSQL, le navigateur E2E et la restauration utilisent leurs
environnements isolés. La seule sonde du démon SSH actif était un appel **health**, depuis
un UID non privilégié ; aucune clé, aucun compte et aucune session n'ont été modifiés.

Les images de production n'ont pas été toutes reconstruites et rescannées pendant cet
audit. Le résultat de `security-check` ne vaut donc pas résultat de la matrice d'images
du workflow Security, ni absence de toute vulnérabilité. Les exclusions et l'exception
documentée de `security/trivy-ignore.yaml` restent applicables.

Les logs des commandes sont disponibles dans `/tmp/galaris-audit-*.log` pendant cette
session ; ils ne constituent pas des artefacts durables du dépôt.

## Défauts et fragilités directement établis

### Q01 — P0 — Le démon root SSH accepte les clients non privilégiés

**Preuve.** `ssh-executor/entrypoint.sh:10` rend `/data` et ses parents traversables ;
`ssh-executor/executord.py:400` utilise un répertoire `0777`, puis un socket `0666`.
`_handle`, ligne 366, exécute les opérations sans contrôle du pair ni authentification.
`sshd_config` ne confine pas les comptes dans un chroot.

La sonde réellement exécutée comme UID **65534** a obtenu `ok=true` pour `health`.
Le chemin testé avait effectivement les permissions `0755/0755/0777/0666`.
La même distribution d'opérations expose notamment `rotate_key`, `ensure_user`,
`disable_user`, `stop_session` et `recycle`.

**Conséquence.** Un processus lancé par un agent dans l'exécuteur peut atteindre le plan
de gestion root et demander des actions sur d'autres comptes. Le répertoire modifiable
permet également d'interférer avec le chemin du socket. L'allowlist des noms d'opérations
ne remplace pas une autorisation du client.

**Proposition.** Répertoire et socket accessibles exclusivement au backend et au démon,
groupe/UID de gestion réservé, contrôle des credentials du pair Unix lorsque pertinent,
et frontière de montage séparée des espaces d'exécution. Ne pas réutiliser simplement
le groupe des agents. Définir explicitement les UID autorisés entre les conteneurs.

**Acceptation.** Une connexion depuis un UID d'agent ou 65534 est refusée avant dispatch ;
le backend conserve ses commandes ; les agents ne peuvent ni remplacer ni supprimer le
socket. Tester ces propriétés dans un véritable conteneur avec plusieurs UID.

### Q02 — P1 — Une erreur d'import de modèle peut produire une cible DDL incomplète

**Preuve.** `back/core/database/model_loader.py:16` absorbe tout `ImportError`, y compris
celui d'une dépendance interne à un module existant. La fonction est appelée par
`back/core/dbadmin/_internal/target.py:16`, qui copie les métadonnées ainsi obtenues.

**Reproduction isolée.** Une erreur `ImportError` portant sur une dépendance transitive
a été injectée dans la fonction réelle extraite par AST : `load_models()` termine sans
erreur. Aucun DDL n'a été exécuté pour cette reproduction.

**Conséquence.** L'absence légitime de `models.py` et l'échec d'un modèle déclaré sont
indiscernables. Si les autres vérifications n'arrêtent pas le chargement, DbAdmin peut
recevoir une cible partielle ; dans un schéma déclaratif, une table manquante peut devenir
une suppression proposée. Ce dernier effet est un risque dérivé du flux, pas une
suppression de données observée pendant l'audit.

**Proposition.** Tester l'existence du module attendu, puis laisser remonter toutes ses
erreurs internes. Valider la complétude du chargement avant tout calcul de diff.

**Acceptation.** Module absent autorisé ; module existant cassé interdit ; dans ce
dernier cas, aucun appel Atlas. Ajouter un test d'orchestration, pas seulement du loader.

### Q03 — P1 — Un routeur cassé peut disparaître sans empêcher le démarrage

**Preuve.** `back/core/util/router_loader.py:33` journalise une exception puis continue.
Le contrôle RBAC vérifie les routes effectivement montées ; il ne peut détecter à lui
seul un routeur qui a entièrement disparu avant ce contrôle.

**Reproduction isolée.** Import d'un routeur déclaré simulé en échec :
`include_routers()` retourne normalement.

**Proposition.** Échouer au démarrage pour une capacité déclarée mais cassée. Conserver
un état « pas de routeur » pour les modules qui n'en ont effectivement pas. Ajouter un
test de composition vérifiant les capacités attendues, notamment les montages explicites
comme OneBot, sans multiplier les listes manuelles de toutes les routes.

### Q04 — P1 — Les erreurs fatales de contributions DbAdmin ne forment pas une barrière immédiate

**Preuve.** Dans `back/core/dbadmin/orchestrator.py:225`, les erreurs de `BEFORE_EXPAND`
sont ajoutées à `issues`, puis l'orchestration continue vers la préparation des enums et
Atlas. Après les datasets et actions, la contraction est également tentée avant le verdict
final. `staged_metadata` ne rend temporaires que les colonnes requises : ce n'est pas une
protection générale contre les suppressions. Le skill `core-dbadmin` documente cette limite.

**Conséquence.** Une erreur dite fatale empêche finalement un démarrage réussi, mais ne
garantit pas l'absence de mutations DDL effectuées après l'erreur. Une transformation
préalable destinée à préserver une donnée peut échouer sans bloquer immédiatement la suite.

**Proposition.** Définir une barrière explicite entre chaque phase : une obligation requise
non satisfaite interdit les opérations qui en dépendent. Séparer clairement expansion,
transformation et contraction ; conserver le déploiement en plusieurs livraisons pour les
contractions destructives. Cela peut rester entièrement dans DbAdmin, sans Alembic.

**Acceptation.** Injecter une panne avant expansion, après expansion et après dataset ;
vérifier les appels DDL interdits et la reprise. Aucune migration destructive réelle
n'a été essayée pendant cet audit.

### Q05 — P1 — Le registre des comptes SSH n'est pas transactionnel sous concurrence

**Preuve.** `_handle` appelle les opérations avec `asyncio.to_thread`.
`ensure_user` lit `next_uid`, crée le compte et réécrit le JSON sans verrou englobant ;
`_save_registry` utilise de plus un nom temporaire commun `users.tmp`.
Sources : `ssh-executor/executord.py:35`, `:42`, `:128`, `:377`.

**Reproduction isolée.** Deux créations simultanées, opérations système remplacées par
des doubles et registre dans un temporaire : **deux succès, un seul utilisateur conservé,
deux allocations de l'UID 20000**. Les écritures finales avaient même été sérialisées
dans la sonde pour isoler la perte de mise à jour du conflit sur le fichier temporaire.

**Proposition.** Sérialiser l'ensemble lecture–allocation–mutation–persistance, employer
des temporaires uniques et une écriture durable. Prévoir la récupération après panne
entre création du compte système et sauvegarde du registre. Une petite base transactionnelle
locale est une option, pas une obligation.

**Acceptation.** Créations et rotations simultanées, UID uniques, aucune entrée perdue,
redémarrage à chaque frontière et sous-processus bornés en durée.

### Q06 — P1 — La capacité navigateur peut être dépassée par des ouvertures concurrentes

**Preuve.** `browser-executor/server.mjs:359` et `:398` contrôlent `sessions.size`, puis
font plusieurs `await` avant d'enregistrer la session. Aucun emplacement n'est réservé.
Le `try` de nettoyage commence après `newContext`, le routage et `newPage`.

**Reproduction isolée.** Avec la fonction `open` réelle et des doubles, une capacité de
**1** accepte **2** sessions simultanées. Aucune requête réseau ni ouverture Chromium
n'a été nécessaire. Une panne pendant la préparation avant `sessions.set` laisse aussi
le contexte hors du nettoyage prévu, d'après la lecture du code.

**Proposition.** Réserver un emplacement avant le premier `await`, le libérer dans tous
les chemins d'échec, englober toute la construction dans le nettoyage. Sérialiser les
actions incompatibles sur une même page et tenir compte des opérations en cours dans le TTL.

**Acceptation.** Rafale supérieure à la limite, panne de `newPage`/routage, fermeture
concurrente, longue action et expiration : pas de dépassement ni de contexte orphelin.

### Q07 — P1 — Un upload binaire interrompu détruit l'ancienne version du fichier de harnais

**Preuve.** `harness_manager/main.py:568` ouvre directement la destination avec `wb` et
écrit les chunks. Le chemin texte, ligne 488, utilise déjà un temporaire et `os.replace`.

**Reproduction isolée.** Sur un fichier canari existant, une coupure après le premier
chunk laisse le contenu partiel publié et détruit le contenu précédent. La fonction
réelle a été extraite ; aucun gestionnaire ni fichier d'instance réel n'a été utilisé.

**Proposition.** Appliquer l'écriture atomique aussi au binaire : temporaire voisin,
limites/délai/quota explicites, fermeture et synchronisation adaptées, remplacement à la
fin, nettoyage sur exception et annulation. Traiter aussi les écritures concurrentes
et les courses entre suppression d'instance, upload et action de cycle de vie.

**Acceptation.** Une interruption préserve l'ancien fichier ; un succès expose l'intégralité
du nouveau ; aucun temporaire ne reste durablement orphelin.

### Q08 — P1 — Certains traitements CPU et caches médias menacent la boucle async

**Preuve.** `back/app/messenger/ingest.py:258` parse le PDF et extrait toutes ses pages
synchroniquement, avant le plafonnement du texte à 20 000 caractères. Le cache d'octets
est limité à **64 entrées**, pas à un nombre total d'octets (`:38`, `:74`).
`back/core/user/auth_service.py:128` appelle également la vérification de mot de passe
synchroniquement dans un chemin async, y compris avant le contrôle du verrouillage.

**Conséquence.** La borne sur le texte rendu ne borne ni le coût du parseur ni sa mémoire.
Des fichiers volumineux ou un burst d'authentifications peuvent retarder le scheduler,
les heartbeats et les autres requêtes du même processus. La latence n'a pas été mesurée
sur une charge représentative pendant cet audit.

**Proposition.** Isoler les parsers coûteux dans des workers bornés, arrêter l'extraction
dès le budget atteint, ajouter des limites de pages et de mémoire, et borner le cache en
octets. Déporter le hashing hors de la boucle, avec une concurrence limitée. Un thread
ne fournit pas à lui seul une interruption forte d'un parseur bloqué.

**Acceptation.** Tests avec PDF volumineux/complexe et authentifications concurrentes ;
mesurer le retard de boucle et vérifier que les leases restent renouvelés.

### Q09 — P2 — La protection contre les réponses frontend obsolètes est incomplète

**Preuve.** `front/app/task/stores/taskStore.ts`, `fetchRecentTasks`, traite une réponse
vide et décrémente `recentPage` **avant** de vérifier `request === recentRequest`.
Dans `front/app/process/stores/processStore.ts`, `loadRuns`, `openRun` et plusieurs autres
actions appliquent directement leur résultat sans génération de requête.

**Reproduction Task.** Une demande page d'index 2 est retardée ; l'index 4 termine ;
la première retourne vide. La page devient **3**, avec une requête parasite à l'offset
150, au lieu de rester sur 4. Test de la fonction réelle avec réponses différées.
La modification concurrente observée dans ce store ne touche pas cette fonction.

**Proposition.** Vérifier la génération avant toute mutation, y compris pagination,
chargement et erreurs. Partager un petit mécanisme de requête courante/annulation.
Nettoyer aussi les timers à la désinscription et gérer les promesses lancées avec `void`.

**Acceptation.** Tests comportementaux de réponses inversées, filtre modifié, modale
fermée pendant le chargement, déconnexion et erreur réseau.

### Q10 — P2 — La liste des salons multiplie les requêtes SQL et les appels distants

**Preuve.** `back/app/messenger/native_facade.py:1016` construit chaque ligne avec
`_room_dto`. Cette fonction (`:749`) charge le dernier message, hydrate ses relations,
compte les non-lus et peut vérifier la présence de l'agent, pour chaque salon. Puis la
liste interroge séquentiellement les providers pour leurs non-lus (`:1031`).

**Conséquence.** La pagination borne les lignes rendues mais conserve un nombre de
requêtes proportionnel aux salons. Un provider lent retarde la liste locale. Ce N+1
est établi par lecture ; son coût réel doit être mesuré sur les données représentatives.

**Proposition.** Charger derniers messages et compteurs par lots, hydrater ensemble,
et dissocier le rafraîchissement distant de l'affichage canonique. Exposer la fraîcheur
des compteurs si nécessaire. Éviter de paralléliser des requêtes sur la même AsyncSession.

**Acceptation.** Budget de requêtes borné sur 10/50/500 salons et latence acceptable
lorsqu'un provider est lent ou hors ligne.

### Q11 — P2 — Les échéances HTTP, SQL et de démarrage ne forment pas un contrat global

**Preuve.** `front/core/api.ts` ne configure pas de timeout global pour Axios ni pour le
refresh direct. `back/core/database/database.py` configure le pool, mais aucune politique
applicative de `statement_timeout`, `lock_timeout` ou `idle_in_transaction_session_timeout`
n'a été trouvée dans la configuration examinée. `wait_for_db` calcule une échéance sans
envelopper la tentative de connexion elle-même dans son temps restant.
Les sous-processus Atlas/psql de `core/dbadmin/_internal/atlas.py` attendent `communicate`
sans borne globale explicite. Le `--lock-timeout` Atlas ne borne pas toute la commande.

**Proposition.** Définir des délais par classe d'opération, propager une échéance restante,
et garantir annulation/nettoyage. Garder des exceptions explicites pour uploads et streams.
Configurer séparément les sessions de synchronisation et celles du trafic interactif.
Un opérateur peut déjà avoir des limites PostgreSQL externes : elles n'ont pas été inspectées.

**Acceptation.** Connexion qui ne répond pas, verrou détenu, provider silencieux et commande
DDL bloquée produisent un résultat borné et libèrent les ressources.

### Q12 — P2 — Le nettoyeur HTML générique laisse passer un protocole actif obfusqué

**Preuve.** `front/core/util/sanitizeHtml.ts:2` teste des préfixes après `trim().toLowerCase()`.
Une tabulation interne au nom de protocole contourne ce test. Dans une page Chromium
isolée, une valeur encodant cette tabulation est conservée et `HTMLAnchorElement.protocol`
la normalise en **`javascript:`**.

La sonde n'a pas établi une exécution de script exploitable dans l'application. La CSP
de production de `front/nginx.conf` bloque les scripts inline ; elle constitue une
protection réelle. Le constat porte sur une promesse de sanitization insuffisante,
pas sur un vol de jeton démontré.

**Proposition.** Une allowlist commune d'éléments, d'attributs et de protocoles, avec
normalisation cohérente avec le navigateur. Évaluer un sanitizer maintenu plutôt que
faire croître une blacklist maison. Conserver la CSP et le sandbox des previews.

**Acceptation.** Tests dans un vrai DOM pour entités HTML, caractères de contrôle,
variantes de casse, attributs URL et contenus imbriqués ; aucun protocole actif conservé.

## Chantiers structurels recommandés

### Q13 — P1 — Rendre le déploiement reproductible et les upgrades répétables

`back/Dockerfile` copie **`arigaio/atlas:latest`**. Plusieurs images et actions suivent
aussi des tags mobiles ; les builds font des mises à jour de paquets. La même révision
Git ne suffit donc pas à reconstruire exactement le même logiciel ni le même moteur DDL.
Le stage de production backend utilise `uv sync --frozen` sans exclusion explicite du
groupe de développement.

Versionner les images livrées par digest, conserver une provenance et un inventaire
des dépendances, publier un artefact construit une fois puis promouvoir cet artefact.
Rendre explicite l'exclusion des outils de développement en production. Inclure les
images des harnais gérés dans la stratégie de version et de validation.

`make update` reconstruit puis passe par `restart`, qui arrête la stack. Définir le temps
d'arrêt attendu, le retour à l'image précédente, et surtout les conditions de compatibilité
du schéma ; un rollback d'image ne restaure pas les données contractées.

### Q14 — P1 — Étendre le test de restauration au véritable service restauré

`bin/test-restore.sh` et `back/tests/restore_probe.py` constituent une bonne base : dump,
restauration, hashes de fichiers et canaris cryptographiques. Les fichiers sont cependant
créés directement sous `/restore`, et leur intégrité est vérifiée directement.

Ajouter un exercice créant un document et une pièce jointe par les façades réelles,
puis redémarrant une stack sur les données restaurées et les relisant par l'API avec
les ACL. Tester les références DB↔fichiers, la cohérence pendant une sauvegarde active,
les clés de transport et les instances de harnais nécessaires à la reprise.

Ajouter une répétition d'upgrade **version précédente → version candidate**, avec jeux
de données non vides et interruptions, puis le scénario de retour arrière autorisé.
Mesurer RPO/RTO plutôt que seulement le succès de commandes. Aucun exercice sur une
sauvegarde réelle de production n'a été effectué ici.

### Q15 — P1 — Faire porter les tests sur les comportements observables

Une part importante des tests frontend lit les `.vue` avec `readFileSync` et vérifie
des expressions régulières : exemples `front/app/goal/lifecycleActions.test.mjs` et
`front/app/chat/roomCreation.test.mjs`. D'autres extraient des fragments de script avec
des doubles. Ils rendent service pour des conventions, mais n'exécutent pas le montage
Vue, la réactivité, les événements et le cycle de vie complets.

Conserver les tests textuels pour les règles réellement structurelles. Ajouter des
tests de composants/stores réels pour les workflows et la concurrence. Étendre les
neuf E2E Chat à login/refresh/MFA, gestion d'agents, création/annulation de Task,
Goals, Process et édition/livraison de documents. Prévoir au moins une vérification
WebKit/Firefox et une vraie mise à jour de PWA : les E2E actuels bloquent les service workers.

Introduire une mesure de couverture de branches sur les domaines critiques, avec un
objectif progressif sur le code modifié. Ajouter des tests de propriétés pour les
machines d'états et un petit ensemble de mutations pour vérifier que les tests échouent
lorsqu'on casse une garantie. Le nombre total de tests ne mesure pas cette sensibilité.

### Q16 — P2 — Réduire les cycles de dépendance par leurs causes métier

La cartographie signale **28 paires backend bidirectionnelles**, une composante fortement
connexe et **7 paires frontend bidirectionnelles**. Le contrôle actuel empêche la dette
de croître ; sa réussite ne signifie pas disparition de la dette.

Priorités suggérées : `file_share` et ses providers, le couple Tools/Connection,
les relations Memory/Topic et les projections de suivi. `app.file_share` autorise
actuellement 15 dépendances de domaines ; Lab en autorise 14 et Dream 12.

Reproduire le patron déjà efficace du port Task consommé par Agent : contrats étroits,
adaptateurs au point de composition, responsabilité de la persistance dans son domaine.
Exporter un modèle ORM depuis `__init__.py` ne supprime pas à lui seul le couplage.
Réduire les baselines après chaque tranche démontrée ; ne pas engager une réécriture globale.

### Q17 — P2 — Découper les unités qui mélangent plusieurs responsabilités

Exemples mesurés dans le dépôt :

| Surface | Taille approximative observée | Frontière d'extraction utile |
|---|---:|---|
| `back/app/memory/service.py` | 4 055 lignes | acquisition, droits, requêtes, graphe, mutations |
| `back/app/lab/mechanism_evaluation_service.py` | 2 963 lignes | préparation, exécution, notation, restitution |
| `back/app/agent/planner_service.py` | 2 543 lignes | validation de plan, matérialisation, transitions, synthèse |
| `back/app/file_share/resource_service.py` | 2 305 lignes | résolution, autorisation, dispatch provider, transferts |
| `front/app/goal/pages/index.vue` | 2 821 lignes | formulaire, arbre, planning, historique, commandes |
| `front/app/agent/pages/index.vue` | 2 477 lignes | liste, configuration, supervision, modales |

L'inventaire AST relève aussi des fonctions de plusieurs centaines de lignes dans les
streams Hermès, la conversation interne et les proxies LLM. La taille seule n'est pas
un défaut ; elle indique où les changements de politique, de transport et de persistance
sont difficiles à vérifier séparément.

Extraire une responsabilité avec un contrat testable, puis déplacer sans changer son
comportement. Éviter les fichiers `utils` fourre-tout et les microfonctions sans autonomie.

### Q18 — P2 — Renforcer les contrats typés et l'évolution des snapshots

Pyright strict est réellement actif, mais les données dynamiques restent nombreuses
dans Agent, LLM, Tools, Lab et Process. `AgentTaskPort` expose encore plusieurs
`Mapping[str, Any]` ; Task et les résultats transportent des données JSON évolutives.

Définir des DTO nommés pour les données qui traversent plusieurs domaines, distinguer
les états par unions discriminées, et limiter `Any` à l'adaptation des bibliothèques.
Versionner les formats durables qui doivent survivre à un upgrade : checkpoints,
résultats, working sets et corrélations de runs. Tester leur lecture depuis la version
précédente, y compris les événements inconnus et les champs optionnels.

Pour les montants financiers qui exigent une égalité exacte, étudier `Decimal`/`Numeric`
à la place des `Float` actuellement utilisés pour les coûts Task/LLM. Distinguer ce besoin
des mesures approximatives ; ce n'est pas un constat d'erreur comptable observée.

### Q19 — P2 — Rendre explicite le contrat mono-processus avant de multiplier les workers

Les leases Task et Conversation sont durables, mais plusieurs autres états sont locaux :
cache de paramètres et listeners de changement, connexions temps réel, registre des
listeners Messenger et périodicité du scheduler. Sources : `core/params/params_service.py`,
`core/websocket.py`, `app/messenger/service.py`, `app/task/scheduler.py:304`.

Le déploiement courant ne configure pas plusieurs workers Uvicorn : ce constat n'est
donc pas une panne actuelle démontrée. Avant un passage à plusieurs processus, choisir
entre une instance coordinatrice explicite et une coordination distribuée par composant.
Tester le rafraîchissement des paramètres, l'unicité des pollers, l'annulation distante
et la réception d'un événement sur un autre worker. Ne pas déduire la compatibilité
multi-worker du seul fait que les Tasks possèdent des leases.

### Q20 — P2 — Ajouter un budget global de travail et une admission équitable

Le harnais interne borne les requêtes et appels outils par run (`runtime.py:1007`) et
le planner borne sa taille. Ces protections sont utiles. Elles ne constituent pas à
elles seules un budget partagé par une racine, ses enfants, les retries, ses appels
de planification et plusieurs cycles de Goal.

Définir un contrat de budget partagé en temps, tokens et coût estimé, avec réservations
avant les appels concurrents et rapprochement après usage. Conserver une marge explicite
pour la réponse finale. Ajouter des quotas et priorités par utilisateur/agent pour
éviter qu'un gros Goal occupe toutes les places du scheduler. Tester les harnais externes
avec la même politique ; ne pas laisser la limite dépendre du seul runtime interne.

### Q21 — P2 — Donner une issue opérable aux livraisons dont le résultat est inconnu

`app/conversation/service.py` distingue déjà `DELIVERED` et `UNKNOWN`, utilise des leases
et persiste des reçus d'artefacts. C'est une bonne base. L'envoi distant et le commit du
reçu ne peuvent cependant pas être atomiques sans aide du provider.

Formaliser par transport les possibilités de clé d'idempotence, de recherche du reçu et
de réconciliation. Exposer les envois `UNKNOWN` à l'opérateur, avec une commande de
résolution et une explication du risque de doublon. Tester la coupure après succès
distant et avant commit local. Ne pas transformer indistinctement les erreurs réseau en
retries automatiques, ni promettre un « exactement une fois » universel.

### Q22 — P2 — Prévoir croissance, rétention et performances avec des données réalistes

Les incidents sont bornés individuellement, mais les surfaces examinées de `app.incident`
et `app.llm` proposent surtout des purges globales/ponctuelles. Leur accumulation, les
messages, les traces et les fichiers doivent avoir une politique de rétention explicite.

Séparer les agrégats utiles au dashboard des détails volumineux, purger par lots avec
curseur, conserver les références requises par les travaux actifs et prévoir l'export.
Mesurer espace disque, croissance des tables/index et dette de nettoyage.

Pour Memory, `search_items` combine le GIN de recherche plein texte avec des fallbacks
`ILIKE '%…%'`. Ne pas ajouter des index à l'aveugle : comparer des plans d'exécution sur
des corpus multilingues réalistes et vérifier l'effet de ces OR et des filtres ACL.
Ajouter des budgets de requêtes et de latence sur les listes les plus utilisées.

### Q23 — P2 — Mesurer la progression effective, pas seulement la présence des boucles

`core/runtime.py:189` contrôle les tâches racines et la base ; les superviseurs et
métriques de jobs existent déjà. Une coroutine encore vivante peut pourtant ne plus
faire avancer son travail. Des limites SQL/CPU manquantes renforcent cette possibilité.

Ajouter âge du dernier progrès utile, ancienneté de la file, taux de reprise de leases,
retard de boucle, saturation du pool, livraisons inconnues, volume de fichiers et échecs
répétés de maintenance. Définir des seuils et des procédures opérationnelles dans le dépôt.
Les alertes déjà configurées dans un compte Logfire externe n'ont pas été inspectées.

Les 12 avertissements pytest incluent des coroutines `Connection._cancel` non attendues
et des paramètres d'échantillonnage ignorés en mode reasoning. Isoler et corriger leur
origine avant de rendre fatales ces classes d'avertissements ; ne pas les masquer globalement.
La localisation d'un warning au moment du GC n'identifie pas forcément le test fautif.

### Q24 — P2 — Compléter la CI et les contrôles statiques selon le risque

Les workflows Quality/Security sont déjà présents. Leurs limites actuelles méritent
des portes complémentaires : tests du démon SSH avec permissions réelles, concurrence du
serveur navigateur (les 7 tests actuels ciblent sa bibliothèque), upgrades DbAdmin,
comportements de composants et cycles de vie de harnais.

Ajouter progressivement lint/format Python et TypeScript/Vue, en ciblant d'abord les
erreurs et le code modifié. Réserver les règles AST aux frontières structurelles ;
l'allowlist de sessions DB est actuellement au niveau fichier, ce qui ne prouve pas
que chaque nouvelle fonction de ce fichier est une racine autonome.

Compléter le suivi automatique des dépendances pour `e2e`, `ssh-executor` et les images
des harnais embarqués ; la configuration Dependabot actuelle ne couvre pas explicitement
toutes ces racines. Vérifier dans GitHub que les jobs agrégateurs sont réellement requis
avant fusion : un fichier workflow ne prouve pas la protection de branche.

### Q25 — P2/P3 — Uniformiser les contrats de configuration et d'interface

La cartographie liste des paramètres `Settings` sans entrée `.env.example` : notamment
les limites navigateur, le pool DB et les tailles de ressources. Plusieurs skills portent
des versions de bibliothèques différentes des manifestes actuels. Mettre ces références
à jour ou préciser leur portée, sans remplacer le code comme source de vérité.

`core/settings.py:136` compose l'URL PostgreSQL par interpolation : utiliser une
construction d'URL structurée pour les identifiants contenant `@`, `/`, `:` ou d'autres
caractères réservés. La validation des secrets dépend aussi de `os.getenv('APP_ENV')`
pendant la définition de classe ; préférer une validation du modèle sur l'environnement
effectivement résolu, couvrant aussi les environnements assimilés à la production.

Côté interface, mutualiser les contrats de pagination, chargement/erreur/vide,
confirmation destructive et fermeture des modales. Tester clavier et focus sur les
modales complexes, ainsi que les largeurs autour de 1024 px. Conserver exactement les
options de pagination prescrites pour les listes paginées, sans imposer une pagination
artificielle aux petits tableaux de présentation.

## Couverture transversale et suites à privilégier

Cette matrice décrit les surfaces examinées ou inventoriées et les validations à approfondir.
Les regroupements ne constituent pas un décompte exhaustif des fonctions lues.

| Domaine | Surfaces et garanties prises en compte | Suite de travail prioritaire |
|---|---|---|
| Core API, User, Authorize | Composition, classification des routes, refus RBAC, login, refresh, MFA, invariants administrateur | Q03, Q08, Q11 ; parcours navigateur d'authentification |
| Database, DbAdmin | Sessions contextuelles, loaders, cible déclarative, phases, journal, tests PostgreSQL | Q02, Q04, Q11, Q14 |
| Params, i18n, configuration | Cache runtime, changements de paramètres, catalogues, settings et documentation | Q19, Q25 |
| Agent, Task | Contrats, port, scheduler, leases, limites, activité, plans, snapshots, tests de reprise | Q16–Q20, Q23 |
| Harness, Harnesses | Streams, requêtes typées, limites internes, lifecycle des runtimes | Q07, Q13, Q18–Q20 |
| Bridges Hermès/Codex/Claude/DeepSeek Harness | Adaptation des exécutions, assets de conteneurs, supervision et suites existantes | Q07, Q13, Q18, Q24 ; contrats communs de driver |
| Messenger, Conversation, Chat | Journal, admission, DTO, non-lus, fichiers, livraison terminale, E2E | Q08–Q12, Q21 |
| Matrix, Nextcloud, OneBot, Telegram, WhatsApp | Entrées et transports via modèle canonique ; tests backend, corrections précédentes | Tests protocolaires de redelivery, reconnexion et panne réelle ; Q19/Q21 |
| Mail, Calendar, n8n | Adaptation, reçus et reprises corrigés, API/outils, tests backend | Tests de contrats avec serveurs simulés, puis smoke tests sur comptes dédiés |
| Process, Goal | Transitions, attentes et résolution, cycles, UI d'administration | Q09, Q18, Q20, Q21 |
| Memory, Topic, Contact, Dream | ACL, recherche/index, projections, graphe, maintenance, mécanismes asynchrones | Q16–Q18, Q22, tests de pertinence multilingue et de non-fuite |
| Tools, MCP, Connection | Catalogue et exposition, gestion des connexions, erreurs et ressources | Q16, Q18, Q19, Q24 ; contrats d'autorisation par outil |
| File Share, Console | URI, transferts, matérialisation et exécution distante | Q01, Q05, Q07, Q08 |
| Browser, Image, Audio, Voice | Isolation, sessions, médias, parsing, timeouts et streaming | Q06, Q08, Q11 ; stress borné et nettoyage après annulation |
| LLM et bridges fournisseurs | Registre, modèles, proxies, coûts, compatibilité, limites et tests | Q13, Q18, Q20, Q22 ; matrice de capacités provider |
| Dashboard, Incident, Lab, Onboarding, Skill | Agrégats, journal, évaluations, configuration et packages | Q15, Q17, Q22–Q24 |
| Frontend core et modules applicatifs | API, stores, composants volumineux, navigation, HTML, i18n, tests | Q09, Q12, Q15, Q17, Q25 |
| Exécuteurs et manager | Processus privilégiés, socket, registre, navigateur, fichiers, limites | Q01, Q05–Q07, Q24 |
| Livraison, CI, docs | Make, scripts isolés, Compose, Dockerfiles, scans, restauration et dette | Q13–Q16, Q24, Q25 |

## Ordre de mise en œuvre proposé

| Lot | Contenu | Preuve de fin attendue |
|---|---|---|
| **1 — Frontières et données** | Q01 à Q07 | Tests adverses et de concurrence ; aucun accès non autorisé, DDL indu ou fichier partiel |
| **2 — Fiabilité sous charge** | Q08 à Q12, Q23 | Boucle réactive, deadlines effectives, budgets SQL, réponses UI ordonnées, sanitizer validé |
| **3 — Livraisons maîtrisées** | Q13 à Q15, Q24 | Artefacts reproductibles, upgrade/restauration applicatifs, tests comportementaux et CI requise |
| **4 — Réduction durable de la complexité** | Q16 à Q22, Q25 | Tranches de découpage avec baselines réduites, contrats durables, budgets et rétention |

Pour chaque lot, garder des changements petits et vérifiables. Prioriser un défaut
reproduit avec son test, puis son correctif ; réserver les changements d'architecture
aux endroits où ils retirent effectivement une responsabilité ou une dépendance.
Les objectifs de latence, de capacité, de RPO/RTO et de budget doivent être fixés sur
les besoins de l'instance et mesurés sur des données représentatives.
