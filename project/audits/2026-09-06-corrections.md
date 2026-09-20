# Corrections de l’audit qualité et fiabilité du 6 septembre 2026

Référence : [audit initial](2026-09-06-quality-reliability.md). Modifications locales, sans
commit. Le correctif SSH et les ajouts DbAdmin ont été activés en développement. Ce suivi distingue les corrections réalisées, les tranches
structurelles livrées et les limites encore présentes ; il ne constitue pas une garantie
d’absence de régression sur les intégrations externes.

Les travaux multimédias et Mammouth apparus dans le même dossier ont été conservés. Une copie
isolée du commit initial, enrichie des seuls changements de cet audit, sert à distinguer les
résultats de validation. Les contrôles du dossier partagé sont également rapportés ci-dessous.

## Reprise après la contre-revue

Les éléments ci-dessous remplacent les constats historiques correspondants de la contre-revue :

- **Q01 activé** : exécuteur SSH reconstruit et recréé seul après vérification de l’absence de
  sessions et de baux actifs. Le backend disposait déjà du groupe 19999. Répertoire vérifié
  0770, socket 0660, root:19999 ; appels de gestion backend réussis, UID 65534 et 20000 refusés.
  Ancienne image conservée sous `galaris-ssh-executor:before-control-hardening-20260906`.
- **Q11, démarrage DB corrigé** : connexion et SELECT utilisent la même échéance absolue.
  Cinq tests réussis sur blocage, reprise et annulation, avec nettoyage du contexte.
- **Q02/Q04, preuves complétées** : import cassé empêchant tout appel Atlas/DB, échecs requis,
  optionnels et différés après expansion/après datasets, rollback et reprise ; 23 tests réussis.
  Les anciennes sections contradictoires des guides DbAdmin FR/EN et du skill ont été corrigées.
- **Q10, volume et pannes Chat testés** : pages de 10, 50 et 500 salons avec requêtes bornées ;
  sept fournisseurs simulés, concurrence maximale de quatre, pannes réseau, appels et fermetures
  bloqués, annulation du demandeur. Les clients actifs sont nettoyés et les comptes locaux restent disponibles.
- **Q21, notifications Task/Process ajoutées** : projection des notifications UNKNOWN dans le
  détail du tour, commande existante étendue, preuve persistée par tentative, refus des baux
  actifs, des liens hors tour et des décisions obsolètes. 58 tests Conversation réussis ;
  Pyright, vue-tsc et tests frontend passent. Parcours clavier validé sur Chromium, Firefox et
  WebKit : états de travail et nombre de messages inchangés, preuve enregistrée. Test HTTP réel
  des refus 401/403/404, résolution autorisée et conflit 409. Coupure après succès distant et
  avant commit local testée pour Task et Process : reprise UNKNOWN, aucun renvoi automatique.
- **Q20 étendu** : partage facultatif des plafonds entre cycles d’un même Goal et quota de
  concurrence par propriétaire. Les tâches archivées restent comptabilisées. Neuf tests DB
  couvrent temps/jetons/coût, réservations, connexions concurrentes, expiration et reprise.
- **Q09/Q15, défaut de rattrapage découvert et corrigé** : Firefox et WebKit pouvaient garder
  une réponse provisoire après coupure HTTP malgré sa persistance. Réconciliation séquentielle
  toutes les trois secondes tant que la réponse visible n’est pas durable ; arrêt à convergence,
  déconnexion ou destruction du store. Trois tests Pinia et six parcours de panne réussis.
- **Q15/Q25 étendus** : MFA et restauration de session, résolution de notifications, retour du
  focus et seuil mobile 1023/1024 testés sur les trois moteurs. Mise à jour réelle du worker et
  du shell PWA validée sur Chromium/Firefox/WebKit. Le test WebKit a révélé un gel lors de
  l’interrogation du service push sans autorisation de notification : cet appel est désormais
  évité. Les abonnements autorisés restent restaurés et les navigateurs sans Notification
  conservent leur boîte de réception. Cinq tests des vrais stores couvrent ces cas.
