# Complément de fiabilisation du 7 septembre 2026

Ce bilan complète les [corrections R01–R25](2026-09-06-review-corrections.md) du
[contre-audit](2026-09-06-quality-reliability-review.md). Il décrit le worktree issu de
`3062cf45f56f0dd97b49e42e0e5ef59c2b7d1d92`, sans commit ni déploiement. Les résultats
du premier lot restent dans son rapport ; les validations ci-dessous concernent les
compléments. Une suite passée ne prouve ni l'absence de tout défaut ni le fonctionnement
des comptes et réseaux externes d'une installation.

## Compléments réalisés

| Points | Résultat et vérification |
|---|---|
| R01, R24 | ESLint JavaScript/TypeScript/Vue bloquant dans Make, CI et build de production ; canaris négatifs sur les trois couches frontend et les templates Vue. Ruff couvre désormais Pyflakes et les captures de variables de boucle. Les versions des dépendances applicatives frontend ont été conservées. |
| R14, R25 | Décodage vocal incrémental hors boucle, par lots de 50 trames, avec réservation d'octets et fermeture du décodeur à l'interruption. La sortie Nextcloud Talk applique une contre-pression à 100 trames ; une génération empêche la réapparition d'audio effacé. Tests sur de vrais échantillons PCM et sur un producteur bloqué. |
| R15 | Le composant LlmCalls rejette les réponses d'une ancienne Task, session ou sélection fermée. Tests du véritable composant Vue avec réponses inversées. Les dialogues Agent émettent leurs modifications au parent au lieu de modifier ses props. |
| R16 | Les erreurs ENOSPC/EDQUOT du manager deviennent des réponses 507, y compris pendant la préparation du verrou. Les injections d'échec d'ouverture, fsync et remplacement vérifient la conservation de l'ancien fichier, l'absence de partiel et une écriture ultérieure réussie. |
| R17, R22 | Double reconstruction sémantique concurrente vérifiée sur 601 et 10 001 éléments. Extraction du calcul pur de différences de contenu Memory, avec conservation des tests de caractérisation et de son point d'appel existant. |
| R18 | Export diagnostic Process paginé, réservé à l'administrateur dans son périmètre Agent. Secrets nommés et URL de téléchargement des fichiers de lancement masqués ; source inchangée. Refus HTTP 401/403, isolation du périmètre et pagination testés. |
| R18, R25 | Mesure horaire du stockage PostgreSQL par table, index et TOAST compris, et du nombre estimé de lignes, sans scanner les contenus. Mesures de l'espace temporaire libre et de la durée d'acquisition SQL, avec succès, timeout et erreur. Saturation, annulation et récupération du pool testées. |
| R20 | Exercice de sauvegarde/restauration avec deux écrivains concurrents de documents et reçus de fichiers. Arrêt coordonné après leurs opérations complètes, puis sauvegarde ; restauration de 32 écritures validée par leurs SHA-256 et leur présence en base. |
| R21 | Port public de ressources FileShare avec enregistrement du fournisseur Mail au bootstrap ; aucune construction du fournisseur sans connexion active. Suppression d'importations privées sur les chemins Connection/Tools/Agent/Task. Baseline réduite sans nouvelle exception. |
| R23 | Snapshot de lancement Process validé et versionné avant tout effet externe. Anciennes valeurs nulles facultatives acceptées ; version future ou contenu invalide isolé au seul job concerné, sans bloquer le suivant. Une date de backoff ou un compteur historique invalide provoque une nouvelle observation au lieu d'abandonner le résultat distant. |
| R23 | Deltas d'index DbAdmin enrichis : expressions, méthode, colonnes incluses, classes d'opérateurs, options de stockage et nulls distincts. Comparaison PostgreSQL d'un index couvrant identique puis modifié. Les définitions observées n'autorisent aucune transformation destructive supplémentaire. |
| R24 | Couverture de branches élargie aux sessions, Process, rétention, checkpoints, livraison multimédia, décodage audio, pool SQL et transferts bornés. Les deux mutations de gardes de transition sont détectées. |
| R25 | Charge mixte locale avec deux pairs WebRTC réels, transport Opus/RTP, encodage binaire hors boucle, pression sur le budget global, 32 lectures HTTP authentifiées concurrentes, copie de fichier et renouvellement d'un lease Task. |

Les corrections R02–R13 déjà livrées dans le premier lot, ainsi que la chaîne d'images
exactes R19, sont couvertes à nouveau par les suites globales et les essais d'images.
Les procédures d'exploitation et DbAdmin sont mises à jour en français et en anglais.

## Disponibilité conservée

Une colonne NOT NULL sans défaut sur une table remplie est créée nullable, avec diagnostic
visible non bloquant. L'application peut remplir les valeurs avant une synchronisation
ultérieure qui resserre la contrainte. La dégradation d'une intégration facultative ne
devient pas une panne générale. Les objets indispensables et les effets distants dont
l'issue est ambiguë conservent les protections nécessaires.

L'export Process est un **export diagnostic borné**, susceptible de troncature, et non une
sauvegarde exhaustive. Suspendre la purge pendant un export multipage destiné à l'analyse.
La sauvegarde complète reste celle de PostgreSQL et des fichiers coordonnés.

## Validations

