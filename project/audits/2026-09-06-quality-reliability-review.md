# Galaris — contre-audit de qualité et de fiabilité

**État examiné : `3062cf45f56f0dd97b49e42e0e5ef59c2b7d1d92`, 6 septembre 2026.**

Le socle a progressé : les tests backend, les contrats d’architecture, les parcours navigateur,
la restauration et l’upgrade passent. Cette revue révèle néanmoins des défauts que ces contrôles
ne couvrent pas, notamment une validation TypeScript inefficace, une course de révocation des
sessions, des renvois de messages et plusieurs limites de reprise.

**Priorité : rendre les contrôles fiables, fermer les défauts de session et de fichiers, puis
fiabiliser les effets externes et les reprises.** Les grands refactorings viennent ensuite.

## Périmètre, méthode et limites

Le dépôt était propre au départ. La revue porte sur les changements intégrés après le précédent
audit, dont le multimédia, et sur les surfaces existantes. Les anciens constats Q01–Q25 ne sont
pas déclarés corrigés ou ouverts en bloc : leur portée réelle est confrontée au code courant.

Inventaire des fichiers Python, TypeScript, Vue, MJS et shell : **1 295 fichiers applicatifs et
outillage, 307 507 lignes ; 527 fichiers de tests, 109 395 lignes**. Ce comptage inclut commentaires
et traductions ; il exclut dépendances, environnements locaux et répertoires nommés `generated`.
Les Dockerfiles, fichiers Compose et workflows ont été examinés séparément. L’inventaire par
domaine est conservé dans [inventory.json](2026-09-06-review-evidence/inventory.json).

La cartographie annonce **69 modules backend, 33 frontend, 97 tables, 128 outils MCP et 490
handlers HTTP/WebSocket**. Ses compteurs statiques ne doivent pas être confondus avec ceux du
routeur au démarrage, qui incluent les montages et routes techniques.

Méthode : inventaire transversal, recherches sur toutes les couches, lecture des contrats et
tests des chemins sensibles, exécution des suites, puis contre-exemples ciblés sur le code réel.
Les contre-exemples utilisent PostgreSQL éphémère, des transports simulés, des fichiers canaris
et un Chromium jetable. Aucun message n’a été envoyé à un fournisseur ; aucune donnée de
développement n’a été modifiée ; aucune instance active n’a été redémarrée.

Cette revue **ne constitue pas une lecture ligne par ligne des 416 902 lignes inventoriées**,
ni une certification de chaque intégration distante. Elle distingue ci-dessous les défauts
reproduits, les comportements établis par lecture et les investissements proposés. Les services
externes payants, Safari/iOS physiques, la saturation prolongée et un rollback complet de
production n’ont pas été exercés. Aucun code de production n’est modifié par ce rapport.

## Vérifications exécutées sur cet état

| Contrôle | Résultat et portée |
|---|---|
| `make tests` | **3 230 succès**, 5 avertissements ; 133 s de pytest |
| Pyright via `make typecheck` | **0 erreur** |
| Commande frontend actuelle via `make typecheck` | Code de sortie 0, mais **contrôle inopérant : voir R01** |
| Typage explicite `vue-tsc --noEmit -p tsconfig.app.json` | **180 erreurs dans 44 fichiers**, sans sonde temporaire |
| Tests frontend | **359 succès** |
| Traductions | **4 516 paires anglais/français et 4 516 messages chinois** vérifiés ; ne détecte pas les propriétés dupliquées avant évaluation |
| `make architecture-check` | Cartographie et frontières validées, **27 tests** réussis |
| `make lint format-check` | Réussi ; Ruff minimal et format de **6 fichiers** uniquement |
| `make tests-browser` | **12 succès**, dont une intégration HTTP avec Chromium |
| `make tests-executor` | **9 succès**, dont credentials Unix et concurrence du registre |
| `make tests-harness-manager` | **12 succès** |
| `make tests-e2e` | **42 succès** : 14 parcours × Chromium, Firefox, WebKit GTK ; une répétition par navigateur |
| `make security-check` | Réussi selon la politique/exclusions du dépôt ; Semgrep : **79 règles, 1 095 fichiers, aucun constat** |
| `make tests-restore` | PostgreSQL, fichiers, clés, lecture applicative et ACL validés |
| `UPGRADE_FROM=2a434b48 make tests-upgrade` | Schéma précédent rempli → candidat, lecture/ACL puis deuxième convergence : réussi |
| Contre-exemples supplémentaires | **6 tests backend**, **3 scénarios frontend**, **1 scénario fichiers**, **1 panne Chromium** reproduisent les comportements décrits |

