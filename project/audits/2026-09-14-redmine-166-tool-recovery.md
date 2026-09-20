# Reprise d’un outil au résultat inconnu — synthèse technique

Version publique de l’investigation du 14 septembre 2026. Les identités de tâches,
horaires individuels, commandes capturées, chemins locaux, empreintes et métadonnées
du dépôt distant ont été retirés. La [synthèse JSON](2026-09-14-redmine-166-tool-recovery-evidence.json)
conserve seulement les observations techniques et les totaux de validation.

## Conclusions conservées

- Un appel `console_exec` non idempotent avait une issue inconnue après interruption.
  Des effets existaient, mais aucun reçu durable ne permettait de prouver son achèvement.
  Le refus de rejouer automatiquement était justifié.
- La console annonçait `operation_recovery_available=false`. Cela explique la limite de
  récupération, sans établir la cause de la première perte de résultat.
- Un diagnostic distinct a rencontré une issue inconnue sur `file_copy`.
- Une commande de lecture contenant les mots `git push` dans un filtre a produit un faux
  reçu de livraison. Un exit code nul et une correspondance textuelle ne prouvent aucun push.
- Aucun double commit, push ou fichier n’a été démontré. La cause initiale reste indéterminée.

Les recommandations ci-dessous décrivent l’état de l’investigation ; le
[suivi de prévention](2026-09-14-redmine-166-prevention.md) documente les travaux suivants.

## Mécanismes existants : garanties et limites

| Surface | Garantie constatée dans le code/tests | Limite pour #166 |
|---|---|---|
| [checkpoint.py](../../back/app/harness/checkpoint.py), `started/completed/prepare_resume` | UUID écrit avant dispatch, arguments et politique ; snapshot détaché ; effet inconnu interdit au rejeu ; réconciliation avant reprise | Ne détermine pas seul les effets du monde extérieur |
| [contracts.py](../../back/app/tools/contracts.py), [execution_evidence.py](../../back/app/tools/execution_evidence.py) | Rejet natif corrélé à l’opération et au nom ; refus de preuves externes forgées | Une erreur générique après dispatch reste inconnue, même si elle semble sans effet |
| [executor.py](../../back/app/harness/executor.py), `recover_console_effect` | Récupération bornée aux outils console et au même scope connexion/hôte/port/utilisateur/clé hôte | Scope présent ne signifie pas helper v2 disponible ; changement de cible bloque |
| [ssh_client.py](../../back/app/console/ssh_client.py), `exec_operation/recover_operation` | Helper v2 utilisé si disponible ; sinon SSH conservateur ; UUID de résultat vérifié | `recover_operation` accepte aussi `running` ; résultat retrouvé ne signifie donc pas opération métier achevée |
| [galaris-exec](../../back/app/console/assets/galaris-exec) | Intention, empreinte commande/cwd/task, verrou et superviseur ; doublons du même UUID retrouvent l’opération ; conflit d’arguments refusé | Au plus une exécution par UUID, pas atomicité d’une séquence shell ; home/reçus à conserver |
| [agent_adapter.py](../../back/app/task/agent_adapter.py), `persist_agent_run_state` | Écriture conditionnée à la tentative active, lease et objectif ; checkpoint archivé dans la tentative | Le lease fence les écritures Galaris, pas un effet distant déjà parti |
| [task_service.py](../../back/app/task/task_service.py), `retry` ; [facade.py](../../back/app/agent/facade.py), `has_resumable_run_checkpoint` | Retry manuel conserve le journal ; admission de réconciliations console bornées | Nouvelle Task = nouveau scope de journal ; aucun dédoublonnage global d’intention |
| [checkpoint.py](../../back/app/harness/checkpoint.py), `take_replay` | Résultats non idempotents acquittés réutilisés dans une file par signature nom+arguments | Signature insuffisante pour distinguer un nouvel appel intentionnel aux mêmes arguments d’une reprise ; garantie à tester avant généralisation |
| [process_service.py](../../back/app/process/process_service.py) | Clés d’idempotence, corrélation engine, refresh, états terminaux et résolution d’attente durable | Contrat Process, pas un wrapper universel de toute commande console/copie |
| [resource_service.py](../../back/app/file_share/resource_service.py), `resource_copy` | URI, droits, bornes et contrôle d’overwrite ; création/mutation selon le provider | Pas de réconciliation générique par opération du transfert ; absence actuelle du fichier insuffisante |
| [resource_effects.py](../../back/app/tools/resource_effects.py) | Projection d’artefacts et reçus après retour | Reçu Git heuristique : faux positif vérifié ; ne pas l’utiliser comme autorité de reprise |

