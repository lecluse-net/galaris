# Corrections du contre-audit du 6 septembre 2026

Référence : [contre-audit détaillé](2026-09-06-quality-reliability-review.md),
base `3062cf45f56f0dd97b49e42e0e5ef59c2b7d1d92`. Corrections dans le worktree,
sans commit ni déploiement. Les preuves historiques restent inchangées : leurs
assertions reproduisent volontairement les anciens défauts.

## Traitement point par point

| Point | Modification et preuve |
|---|---|
| R01 — TypeScript | Projets app/bridge/node réellement contrôlés, 180 diagnostics corrigés sans désactiver le mode strict ; canaris négatifs de typecheck **et build** ; builds de production réussis |
| R02 — révocation | Verrou utilisateur partagé par création, rotation et révocation ; 10 courses PostgreSQL indépendantes dans les deux ordres, incluant MFA ; changement de sécurité atomique |
| R03 — session navigateur | Génération partagée, Web Locks, rejet des anciennes réponses et des retries inter-comptes, hooks logout bornés ; synchronisation entre onglets et recharge de l’identité après changement de rôle ; vrais cookies vérifiés sur trois navigateurs |
| R04 — fichiers manager | Ouverture par descripteurs sans suivi de liens, inode retenu avant émission des en-têtes, écritures atomiques ; substitutions concurrentes de chemins testées |
| R05 — Chromium | Déconnexion inattendue du navigateur provoquant un arrêt Node en échec et borné ; test tuant réellement Chromium puis vérifiant une nouvelle instance saine |
| R06 — Telegram | Pas de retry automatique des mutations après une issue ambiguë ; distinction avec les lectures sûres et le rejet explicite de débit |
| R07 — WhatsApp/Nextcloud | Mutations ambiguës signalées par `DeliveryOutcomeUnknown` ; suppression des faux succès et retries aveugles ; suites des bridges exercées |
| R08 — DbAdmin | Criticité historisée, succession `compatible_checksums`, action facultative incompatible différée avec préservation des sources ; matrice de compatibilité et transitions PostgreSQL |
| R09 — rétention Process | Protection des consommateurs avant sélection du lot, des attentes Task, notifications et reçus multimédia ; aperçu administrateur ; lots sans famine par lignes déjà purgées |
| R10 — files Process | Jobs indépendants par moteur, quatre branches avec sessions propres, alternance des agents ; baux adaptés au délai moteur ; admission lente et worker concurrent testés sans double soumission |
| R11 — observation distante | `unknown` et backoff sans fabriquer un terminal ; identifiant distant conservé ; récupération après douze erreurs d’observation testée |
| R12 — multimédia | Manifeste et identité des sorties durables, UPSERT unique, un BLOB chargé à la fois, bail de livraison ; réparation avec preuve et SHA-256, idempotence par tentative ; refus HTTP et périmètre Agent testés |
| R13 — matérialisation | Limites propagées aux transports, comptage avant écriture, délai global et suppression du partiel ; MIME Mail borné avant lecture et descripteur sans téléchargement ; pagination textuelle incrémentale |
| R14 — buffers | Admission globale en octets/opérations et par identité ; lectures/encodages déplacés hors boucle ; fichier grossissant borné à la lecture ; réservation Mail conservée jusqu’à la fin du thread |
| R15 — UI obsolète | Générations Goal, arrêt Inbox et cycle de vie des journaux de harnais ; réponses inversées, erreur tardive et fermeture de sélection testées sur les vrais modules TS/Vue |
| R16 — manager | Verrous d’identité inter-processus, conflits 409, conservation après échec Docker, limite upload et terminaison du groupe de processus ; 23 tests |
| R17 — index sémantique | Pages de 250, écritures groupées, UPSERT ; fingerprints et jobs commités ensemble ; reprise après interruption d’un lot et double reconstruction réelle de 601 éléments sans doublon |
| R18 — rétention | Portée causale des Tasks pour les traces LLM ; purge des refresh expirés depuis sept jours ; preuves non expirées et octets multimédia incertains préservés |
| R19 — images exactes | Overlay E2E sans montage du code applicatif, vérification des IDs, tests des exécuteurs exacts, scans et manifeste de qualification ; `make update RELEASE_DIR=...` sans rebuild ; harnais inclus ou explicitement externes |
| R20 — restauration | Ancienne image explicite en CI, sauvegarde coordonnée et retour arrière avec ancien schéma/code ; essai local entre deux véritables images de production passé, dont celle du commit initial |
| R21 — frontières | Suppression de LLM→Memory, ports publics Tools/Connection, filtres de consommateurs enregistrés au bootstrap ; baseline de 294 à 292 imports privés, de 27 à 26 paires bidirectionnelles |
| R22 — responsabilités | Extractions workers/rétention Process, checkpoints/réparation multimédia et composable des journaux Agent ; contrôles de formatage étendus aux douze nouveaux modules |
| R23 — contrats durables | Checkpoint multimédia versionné, données historiques sans version acceptées comme v1, version future refusée pour le seul run ; deltas avant/après types/défauts/index/FK testés sur PostgreSQL |
| R24 — tests | Courses avec transactions indépendantes, crash réel, inversions UI, assertions HTTP strictes remplaçant un test acceptant des 404, détection AST des clés i18n dupliquées ; parcours Goal/Process/Documents/Préférences et changement de compte |
| R25 — exploitation | Âges des files, observations, notifications, leases expirés, buffers réservés et occupation du pool ; test de charge contrôlée combinant login, huit lectures concurrentes, copie de 4 Mio et renouvellement réel d’un lease ; procédures FR/EN et seuils initiaux |