Les 180 diagnostics TypeScript ne représentent pas nécessairement 180 bugs d’exécution : ils
mélangent contrats incorrects, inférences insuffisantes, nullabilité, paramètres non typés et
code inutilisé. Ils invalident en revanche la conclusion « frontend strict validé ».

Les avertissements backend restants concernent SlowAPI (`asyncio.iscoroutinefunction`) et les
paramètres d’échantillonnage ignorés avec certains modèles en raisonnement. Aucun nouvel audit
complet des images de production n’a été exécuté ici. Les tests d’upgrade réutilisent les
dépendances Python du candidat : limite détaillée en R20.

## Défauts et risques prioritaires

### R01 — P1 — Le contrôle TypeScript peut réussir sans contrôler l’application

**Reproduit.** `front/tsconfig.json` contient `files: []` et des références de projets.
`front/package.json` lance `vue-tsc --noEmit`, sans sélectionner le projet applicatif ni lancer
le mode build. Un fichier temporaire sous `front/app` contenant une affectation `string → number`
laisse cette commande sortir avec 0. La commande avec `-p tsconfig.app.json` détecte la sonde.
Après suppression de celle-ci, elle détecte **180 erreurs dans 44 fichiers**, dont 86 dans la
page Agent. Les versions des dépendances installées ont été comparées au lockfile : aucune
divergence constatée parmi les packages présents. La commande de build réutilise le même
précontrôle insuffisant.

**Proposition.** Cibler explicitement tous les projets utiles dans les scripts locaux et CI,
réduire les erreurs par domaine, typer les états initialisés à `null` ou `{}`, les événements,
les lignes Quasar et les contrats de navigation. Vérifier aussi les fichiers de bridges et la
configuration Vite, actuellement marquée `@ts-nocheck`. Éviter une suppression générale de
`strict` ou une généralisation de `any` pour obtenir du vert.

**Acceptation.** Une mutation TypeScript volontaire fait échouer le contrôle et le build ; le
code réel passe ensuite les projets explicitement contrôlés. Conserver cette vérification de
l’efficacité de la porte dans un environnement jetable. Diagnostics complets :
[typescript-diagnostics.txt](2026-09-06-review-evidence/typescript-diagnostics.txt).

### R02 — P1 — Une déconnexion concurrente au refresh peut laisser une session active

**Reproduit sur PostgreSQL avec connexions indépendantes.**
`back/core/user/refresh_session_service.py:110` verrouille le jeton à renouveler ;
`revoke_refresh_token`, ligne 198, lit sans verrou puis révoque les lignes actuellement actives
de la famille. Si son `UPDATE` attend la rotation en cours, il peut ne révoquer ni l’ancienne
ligne devenue inactive ni la nouvelle ligne hors de son snapshot. La déconnexion retourne
`True`, mais le remplacement reste renouvelable. `is_family_active` continue donc à valider
cette famille pour les accès.

**Proposition.** Donner à la famille une autorité de révocation durable et un verrou commun aux
rotations/révocations, ou une sérialisation équivalente prouvée. Appliquer le même raisonnement
à la révocation de toutes les sessions, aux changements de mot de passe et aux changements MFA.

**Acceptation.** Matrices rotation/logout, rotation/révocation globale et rotation/désactivation,
dans les deux ordres, avec véritables commits et attentes de verrous. Aucun remplacement issu
d’une famille révoquée ne permet un nouvel accès.

### R03 — P1 — Un ancien refresh peut écraser la session d’un autre compte

**Reproduit sur le module TypeScript réel.** `front/core/api.ts:88` mutualise le refresh, mais
son succès appelle toujours `saveAccessToken`. `clearStoredSession`, ligne 41, n’invalide pas la
requête en vol. Séquence reproduite : refresh A → déconnexion → connexion B → réponse A ; le
jeton stocké devient celui d’A, alors que l’interface peut encore afficher B.

**Proposition.** Introduire une génération de session et vérifier son identité avant toute
écriture ou répétition de requête. Invalider les opérations en vol à la déconnexion, au changement
de compte et de rôle ; coordonner les onglets. Borner aussi les hooks exécutés avant logout :
une attente indéfinie du service Push ne doit pas empêcher la révocation serveur.

**Acceptation.** Réponses A tardives ignorées après connexion B, y compris erreurs 401 ; aucune
requête A n’est rejouée avec le compte B. Couvrir cookies et stockage dans un vrai navigateur.

### R04 — P1 — Le gestionnaire de harnais peut ouvrir un fichier après invalidation du contrôle de chemin

