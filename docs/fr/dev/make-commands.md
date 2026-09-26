<p align="right"><strong>Français</strong> · <a href="../../en/dev/make-commands.md">English</a></p>

# Catalogue des commandes Make

Les cibles ci-dessous proviennent des six `Makefile` du dépôt. Depuis la racine, utiliser
`make help` pour afficher l'aide courante et `make <cible>` pour lancer une commande.
Le `Makefile` reste la référence. Installation standard : **`make install` → configurer
`.env` et `compose.override.yaml` → `make start`** ; voir le [guide d’installation](../admin/installation.md).

## Stack et exploitation

| Cible | Rôle |
|---|---|
| `help` | Afficher les commandes publiques. |
| `install` | Choisir PostgreSQL et un port libre (8484 par défaut), préparer configuration et secrets ; `INSTALL_PORT` permet l’automatisation. |
| `build` | Construire les images avec cache sans modifier les conteneurs. |
| `start` | Relancer les conteneurs existants ; appeler `update` s’ils sont absents, incomplets ou en échec. |
| `stop` | Arrêter la stack en conservant les conteneurs. |
| `uninstall` | Supprimer conteneurs et réseaux du projet ; proposer séparément la purge des volumes, images Compose locales et conteneurs orphelins (non par défaut). |
| `restart` | Enchaîner `stop` puis `start`. |
| `restart-service` | Redémarrer un seul service sans reconstruire ; `SERVICE` obligatoire. |
| `status` | Afficher l'état des conteneurs ; filtrer avec `SERVICE` si nécessaire. |
| `update` | Régénérer la documentation, construire et déployer les sources présentes, puis actualiser l’index documentaire ; seul `VERSION` déclenche la récupération d’un tag ou d’une branche Git. Accepte `RELEASE_DIR` hors dev, sans Git, avec la documentation embarquée du paquet. |
| `logs` | Suivre tous les journaux. |
| `logs-back`, `logs-front`, `logs-search` | Suivre les journaux du service désigné. |
| `check-search` | Vérifier les sources et dégradations sur quatre requêtes publiques réelles ; diagnostic volontaire, distinct du healthcheck. |
| `logs-browser` | Suivre les journaux du navigateur isolé. |
| `status-executor` | Inspecter l'exécuteur SSH et lancer son contrôle de santé. |
| `logs-executor` | Suivre les journaux de l'exécuteur SSH. |
| `backup-executor` | Sauvegarder les homes, clés et registre de l'exécuteur dans `backups/`. |
| `clean` | Supprimer les conteneurs et volumes de la stack. Destructif. |

Le hot reload suffit pour les éditions Python/Vue en développement. `update` applique
les nouvelles sources et configurations. `start` et `restart` ne construisent pas lorsque
les conteneurs sont réutilisables ; une relance qui échoue déclenche au plus un `update GIT_UPDATE=0`.
`restart-service` redémarre un service sans construire. `uninstall` demande une confirmation
distincte pour les volumes, les images locales (`--rmi local`) et les conteneurs orphelins du
projet. Les images avec un tag explicite et le cache partagé restent conservés ; aucun `prune`
global n’est exécuté. `clean` supprime les volumes sans confirmation.

```bash
make status
make status SERVICE=browser-executor
make restart-service SERVICE=browser-executor
make restart-service SERVICE=ssh-executor
```

Ces commandes utilisent les fichiers Compose sélectionnés pour l'environnement courant.
`status-executor` ajoute un contrôle de santé SSH à l'état des conteneurs.

## Développement et maintenance

