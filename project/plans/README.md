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
| [amelioration-globale-memoire.md](amelioration-globale-memoire.md) | `partial` | Transcriptions et analyses acquises vers les souvenirs, reçus tardifs et provenance réalisés (0169). Restent analyses partielles/Tasks descendantes, index PJ précis, pertinence/utilité aval sur corpus élargi, observation et réaffectation des Topics. Qualifications particulières du catalogue File Share regroupées ici. |
| [analyse-documentaire-unifiee.md](analyse-documentaire-unifiee.md) | `partial` | XLS structurel, formats non couverts, isolation réseau, contrôles sémantiques et qualification répétée des grandes sources. |
| [graphe-memoire-multiechelle.md](graphe-memoire-multiechelle.md) | `partial` | Graphe exclusivement 3D (0168), répertoires connus dès l'ouverture, fichiers paginés à l'approche, représentants des éléments masqués et actualisation sans perte de cadrage. Les états incompatibles reconstruisent le placement. Générations serveur, occurrences de fichiers, carte régionale préparée et qualification très grands volumes restent planifiées. |
| [fiabilisation-conversationnelle.md](fiabilisation-conversationnelle.md) | `partial` | Arbre Task/Process coordonné livré (0170), preuve distante tardive sans rejeu. Restent Goal active, qualification des autres runtimes, mesures des prompts/capacités et parcours illustré complet. |
| [lab-evaluation-mecanismes-ia.md](lab-evaluation-mecanismes-ia.md) | `partial` | Étalonnage, incertitude, comparabilité/tendances, gardes et portabilité ; campagnes des modèles de décision ; intégration progressive des tests/benchmarks Process, mocks d'applications en seconde phase. |
| [llm-calls-durables.md](llm-calls-durables.md) | `partial` | Préparation/démarrage explicite, révision des commandes et échéance globale livrés (0170). Restent entrées médias supplémentaires et mesures du journal selon consommateur ; qualification fournisseur distincte. |
| [convergence-pydantic-ai.md](convergence-pydantic-ai.md) | `partial` | Métadonnées OpenRouter, transport Codex alternatif, projection des réglages, surfaces supplémentaires et adaptateurs de décision différés. |
| [portee-provenance-execution-agentique.md](portee-provenance-execution-agentique.md) | `partial` | Contrat v1, admission/héritage/amendement, validation du plan, descripteurs natifs et préflight durable intégrés à l'activité (0170). Restent qualification élargie, cibles non canoniques et métadonnées des outils externes. |
| [outils-mcp-multimedia.md](outils-mcp-multimedia.md) | `partial` | Accès officiel Suno, références/composition/annulation distante et extensions locales ; recettes des comptes dans le guide. |

## Conceptions

| Plan | Statut | Portée |
|---|---|---|
| [editeur-code-conversationnel.md](editeur-code-conversationnel.md) | `design` | code-server dans le panneau documentaire du Chat, même dépôt/worktree et fonctionnement standard de VS Code ; Git humain avec la configuration et les clés SSH existantes de l'agent, présentation pendant les Tasks. Consoles interne et externe requises ; identité humaine séparée et environnement terminal complet facultatifs. Sessions, droits et consultation protégée à qualifier. |
| [processus-metier-internes-bpmn.md](processus-metier-internes-bpmn.md) | `design` | BPMN interne : Tasks/prompts, IF/FOR/WHILE, parallélisme selon graphe/harnais, erreurs, imbrication et reprise ; aucun budget v1. Lancement du contenu courant sans choix de version, historique/restauration, WYSIWYG/débogueur, métriques, Dataset/PJ, partage Document et audit MCP ; accès humains/lecture seule/orphelins administrés, Tools/Connections/REST, coexistence n8n ; Lab progressif et mocks en seconde phase. |
| [programmes-documentaires-json.md](programmes-documentaires-json.md) | `design` | Programmes dans les Documents, `document_exec` avec nom personnel et entrée/sortie JSON, dernier contenu sauvegardé au démarrage, moteur isolé, suivi Process et amélioration autonome. |
| [ordonnancement-llm-par-fournisseur.md](ordonnancement-llm-par-fournisseur.md) | `design` | Provenance exhaustive, limite par connexion, priorités par type avec audio réservé, admission/annulation, activité et reprise. |
| [supervision-execution-llm.md](supervision-execution-llm.md) | `design` | Conversation conservée, petits exécuteurs et supervision par gros modèle à comparer ; corpus synthétiques, benchmarks de tâches complètes, escalade, coût par réussite et décision par famille. |
| [navigation-file-share-harnais.md](navigation-file-share-harnais.md) | `design` | Hypothèse à confirmer : premier essai non concluant, aucun chantier FUSE engagé avant un gain utile démontré par une comparaison MCP/répertoire fiable. |
| [infrastructure-plugins-galaris.md](infrastructure-plugins-galaris.md) | `design` | Bundle, SDK/TCK, activation par génération, frontend précompilé, permissions, conservation SQL, rollback et store signé. |
| [controle-distant-vnc.md](controle-distant-vnc.md) | `design` | Connexion VNC, captures MCP, simulation clavier/souris, sessions isolées et reprise humaine ; client RFB et compatibilité OS/serveurs à qualifier. |
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
