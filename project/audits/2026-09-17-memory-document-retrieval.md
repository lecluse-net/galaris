# Validation du rappel documentaire — 17 septembre 2026

Périmètre : premier ensemble d’implémentations du
[plan mémoire](../plans/amelioration-globale-memoire.md), selon la
[décision 0108](../decisions/0108-memory-document-retrieval.md).

## Vérifications exécutées

| Vérification | Résultat |
|---|---|
| Reproduction initiale : révocation, correction et oubli pendant un repli lexical | 3 échecs reproduits avant correction |
| Suite Memory, contexte conversationnel et façade Agent, service de ressources File Sharing | 461 tests réussis, 2 avertissements de dépréciation tiers |
| `make typecheck` | Réussi : Pyright, vue-tsc, tests de tooling et catalogues i18n |
| `make project-context`, puis `make architecture-check` | Cartographies à jour, contrats satisfaits, 28 tests réussis |
| `make sync-db` en développement | Convergence DbAdmin, aucune anomalie signalée |
| `git diff --check` | Réussi |

Commande de la suite principale :

```sh
make tests ARGS='app/memory/tests app/agent/tests/test_conversation_context.py app/agent/tests/test_facade.py app/file_share/tests/test_resource_service.py -q'
```

Les nouveaux scénarios passent par PostgreSQL réel et des sessions distinctes pour les
modifications concurrentes. Ils couvrent le repli préchargé, les deux lectures vectorielles,
le brief et la reprise d’une capsule, ainsi que les passages relus via `file_read`,
un fragment manquant, sa réparation, une transaction source annulée, une description de PJ,
la fin d’un document de 100 000 mots et le changement de modèle configuré.

Le fournisseur est substitué dans ces tests : ils prouvent la cohérence et les contrats de
recherche, sans mesurer la qualité linguistique des embeddings de production.

## Vérification opérationnelle locale

**Actualisation :** après relance du fournisseur par l'utilisateur, la réindexation du corpus privé
est complète et une [campagne réelle avec nomic](2026-09-17-private-corpus-memory-relevance.md)
a été conduite. Elle révèle deux défauts corrigés et un classement restant insuffisant.
Les constats de panne ci-dessous décrivent la sonde initiale, avant cette relance.

Une seule requête de disponibilité a été envoyée au modèle configuré, `nomic`, sans modifier
le profil ni les paramètres. Elle échoue avec `MemoryEmbeddingProviderUnavailableError` :
le fournisseur ne peut pas être joint depuis le backend de développement.

Le contrôle trouve 26 documents, 508 mémoires, 18 compagnons de pièces jointes et 10 dossiers,
sans génération courante publiée. Ces nombres concernent le développement, pas la production.
Après correction, `make rebuild-memory-index ARGS='--all'` remet en file les 534 items éligibles
avec le même modèle. La reconstruction n’est pas annoncée terminée : elle attend le fournisseur.
Le rappel lexical reste disponible et les résultats déclarent leur dégradation.

## Limites

Les coefficients enregistrés de classement n’ont pas été recalibrés. La campagne du corpus privé
et ses ablations exploratoires sont désormais réalisées ; des labels complets et un jeu de
validation indépendant restent nécessaires avant qualification générale.
La préparation du code et les vérifications locales ne constituent pas une qualification de
publication par `make validate`. Aucun commit ni déploiement n’a été effectué par cette tâche.
Les autres changements simultanés du worktree ont été préservés.