| Cible | Rôle |
|---|---|
| `sync-db` | Synchroniser schéma et datasets sans redémarrage, uniquement avec `APP_ENV=dev`. |
| `upgrade-deps-back` | Actualiser le verrou backend puis synchroniser l'environnement avec uv. |
| `upgrade-deps-front` | Actualiser et installer les dépendances npm. |
| `rebuild-source-memory` | Reconstruire les projections mémoire Agent/Goal ; options via `ARGS`. |
| `rebuild-messenger-contacts` | Reconstruire les mémoires de contacts à partir du journal Messenger. |
| `rebuild-memory-index` | Mettre en file la reconstruction de l'index sémantique ; options via `ARGS`. |
| `rebuild-memory-links` | Réconcilier les liens mémoire dérivés ; options via `ARGS`. |
| `project-context` | Régénérer les cartographies du projet et des menus frontend depuis le code, hors ligne. |
| `project-context-check` | Vérifier la fraîcheur des cartographies du projet et des menus. |
| `docs-prepare` | Régénérer les cartes et vérifier le corpus FR/EN hors ligne avant validation. |
| `docs-check` | Vérifier cartes, sources documentaires et liens sans régénération. |
| `docs-update` | En développement, préparer la documentation puis vérifier le corpus actif et synchroniser sa recherche textuelle. |
| `architecture-baseline` | Actualiser les baselines de dette après revue du diff ; seules ces deux sorties JSON sont inscriptibles. |
| `architecture-check` | Vérifier cartographie, frontières et tests d'architecture. |
| `test-hermes-management` | Diagnostiquer la configuration et la connectivité de l'adaptateur Hermès. |
| `test-harness-management` | Diagnostiquer le gestionnaire générique de harnais. |
| `qualify-lab` | Lancer un exercice Lab explicitement budgété ou comparer des runs ; `ARGS`, `LAB_ACCESS_TOKEN`. |
| `qualify-matrix` | Envoyer un texte/fichier synthétique dans un salon Matrix de test explicitement autorisé. |

Les diagnostics de gestion utilisent le backend actif. Les scripts manuels restent accessibles
avec leur lanceur Python dans ce conteneur :

```bash
docker compose exec backend python scripts/manual_test.py tests/manual/<script>.py
```

Lire le [guide des diagnostics manuels](../../../back/tests/manual/README.md) avant de les
exécuter. Ils ne remplacent pas les tests automatisés sur base éphémère.
Voir [Tester les comportements](testing.md).

## Validation et livraison

| Cible | Rôle |
|---|---|
| `typecheck` | Pyright, vue-tsc, tests unitaires frontend et parité i18n. |
| `lint` | Ruff backend et lint frontend. |
| `format-check` | Contrôler le formatage du périmètre défini par le script dédié. |
| `tests` | Tests backend avec PostgreSQL éphémère ; sélection via `ARGS`. |
| `tests-recovery` | Sélection de tests de reprise, reçus durables, retries et propriété des tentatives. |
| `tests-harness-contracts` | Contrats de harnais, adaptateurs et intégration Task. |
| `tests-harness-runtimes` | SDK réels épinglés avec modèle déterministe isolé. |
| `tests-providers` | Contrats fournisseurs sans appels API externes. |
| `tests-dbadmin-load` | Transitions de schéma et indexation sur 100 000 lignes isolées. |
| `tests-load` | Charge mixte locale WebRTC, HTTP et fichiers avec maintien du lease. |
| `tests-browser` | Tests unitaires de l'exécuteur navigateur. |
| `tests-executor` | Concurrence du registre SSH et permissions Unix réelles. |
| `tests-harness-manager` | Tests du gestionnaire de harnais dans Docker. |
| `tests-front-tooling` | Vérifier que le contrôle TypeScript refuse le code invalide. |
| `tests-front-components` | Interactions des vrais composants Vue/Quasar dans un navigateur isolé. |
| `tests-focus-gates` | Vérifier que les configurations Playwright refusent les tests focalisés. |
| `tests-e2e` | Parcours navigateur et mises à jour PWA dans une stack isolée. |
| `tests-update` | Vérifier installation, configuration conservée, mises à jour et échecs avec Docker simulé. |
| `tests-documentation` | Vérifier le lanceur documentaire hors ligne, puis son confinement dans de vrais conteneurs. |
| `tests-install` | Installer réellement une copie isolée avec volumes neufs, vérifier la disponibilité HTTP et la conservation des conteneurs après stop/start. Port de test : `INSTALL_TEST_PORT=18484` par défaut. |
| `tests-validation-source` | Vérifier la conservation et l'empreinte des changements non committés lors de la validation. |
| `tests-coverage` | Exécuter la couverture backend, produire les rapports et appliquer les seuils. |
| `coverage-check` | Contrôler les rapports de couverture existants et les branches modifiées. |
| `tests-mutations` | Vérifier des mutations ciblées sur des copies jetables des sources. |
| `regression-check` | Vérifier les liens entre régressions et rapports de tests/mutations réussis. |
| `quality` | Enchaîner les contrôles locaux ; certains nécessitent la stack de développement active. |
| `validate` | Qualifier un instantané isolé, incluant les changements non committés, sans stack de développement. |
| `security-check` | Scanner dépendances, secrets et code sensible. |
| `tests-restore` | Répéter la restauration DB, fichiers et clés sur des données isolées. |
| `tests-upgrade` | Répéter une mise à jour isolée depuis `UPGRADE_PREVIOUS_IMAGE` ou `UPGRADE_FROM`. |
| `build-release` | Construire/exporter les images immuables de `RELEASE_REF` (HEAD committé par défaut). |
| `tests-release` | Qualifier les images de production exactes de `RELEASE_DIR`. |

