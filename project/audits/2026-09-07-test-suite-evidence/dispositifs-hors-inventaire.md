# Dispositifs hors décompte des définitions de tests

Les fichiers de support et les scénarios opérationnels ne sont pas tous des fonctions `test_*` ou des déclarations `test(...)`. Cette table évite de les oublier ou de les compter à tort comme des tests automatisés ordinaires.

| Dispositif | Pertinence | Exécution dans cet audit |
|---|---|---|
| `bin/test-back.sh`, `compose.test.yaml`, `back/conftest.py`, préparation des bases modèles | Isolation PostgreSQL, initialisation du schéma et fixtures ; infrastructure indispensable | Exercés par la suite backend |
| `bin/test-e2e.sh`, `e2e/playwright.config.mjs`, `back/tests/e2e_app.py` et helpers E2E | Démarrage isolé, serveur applicatif et navigateur réels ; fournisseur agent déterministe | 48 cas réussis |
| `back/scripts/check_workflow_mutations.py` | Référence puis quatre altérations réelles de garde-fous ; exige l'échec des tests attendus | Référence et quatre détections vérifiées |
| `bin/test-restore.sh`, `back/tests/restore_probe.py`, `back/tests/restore_concurrency.py` | Sauvegarde/restauration DB, fichiers et clés, vérification des contenus et droits, écrivains concurrents et frontière de quiescence | Réussi sur la deuxième copie ; 28 écritures validées restaurées, aucune perdue |
| `bin/test-upgrade.sh` | Ancienne version peuplée vers candidate, convergence idempotente, vérification et restauration avec ancien binaire | Lecture ; pas exécuté ; nécessite le choix de la version précédente |
| `bin/test-release.sh`, `back/scripts/release_qualification.py` | Rattache les preuves aux images exactes et vérifie la qualification de l'upgrade | Lecture ; pas de bundle de release qualifié pendant cet audit |
| `make tests-dbadmin-load` | Qualification sur 100 000 lignes, écritures concurrentes et transitions DDL | Ignoré dans la référence initiale ; voir exécution du delta |
| `make tests-load` | Étend à 60 secondes le scénario mixte local avec heartbeat sous saturation | Variante courte puis variante 60 secondes réussies |
| `make tests-coverage`, `back/coverage-critical.ini` | Couverture de branches sur un sous-ensemble, seuil agrégé 70 % | Configuration lue ; couverture non mesurée ici |
| `architecture-check`, `project-context-check`, `docs-i18n-check`, lint/typecheck | Contrats et analyse statique complémentaires ; pertinents mais distincts d'un parcours utilisateur | Scripts/configuration examinés ; commandes indépendantes non exécutées |
| `front/scripts/typecheck-gate.test.mjs`, `lint-gate.test.mjs`, `catalog-syntax.test.mjs` | Canaris du périmètre de contrôle ; déjà inclus dans l'inventaire Node | Exécutés ; canari TypeScript coûteux |
| `bin/security-check.sh` | Scans de dépendances, secrets et images ; complément de sécurité | Lecture du déclenchement ; pas de scan effectué |
| `back/scripts/test_bridge_harness.py`, `test_bridge_hermes.py` | Connexion réelle au manager configuré et lecture de son état | Diagnostic manuel non exécuté |
| `back/scripts/manual_test.py` et `manual_test_process.py` | Lanceur/inspection de diagnostics ; pas de preuve automatique de comportement | Non exécutés |
| `back/tests/manual/test_message_history.py` | Deux essais IA avec affichage ; ne garantissent pas automatiquement la pertinence des réponses | Exclus de pytest, non exécutés |
| `back/tests/manual/test1.py` | `main()` vide ; aucun bénéfice de validation | Suppression possible du squelette |
| `front/core/util/model3d.browser.mjs` | Assertions réelles sur le navigateur, liées à un serveur frontend accessible ; hors découverte Node/E2E normale ; commande manuelle en tête de fichier | Relu, non exécuté ; raccorder à une cible automatisée si cette protection est attendue |

La CI existante comporte des garanties opérationnelles : `security.yml` appelle restore, upgrade, harness manager et SSH executor ; `release-artifact.yml` qualifie le bundle et son upgrade ; `quality.yml` couvre notamment backend, frontend, browser-executor, mutations et E2E répétés. Il serait incorrect de présenter ces suites comme absentes de CI. La protection effective des branches n'a pas été interrogée.

Les cibles longues `tests-load` et `tests-dbadmin-load` ne sont pas invoquées par les workflows examinés. Leur existence permet une qualification volontaire ; elle ne signifie pas qu'elle a lieu sur chaque changement.