- **Limitation WPE identifiée** : la répétition triple a donné 125/126 succès, avec crash natif
  WebKit pendant MFA. Le défaut est reproductible sur WPE headless, même sans traces ni filtre
  graphique ; protocole `crashed: true`. Dix répétitions MFA passent via le port GTK officiel.
  La configuration Linux utilise donc GTK/Xvfb, sans exclusion de scénario ni relance automatique.
  Le défaut WPE reste ouvert ; aucune correction cosmétique n’a été conservée dans l’application.
- **Synchronisation dev effectuée** après inspection du dry-run, limité à l’ajout de la table
  `conversation_notification_resolutions`. `make sync-db` termine convergé, sans anomalie.
- **Q13, transport du bundle exercé** : export compressé des quatre images de validation
  (1,9 Go), rechargement avec comparaison des identités, puis refus d’un manifeste altéré avant
  chargement. Aucun service redémarré. Ce test ne transforme pas les changements non commités
  en artefact publiable ; les harnais gérés restent hors de ce bundle.
- **Validation globale de la reprise** : 3 228 tests backend réussis, puis 53 tests de résolution,
  coupure et isolation ; 356 tests frontend, typage strict et 4 516 paires de traductions vérifiés.
  Architecture : 27 tests et frontières valides. Couverture ciblée : 88,44 %, 70 tests.
  Navigateurs : **84/84 parcours Chromium/Firefox**, puis **42/42 WebKit GTK**, soit les 14
  scénarios répétés trois fois sur chaque moteur. Les dix répétitions MFA GTK et les six tests
  d’isolation supplémentaires passent également. L’ancien échec WPE reste conservé dans les preuves.

Journaux de cette reprise : `/tmp/galaris-followup-*.log`, avec copie des validations finales
dans `artifacts/quality-reliability/followup/`. Les traces E2E sont isolées par exécution sous
`artifacts/e2e/`, pour éviter qu’un essai parallèle écrase les preuves précédentes. Aucun commit créé.

## Critères encore ouverts après la reprise

**Le travail demandé n’est pas intégralement terminé.** Une réalisation dans chacune des
25 lignes ne signifie pas que tous les critères de l’audit sont satisfaits. Le bilan précédent
mettait trop en avant le nombre de tests réussis et pas assez les critères encore ouverts.
Les preuves de la reprise figurent ci-dessus. Les critères suivants restent à traiter ou
à valider ; les corrections démontrées ne sont plus présentées comme manquantes.

| Points | Critères encore ouverts ou preuve insuffisante |
|---|---|
| Q05–Q08 | Les tests de concurrence/reprise et les limites sont utiles, mais ne couvrent pas toutes les frontières de panne proposées, les courses upload/suppression/lifecycle, ni une charge de PDF complexes et d’authentifications concurrentes avec renouvellement effectif des leases. |
| Q09–Q11 | Rattrapage Chat, erreurs fournisseurs, pages 10/50/500 et délai global de démarrage DB validés. Toutes les fermetures de vues et la propagation d’échéance de bout en bout entre services ne sont pas couvertes. |
| Q13–Q14 | Transport des quatre images exercé, mais pas de bundle d’un commit contenant ces changements ni de toutes les images des harnais gérés. Pas de répétition complète du retour arrière, de sauvegarde sous écritures concurrentes, de reprise des harnais ni de mesure RPO/RTO. Le test d’upgrade réutilise les dépendances candidates pour l’ancien source. |
| Q15 | Parcours Chat, MFA, résolution des notifications, sanitizer et mise à jour PWA étendus aux trois moteurs, WebKit via GTK. Crash natif WPE headless toujours ouvert ; pas de validation Safari/iOS physique. Workflows complets Agent/Goal/Process/document encore partiellement couverts. |
| Q16–Q18 | Un cycle supprimé et plusieurs extractions/versionnements réalisés ; les autres cycles prioritaires, grandes unités et contrats JSON durables restent partiellement traités. |
| Q20–Q22 | Budgets Goal, quota propriétaire et résolution des notifications Task/Process ajoutés. Les réserves ne garantissent pas la facture finale ; aucune réconciliation distante automatique générale. Rétention limitée et très conservatrice, sans stratégie complète fichiers/messages/export. |
| Q23–Q25 | Signaux et portes ajoutés, mais toutes les mesures de saturation/progression et procédures ne sont pas couvertes ; avertissements de dépendances subsistants, protection GitHub non vérifiée, lint/format global TS/Vue et accessibilité de toutes les vues encore incomplets. Clavier, retour du focus et seuil mobile vérifiés pour le parcours de résolution. |