`validate` et `quality` ont des environnements et des étapes différents. Avant publication sans
CI, utiliser `make validate` et lire son rapport ; `make quality` n'est pas un substitut.

## Makefiles des harnais

Ces cibles se lancent dans leur répertoire, par exemple `make -C harness_manager help`.
Elles servent aussi au pilotage des instances et ne sont pas des alias de la stack racine.

| Répertoire | Cibles |
|---|---|
| `harness_manager/` | `help`, `install`, `create-secret`, `uninstall`, `start`, `stop`, `restart`, `logs`, `service-file`, `service-install`, `service-uninstall`, `service-status`, `service-logs` |
| `back/bridge/claude_agent/default-agent/` | `start`, `stop`, `restart`, `update` |
| `back/bridge/deepseek_harness/default-agent/` | `start`, `stop`, `restart`, `update` |
| `back/bridge/codex/default-agent/` | `start`, `stop`, `restart`, `update`, `logs` |
| `back/bridge/hermes/default-agent/` | `help`, `start`, `prepare-delete`, `stop`, `restart`, `update`, `hermes`, `logs`, `clean` |

Pour Hermès, `prepare-delete` restitue les droits des données au gestionnaire avant suppression.
Son `clean` effectue un nettoyage Docker global après confirmation ; sa portée dépasse celle du
`clean` de la racine.

Pour ouvrir un shell ponctuellement, utiliser `docker compose exec ssh-executor bash` depuis
la racine, ou `docker compose exec agent /bin/bash` depuis le répertoire de l'instance Hermès.

## Périmètre conservé

Les raccourcis `logs-*` restent disponibles. L'inspection et le redémarrage ciblés passent par
`status` et `restart-service`, avec `SERVICE` ; le diagnostic `status-executor` reste distinct.

`quality` est conservée pour les contrôles sur l'environnement de développement existant.
`validate` fige les sources et lance les contrôles dans un environnement isolé ; elle inclut
aussi la qualification des SDK de harnais réels. Ces deux workflows ne sont pas des alias.

Les commandes de reconstruction réparent des données ; les diagnostics Hermès et gestionnaire
générique visent deux couches distinctes. Les cibles de test servent aux contrôles ciblés, à la
CI ou à la qualification des releases. Une cible appelée par une autre reste utile pour
relancer un contrôle isolément.

Les commandes documentaires hors ligne ne passent ni par le Compose applicatif ni par son
`.env` : elles analysent un instantané filtré des sources et n'écrivent que les sorties
attendues. Détails dans [Tests et typage](README.md) et décision
[0137](../../../project/decisions/0137-offline-documentation-toolchain.md).
