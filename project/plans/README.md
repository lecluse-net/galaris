# Plans actifs de Galaris

Revue documentaire du **1er octobre 2026**, fondée sur le code, les contrats, les tests et
les décisions du dépôt. Elle ne relance pas les qualifications et ne prouve aucun déploiement.

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
| [analyse-documentaire-unifiee.md](analyse-documentaire-unifiee.md) | `partial` | Formats non qualifiés et XLS structurel, isolation réseau des convertisseurs, contrôles sémantiques et qualification exhaustive et répétée des grandes sources. |
| [fiabilisation-conversationnelle.md](fiabilisation-conversationnelle.md) | `partial` | Mesures de latence, dont le dispatcher ; arrêt physique des autres runtimes et effets distants réels (worker Hermès direct qualifié en environnement synthétique), remplacement coordonné Task/Goal/Process ; autres surfaces de capacités et diagnostics ; recherche dans l'environnement cible, livraison d'images, contexte utile ; objets candidats concurrents et langue/effort hors du dispatcher qualifié FR/EN ; frictions du parcours complet. |
| [llm-calls-durables.md](llm-calls-durables.md) | `partial` | Création différée, commandes avec révision attendue, échéance cumulée des tentatives, entrées média et arbitrages de rejeu incertain justifiés par un consommateur. |
| [convergence-pydantic-ai.md](convergence-pydantic-ai.md) | `partial` | Métadonnées OpenRouter, étude d'un transport Codex natif alternatif, projection des réglages demandés/envoyés et extensions embeddings, realtime et média. |
| [portee-provenance-execution-agentique.md](portee-provenance-execution-agentique.md) | `partial` | Contrat générique de portée, descripteurs d'effets, plan validé, préflight et intégration de ces décisions dans l'activité existante. |
| [lab-evaluation-mecanismes-ia.md](lab-evaluation-mecanismes-ia.md) | `partial` | Qualification des campagnes FR/EN avec fournisseurs réels, étalonnage du juge, incertitude, politiques de comparabilité élargies et tendances, gardes de promotion, portabilité et jugement renforcé. |
| [optimisation-prompts-agentiques.md](optimisation-prompts-agentiques.md) | `partial` | Mesures sur corpus multilingue et sélection du contexte selon les résultats, sans modifier le contrat des sessions de Task. |
| [amelioration-globale-memoire.md](amelioration-globale-memoire.md) | `partial` | Qualification et expériences Memory/Dream/Topics ; transcriptions audio et analyses de PJ vers les souvenirs, provenance et couverture explicites, évaluation du texte extrait documentaire et utilité aval. |
| [outils-mcp-multimedia.md](outils-mcp-multimedia.md) | `partial` | Qualification des comptes et livraisons réels ; accès officiel Suno, références média, composition avancée et extensions locales à concevoir séparément. |
| [modeles-decision.md](modeles-decision.md) | `partial` | Comparaisons spécialisé/texte avec répétitions et témoin, qualification Jev réelle des usages Topics et mémoire, latence de bout en bout et optimisations guidées par les mesures ; nouveaux usages et adaptateurs locaux différés. |

## Conceptions conservées

| Plan | Statut | Portée et dépendances |
|---|---|---|
| [ordonnancement-llm-par-fournisseur.md](ordonnancement-llm-par-fournisseur.md) | `design` | Inventaire complet des appels et audit de leur demandeur/origine ; limite par connexion LLMProvider, priorités configurables par type avec audio en tête, administration, annulation, traces et chemins directs. |
| [cible.md](cible.md) | `design` | Livraison publique, gouvernance des effets, releases d'agents, autonomie, interopérabilité et exploitation. |
| [infrastructure-plugins-galaris.md](infrastructure-plugins-galaris.md) | `design` | Bundles, activation, frontend précompilé, permissions, conservation des données, compatibilité et rollback. |
| [graphe-memoire-multiechelle.md](graphe-memoire-multiechelle.md) | `design` | Repli des branches exclusives, hiérarchie et placement stables, chargement par zone/niveau de détail, actualisation progressive et qualification ; suppression du plafond global d'exploration avec budgets bornés par vue. |
| [consolidation-parametrique-lora.md](consolidation-parametrique-lora.md) | `design` | Entraînement et service de modèles à qualifier ; dépend des campagnes, de l'étalonnage et des gardes du Lab. |
| [indexation-file-share-memory.md](indexation-file-share-memory.md) | `partial` | Catalogue privé, fiches éditables, parcours Dream périodique/reprenable, réconciliation, réparation durable et suivi Memory implémentés. Identité SHA-256 par agent, emplacements File Share/Messenger, résumé partagé et aperçus intégrés. Qualification synthétique jusqu’à 100 000 entrées réalisée ; démarrage à froid et installations réelles encore à qualifier. Documents, Galaris, Web et Mail exclus. |

La piste optionnelle de visualisation 3D de la mémoire reste dans la
[cible prospective](cible.md#piste-optionnelle--visualisation-3d-de-la-mémoire).

## Suivi hors plans d'implémentation

La [matrice projet et le suivi opérationnel](../audits/2026-09-19-fiabilisation-transversale.md)
conservent les preuves de stabilisation et le point de synchronisation des anciens droits
de dialogue. Retirer un plan réalisé n'efface ni un blocage opérationnel ni une limite de
qualification. Le contrat du dialogue reste la [décision 0083](../decisions/0083-shared-teams-and-dialogue-permissions.md).

AgentAdmin est réalisé : sa [recette fournisseur](../../docs/fr/dev/agent-admin.md#recette-avec-un-fournisseur-réel)
a été réalisée en développement le 2 octobre 2026 avec OpenRouter authentifié : génération,
remplacement, réouverture et autorisations ponctuelles. Les résultats et leur périmètre sont
conservés dans le guide de vérification, sans maintenir un plan d'implémentation terminé.

Les autorisations ponctuelles MCP et des runtimes sont réalisées : leur contrat est conservé
dans la [décision 0153](../decisions/0153-common-action-authorizations.md), les parcours dans
le [guide d'administration](../../docs/fr/admin/tool-administration.md), et les preuves dans
le [catalogue des tests](../../docs/fr/dev/functional-tests.md). Les qualifications synthétiques
ne prouvent pas un déploiement. La recette AgentAdmin complète ces preuves avec un fournisseur
image réel derrière MCP ; les modèles distants propres aux quatre SDK de harnais restent
hors du périmètre de cette recette.

## Maintenance

- Chaque plan du répertoire possède exactement une entrée et un statut cohérent.
- Garder uniquement le travail restant et ses critères de réception ; renvoyer les acquis
  vers leurs sources canoniques, sans maintenir de journal d'implémentation dans les plans.
- Supprimer un plan réalisé ou absorbé et corriger ses liens entrants dans le même changement.
- Regrouper les mesures communes ; la qualification habituelle avant publication ne justifie
  pas à elle seule de conserver chaque ancien plan d'implémentation.
- Préserver les intentions non réalisées et les blocages explicites ; un nettoyage ne vaut
  ni abandon produit, ni autorisation de synchronisation ou de déploiement.
