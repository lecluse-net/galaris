# Corrections de la revue A01–A18

Travail du 7 septembre 2026, demandé après la
[revue post-commit](2026-09-07-postcommit-quality-review.md). Aucun commit ni déploiement
n'est effectué par ce lot. Les sondes historiques décrivant les défauts restent inchangées ;
les tests produit vérifient désormais le comportement corrigé.

## État après achèvement des compléments locaux

Les compléments locaux A12, A13, A16 et A17 sont réalisés et testés. La qualification A18
sur l'installation réelle reste ouverte : la cible, les volumes représentatifs et le monitoring
ont été demandés mais ne sont pas identifiés. Une stack de développement ne constitue pas
une cible de production. Aucun fournisseur payant n'est appelé.

| Point repris | Résultat et preuve |
|---|---|
| A12 | Douze semaines simulées, 2 016 appels, plateau de 420 traces / 1 720 320 octets logiques ; après consommation, zéro trace brute et coûts/tokens conservés. [Rapport](2026-09-07-closure-evidence/llm-retention-growth.json). |
| A13 | Sur 100 puis 1 000 documents et 10 000 puis 100 000 révisions : quatre requêtes par page de 50, aucune révision ORM chargée, pic Python de 2,22 puis 2,00 Mo. ACL et facettes vérifiées. [Rapport](2026-09-07-closure-evidence/memory-library-benchmark.json). |
| A16 | Lab séparé en claim / inférence / publication avec DTO détachés ; bibliothèque et projection Memory extraites ; composable Process propriétaire des actions, du dialogue et du polling. Tests des leases remplacés, snapshots copiés, fermetures et erreurs tardives. Un import privé retiré de la baseline. |
| A17 | 100 000 lignes, 423 écritures concurrentes, attente de verrou PostgreSQL observée ; mesures séparées pour expansion, backfill, resserrement, indexation et rejeu. [Rapport](2026-09-07-closure-evidence/dbadmin-volume-benchmark.json). |
| A18 | Nouvelle qualification locale des images réussie ; qualification de l'installation, activation des alertes distantes et essais des services externes encore dépendants des accès/informations manquants. |

Le scénario DbAdmin dure 3,94 s : expansion nullable 0,61 s, backfill 0,14 s,
resserrement 0,65 s, indexation 0,95 s et rejeu 0,42 s. L'attente maximale de l'écrivain
pendant le verrou provoqué atteint 0,22 s. Les phases de convergence incluent inspection
et planification Atlas ; ces mesures locales ne prédisent pas les temps de production.

## Vérifications des compléments

- Suite backend complète : **3 360 passés**, un scénario opt-in ignoré, 170,73 s.
- Pyright et vue-tsc : aucune erreur ; **398 tests frontend passés**, parité de 4 517 messages.
- Couverture critique étendue aux phases Lab : **78,30 %**, 579 tests passés, un opt-in ignoré.
- Lint, formatage des 36 modules et architecture : conformes ; 27 tests d'architecture passés.
- Sécurité du source : Trivy conforme et 79 règles Semgrep sur 1 147 fichiers, aucun résultat.
- Images exactes : upgrade/restauration réussis ; **48 E2E passés** sur trois navigateurs,
  17 tests Browser et 9 tests SSH. Scans HIGH/CRITICAL : **251 / 0 / 2 / 200** avis sans
  correctif, aucun correctif disponible laissé non appliqué.