Cette liste décrit les limites actuelles, sans annuler les preuves déjà obtenues.

## Contrat DbAdmin

Une colonne obligatoire sans défaut sur une table remplie est ajoutée **nullable**, avec une
erreur explicite dans le journal et un résultat non bloquant. L’application peut renseigner les
valeurs ; la synchronisation suivante applique `NOT NULL`. Une contraction échouant après une
expansion utilisable est également non bloquante. L’expansion préserve les tables et colonnes
sources tant que les transformations ne sont pas terminées.

En revanche, un import de modèles cassé, une préparation indispensable en échec ou l’impossibilité
de créer les objets nécessaires arrêtent la synchronisation. Une cible incomplète ne doit pas
permettre de supprimer des données. Ces règles sont exercées sur PostgreSQL, avec reprises.

## Suivi point par point

| Point | Réalisation et portée |
|---|---|
| Q01 | Répertoire SSH root:groupe 19999 en 0770, socket 0660, contrôle `SO_PEERCRED` avant dispatch. Activation vérifiée en développement ; les UID 20000 et 65534 sont refusés, le backend reste autorisé. |
| Q02 | Absence facultative d’un module distinguée d’une erreur d’import transitive. Une erreur réelle remonte avant la génération d’une cible partielle. |
| Q03 | Les routers existants mais cassés empêchent le démarrage ; les modules sans router et les montages explicites des bridges restent supportés. |
| Q04 | Expansion conservatrice, barrière pour préparations indispensables, contractions différées et erreurs de resserrement non bloquantes. Tests d’échec, conservation des sources et reprise nullable → remplissage → NOT NULL. |
| Q05 | Verrou interthreads et interprocessus du registre SSH, réservation durable des UID avant effets système, temporaires uniques, remplacement atomique et fsync. Tests de concurrence et récupération après panne. |
| Q06 | Capacité réservée dès l’ouverture, nettoyage après échec, actions sérialisées, protection contre expiration pendant une action. Test HTTP avec véritable Chromium en plus des tests du pool. |
| Q07 | Upload binaire atomique, écritures hors boucle async, ancien contenu conservé sur interruption et temporaires nettoyés. Tests du manager sur les chemins de succès et d’annulation. |
| Q08 | Bcrypt exécuté hors boucle, cache PDF borné en nombre et en octets, extraction en processus avec limites mémoire/CPU/pages/entrée/sortie et délai de terminaison. |
| Q09 | Générations de requêtes dans les stores Task/Process, y compris pagination et détails ; une réponse ancienne ne remplace plus la réponse récente. Tests des véritables stores Pinia. |
| Q10 | Projections Chat et codes Tools groupés, fournisseurs distants concurrents bornés. Mesure Memory complémentaire : 54 → 5 SELECT pour 50 résultats sur 6 000 éléments multilingues, sans index ajouté à l’aveugle. |
| Q11 | Délais HTTP adaptés aux opérations, timeout SQL/attente de verrou, délais Atlas/psql et nettoyage effectif des sous-processus après expiration ou annulation. |
| Q12 | Allowlist HTML commune et validation des protocoles par URL normalisée. Test DOM Chromium des protocoles encodés, attributs et formulaires ; liens et contenus usuels préservés. |
| Q13 | Bases principales Docker figées par digest, dépendances dev exclues de production, import de `devtools` retiré du planner. Construction de quatre images, export avec identités/SHA-256 et chargement vérifié sans redémarrage ; procédure de promotion/retour arrière documentée. |
| Q14 | Restauration de DB/fichiers/clés vérifiée par login, lecture de document et pièce jointe, refus ACL. Upgrade d’un schéma précédent rempli vers le candidat, vérifications applicatives puis deuxième synchronisation. |
| Q15 | Parcours navigateur, tests des stores, corpus de transitions, mesure de branches sur contrats critiques et deux mutations de gardes détectées. La couverture mesurée est ciblée, pas celle de tout le backend. |
| Q16 | Réaction aux paramètres Voice déplacée dans Voice et composée au bootstrap ; Messenger n’importe plus Voice. Un cycle direct retiré (28 → 27 sur le périmètre initial), contrat de dépendance réduit sans augmenter la baseline. Les grands ensembles cycliques restent à réduire progressivement. |
| Q17 | Contrats/politiques du planner extraits dans `planner_contracts.py` ; budget, rétention et extraction PDF disposent de responsabilités séparées. Pas de réécriture globale des grands services Memory/Lab ni des grandes pages Vue. |
| Q18 | Versions explicites des checkpoints, WorkingSet et ExecutionResult, lecture des anciens formats, rejet des versions futures. `HistoryMixin` corrigé pour exposer de véritables datetime typés ; casts devenus inutiles retirés. Les frontières JSON dynamiques restantes et les coûts estimatifs Float ne sont pas tous convertis. |
| Q19 | Contrat mono-worker vérifié au lancement standard ; refus des configurations multi-workers incompatibles avec les états locaux. Aucune compatibilité distribuée implicite. |
| Q20 | Budgets d’admission par arbre causal ou, sur option, par Goal, réservations sous verrou et libération à expiration. Quota simultané par propriétaire, limite par agent existante, équité par ancienneté. Tests sur connexions indépendantes ; nouvelles politiques désactivées par défaut. |
| Q21 | Résolution UNKNOWN des tours et notifications Task/Process, privilège/scope vérifiés, preuve par tentative, idempotence et verrouillage. Aucun renvoi ni rejeu d’effet. Possibilités réelles de vérification des six transports documentées ; aucune réconciliation automatique par texte ou clé non persistée. |
| Q22 | Rétention opt-in, lots bornés avec aperçu et `SKIP LOCKED`, conservation des agrégats et références ; protection conservatrice des travaux actifs. Benchmark de recherche multilingue avec ACL et plans EXPLAIN. Pas de purge générale des messages/fichiers. |
| Q23 | Retard de boucle, âge du moniteur et attente de phase mesurés ; readiness refusée si le moniteur n’avance plus. Nettoyage du pool avant destruction des boucles de test, collections ORM corrigées après suppression bulk, contexte distribué désactivé en tests. Alertes externes non configurées. |
| Q24 | Ruff ciblé, vérification de format des modules extraits, couverture/mutations en CI, tests SSH/navigateur/upgrade et Dependabot étendu. `make quality` inclut lint, format et manager. Protection des branches GitHub et lint global TypeScript/Vue non modifiés. |
| Q25 | URL PostgreSQL structurée, validation des secrets sur APP_ENV résolu, limites documentées, références Pinia actualisées, traductions synchronisées. Les nouvelles modales sont fermables par l’arrière-plan ; aucun changement global des conventions de pagination. |

