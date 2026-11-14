# Plans actifs de Galaris

Tri du **14 novembre 2026**, à partir du code, des contrats, des tests et des décisions.
Ce répertoire conserve les travaux et conceptions encore ouverts. Les lots réalisés
et leurs historiques sont retirés des plans ; leurs preuves restent dans les
[décisions](../decisions/README.md), les [audits](../audits/) et la
[documentation](../../docs/fr/README.md).
Cette revue ne rejoue ni les parcours applicatifs ni les benchmarks.

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
| [optimisation-generalisee.md](optimisation-generalisee.md) | `in-progress` | Process/MCP par élément, métadonnées Tools, grands ensembles Contact, repos/RSS/concurrence/endurance, qualification combinée et couverture restante. |
| [processus-metier-internes-bpmn.md](processus-metier-internes-bpmn.md) | `partial` | Python généraliste sur VM/hôte dédié, broker de capacités, worker Process distinct et qualifications de charge, reprise et multi-harnais. |
| [amelioration-globale-memoire.md](amelioration-globale-memoire.md) | `partial` | Embeddings réels, analyses partielles/échouées, recherche précise dans les pièces jointes, campagnes générales de rappel/acquisition et organisation des Topics après preuve de gain. |
| [graphe-memoire-multiechelle.md](graphe-memoire-multiechelle.md) | `partial` | Générations serveur, occurrences de fichiers, placement préparé, lecture régionale et qualification des très grands volumes. |
| [fiabilisation-conversationnelle.md](fiabilisation-conversationnelle.md) | `partial` | Identité sémantique, réserve indépendante, qualification multi-contextes/harnais, comptes externes, coordination de l'arrêt des Goals et parcours natifs restants. |
| [lab-evaluation-mecanismes-ia.md](lab-evaluation-mecanismes-ia.md) | `partial` | Campagnes annotées réelles, séparation des variances, comparabilité/tendances, gardes, portabilité, campagnes de modèles de décision et mocks d'applications Process. |
| [ordonnancement-llm-par-fournisseur.md](ordonnancement-llm-par-fournisseur.md) | `partial` | Provenance exhaustive en amont, priorités par opération, transports non tracés, coordination multi-backend et qualification fournisseur/charge. |
| [outils-mcp-multimedia.md](outils-mcp-multimedia.md) | `partial` | Accès officiel Suno, références/composition/annulation distante et extensions locales. |
| [programmes-documentaires-json.md](programmes-documentaires-json.md) | `partial` | Parcours d'autorisation des nouvelles applications avec données et qualification création/utilisation/persistance/partage/amélioration par un agent. |

## Conceptions

| Plan | Statut | Portée |
|---|---|---|
| [connexions-personnelles-et-partagees.md](connexions-personnelles-et-partagees.md) | `design` | Propriété humaine ou agentique, partage commun identique aux Documents, permissions par couple connexion/agent et migration DbAdmin conservant comptes, OAuth, droits et identités ; reprise et consommateurs à qualifier avant réalisation. |
| [cartes-mentales-documentaires.md](cartes-mentales-documentaires.md) | `design` | Éditeur natif Galaris à placement automatique, contenus documentaires complets, thèmes Solaire, aperçus et insertion avec barre contextuelle. Référence Planner à préciser ; contrats, prototype et qualifications restent à réaliser. |
| [migration-progressive-rust.md](migration-progressive-rust.md) | `design` | Prototypes de runtimes, protocole d'hôte et qualification sans régression ; Pydantic AI conservé comme référence. Aucun driver Rust intégré ni gain démontré. |
| [supervision-execution-llm.md](supervision-execution-llm.md) | `design` | Pilote petit/gros exécuteur, vérification métier indépendante, attente fournisseur, parcours persistant, puis supervision et escalade expérimentales. |
| [infrastructure-plugins-galaris.md](infrastructure-plugins-galaris.md) | `design` | Bundle, SDK/TCK, activation par génération et store signé ; intégrations externes et conservation des ressources après retrait. |
| [controle-distant-vnc.md](controle-distant-vnc.md) | `design` | Connexion VNC, captures MCP, simulation clavier/souris, sessions isolées et reprise humaine ; client RFB et compatibilité OS/serveurs à qualifier. |
| [consolidation-parametrique-lora.md](consolidation-parametrique-lora.md) | `design` | Gain à mesurer, corpus gouverné, trainer/serving à qualifier, invalidation et promotion dépendant des gardes du Lab. |
| [cible.md](cible.md) | `design` | Distribution publique, gouvernance d'effets, releases d'agents, autonomie événementielle, collaboration, interopérabilité, flotte et écosystème. |

## Maintenance

Chaque plan possède une seule entrée et un statut cohérent. Garder le manque actuel,
ses dépendances et ses critères de réception ; retirer les acquis vers leurs sources
canoniques, sans journal d'implémentation.
Supprimer un plan réalisé/absorbé et corriger ses liens entrants.
Regrouper les mesures communes ; une recette usuelle avant publication ne suffit pas
à maintenir un ancien plan. Préserver intentions non réalisées et blocages explicites.
