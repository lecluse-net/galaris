# Qualification du suivi d’activité des tâches — 11 septembre 2026

Périmètre : chat, fiche tâche et `task_get`, source native ou appels LLM corrélés, état
opérationnel, demande initiale et reçus existants. Contrat :
[décision 0087](../decisions/0087-task-activity-snapshots.md).

## Preuves exécutées

| Vérification | Résultat |
|---|---|
| Régression d’événements après terminal, avant correction | 3 échecs attendus : message tardif, second résultat, exception de transport tardive |
| Campagne backend activité, runs, états, inspection, service Task, façade, action guard, harnais et corrélation LLM | 148 tests réussis |
| Complément backend : lecture MCP avec tâches persistées, filtre batch, checkpoints du harnais et livraisons conversationnelles | 55 tests réussis |
| Contrats finaux : source figée du harnais, tentative active dans `task_get`, exclusion des prompts live | 22 tests réussis |
| Reprise d’un même run : tentative, checkpoint, séquences et façade terminale | 40 tests réussis |
| `make typecheck` | Pyright et vue-tsc réussis ; 218 tests frontend réussis ; catalogues FR/EN/ZH cohérents |
| `make tests-front-components ARGS='task-panel.spec.mjs'` | 7 scénarios Chromium réussis |
| `make project-context` et contrôle de cartographie | Réussis |
| `make architecture-check` | Bloqué par la parité documentaire FR/EN de `features.md`, modifiée en parallèle ; aucune nouvelle dette de couplage acceptée |
| `git diff --check` | Réussi |

Ces campagnes se recoupent : leurs effectifs ne constituent pas un total de tests distincts.
Les tests utilisent des bases PostgreSQL et un navigateur isolés ; aucun appel fournisseur
payant n’a été lancé. Cette qualification porte sur le code du worktree, pas sur une release.

## Garanties couvertes

- Une lecture par lot ne révèle pas les tâches ou appels hors du périmètre de gestion.
- Un checkpoint cumulatif survit à la perte du cache et ne modifie pas le checkpoint d’effets.
- Les séquences rejouées et les anciens runs ne sont pas ajoutés une seconde fois.
- Une reprise du même run réinitialise la séquence de la nouvelle tentative sans reprendre
  le cache ni accepter les événements de l’ancienne tentative.
- Le snapshot restaure le chat même lorsque le run n’est pas encore présent dans l’événement Task.
- Le repli LLM exclut les autres runs et les appels auxiliaires ; mise à jour et suppression
  remplacent ou retirent leur activité, sans ajout de messages natifs.
- La fermeture d’une vue préserve l’abonnement encore utilisé par l’autre.
- Les attentes arrêtent les animations ; la fiche distingue une pause demandée et montre
  demande initiale et reçu enregistré.
- Les protections existantes contre le rejeu d’outils et les doubles livraisons restent vertes.

## Limites explicites

Le checkpoint visuel conserve une activité récente bornée et peut perdre sa dernière seconde
en cas d’arrêt brutal. Les reçus durables restent la preuve d’un effet ; l’activité visuelle
n’en constitue jamais une. L’historique des appels est borné et signale sa limite à 500 appels.
Le préflight générique de portée reste dans le plan de provenance, désormais `partial`.