## Disponibilité et sécurité conservées

Une colonne NOT NULL sans défaut sur une table remplie est ajoutée **nullable** avec
un diagnostic explicite non bloquant. Le remplissage peut continuer dans l’application ;
la synchronisation suivante resserre la contrainte. Les objets indispensables et les
transformations destructives non prouvées conservent leurs protections.

La règle serveur de grâce/rejeu des refresh tokens reste inchangée. Une extension de
récupération des anciens jetons a été refusée par le contrôle automatique et n’a pas
été appliquée. Le correctif retenu utilise le transport navigateur `fetch/keepalive`,
les générations et la sérialisation des opérations. Les tests distinguent navigation
interne par les vrais menus et restauration d’une session par rechargement.

La suite globale a également révélé une famine des compteurs Messenger : chaque lecture
fournisseur a maintenant son propre délai, en plus du délai global, afin de libérer les
places pour les connexions suivantes.

## Validation du premier lot

- `make typecheck lint format-check` : Pyright strict sans diagnostic, 370 tests frontend,
  parité de 4 516 paires anglais/français et contrôle des traductions chinoises ; lint et
  les 18 modules soumis au formatage conformes.
- `make architecture-check` : contrats satisfaits et 27 tests d’architecture passés ;
  cartes françaises et anglaises régénérées.
- `make tests-harness-manager tests-browser tests-executor` : 23 / 13 / 9 tests passés.
- Exécuteurs exacts sans montage du code : Browser 13 tests, SSH 9 tests passés.
- `make tests-restore` : PostgreSQL, fichiers, clés et canaris de harnais restaurés ;
  exercice local de 32 secondes.
- `UPGRADE_PREVIOUS_IMAGE=<ID de l’image 3062cf45> UPGRADE_CANDIDATE_IMAGE=<ID candidat>
  make tests-upgrade` : convergence, API document/pièce jointe, refus ACL, seconde
  synchronisation et restauration sous l’ancienne image passés ; phase candidate 24 s.
- Scans des quatre images candidates : aucun HIGH/CRITICAL avec correctif disponible.
  Inventaires sans correctif disponible : backend 251, frontend 0, Browser 2, SSH 200.
  Les rapports complets sont sous `artifacts/security/` ; ce résultat ne signifie pas
  absence de vulnérabilités connues.
- `make tests` : **3 286 tests passés**, 8 avertissements de dépendances, en 153,62 s.
- `RELEASE_DIR=<manifeste des images candidates> make tests-e2e` : **48 tests passés**
  sur Chromium, Firefox et WebKit en 2,7 min, sans retry automatique.
- `make project-context-check` et `git diff --check` : conformes après les dernières
  corrections documentaires.

Les images locales portent le tag `audit-working-tree`, avec IDs vérifiés avant les
scénarios. Elles qualifient ce travail non commité, sans prétendre constituer une release
archivée depuis un commit. La CI de release exige la véritable image précédemment déployée.

Identités des images testées et scannées :

```text
backend  51a51b83456fbe3ee1686acd3814f5ef2e760ead312c9bc3b548fbac39579df8
frontend c11e114620d31ab1df19fb3f01fa5aade2cfa861931123092f4ef6e1f621b5c3
browser  e4c2dd9ba672a0e7bf704149607112cd98933d3f32ef9260257dcc3177b30651
ssh      50febd72f4c72dbccf703d663c8f74469463b53fc476b71bf5229123be24eca0
```

## État après le complément du 7 septembre

Le [bilan de clôture technique](2026-09-07-review-completion.md) décrit les compléments et
leurs validations. Les chiffres ci-dessus sont les preuves du premier lot, conservées
pour distinguer les exécutions.

## Limites de la qualification

L'admission borne les opérations binaires prises en charge, y compris le décodeur vocal,
mais pas toute la RSS ni la facture fournisseur. La charge locale comprend maintenant du
WebRTC réel ; elle ne qualifie pas le réseau TURN ni les comptes fournisseurs d'une installation.

Les rétentions restent conservatrices devant une livraison sans preuve. Les deltas SQL
observés ne prouvent pas une conversion sans perte. Après interruption, l'index sémantique
rescane les pages ; ses jobs commités et leurs clés assurent la reprise sans curseur global.

L'audit demandait une réduction progressive des couplages et responsabilités, pas une remise
à zéro arbitraire de la baseline. Cette réduction est vérifiée : 294 → 284 imports privés,
27 → 25 paires bidirectionnelles, composante cyclique 18 → 17 domaines. Les grandes unités
historiques demeurent une dette de maintenance ; elles ne sont pas présentées comme réécrites.
Le lint JavaScript/TypeScript/Vue est désormais bloquant dans Make, la CI et le build frontend.

La qualification d'un upgrade de production exige la référence immuable réellement déployée
et le volume de cette installation. En l'absence de cette référence, les essais locaux entre
images de production ne sont pas assimilés à une certification de l'installation distante.