La [qualification finale locale](2026-09-07-closure-evidence/QUALIFICATION.json) est liée à
la [preuve d'upgrade](2026-09-07-closure-evidence/UPGRADE_QUALIFICATION.json) et aux
[quatre digests exportés](2026-09-07-closure-evidence/IMAGE_IDS). Le backend corrigé est
`sha256:22e719d7c3d4577de81c1cc241bb9e7e3b25869fccdb377321bc7ed697f4f1c5`.
Le bundle `/tmp/galaris-close-bundle` est marqué comme worktree : il ne peut pas être promu
comme une release commitée. Les [comptages de sécurité](2026-09-07-closure-evidence/SECURITY_IMAGES.json)
restent des occurrences par image, pas un nombre de vulnérabilités distinctes.

Les rapports sous `2026-09-07-closure-evidence/` documentent ces compléments ; ceux sous
`2026-09-07-correction-evidence/` restent les preuves du premier lot. Les logs de cette
reprise sont sous `/tmp/galaris-close-*.log`. Les suites portent sur le worktree partagé,
dont d'autres modifications de prévisualisation ont évolué pendant cette reprise.
L'instantané des images est conservé sous `/tmp/galaris-close-source`, avec l'empreinte
de son inventaire dans [LOCAL_CHECKS.json](2026-09-07-closure-evidence/LOCAL_CHECKS.json).
Le commit indépendant `db1092d1` de prévisualisation est apparu pendant la qualification.
Une refonte Lab a ensuite commencé à modifier contrats, modèles et mécanismes ; elle est
préservée et ne bénéficie pas implicitement des résultats de l'instantané antérieur.

## Traitement point par point

| Point | Correction et preuve du contrat |
|---|---|
| A01 | Réservations propres et enveloppes enfants explicites, phases génération/livraison séparées, libération après drainage des enfants même en cas d'annulation. Une expiration d'admission locale remet le job en attente sans consommer de tentative fournisseur. Test avec **100 000 000 octets** dans le parcours réel Resource → Messenger → WhatsApp ; seul le transport distant est simulé. Telegram conserve sa limite propre, inférieure à 100 Mo. |
| A02 | Résultat fournisseur et identité des sorties persistés sous verrou, reçus idempotents, succès protégé contre une erreur tardive. Finalisation comptable verrouillée et monotone pour le multimédia. Tests de reçus concurrents et de succès suivi d'une erreur puis d'un doublon avec un coût différent. |
| A03 | Helper commun de drainage des I/O en thread, fermeture après fin des écritures, fsync du fichier et du répertoire. Nettoyage des créations annulées avec contrôle des références DB, y compris lorsque le commit a réussi mais son accusé est perdu. Tests aux phases écriture/flush/fsync/replace/répertoire. Inventaire d'orphelins paginé et suppression uniquement d'une liste revue, après arrêt explicite des écritures, contrôle d'ancienneté et des révisions historiques. |
| A04 | Délais par composant, suivi des callbacks encore vivants, reprise indépendante des autres composants et interdiction d'un second démarrage tant que le premier peut encore produire des effets. Tests de démarrage/arrêt non coopératifs. Le superviseur ne prétend pas pouvoir tuer une coroutine Python arbitraire : l'arrêt forcé du conteneur reste la dernière borne. |
| A05 | Expansion calendaire itérée avec plafond de 1 000 occurrences et fenêtre de 366 jours ; calcul isolé dans un processus limité à 256 Mio, 2 s CPU, 5 s de communication, deux calculs simultanés. Test du parseur réel sur 5 000 occurrences et maintien de la réactivité de la boucle. |
| A06 | Publication Lab extraite : relecture sous verrou, comparaison du jeton, prise en compte de l'annulation, résultat/compteurs/clôture atomiques et idempotents. Tests avec transactions PostgreSQL indépendantes. Le résultat terminé pendant une annulation conserve son coût ; le run reste annulé. Un worker remplacé n'écrit rien. |
| A07 | Génération de sélection appliquée aux actions Process et à la fermeture de la fiche, ainsi qu'aux erreurs tardives. Tests sur le vrai store Pinia : rafraîchir/annuler/supprimer/analyser A ne reprend pas la fiche B ou une fiche fermée. |
| A08 | Ensemble explicite des rooms souhaitées, réconciliation à chaque connexion, départ hors ligne et logout effectifs, sans accumulation de callbacks. Tests de reconnexion et de déduplication. |
| A09 | Masquage commun des credentials Atlas bruts, encodés et inclus dans les URL. Tests avec caractères réservés, conservation d'un diagnostic utile. |
| A10 | Réception TTS en flux avant accumulation, limite commune de 32 Mio et délai global de 90 s ; gzip/deflate décodés par blocs bornés. Téléchargement Media borné avant extension du tampon et soumis à un délai global. Tests sans Content-Length, flux lent, compression excessive et réponse compressée valide. |
| A11 | `Idempotency-Key` du webhook générique, identité composée outil/connexion/événement et empreinte du contenu. Même clé et même contenu : même Task ; contenu différent : 409 ; absence de clé : demandes distinctes. Tests HTTP et DB. |
| A12 | Libération positive des traces par Conversation et Process après consommation, conservation en cas de travail actif ou incertain et si le consommateur n'est pas enregistré. Aperçu des motifs via `/llm-calls/retention/preview`, privilège de purge et périmètre de gestion identique à l'historique. Les API de lecture/export existantes restent disponibles avant purge. Tests sur des traces de 60 jours, coûts conservés, attente Process et périmètres vides/restreints. |
| A13 | Bibliothèque documentaire sans chargement de toutes les révisions, facettes calculées en SQL, projection paginée des versions de contenu, pagination de l'historique générique. Frontend : 50 par défaut, choix `[10, 20, 50, 100, 500]`, chargement supplémentaire protégé contre les réponses d'une ancienne sélection. Test DB sur 1 001 révisions : seule la page demandée est matérialisée. |
| A14 | Preuve d'upgrade liée aux digests précédent/candidat, provenance des tests, convergence, restauration et limites du jeu de données. Qualification liée à cette preuve et à toutes les images ; promotion comparée au backend réellement installé. Un nouvel essai invalide l'ancien marqueur et une qualification de worktree ne peut pas être promue comme release commitée. |
| A15 | Manifeste de formatage partagé Make/CI, couverture étendue au moteur, stockage, superviseur et publication Lab, seuil de 70 % conservé ; règles de promesses frontend sur les frontières concernées. Quatre mutations de gardes détectées, dont enveloppe enfant et double démarrage. |
| A16 | Extractions effectives : observations fournisseur, publication Lab, projection des révisions, réconciliation du stockage, I/O en thread, réception HTTP et calcul calendaire. Les services délèguent ces responsabilités avec tests de contrat. La dette restante des grandes unités n'est pas déclarée éliminée. |
| A17 | Essai DbAdmin sur 100 000 lignes avec écrivain concurrent, verrou exclusif, interruption/reprise, ajout nullable, remplissage, resserrement, indexation et nouvelle convergence sans delta. Observation exacte des contraintes CHECK/exclusion PostgreSQL, sans inférer une équivalence SQL ni autoriser de nouvelle opération destructive. |
| A18 | Objectifs et règles d'alerte versionnés, essai mixte de 60 s, restauration coordonnée et qualification locale d'un couple d'images. La qualification de l'installation réelle reste distincte et nécessite son digest déployé, ses volumes et ses services externes. |

## Politique DbAdmin préservée

Une colonne NOT NULL sans valeur par défaut sur une table peuplée est ajoutée nullable,
avec diagnostic non bloquant. Elle peut ensuite être remplie et devenir NOT NULL lors
de la convergence suivante. L'observation supplémentaire des contraintes ne transforme
pas une convergence facultative en panne de démarrage. L'impossibilité de fournir un
objet indispensable ou de préserver les données reste un cas bloquant.

## Vérifications du premier lot (avant les compléments)

| Contrôle final | Résultat |
|---|---|
| Suite backend complète | **3 365 passés**, un scénario de volume opt-in ignoré, 173,03 s ; huit avertissements de dépendances |
| Types et frontend | Pyright et vue-tsc conformes ; **396 tests passés**, 4 520 paires FR/EN et messages chinois vérifiés |
| Lint et formatage | Conformes ; même manifeste de 31 fichiers pour Make et CI |
| Architecture | Cartes FR/EN à jour, contrats conformes et **27 tests passés** |
| Exécuteurs auxiliaires | Harness manager **26**, navigateur **17**, SSH **9** tests passés |
| Images de production exactes | Upgrade/restauration et **48 E2E passés** sur Chromium, Firefox et WebKit, 2,8 min ; tests Browser/SSH également rejoués dans les images exportées |
| Sécurité du source | Trivy conforme sur les dépendances/secrets ; Semgrep : **79 règles, 1 149 fichiers, aucun résultat** dans son périmètre configuré |

La [preuve d'upgrade](2026-09-07-correction-evidence/UPGRADE_QUALIFICATION.json),
la [qualification du bundle](2026-09-07-correction-evidence/QUALIFICATION.json) et les
[identités des quatre images](2026-09-07-correction-evidence/IMAGE_IDS) sont conservées.
Le backend candidat est `sha256:fe6d6402f39893360c7f2bc12929a3c62a624a6483050c057f3116f32ad62767` ;
l'ancienne image locale est `sha256:aac421515754afdd5870de4d963a4e357bdad7fd68f1b8d2f0a58fdee39da30c`
(source historique `3062cf45`, pas une attestation de l'image réellement déployée).
Le bundle local `/tmp/galaris-a18-bundle` est explicitement marqué comme qualification
de worktree ; il ne peut pas être promu comme une release commitée. La future release
doit être reconstruite depuis son commit puis qualifiée à son tour.

Les scans des quatre digests ne trouvent aucun avis HIGH/CRITICAL avec correctif
disponible non appliqué. Ils conservent respectivement **251 / 0 / 2 / 200** avis sans
correctif pour backend / frontend / Browser / SSH. Ce sont des occurrences par image,
pas un nombre de vulnérabilités distinctes sur l'ensemble de la plateforme.

Essais déjà exécutés sur ce lot :

- couverture étendue finale : **77,92 %**, 538 tests passés et un scénario de volume opt-in ignoré ;
- quatre mutations de gardes détectées, sans abaissement du seuil de couverture ;
- DbAdmin : **100 000 lignes**, interruption/reprise et convergence, 3,46 s pour le scénario ;
- charge mixte : **60,59 s**, latence p95 de l'identité 21,49 ms, hausse de RSS
  65 622 016 octets, retard maximal de boucle 92,31 ms, 2 754 trames WebRTC et lease renouvelé ;
- restauration quiescente : **26 écritures acquittées restaurées, aucune perdue**, essai local
  d'environ 48 s ; le transfert d'une sauvegarde distante et le délai de détection sont exclus ;
- livraison de 100 Mo par la chaîne WhatsApp réelle avec client distant simulé : réussie.

Les logs bruts sont conservés localement sous `/tmp/galaris-a18-*.log` ; les artefacts E2E,
de couverture et de sécurité sont sous `artifacts/`. Ces emplacements ne sont pas une
archive durable de production.

## Revue du worktree partagé et de l'architecture

La revue initiale portait sur `b8a8b8df`. Le commit indépendant `15881f3c` de réduction
de l'activité du navigateur est apparu pendant ce travail, ainsi qu'un refactoring des
prévisualisations et des modifications Browser/plans. Ils sont préservés. Les tests finaux
portent sur l'état partagé courant ; ils ne sont pas attribués artificiellement au seul lot A01–A18.

La baseline backend n'augmente pas. La revue explicite de la baseline frontend accepte
trois dépendances publiques liées à la prévisualisation : `app/chat → core/preview`,
`app/memory → core/preview` et `core/util → core/preview`. Les deux premières consomment
l'index public de composants ; la dernière consomme l'interface pure sans charger Vue.
Aucun import privé ni cycle supplémentaire n'est accepté. L'ancien import privé du
CodeEditor par la page Skill est retiré. Une assertion de test liée à l'ancienne grille
de pièces jointes est adaptée au conteneur flex actuel, en conservant ses dimensions vérifiées.
Les cartes FR/EN sont régénérées depuis le code.

## Limites et qualification de l'installation

Le manifeste d'[objectifs opérationnels](../../docs/fr/dev/operational-objectives.json)
définit seuil, durée, diagnostic et réparation. Il **n'installe pas des alertes dans un service
de monitoring distant**. Son activation doit être vérifiée sur l'installation concernée.

Les points A17/A18 ne certifient ni plusieurs jours de charge réelle, ni un réseau TURN
externe, ni les quotas ou contrats de tous les fournisseurs. Aucun appel payant n'est
effectué. Le digest réellement déployé et les volumes représentatifs ont été demandés ;
ils ne sont pas disponibles au moment de cette qualification locale. La sauvegarde à
chaud n'est pas annoncée cohérente sur la seule preuve d'une sauvegarde quiescente.

Les bornes mémoire concernent les buffers admis, pas la RSS totale du backend, et les
contrôles d'admission ne constituent pas un plafond de facturation fournisseur.
Les avis de sécurité sans correctif restent dans les inventaires des scans ; un gate vert
ne signifie pas absence de vulnérabilité connue.