Attention : `galaris-exec poll` lance le superviseur si l’intention est encore `prepared`.
**Ce n’est pas une inspection forensique purement en lecture.** Pour préserver les preuves,
lire d’abord les métadonnées et l’état des processus sans passer par ce polling.
Une activation ultérieure de cette réconciliation doit être une action de reprise délibérée.

## Procédure opérationnelle

1. **Identifier et conserver.** Relever URI Task, révision, tentative/lease, driver, run,
   tool_call_id, operation_id, nom, arguments exacts, cible et politique. Lire toutes les
   pages du snapshot à révision constante. Conserver les preuves dans un dossier d’audit
   distinct avec heure et empreinte ; ne pas supprimer le checkpoint ni les reçus.
2. **Écarter une exécution concurrente.** Inspecter le superviseur et ses descendants avec
   identité de démarrage, utilisateur et machine ; un PID seul peut être réutilisé.
   Consulter les jobs/providers correspondants. Tant qu’un appel est actif ou introuvable
   sans preuve fiable d’arrêt, aucune seconde mutation.
3. **Décomposer l’intention.** Construire une ligne par sous-étape, avec effet attendu,
   état avant, destination, preuve, observation actuelle et verdict. Une commande shell
   composite ne reçoit pas un verdict global « à refaire ».
4. **Vérifier les effets acquis.** Utiliser les contrôles ci-dessous. Un état ressemblant
   ou un texte final d’agent ne constitue pas une preuve de la même opération.
5. **Décider.** Appliquer la table de décision. Un arbitre humain peut préciser l’intention
   et la cible ; il ne transforme pas une issue inconnue en succès ou rejet technique.
6. **Reprendre les seuls manques prouvés.** Revalider droits, destination, contenu/révision
   et exclusivité juste avant action. Réutiliser l’UUID de l’opération d’origine lorsque
   le provider l’accepte ; une étape de réparation distincte reçoit sa propre identité,
   liée à l’effet d’origine. Vérifier et enregistrer son résultat avant l’étape suivante.
7. **Résister aux nouvelles interruptions.** Relire les décisions et reçus déjà enregistrés.
   Une réconciliation interrompue reprend l’inspection ; elle ne remet pas le compteur
   d’effets à zéro. Sans preuve nouvelle, un état inconnu reste bloqué et visible.

| Effet | Contrôles permettant de reconnaître l’opération |
|---|---|
| Commit | Dépôt/worktree exact, état de l’index et des fichiers, parent(s), arbre et diff attendus, SHA et provenance temporelle. `git status` avec verrous optionnels désactivés, `diff`, `diff --cached`, `log`, `show`, `reflog`. Même titre/auteur ne suffit pas. Ne pas utiliser pull/reset/checkout pendant l’inspection. |
| Push | Projet/remote et ref de destination exacts, SHA attendu, état distant par `ls-remote`, reçu/audit si disponible. Le remote-tracking local seul n’est pas l’état du serveur. Une ref qui a avancé impose de vérifier l’ascendance et la concurrence, sans force-push. L’état attendu déjà présent suffit à éviter une nouvelle mutation ; son auteur reste inconnu sans audit. |
| MR | Projet numérique, IID existant, source et cible, SHA/versions et historique de création. Chercher aussi les MR fermées/fusionnées avec pagination complète. Une MR de titre voisin ne prouve rien ; ne pas créer de doublon parce qu’une MR existante est fermée. |
| Copie | URI source avec révision/contenu figé, URI et identité provider de destination, taille et empreinte complètes, reçu éventuel, état préalable. Nom/mtime/taille seuls insuffisants. Un fichier partiel n’autorise ni écrasement ni suppression sans prouver son appartenance ; préserver un contenu concurrent. |

