# Plans actifs de Galaris

Revue du **8 octobre 2026**, par comparaison des sources, contrats, tests et décisions.
Elle prend en compte le worktree courant ; elle ne rejoue pas les campagnes et ne prouve
ni qualification globale ni déploiement.

Ce répertoire conserve les écarts concrets, conceptions et expériences encore ouverts.
Les contrats réalisés appartiennent aux [décisions](../decisions/README.md),
aux tests et à la [documentation](../../docs/fr/README.md).
Un plan ne vaut ni ordre d'implémentation ni nouvelle priorité produit.

## Statuts

| Statut | Signification |
|---|---|
| `design` | Conception conservée ; réalisation non engagée ou non démontrée. |
| `approved` | Périmètre accepté ; implémentation non commencée ou non démontrée. |
| `in-progress` | Implémentation en cours. |
| `partial` | Socle réalisé ; extensions ou expériences spécifiques ouvertes. |

## Extensions et expériences

| Plan | Statut | Reste à faire |
|---|---|---|
| [amelioration-globale-memoire.md](amelioration-globale-memoire.md) | `partial` | Transcriptions/PJ vers les souvenirs, provenance et texte extrait ; pertinence/utilité aval sur corpus élargi ; observation détaillée, granularité et réaffectation des Topics. Qualifications particulières du catalogue File Share regroupées ici. |
| [analyse-documentaire-unifiee.md](analyse-documentaire-unifiee.md) | `partial` | XLS structurel, formats non couverts, isolation réseau, contrôles sémantiques et qualification répétée des grandes sources. |
| [graphe-memoire-multiechelle.md](graphe-memoire-multiechelle.md) | `partial` | Socle 2D avec positions et présentation persistées par utilisateur ; conception de la carte 3D, hiérarchie de fichiers/Topics/contacts, placement précalculé périodique avec ajouts en direct, lecture régionale et qualification petits/grands volumes. |
| [fiabilisation-conversationnelle.md](fiabilisation-conversationnelle.md) | `partial` | Mesures du parcours/dispatcher et des prompts ; arrêt externe et remplacement coordonné ; autres capacités/diagnostics, contexte, langue et parcours illustré complet. |
| [lab-evaluation-mecanismes-ia.md](lab-evaluation-mecanismes-ia.md) | `partial` | Étalonnage, incertitude, comparabilité/tendances, gardes et portabilité ; campagnes spécialisé/texte des modèles de décision regroupées ici. |
| [llm-calls-durables.md](llm-calls-durables.md) | `partial` | Préparation différée, révision des commandes, échéance cumulée, médias et arbitrages de rejeu justifiés par un consommateur. |
| [convergence-pydantic-ai.md](convergence-pydantic-ai.md) | `partial` | Métadonnées OpenRouter, transport Codex alternatif, projection des réglages, surfaces supplémentaires et adaptateurs de décision différés. |
| [portee-provenance-execution-agentique.md](portee-provenance-execution-agentique.md) | `partial` | Scope/grants génériques, descripteurs d'effets, plan validé, préflight et intégration dans activité/reprise existantes. |
| [outils-mcp-multimedia.md](outils-mcp-multimedia.md) | `partial` | Accès officiel Suno, références/composition/annulation distante et extensions locales ; recettes des comptes dans le guide. |

## Conceptions

| Plan | Statut | Portée |
|---|---|---|
| [ordonnancement-llm-par-fournisseur.md](ordonnancement-llm-par-fournisseur.md) | `design` | Provenance exhaustive, limite par connexion, priorités par type avec audio réservé, admission/annulation, activité et reprise. |
| [infrastructure-plugins-galaris.md](infrastructure-plugins-galaris.md) | `design` | Bundle, SDK/TCK, activation par génération, frontend précompilé, permissions, conservation SQL, rollback et store signé. |
| [consolidation-parametrique-lora.md](consolidation-parametrique-lora.md) | `design` | Gain à mesurer, corpus gouverné, trainer/serving à qualifier, invalidation et promotion dépendant des gardes du Lab. |
| [cible.md](cible.md) | `design` | Distribution publique, gouvernance d'effets, releases d'agents, autonomie événementielle, collaboration, interopérabilité, flotte et écosystème ; piste 3D optionnelle. |

## Plans retirés et suivi conservé

- **Indexation File Share/Memory** : catalogue, reprise, réparation, Dream, SHA-256 et
  emplacements Messenger réalisés ; contrats dans [0155](../decisions/0155-durable-file-indexing.md).
  Recettes de démarrage à froid/providers et capacités avancées dans le plan mémoire.
- **Optimisation des prompts** : composition livrée ; mesures/contexte repris dans
  Conversation, pertinence/capture dans Mémoire, infrastructure dans le Lab.
- **Modèles de décision** : workflows livrés ; comparaisons dans le Lab,
  adaptateurs différés dans SDK et fournisseurs.

Les preuves de stabilisation et blocages opérationnels restent dans la
[matrice projet](../audits/2026-09-19-fiabilisation-transversale.md).
AgentAdmin et les autorisations ponctuelles ont leurs
[recettes](../../docs/fr/dev/agent-admin.md#recette-avec-un-fournisseur-réel),
[contrat](../decisions/0153-common-action-authorizations.md) et
[tests](../../docs/fr/dev/functional-tests.md), sans plan d'implémentation terminé.

## Maintenance

Chaque plan possède une seule entrée et un statut cohérent. Garder le manque actuel,
ses dépendances et ses critères de réception ; retirer les acquis vers leurs sources
canoniques, sans journal d'implémentation.
Supprimer un plan réalisé/absorbé et corriger ses liens entrants.
Regrouper les mesures communes ; une recette usuelle avant publication ne suffit pas
à maintenir un ancien plan. Préserver intentions non réalisées et blocages explicites.
