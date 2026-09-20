# Plans actifs de Galaris

Nettoyage documentaire du **19 septembre 2026**, fondé sur les contrats, décisions et preuves
déjà consignés. Il ne relance pas les qualifications et ne prouve aucun déploiement.

Cet index contient uniquement les extensions, mesures et conceptions encore ouvertes.
Les étapes réalisées appartiennent aux [décisions](../decisions/README.md), aux tests et à la
[documentation](../../docs/fr/README.md). La présence d'un plan ne vaut ni autorisation
d'implémentation ni nouvel ordre de priorité produit.

## Statuts

| Statut | Signification |
|---|---|
| `design` | Conception conservée ; réalisation non engagée ou non démontrée |
| `approved` | Périmètre accepté, implémentation non commencée ou non démontrée |
| `in-progress` | Implémentation encore en cours |
| `partial` | Socle réalisé ; extensions ou qualifications spécifiques ouvertes |

## Travaux à terminer

| Plan | Statut | Reste à faire |
|---|---|---|
| [fiabilisation-conversationnelle.md](fiabilisation-conversationnelle.md) | `partial` | Mesures de latence, dont le dispatcher ; arrêt physique des runtimes et remplacement coordonné Task/Goal/Process ; autres surfaces de capacités et diagnostics ; recherche dans l'environnement cible, livraison d'images, contexte utile, langue/effort et frictions du parcours complet. |
| [llm-calls-durables.md](llm-calls-durables.md) | `partial` | Création différée, commandes avec révision attendue, échéance globale, entrées média, rétention et arbitrages de rejeu incertain justifiés par un consommateur. |
| [convergence-pydantic-ai.md](convergence-pydantic-ai.md) | `partial` | Métadonnées OpenRouter, changements d'intégration/protocole à qualifier, projection des réglages demandés/envoyés et surfaces média. |
| [portee-provenance-execution-agentique.md](portee-provenance-execution-agentique.md) | `partial` | Contrat générique de portée, descripteurs d'effets, briefing validé, préflight et intégration de ces décisions dans l'activité existante. |
| [lab-evaluation-mecanismes-ia.md](lab-evaluation-mecanismes-ia.md) | `partial` | Étalonnage du juge, incertitude, comparabilité et tendances, gardes de promotion, portabilité et jugement renforcé. |
| [optimisation-prompts-agentiques.md](optimisation-prompts-agentiques.md) | `partial` | Mesures sur corpus multilingue et sélection du contexte selon les résultats, sans modifier le contrat des sessions de Task. |
| [amelioration-globale-memoire.md](amelioration-globale-memoire.md) | `partial` | Qualification multilingue et sur d'autres corpus, utilité aval, nouvelles extractions de PJ, provenance fine, observation et expériences Memory/Dream/Topics. |
| [outils-mcp-multimedia.md](outils-mcp-multimedia.md) | `partial` | Qualification des comptes et livraisons réels ; accès officiel Suno, références média, composition avancée et extensions locales à concevoir séparément. |

## Conceptions conservées

| Plan | Statut | Portée et dépendances |
|---|---|---|
| [cible.md](cible.md) | `design` | Livraison publique, gouvernance des effets, releases d'agents, autonomie, interopérabilité et exploitation. |
| [infrastructure-plugins-galaris.md](infrastructure-plugins-galaris.md) | `design` | Bundles, activation, frontend précompilé, permissions, conservation des données, compatibilité et rollback. |
| [consolidation-parametrique-lora.md](consolidation-parametrique-lora.md) | `design` | Entraînement et service de modèles à qualifier ; dépend des campagnes, de l'étalonnage et des gardes du Lab. |

La piste optionnelle de visualisation 3D de la mémoire reste dans la
[cible prospective](cible.md#piste-optionnelle--visualisation-3d-de-la-mémoire).

## Suivi hors plans d'implémentation

La [matrice projet et le suivi opérationnel](../audits/2026-09-19-fiabilisation-transversale.md)
conservent les preuves de stabilisation et le point de synchronisation des anciens droits
de dialogue. Retirer un plan réalisé n'efface ni un blocage opérationnel ni une limite de
qualification. Le contrat du dialogue reste la [décision 0083](../decisions/0083-shared-teams-and-dialogue-permissions.md).

## Maintenance

- Chaque plan du répertoire possède exactement une entrée et un statut cohérent.
- Garder uniquement le travail restant et ses critères de réception ; renvoyer les acquis
  vers leurs sources canoniques, sans maintenir de journal d'implémentation dans les plans.
- Supprimer un plan réalisé ou absorbé et corriger ses liens entrants dans le même changement.
- Regrouper les mesures communes ; la qualification habituelle avant publication ne justifie
  pas à elle seule de conserver chaque ancien plan d'implémentation.
- Préserver les intentions non réalisées et les blocages explicites ; un nettoyage ne vaut
  ni abandon produit, ni autorisation de synchronisation ou de déploiement.