**Reproduit.** `harness_manager/main.py:167` résout et contrôle le chemin. `download_raw`, ligne
539, lit sa taille puis retourne un générateur qui ouvre le fichier plus tard. Entre ces étapes,
le remplacement d’un parent par un lien symbolique permet de lire un canari hors de l’instance.
Le test annonce 7 octets et en lit 22. Un simple remplacement atomique concurrent peut également
rendre le `Content-Length` faux, même sans tentative de franchissement.

Le scénario exige la capacité de modifier le répertoire concerné : ce n’est pas un endpoint
accessible sans authentification. Les répertoires partagés avec un runtime doivent néanmoins
être considérés comme modifiables pendant la requête.

**Proposition.** Ouvrir un descripteur contrôlé avant la réponse, calculer la taille par `fstat`,
et protéger la résolution de chaque composant contre les substitutions de liens. Étendre la
garantie aux écritures, lectures texte et suppressions ; un second `resolve()` ne ferme pas la
fenêtre de concurrence.

**Acceptation.** Tests de substitution de parent pendant lecture/écriture et de remplacement
concurrent ; aucun octet hors racine, réponse cohérente et fermeture des descripteurs à l’abandon.

### R05 — P1 — Un crash de Chromium peut laisser le navigateur indisponible sans reprise