## Table de décision

| État démontré | Verdict / action permise | Effets supplémentaires attendus |
|---|---|---|
| Non-exécution prouvée et aucun appel actif | Rejet avant dispatch ou intention jamais prise en charge ; exécuter la seule étape manquante avec contrôle de concurrence | Une fois pour l’étape manquante |
| Effets partiels identifiés | Confirmer les étapes acquises ; inspecter/réparer les seules étapes incomplètes avec préconditions précises | Zéro pour les étapes acquises ; au plus une réalisation de chaque manque |
| Exécution complète, réponse perdue | Reconstituer le résultat depuis un reçu/état corrélé, puis poursuivre | Zéro rejeu de l’effet acquis |
| Appel encore actif | Conserver l’état actif/inconnu, suivre la même opération ; attendre un terminal vérifié | Zéro seconde mutation |
| État indéterminable, distant inaccessible, preuve contradictoire | Arrêt sûr, exposition de l’identité et des preuves manquantes ; aucune réussite annoncée | Zéro mutation |
| Changement concurrent de cible/contenu/branche | Invalider la décision préparée et réinspecter ; arbitrage si intention divergente | Zéro écrasement automatique |
| Nouvelle intention volontairement distincte | Identité distincte, préconditions et autorisation propres ; ne pas dédupliquer par texte seul | Son effet propre une fois, sans supprimer l’opération précédente |

Un exit code terminal, même nul, ne prouve pas la réussite de toutes les commandes d’une
séquence avec `;` : une dernière commande de lecture peut masquer un échec antérieur.

## Propositions ciblées, non implémentées

1. **Preuve Git : priorité immédiate.** Retirer la valeur probante de la détection regex
   sur une commande arbitraire. Enregistrer une livraison Git seulement avec une opération
   corrélée et un résultat vérifié portant dépôt distant, ref et SHA. Ne pas remplacer la
   regex par un parseur shell prétendant prouver les effets. Préserver les anciens reçus
   comme indices historiques non vérifiés. Ajouter le cas réel `grep 'git push'`.
2. **Console : réutiliser l’ADR 0093.** Vérifier et installer le helper v2 selon la procédure
   de déploiement existante, dans un chantier explicite ultérieur ; qualifier une cible
   isolée et exposer clairement l’indisponibilité. Distinguer « candidat à réconciliation »
   et « provider capable ». Une mise à jour ne recrée pas les reçus des anciennes commandes.
3. **Issue active et inspection.** Prévoir une lecture de statut sans lancement implicite ;
   qualifier `running` séparément de terminal. Pour `console_exec`, ne pas laisser un
   résultat actif autoriser une nouvelle mutation sur le même état. Pour `console_start`,
   distinguer l’acquittement du lancement de l’achèvement du travail.
4. **Identité et résolution explicite.** Étendre les contrats existants uniquement après
   tests des reprises répétées : distinguer la réutilisation d’un effet du nouvel appel aux
   mêmes arguments, et prévoir une résolution auditée liée à la révision du checkpoint,
   à l’opération et aux preuves. Aucune édition manuelle de `resume_safe` en production.
5. **Copie : diagnostic avant correction.** Retrouver la première exception native de S3.
   Si un refus avant effet est démontré dans le code, le signaler par la preuve native
   existante ; ne pas reclassifier toutes les erreurs de copie comme sans effet. Pour un
   provider réellement asynchrone, réutiliser Process et son contrat de récupération.

Ces propositions restent soumises à une prise en charge d’implémentation ultérieure.
Aucune nouvelle décision structurelle n’est déclarée acceptée par cette étude.

## Plan de validation à réaliser

Environnement : Docker isolé, base PostgreSQL éphémère, deux dépôts Git jetables (local et
bare distant), faux fournisseur MR avec journal durable, providers fichiers de test.
Ne jamais reproduire les pannes sur une installation ou une demande de fusion réelle.

