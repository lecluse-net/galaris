# Plugins Galaris — conception de distribution et activation

- Statut : `design`
- Revue des sources : 2026-10-08.

## Résultat recherché

Installer un bundle backend/frontend versionné sans l'activer, vérifier identité,
intégrité, compatibilité et permissions, puis appliquer une génération cohérente au
redémarrage. Désactivation et retrait conservent les données ; purge séparée et explicite.
Le store signé réutilise exactement cette chaîne.

Le bootstrap statique de `back/modules.py` et `front/modules.ts` reste le socle courant ;
il ne constitue pas une infrastructure d'installation de plugins.
`plugins` représente une origine de distribution/confiance, pas une quatrième couche
métier. Les contributions passent par les surfaces publiques de core/app/bridge.
Le [chantier d'écosystème](cible.md#écosystème-signé) porte la direction produit.

## Contrats proposés

| Objet | Rôle |
|---|---|
| Plugin / release | Identité stable ; version immuable et digest du bundle. |
| Installation / deployment | Présence locale vérifiée ; version désirée distincte de la version effective. |
| Génération | Snapshot atomique des releases effectives, schémas retenus et dernière génération fonctionnelle. |
| Permissions / événement | Grants locaux de version précise ; décisions et erreurs administratives expurgées. |
| Catalogue / store | Métadonnées distantes et interface locale, sans autorité d'activation distante. |

Domaine candidat `app.plugin` pour workflow, persistance, RBAC et administration.
Infrastructure core indépendante pour archives, manifests, stockage immuable, boot
et contrats techniques ; composition racine avec les ports des domaines.

Bundles : manifeste versionné, sources backend/frontend, licences/crédits,
frontend précompilé et attestations (digests, SBOM, provenance, signature).
Manifeste : identifiant global/code/module sûrs, SemVer, métadonnées FR/EN,
compatibilités Galaris/SDK/Python, entrypoints, contributions, dépendances,
permissions, objets SQL possédés et contrat de rollback. Aucun secret/binding local.

Conserver des releases externes sur volume dédié, hors checkout/image, avec staging,
quarantaine, versions par digest et registres desired/effective/last-known-good.
Le frontend n'accède qu'aux artefacts publics, jamais au volume général de données.

## Backend, frontend et schéma

- Entrypoint backend typé décrivant modèles, routes, privilèges, DbAdmin, MCP, paramètres,
  i18n, runtime supervisé et ports publics. Contributions réelles identiques au manifeste.
- Imports publics déclarés ; aucun import core/app/bridge vers un plugin, monkeypatch,
  collision ou modification implicite des registres/dépendances du cœur.
  Première version limitée aux dépendances déjà fournies par l'image/SDK.
- Espaces réservés pour routes, tables, contraintes, outils, privilèges, paramètres et i18n.
  Dépendances inter-plugins déclarées et acycliques si retenues.
- Frontend précompilé reproductible et content-addressé ; aucune compilation npm en
  production. SDK borné pour routes/navigation/i18n/slots/services/stores et nettoyage,
  avec une seule instance des runtimes Vue/Quasar/Pinia/Router/i18n fournie par l'hôte.
- Manifeste frontend des seules releases effectives ; cache immuable des artefacts,
  manifeste frais, nouvelle URL par génération et rafraîchissement des clients ouverts.
  Aucune route d'un plugin désactivé après recharge.
- DbAdmin reste l'autorité du schéma public, sans Alembic ni Atlas autonome.
  Distinguer `schema_installed` de `runtime_enabled` : désactivation/import défaillant/retrait
  ne donnent jamais un droit de DROP.
- Modèles retenus même sans runtime ; datasets/reconcilers fonctionnels arrêtés.
  Interdire mutation des objets d'un autre propriétaire ; FK externes exceptionnelles.
  Évolutions expand/contract et actions/reconcilers idempotents pour transformations avancées.
  Rollback seulement si compatibilité démontrée, sans annulation fictive des données.

## Cycle de vie et confiance

Installer : ZIP borné, refus traversal/symlinks/types spéciaux/bombes de compression,
staging non exécutable, validation manifeste/digests/signature/compatibilité/collisions,
TCK/imports isolés, publication atomique, état installé inactif.
Crash/retry laisse la génération courante intacte.

Activer : sérialiser par plugin/génération, revalider grants et artefacts, calculer
delta DbAdmin candidat, refuser par défaut destruction/hors-périmètre, publier frontend
et génération désirée, redémarrer, converger avant API, vérifier readiness/probes,
puis promouvoir ou restaurer last-known-good.
Aucun chargement backend à chaud ni socket Docker général remis au backend.

Désactiver/retirer : supprimer surfaces/runtime, conserver données et inventaire SQL.
Purger : inventaire, dépendances, privilèges, confirmation et sauvegarde selon politique,
action DbAdmin gouvernée et journal de l'effet.

Le mode initial est natif de confiance : signature et permissions déclaratives
n'isolent pas Python in-process ni JavaScript de même origine.
Ouverture à des tiers non fiables après runner isolé, identité limitée, réseau,
secrets/volumes/quotas imposés et frontend isolé si nécessaire.
Élargissement des permissions à une mise à jour soumis à approbation locale.

Store initial administré/configuré : cache de métadonnées, versions et révocations,
vérification indépendante du TLS, puis installateur local.
Pas de marché public, paiement, notation ou activation automatique dans le premier palier.

## Lots et réception

| Lot | Preuve de sortie |
|---|---|
| 0 — ADR/SDK/contrats | Manifeste, namespaces, confiance, permissions, DbAdmin et rollback décrivent un plugin sans imports privés ; threat model d'installation de code. |
| 1 — Bundle et registre | Installation inactive et idempotente ; crash à chaque étape sans corruption de release/génération. |
| 2 — Backend natif | Contributions, runtime et schéma cohérents au redémarrage ; échec d'import/probe avec cœur administrable et aucun DROP implicite. |
| 3 — Frontend runtime | Activation/désactivation visibles après application/recharge, sans rebuild du frontend ; cohérence back/front/cache et séparation des volumes. |
| 4 — Administration et TCK | Import, permissions, activation, update, rollback, retrait et purge ; refus RBAC et parcours complet d'un plugin de référence hors monorepo. |
| 5 — Catalogue signé | Bundle altéré, révoqué, incompatible ou permissions élargies non approuvées refusés par le pipeline commun. |
| 6 — Mode isolé | TCK adversarial : aucun accès non accordé, mutation du cœur ou survie après désactivation. |

Administration : versions désirées/effectives, manifeste/permissions, erreurs expurgées,
progression/readiness, rollback, retrait/purge et journal. Distinguer privilèges de lecture,
installation, approbation, activation, rollback et purge.
Corréler version/digest/génération/opération ; readiness distingue candidat requis invalide,
composant facultatif dégradé, configuration et révocation.

TCK : archives/intégrité/reproductibilité, imports/namespaces, contributions, Pyright/types,
FR/EN, RBAC, cycle complet, interruptions et conservation des données.
Cartographie du dépôt déterministe ; release externe avec son propre rapport et inventaire runtime.

Arbitrages avant implémentation : autorités de signature, partage des runtimes frontend,
inventaire de schéma après retrait du code, dépendances entre plugins, superviseur borné,
slots SDK stables, sauvegardes/purges et catalogues autorisés.
Retirer les lots réalisés vers décisions, SDK, guides et tests.