## Vérifications avant la reprise

Résultats conservés dans les journaux `/tmp/galaris-fix-*.log` de cette session. Les rapports
de couverture et de benchmark sont copiés sous `artifacts/quality-reliability/` ; les workflows
conservent aussi leurs artefacts. Ces répertoires ne sont pas versionnés.

| Contrôle | Résultat |
|---|---|
| Backend isolé final, RuntimeWarning et SAWarning fatals | 3 162 tests réussis ; aucun de ces avertissements |
| Backend final du dossier partagé | **3 203 tests réussis**, 5 avertissements de dépendances identifiés |
| Agent/Task avec RuntimeWarning fatal après nettoyage | 477 tests réussis, plus de coroutine asyncpg non attendue |
| Réservations de budget entre connexions indépendantes | 3 tests réussis |
| Memory/Contact avec SAWarning fatal | 47 tests réussis |
| Typage du dossier partagé | Pyright strict : 0 erreur ; vue-tsc réussi |
| Frontend du dossier partagé | 333 tests réussis ; 4 488 paires anglais/français et messages chinois vérifiés |
| Architecture du dossier partagé | Cartographie régénérée ; contrôle des frontières et 27 tests réussis |
| Ruff et format ciblé | Réussis |
| Exécuteurs et manager | 9 tests SSH, 12 tests navigateur et 12 tests manager réussis |
| Chromium E2E isolé | 10 parcours réussis |
| Couverture critique de branches | 88,04 %, seuil 70 %, 57 tests réussis lors de la mesure |
| Mutation des transitions | Les deux affaiblissements volontaires sont détectés |
| Restauration applicative finale | Réussie : PostgreSQL, fichiers, clés, login, lecture, refus ACL |
| Upgrade et deuxième convergence | Réussis depuis le schéma initial rempli |
| Images de production | Les quatre constructions réussissent ; import backend sans pytest/devtools réussi |
| Sécurité source et dépendances | `make security-check` réussi ; Semgrep : 79 règles, 1 088 fichiers, aucun constat |
| Skills modifiés | Validation des skills DbAdmin et Galaris réussie |

