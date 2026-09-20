# Redmine #166 — Correctifs de prévention

Date : 14 septembre 2026. Suite de l'[investigation](2026-09-14-redmine-166-tool-recovery.md).
Statut : correctifs applicatifs dans le worktree ; helper v2 activé sur la console de test.
L'application complète n'a pas été déployée. Les autres changements du dépôt sont préservés.

## Garanties et changements

- La détection préfère un helper v2 disponible à un helper utilisateur v1. L'installation
  vérifie sa version et `operation_recovery_available`. L'interface propose la mise à jour
  même lorsqu'une ancienne installation annonce déjà le mode enhanced.
- Un reçu `running` acquitte le lancement de `console_start`, mais ne clôt pas un
  `console_exec` interrompu. L'issue inconnue reste bloquante : aucun retry aveugle n'est ajouté.
- Les descriptions MCP et le guide système demandent de séparer les éditions, les tests longs
  et la publication. Les tests longs utilisent `console_start`, puis `console_poll` sur le même run.
- Une commande shell contenant `git push` ne crée plus de preuve de livraison. Les anciens
  reçus heuristiques restent archivés mais ne valident plus un plan ou une récupération après
  livraison. Les destinations durables explicitement demandées et les reçus de livraison
  effective conservent leurs garanties. Les consommateurs conversationnels vérifient déjà
  le fichier et la destination exacts. Aucun nouvel outil de publication Git n'est ajouté.

L'[ADR 0093](../decisions/0093-tool-outcome-evidence-and-console-recovery.md) précise ce contrat.

## Activation du helper

La vérification préalable a découvert une incompatibilité supplémentaire : l'asset v2 utilisait
une syntaxe d'exceptions propre à Python 3.14, refusée par Python 3.13.5 sur la console de test.
L'installation a été arrêtée avant remplacement. La correction ajoute les parenthèses nécessaires ;
le test de l'asset vérifie maintenant la grammaire Python 3.11, indépendamment du backend.

Après un essai du fichier préparé, le helper v2 a été installé et sa capacité de
récupération vérifiée. Deux lancements portant la même identité d’opération ont produit
un seul effet ; le parcours `console_start` / `console_poll` a retrouvé un résultat terminal.
Les identifiants, chemins, empreintes et sorties de cette installation ne sont pas publiés.
Les tâches de l’incident n’ont pas été relancées ; la mise à jour ne recrée pas leurs reçus.

## Validation et limites

Les défauts de détection, de preuve Git et de syntaxe ont été reproduits avant correction.
La sélection backend passe avec 489 tests, puis les 23 tests de console et de reprise SSH passent
après la correction de syntaxe. Le scénario navigateur du helper, `make typecheck`,
`make architecture-check`, la validation du guide système et `git diff --check` passent.

`make validate` a testé l'instantané `a682d42fd683ed82a34b1b4e7e5355ff3ca76139004a20b43e8091de45082a52`
dans `artifacts/validation/artifacts-validation.vamsNG/` : 5 197 tests backend passent, un est ignoré,
les seuils de couverture passent et les 269 tests de composants passent. Le bilan global reste
rouge : une mutation LLM devenue inadaptée entraîne l'échec des preuves de régression ; un parcours
du Lab expire une fois sous Firefox (368 E2E réussis sur 369). Le dépôt a aussi changé pendant
l'exécution : le rapport est marqué `STALE` et ne qualifie pas le worktree courant.

Les corrections concurrentes de ces deux contrôles ont ensuite été vérifiées : les 15 mutations
sont détectées, les 6 liens de régression sont validés avec le JUnit complet et les 9 tests ciblés
du Lab sous Firefox passent sur trois répétitions. Ces résultats sont conservés dans
`artifacts/redmine-166/`. Ils ne remplacent pas une nouvelle validation globale sur un dépôt
stabilisé avant publication des changements applicatifs.