| Contrôle final | Résultat |
|---|---|
| `make tests` | **3 305 tests passés**, 8 avertissements de dépendances, 158,98 s |
| `make typecheck lint format-check` | Pyright strict sans diagnostic, **373 tests frontend**, parité des 4 516 paires FR/EN et des messages chinois, lint et 24 modules soumis au formatage conformes |
| `make architecture-check` | Cartographies FR/EN à jour, contrats respectés et **27 tests passés** |
| E2E des images finales sans montage applicatif | **48 tests passés** sur Chromium, Firefox et WebKit, 2,9 min, sans retry automatique |
| `make security-check` | Trivy conforme ; Semgrep : **0 résultat** sur 1 122 fichiers avec 79 règles |
| Scans des images finales | Backend : 251 avis HIGH/CRITICAL sans correctif disponible ; frontend : 0. **Aucun correctif HIGH/CRITICAL disponible laissé inappliqué** |
| Audit npm des dépendances de production frontend | **0 vulnérabilité** signalée |
| Scripts shell modifiés et `git diff --check` | Conformes |

Les deux appels HTTP signalés initialement par Semgrep sont des sondes historiques de santé
sur `127.0.0.1`, dans un conteneur jetable sans réseau externe et sans données applicatives.
Deux annotations ciblées expliquent cette exception ; leurs assertions sont inchangées et
aucune règle de sécurité applicative n'a été désactivée.

Résultats des exercices ciblés :

- 26 tests du manager de harnais, dont les pannes disque ; 44 tests de configuration
  Hermès après correction d'un renommage fautif révélé par la première suite globale.
- 44 tests de charge, audio et Nextcloud ; 73 tests des contrats Process, DbAdmin et pool.
- Couverture ciblée finale : 500 tests passés, **76,52 %** avec branches, seuil de 70 %.
  Ce pourcentage concerne les fichiers de `back/coverage-critical.ini`, pas tout Galaris.
- Mutation : baseline réussie et deux mutants rejetés, transition invalide acceptée et
  collaboration terminale rouverte.
- Restauration concurrente : **32 écritures, aucune perdue à la frontière d'arrêt
  coordonné, exercice de 49 secondes**. Ce n'est pas un RPO nul pour une sauvegarde à chaud.
- Upgrade entre les images locales ancienne et candidate : convergence d'un schéma peuplé,
  lecture documentaire et refus ACL, seconde synchronisation et restauration sous l'ancien
  binaire réussis ; phase candidate **25 secondes**.

Les exécuteurs Browser et SSH n'ont pas changé depuis le premier lot : leurs images exactes
ont passé respectivement 13 et 9 tests. Leurs scans conservés recensent respectivement 2 et
200 avis HIGH/CRITICAL sans correctif disponible, aucun avec correctif disponible.

Images qualifiées localement, identifiées par leur contenu :

```text
backend  sha256:9db797b5fdafc43d4919ab4fb5bdb87c9c19094fa5686f614f3321d0c4de5c33
frontend sha256:9be0ea42d9e528a5a0b0645ab859624f045b1533f6645f8782fc7a16a978d690
browser  sha256:e4c2dd9ba672a0e7bf704149607112cd98933d3f32ef9260257dcc3177b30651
ssh      sha256:50febd72f4c72dbccf703d663c8f74469463b53fc476b71bf5229123be24eca0
```

Le manifeste local est `/tmp/galaris-finish-production-images/IMAGE_IDS`, vérifié par SHA-256
avant les E2E ; les rapports de scan sont sous `artifacts/security/`. Les logs d'exécution
sont sous `/tmp/galaris-finish-*.log`. Ces chemins sont des preuves de cette session, pas une
archive de release. Le rapport conserve les identités et résultats ; la CI reconstruit et
qualifie un bundle depuis le commit qui sera effectivement livré.

Mesures de la charge mixte, dans cet environnement local :

| Mesure | Observation |
|---|---:|
| Trames WebRTC reçues | 234 |
| Latence p95 des lectures d'identité | 301 ms |
| Retard maximal de la boucle | 62 ms |
| Croissance maximale de RSS | 61,4 Mio |
| Fichier copié et vérifié | 4 Mio |
| Lease Task renouvelé pendant la charge | oui |

Ce scénario teste une admission binaire bornée avec WebRTC réel. Il n'utilise pas de modèle
payant et ne mesure ni un serveur TURN distant ni la capacité de production maximale.

## Limites explicites

- L'architecture reste une consolidation progressive : **294 → 284 imports privés**, **27 → 25
  paires bidirectionnelles**, composante cyclique **18 → 17 domaines**. Les grands services
  historiques ne sont pas tous réécrits. Aucune augmentation de baseline ne masque les écarts.
- Le budget borne les chemins binaires couverts, pas toute la mémoire du processus ni la
  facture des fournisseurs. Les seuils opérationnels sont à ajuster avec les mesures réelles.
- Les contraintes CHECK/exclusion et certaines différences de représentation d'index ne
  constituent pas un contrat sémantique complet de `SchemaTransitionSet` ; Atlas conserve
  la planification SQL. Aucun automatisme nouveau de conversion ne s'appuie sur ces lacunes.
- L'ancienne image locale correspond au commit initial, avec son propre code et ses propres
  dépendances. Elle n'est pas certifiée comme étant l'image réellement déployée chez
  l'utilisateur. Cette référence a été demandée ; sa fourniture et un jeu de données
  représentatif restent nécessaires pour qualifier **son** upgrade de production.
- Les comptes fournisseurs réels, le réseau TURN et les protections du dépôt distant ne sont
  pas certifiés par ces essais locaux. Aucun appel payant ni déploiement n'a été effectué.