Un premier contrôle du dossier partagé a donné 3 194 succès et 3 échecs liés aux ajouts
multimédias concomitants. La documentation des cinq outils, l’allowlist du callback et les
attentes des capacités ElevenLabs ont été complétées après vérification de leurs contrats.
Quatre tests du callback vérifient également le bon jeton, le rejet des autres jetons/moteurs
et l’absence de transition à partir d’un contenu fournisseur non vérifié : 23 tests ciblés
réussissent. Les modifications de production multimédias ont été conservées.
La suite complète a ensuite été rejouée dans le dossier partagé : **3 203 succès, aucun échec**.

## Limites et activation

- Les budgets contrôlent l’admission des phases. Une phase en cours peut dépasser sa réserve,
  un harnais externe peut rapporter un usage incomplet. Le partage entre cycles d’un Goal est
  facultatif, comme le quota de concurrence par propriétaire. Ce n’est pas une garantie de facture.
- Les règles de rétention valent 0 par défaut. Les traces conversation/process restent
  conservées, ainsi que celles des tâches tant qu’une tâche quelconque est active. C’est une
  première politique prudente, pas une stratégie complète de stockage/export.
- La résolution couvre le tour et ses notifications Task/Process. Elle n’ajoute pas de garantie
  d’idempotence distante ; l’opérateur doit vérifier la destination avant de décider.
- SlowAPI et les tests SDK de reasoning émettent encore des avertissements identifiés.
  RuntimeWarning et SAWarning sont maintenant fatals dans la configuration pytest. Les métriques
  n’impliquent pas que des alertes ont été créées dans le compte Logfire.
- Aucun commit ni déploiement de production. L’exécuteur SSH a été recréé en développement,
  son ancienne image conservée et l’accès du backend vérifié. Le backend n’a pas été redémarré.
  Les tables de résolution ont été synchronisées en développement après inspection du dry-run.
- Les scripts de bundle sont prêts mais l’export complet d’un commit contenant ces changements
  n’a pas été exercé : les modifications ne sont pas commitées. L’export/rechargement réel des
  quatre images de validation et le refus d’un manifeste altéré ont été vérifiés séparément.
  Les quatre builds et le smoke test de production ont été exécutés sur la copie isolée.
  Les images n’ont pas été promues ni
  toutes rescannées localement ; le workflow de release scanne les images exportées.

Consulter [l’exploitation des garanties](../../docs/fr/dev/reliability-operations.md) et
la [décision 0073](../decisions/0073-operational-schema-and-runtime-limits.md) avant activation.