**Reproduit avec un vrai Chromium jetable.** `browser-executor/server.mjs:540` ferme seulement
le serveur HTTP à l’événement `disconnected`. Le proxy réseau reste en écoute et conserve Node
vivant. Après destruction du processus Chromium, `/health` devient inaccessible et Node ne sort
pas. La politique `unless-stopped` de Compose ne suffit alors pas : les politiques de restart
s’appliquent à l’arrêt du conteneur. [Documentation Docker](https://docs.docker.com/engine/containers/start-containers-automatically/).

**Proposition.** Après une panne inattendue du navigateur, invalider les sessions puis terminer
le service avec un code d’échec, avec nettoyage borné ; ou implémenter une relance interne dont
l’état et les garanties sont explicites. Différencier cette panne d’un arrêt volontaire.

**Acceptation.** Crash du navigateur → panne observable → nouvelle instance saine dans un délai
borné. Les anciennes sessions échouent clairement et une nouvelle session peut être créée.

### R06 — P1 — Telegram et WhatsApp peuvent répéter un envoi déjà accepté

**Reproduit sur les clients avec perte de réponse simulée après effet distant.**
`back/bridge/telegram/client.py:35` applique `_retry` à `sendMessage`, fichiers et voix.
`back/bridge/whatsapp/client.py:75` réessaie les POST après timeout/erreur réseau et certains
statuts HTTP. Dans les deux contre-exemples, un appel utilisateur produit deux effets distants.
Le journal supérieur ne peut pas empêcher une répétition cachée dans le client de transport.

**Proposition.** Séparer lectures, opérations idempotentes et mutations sans déduplication
distante. Après une perte de réponse d’un envoi, préserver le résultat incertain et la preuve
locale ; reprendre automatiquement seulement avec une garantie du protocole. Une réponse de
rate limiting doit être traitée selon son contrat, distinctement d’un timeout ambigu.

**Acceptation.** Serveur simulé acceptant puis coupant la réponse : un seul envoi. Tester aussi
la coupure avant envoi et les messages multiparties, avec reçus par partie lorsque nécessaire.

### R07 — P1 — Nextcloud transforme tous les HTTP 5xx d’envoi en succès présumé

**Établi par lecture.** `back/bridge/nextcloud/client.py:387` retourne `{}` pour tout HTTP ≥ 500
pendant `send_message`. `messenger.py:291` construit alors un message sortant sans identifiant
distant. Une panne serveur ayant empêché l’envoi reçoit donc le même traitement qu’un problème
de post-traitement après envoi.

**Proposition.** Conserver l’absence de retry aveugle, mais exposer une admission/livraison
incertaine, avec réconciliation par preuve distante quand elle existe. Cela laisse fonctionner
l’application sans annoncer une livraison non prouvée.

**Acceptation.** Distinguer « accepté puis erreur » et « erreur avant acceptation » ; aucun
faux reçu de livraison et aucun doublon automatique. Préserver le comportement compatible des
réponses normales de Talk.

### R08 — P1 — La correction d’une action DbAdmin facultative peut devenir bloquante

**Reproduit.** `back/core/dbadmin/actions.py:33` refuse tout changement de checksum d’une
action inachevée, avant sa postcondition et sans distinction `required=False`. Une action
facultative en échec, corrigée de v1 vers v2, empêche donc le démarrage alors même que sa
postcondition pourrait déjà être vraie. Le journal ne conserve pas sa criticité.

Le staging nullable et les barrières de protection existantes passent leurs tests. Il ne faut
pas revenir dessus. Le problème ici est une règle supplémentaire trop globale ; elle est
actuellement documentée, son évolution demande donc un contrat explicite.

**Proposition.** Prévoir une succession déclarée d’actions/checksums, vérifier les postconditions
compatibles et distinguer obligations indispensables et facultatives. Garder les données sources
et signaler les écarts facultatifs sans bloquer l’expansion utilisable. Ne pas ignorer aveuglément
un changement de transformation destructive.

**Acceptation.** Action facultative corrigée ou déjà satisfaite : application opérationnelle,
écart journalisé si nécessaire. Transformation indispensable incompatible : arrêt expliqué et
sources conservées. Ajouter la matrice aux tests réels de convergence.

### R09 — P1 — La rétention Process peut supprimer un résultat encore attendu

**Reproduit avec la rétention des runs activée.**
`back/app/process/process_service.py:1683` purge selon l’âge et le statut terminal, sans vérifier
`await_resolved_at`, les tâches dépendantes ou les notifications restant à délivrer. Un run
`success` ancien, dont le résultat n’a pas encore été transmis à sa tâche d’attente, est supprimé.
La reprise ne peut plus restituer ce résultat. Les événements sont également purgés selon leur
âge sans condition d’état du run ; les liens conversationnels sont en cascade à la suppression.

**Proposition.** Définir l’éligibilité depuis les consommateurs durables du résultat, puis purger
par lots bornés. Protéger attentes, notifications et preuves de livraison ; offrir un aperçu.
La purge des runs est désactivée par défaut, ce qui limite actuellement l’exposition.

**Acceptation.** Résultat terminal non consommé protégé, résultat consommé purgeable ; une reprise
après arrêt prolongé réussit même si la rétention et la réconciliation démarrent simultanément.

### R10 — P1 — Un appel multimédia lent retarde tous les Process de sa file

**Établi par lecture.** `process_start_jobs`, ligne 1533, traite dix jobs séquentiellement ;
`refresh_active_runs`, ligne 1163, fait de même pour cent runs. Le moteur multimédia autorise
660 secondes par opération. Les jobs périodiques, enregistrés dans `app/process/__init__.py:50`,
ont 900 secondes au minimum avec les valeurs par défaut. Deux générations synchrones lentes
peuvent donc retarder les autres moteurs et faire expirer le lot au milieu d’une soumission.

**Proposition.** Petite concurrence bornée avec une session DB par branche, équité entre moteurs
et propriétaires, leases de jobs adaptés à la durée réelle et délais globaux cohérents. Garder
la réservation durable avant toute requête facturable.

**Acceptation.** Une génération lente ne bloque pas le démarrage d’un Process court indépendant ;
expiration/restart du worker sans double soumission. Mesurer la latence de file par moteur.

### R11 — P1 — Une panne de consultation peut être confondue avec l’échec définitif du travail distant

**Établi par lecture.** `process_service.py:1213` transforme un run en `error` après
`PROCESS_REFRESH_MAX_FAILURES` erreurs, dix par défaut. Les terminaux sont ensuite exclus du
polling. Un fournisseur multimédia ayant accepté un travail peut finir pendant une panne réseau ;
Galaris cessera pourtant de rechercher son résultat et aura échoué les tâches en attente.

**Proposition.** Distinguer résultat métier terminal et incapacité d’observation. Conserver
l’identifiant distant, utiliser un état dégradé/incertain, un backoff et une reprise explicite.
La disponibilité de l’application ne doit pas dépendre d’un poll réussi ; la commande humaine
peut abandonner l’attente sans prétendre annuler une facturation distante.

**Acceptation.** Fournisseur indisponible plus longtemps que dix polls, puis revenu avec succès :
résultat récupérable et aucun nouvel appel de génération.

### R12 — P2 — Le multimédia évite la duplication mais manque d’un chemin complet de réparation

**Établi par lecture et tests existants.** `app/multimedia/engine.py` mémorise une soumission,
puis des reçus de sortie. `delivery_started=True` sans URI retourne durablement
`delivery_unknown` ; les octets sont conservés en base. Il n’existe pas ici de commande dédiée
permettant de rattacher une destination vérifiée ou de reprendre une livraison dont l’absence a
été prouvée. `_receive` utilise aussi une séquence SELECT/INSERT avant la contrainte unique
`(run_id, ordinal)` : deux refresh concurrents demandent un traitement explicite de cette course.

**Proposition.** États de livraison par artefact, prise de travail atomique, manifestes de sorties
persistés tôt, rattachement d’URI contrôlé et reprise idempotente lorsque le provider de fichiers
le permet. Conserver le refus de répéter une génération possiblement payée. Ajouter version et
validation aux métadonnées de checkpoints propres à cet engine.

**Acceptation.** Coupures après admission, après téléchargement, après création distante et avant
commit local ; un refresh UI simultané au scheduler ne corrompt pas les reçus. Les fichiers déjà
livrés restent identifiables et les autres réparables sans nouvelle génération.

### R13 — P1 — `max_bytes` n’est pas transmis jusqu’au téléchargement

**Reproduit.** `app/file_share/resource_service.py:899` contrôle les métadonnées avant transfert,
puis appelle `download_to` sans transmettre `max_bytes`. Il vérifie la taille réelle seulement
après le retour. Un provider sans taille fiable peut donc télécharger 1 000 octets malgré une
limite de 10, puis seulement être rejeté et nettoyé. Le transport HTTPS a sa propre borne de
512 MiB ; ce n’est pas la limite demandée par l’appelant. Le canal raw du manager n’a pas de borne.

**Proposition.** Faire porter au contrat de transport une limite d’octets consommés et une échéance
globale, appliquées pendant le stream. Les métadonnées et `Content-Length` restent des indications.
Étendre la garantie à toutes les matérialisations, y compris Messenger et console.

**Acceptation.** Taille absente ou mensongère, flux compressé, source qui grossit et flux lent :
arrêt à la limite effective, nettoyage et libération des connexions, sans attendre tout le fichier.

### R14 — P2 — Les limites par fichier ne bornent pas la mémoire totale du backend

**Risque établi dans les chemins de code, sans test de saturation ici.** Telegram et WhatsApp
lisent des fichiers entiers avec `Path.read_bytes` dans leurs méthodes async. OpenRouter et
Mammouth font lecture + base64 ; les générations peuvent garder plusieurs sorties de 100 Mo,
puis les receipts ORM binaires. Ces allocations se cumulent entre requêtes. L’extraction PDF
dispose déjà de deux slots et de limites de processus : ce point n’est pas à redéclarer absent.

**Proposition.** Admission par octets et nombre d’opérations, streaming quand les SDK le permettent,
travaux disque/encodage hors boucle async, plafonds par moteur et propriétaire. Conserver un
stockage durable des sorties à réparer ; ne pas le remplacer par un temporaire perdu au restart.

**Acceptation.** Charge mixte médias, login et renouvellement des leases : mémoire plafonnée,
latence mesurée et aucun bail perdu uniquement à cause d’un encodage ou d’une lecture disque.

### R15 — P2 — Les réponses obsolètes ne sont pas écartées dans tous les stores

**Reproduit sur les vrais stores.** `front/app/goal/stores/goalStore.ts:156` accepte une ancienne
réponse de détail et remplace l’objectif sélectionné plus récemment, avec ses cycles. Les gardes
de révision protègent une entité, pas la sélection de l’utilisateur. `chat/stores/inbox.ts:95`
réécrit le compteur après `stop`, ligne 260, si une requête ancienne revient. Les stores Task
et Process disposent déjà de protections : étendre cette garantie au reste des vues.

**Proposition.** Identité de sélection + génération de session/requête, annulation utile et garde
avant chaque mutation, y compris états d’erreur et chargement. Auditer liste, filtres, détails,
fermeture de modale et callbacks WebSocket.

**Acceptation.** Réponses inversées A/B, changement de compte, fermeture, désabonnement et refresh
simultané ; aucun contenu, compteur ou état de chargement appartenant à l’ancienne sélection.

### R16 — P2 — Coordonner le cycle de vie du gestionnaire et les opérations de fichiers

**Établi par lecture, matrice de pannes à compléter.** `harness_manager/main.py` n’a pas de verrou
commun pour `create_instance`, actions Make, uploads et suppression/recréation. L’upload atomique
protège l’ancien fichier, mais pas l’identité d’une instance qui change pendant le transfert.
`_run_make`, ligne 203, ne définit pas de stratégie de terminaison du groupe de sous-processus.
La suppression peut continuer après échec de l’arrêt du runtime.

**Proposition.** Sérialiser les transitions par identité/génération d’instance ; réserver les
opérations de fichiers contre suppression ; limiter transferts et commandes ; journaliser les
nettoyages différés sans réutiliser un runtime résiduel comme instance neuve. Arrêter explicitement
les descendants d’une commande expirée et vérifier le résultat Docker.

**Acceptation.** Upload/delete/recreate et start/stop simultanés, timeout Make avec enfant actif,
échec de suppression de volume et espace disque plein. Aucun ancien travail ne modifie la nouvelle
instance ; les restes sont visibles et réparables.

### R17 — P2 — La reconstruction sémantique Memory reste globale et comporte du N+1

**Établi par lecture, pas un benchmark de saturation.**
`back/app/memory/semantic_index.py:207` charge tous les éléments et projections courantes en
mémoire, puis `_ensure_index_job`, ligne 133, fait un SELECT par élément à mettre en file et une
insertion conditionnelle. Deux réconciliations concurrentes peuvent viser la même clé unique.
Le benchmark de recherche déjà amélioré ne mesure pas cette reconstruction.

**Proposition.** Pagination par clé, opérations groupées et UPSERT de jobs, transactions courtes
et reprise persistée. Séparer progrès de reconstruction et disponibilité de la recherche lexicale.

**Acceptation.** Corpus volumineux, changement de modèle, double déclenchement et crash au milieu :
mémoire et taille des lots bornées, pas de doublon, compteur de progrès fidèle.

## Consolidation structurelle et exploitation

### R18 — P2 — Définir la rétention à partir des usages, pas seulement de l’âge

`app/llm/retention.py` protège volontairement tous les appels liés aux Tasks tant qu’une Task
reste active quelque part. C’est conservateur, mais une installation constamment occupée peut
ne jamais libérer ces traces. `UserRefreshSession` accumule des rotations sans purge dédiée ;
les octets de reçus multimédia incertains peuvent aussi rester indéfiniment.

Proposer des politiques distinctes pour données métier, résultats consommés, comptes rendus,
traces et secrets expirés. Conserver les preuves nécessaires à la sécurité, à la reprise et à la
comptabilité. Ajouter aperçu, export, lots et métriques de volume ; tester les racines encore
actives et l’expiration des familles de sessions. Corriger R09 avant d’étendre les purges.

### R19 — P2 — Tester puis promouvoir exactement les images livrées

Le bundle immuable et ses identités existent. Toutefois le workflow
`.github/workflows/release-artifact.yml` exécute les suites avant de construire ce bundle ; il
scanne ensuite les images exportées mais ne rejoue pas les workflows sur celles-ci. L’import
de production dans `bin/build-release.sh` est utile, mais n’est pas un test applicatif complet.
`make update` suit encore son propre chemin pull/build/restart.

Proposer une chaîne build → tests des images exactes → scan → export/promotion, avec version
affichée et manifeste commun. Inclure ou référencer explicitement les images de harnais gérées,
aujourd’hui hors du bundle des quatre services. Critère : les identités testées sont celles
déployées et le chemin usuel d’update permet cette promotion sans reconstruction implicite.

### R20 — P2 — Rendre l’upgrade et la restauration représentatifs d’une vraie livraison

`bin/test-upgrade.sh` monte l’ancien code dans l’image backend du candidat ; il ne vérifie pas
l’ancienne combinaison code/dépendances. `UPGRADE_FROM` vaut `HEAD` par défaut ; en CI `HEAD^`
n’est pas forcément la version déployée. La restauration canari prouve des éléments utiles,
mais ne mesure ni cohérence sous écritures concurrentes, ni récupération de tous les harnais,
ni retour arrière complet après changement de schéma.

Proposer une référence de release précédente explicite, son image authentique, un jeu de données
représentatif des transitions, et une restauration coordonnée DB/fichiers/clés/harnais. Fixer puis
mesurer la perte de données admissible et le délai de reprise. Un rollback d’images n’est autorisé
comme procédure fiable qu’après preuve de compatibilité du schéma ou restauration associée.

### R21 — P2 — Réduire le couplage avec des contrats plus petits

L’architecture autorise encore **294 imports privés** dans la baseline, **27 paires directes**
de domaines et une composante cyclique de **18 modules** ; sept paires directes existent côté
frontend. Ces chiffres sont une dette admise, pas des erreurs que le check serait censé refuser.

Prioriser les relations `llm/memory`, `tools/connection`, puis les chemins partagés
`file_share/messenger/process`. Extraire ports, DTO et enregistrements au bootstrap en gardant
un propriétaire clair par effet. Réduire la baseline après chaque extraction ; vérifier les
imports à froid et les fonctions réellement exercées. Éviter un package « common » qui
concentrerait simplement toutes les dépendances.

### R22 — P2 — Découper les unités difficiles à raisonner

L’inventaire donne notamment : Memory service **4 075 lignes**, Lab mécanismes **2 963**, page
Goal **2 822**, page Agent **2 478**, planner **2 325**, façade file-share **2 307**. Certaines
fonctions sont elles-mêmes très longues : Hermès `_stream` **649 lignes**, conversation interne
`run` **547**, proxy Chat LLM **468**. La longueur n’est pas une preuve de bug, mais augmente le
coût des vérifications de branches, d’annulation et de reprise.

Extraire progressivement préparation, exécution, interprétation, persistance et présentation,
en commençant par la page Agent après R01 et par les chemins touchés par R06/R10. Conserver des
tests de caractérisation avant déplacement ; chaque extraction doit simplifier une responsabilité
et réduire le nombre d’états locaux à comprendre simultanément.

### R23 — P2 — Étendre les contrats typés aux frontières durables et externes

WorkingSet et ExecutionResult possèdent déjà leurs versions. Plusieurs frontières de Process
et multimédia reposent encore sur des dictionnaires et clés littérales, ainsi que sur la forme
implicite d’une réponse fournisseur. Le typage Python strict ne garantit pas ces données après
lecture de JSON historique.

Proposer des schémas versionnés pour snapshots/checkpoints durables et erreurs de transport,
des unions explicites pour succès/en cours/incertain/refus, et des adaptateurs de compatibilité.
Tester champs absents, versions antérieures/futures et incohérences. Une donnée facultative
ancienne ne doit pas bloquer toute l’application ; un effet non idempotent ambigu exige en
revanche une reprise sûre. Compléter les deltas DbAdmin typés avant d’automatiser transformations
de type, contraintes ou index aujourd’hui non décrits dans `SchemaTransitionSet`.

### R24 — P2 — Compléter les tests par les séquences qui échappent aux suites actuelles

Les contre-exemples de cette revue passent entre les mailles de suites pourtant nombreuses.
Le test de refresh « concurrent » existant enchaîne notamment deux requêtes successives ; il
ne reproduit pas les verrous simultanés de R02. Une partie des tests frontend vérifie des regex
dans les sources : utile pour certaines conventions, insuffisant pour le cycle de vie réel.

Prioriser transactions indépendantes, ordres de réponses inversés, crash après effet/avant reçu,
tests de propriétés des transitions et mutations de gardes. Étendre les parcours navigateur à
Goal, Process, documents, paramètres et changements de compte ; conserver les tests AST pour
l’architecture. Automatiser la détection des propriétés i18n dupliquées : le compilateur explicite
en relève trois dans Chat alors que la parité des catalogues passe.

Mesurer la couverture par contrats critiques et les branches d’échec, sans présenter la couverture
partielle existante comme celle de tout le produit. Ajouter progressivement un lint TypeScript/
Vue et élargir Ruff ; le formatage massif n’a pas priorité sur les défauts reproduits.

### R25 — P2 — Superviser la progression réelle et tester la saturation

Le superviseur sait observer ses racines, la boucle et la DB. Cela ne prouve pas qu’un travail
particulier avance : une coroutine périodique vivante peut attendre longtemps un fournisseur.
Le navigateur de R05 illustre aussi la différence entre processus vivant et service disponible.
Les plafonds budgétaires Tasks sont des contrôles d’admission et des estimations, pas une limite
garantie de facturation pour tous les appels, notamment les Process détachés.

Proposer des indicateurs d’âge du plus vieux travail, absence de progrès, renouvellement des
leases, taux de résultats incertains, délai de livraison, mémoire/temporaires et attente du pool
SQL. Définir quelques objectifs de service et seuils d’alerte avec une procédure de réparation
testée. Vérifier les chemins voix/WebRTC, scheduler, fichiers et modèles ensemble sous charge
bornée. Conserver `degraded` pour une intégration facultative indisponible ; éviter de faire
tomber toute l’application sur une dégradation locale.

## Couverture des domaines et axes complémentaires

| Surface | Examen et vérifications | Suite proposée |
|---|---|---|
| Core API, auth, RBAC, WebSocket | Middleware, sessions, protections de routes, tests HTTP/DB et frontières | R02/R03 ; matrices rôle/compte/révocation et connexions longues |
| Base, DbAdmin, datasets | Orchestration, phases, journal, staging et tests PostgreSQL ; upgrade réel du code précédent | R08/R23 ; compatibilité multi-livraisons et gros backfills |
| Agent, Harness, Task, Goal | Contrats, scheduler, leases, budgets, chemins de reprise ; suite complète | R10/R21/R22/R23 ; matrice de crash de chaque driver |
| Process, Tools, MCP, Connection | Soumission, refresh, callbacks, contrats de ressources et rétention | R06/R09–R13 ; admission par moteur et résultats incertains |
| Multimédia et fournisseurs LLM | Contrats, engines, HTTP, receipts, supports/capabilités et tests | R10–R14 ; essais contractuels contre fournisseurs réels avec budget explicite |
| Messenger, Chat, Conversation | Journal, livraisons, stores, types, reconnexion, PWA ; E2E multiengines | R03/R06/R07/R15 ; erreurs entre protocole et reçu |
| Bridges conversationnels | Telegram/WhatsApp/Nextcloud approfondis, autres transports et suites inventoriés/testés | Matrice commune par bridge, médias et messages multiparties |
| Audio, image, voix/WebRTC | Matérialisation, limites et lieux d’allocation ; suites existantes | R13/R14/R25 ; appels longs, charge CPU et déconnexion réseau réelle |
| Memory, documents, Contact, Topic | Services, index, projections et frontend ; tests/ACL, restore et upgrade | R17/R18/R22 ; corpus volumineux, concurrence édition/indexation |
| Dream, Lab, Dashboard, Onboarding | Inventaire et tests ; tailles/relations/points d’entrée | Tests fonctionnels ciblés supplémentaires, grands lots et reprise de jobs |
| Mail, Calendar, n8n | Contrats, reçus/jobs et suites du dépôt | Parité de reprise des effets et restauration avec comptes de test distants |
| Console et SSH | Registre, frontières et tests multi-UID/concurrence | Pannes système, disque plein et restauration des homes |
| Browser et manager de harnais | Suites + contre-exemples avec vrais fichiers/processus | R04/R05/R16 ; terminaison et générations d’instances |
| Front core/app/bridge | Inventaire complet, contrôle négatif des types, stores, grandes vues, E2E | R01/R03/R15/R22/R24 ; accessibilité et responsive sur l’ensemble des parcours |
| Compose, images, Make, CI, sécurité | Lecture des chemins de build/update/scan, suites et répétitions isolées | R19/R20 ; vérifier les protections de branches et tester les artefacts exacts |
| Documentation et skills | Confrontation aux contrats et cartographie ; historique des corrections | Actualiser les promesses de typage/concurrence, ne pas certifier une surface seulement inventoriée |

Cette matrice précise les niveaux d’examen : « suite passée » ou « inventorié » ne signifie pas
que chaque méthode du domaine a été relue ni que son service externe est validé.

## Ordre de réalisation proposé, avec protection contre les régressions

| Lot | Contenu | Condition de clôture |
|---|---|---|
| 1 — Validation et identité | R01, R02, R03 | Contrôles réellement exécutés ; mutations négatives détectées ; courses auth interdites |
| 2 — Fichiers et exécuteurs | R04, R05, R13, puis R16 | Pas de franchissement de racine, limite effective en stream, reprise après crash |
| 3 — Effets externes et DB opérationnelle | R06–R12 | Aucun renvoi aveugle, aucun faux succès, résultats récupérables ; DbAdmin facultatif non bloquant |
| 4 — Interface et charge | R14, R15, R17, R18, R25 | Réponses obsolètes écartées, mémoire et files bornées, purges compatibles avec la reprise |
| 5 — Livraison et entretien | R19–R24 | Artefacts exacts validés, restauration mesurée, couplage réduit et contrats durables testés |

Faire des changements limités à un contrat, avec un test qui échoue avant et passe après.
Pour les états durables, tester les anciens enregistrements et le restart ; pour les fichiers et
réseaux, injecter la panne entre effet et commit. Après les tests ciblés, exécuter les portes
réellement applicables, puis les suites de risque correspondantes. Aucun refactoring global
n’est nécessaire pour fermer d’abord les défauts prioritaires.

**Principe DbAdmin conservé :** une colonne obligatoire impossible à remplir immédiatement
est créée nullable, l’écart est visible et non bloquant, puis la prochaine convergence resserre
la contrainte après remplissage. Seuls les prérequis indispensables et la protection des données
justifient l’arrêt ; une contrainte plus parfaite ne vaut pas une application inutilisable.

Les sondes et leur mode d’emploi figurent dans
[le dossier de preuves](2026-09-06-review-evidence/README.md). Elles documentent l’état audité ;
ce ne sont pas des corrections, ni des tests permanents destinés à exiger que les bugs restent.