Chaque scénario enregistre : identité logique, tentative, operation_id/tool_call_id,
arguments, SHA/révisions et destination avant/après ; nombre de dispatchs, commits
nouveaux, modifications de ref, créations MR, écritures finales et octets publiés.
Une ref inchangée ne suffit pas à prouver l’absence de double appel distant : compter
aussi les invocations. Répéter la reprise au moins trois fois, dont une après
redémarrage ; vérifier les états durables, pas seulement le message final.

| Scénario / injection | Observations et assertions attendues | Point de départ existant |
|---|---|---|
| Avant dispatch et après intention avant prise en charge | Zéro effet avant reprise, puis un ; même UUID ; aucun effet après reprises suivantes | `test_launcher_killed_after_intent_is_recovered_without_duplicate` |
| Après commit avant push/MR | Un commit retrouvé par parent/arbre/SHA ; zéro recommit ; un push et une MR seulement pour les étapes manquantes | Ajouter parcours Git/MR réel + fournisseur de test |
| Copie partielle | Couper après N octets ; reconnaître l’incomplet ; ne pas publier comme complet ; réparation contrôlée, un objet final ; fichier indépendant inchangé | Étendre les tests de transfert file_share |
| Réponse perdue après effet complet | Cas séparés commit, push, MR, copie ; couper l’accusé avant checkpoint ; retrouver l’identité exacte ; zéro nouvel effet et zéro second dispatch | `test_lost_ssh_ack_recovers_from_database_and_never_repeats_command` |
| Réconciliation elle-même interrompue | Tuer après lecture du reçu puis après persistance de résolution ; reprise conserve le résultat ; compteurs inchangés | Étendre tests checkpoint/DB |
| Résultat inconnu persistant | Masquer le reçu, rendre le distant inaccessible, injecter des preuves contradictoires ; aucun nouveau dispatch, aucun faux succès, même blocage sans preuve nouvelle | `test_unfinished_effect_blocks_automatic_resume`, tests de transport |
| Appel actif / concurrence | Retarder le terminal, reprendre ; zéro second lancement ; modifier destination/ref entre inspection et action ; refus de la décision devenue périmée | Tests de doublons console, puis parcours harness complet avec `running` |
| Reçu mal corrélé | Reçu d’une autre opération, MR similaire, même nom de fichier, commit indépendant ; tous refusés comme preuve de l’appel initial | Tests de preuve MCP + nouveau cas réel de faux reçu Git |
| Intentions distinctes | Même outil et mêmes arguments, deux identités intentionnelles : chacune produit son effet une fois ; une reprise de A ne consomme pas B | Étendre `take_replay` au niveau du contrat de reprise |
| Lease périmé / scope changé | Ancien worker écrit après reprise ou nouvelle cible SSH : checkpoint protégé, aucun effet relancé sur autre cible | Tests agent_run_trace, scheduler et SSH |
| Helper indisponible / inspection passive | Capacité fausse, reçu absent : arrêt sûr ; lecture de `prepared` sans lancement ; aucune fausse garantie v2 | Étendre tests console/capacité et inspection |

Les cas Git/MR/copie ci-dessus sont **proposés**, pas exécutés ici. Les tests existants
vérifient des garanties partielles et servent de socle ; leur réussite ne qualifie pas
une réconciliation générale d’opérations métier arbitraires.

## Validation réellement exécutée

- `make tests-recovery` : **411 réussites, 2 avertissements de dépréciation, 7,35 s pytest**,
  code retour 0. Base PostgreSQL éphémère ; tests réels MCP/SSH, arrêts de processus,
  journal/checkpoints, retries, scheduler, preuves d’exécution et outils.
  Premier lancement limité par le sandbox Docker, relancé avec accès Docker autorisé.
  Journal de session : `/tmp/redmine-166-recovery.log`.
- `git diff --check` : succès lors de l’inspection et à la relecture finale.
- Aucun test produit ajouté, aucune correction runtime. Typage, architecture globale et
  `make validate` non relancés pour ce seul livrable d’investigation. Les 411 tests ne
  constituent pas une qualification de publication du worktree concurrent.
