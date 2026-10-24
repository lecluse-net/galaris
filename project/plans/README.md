# Plans actifs de Galaris

Tri du **24 octobre 2026**, à partir des contrats, du code, des tests existants et des
décisions. Les plans de l'éditeur de code, de la séparation Memory/Document, des
inférences durables et du contrat de portée/provenance sont retirés : leur périmètre
livré est documenté dans les décisions 0173, 0223, 0097, 0170 et 0206. La revue
des baselines de la séparation est acquise ; son ancienne attente est périmée.
Les autres plans conservent des extensions, conceptions ou expériences ouvertes.
Le socle Process du Lab est réalisé ; ses mocks d'applications restent à concevoir.
Ce tri ne rejoue ni les parcours applicatifs ni les benchmarks et ne prouve aucun déploiement.

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
| [optimisation-generalisee.md](optimisation-generalisee.md) | `in-progress` | En pause le soir du 24 octobre, reprise prévue le 25 : Process/MCP par élément, métadonnées Tools, grands ensembles Contact, repos/RSS/concurrence/endurance, qualification combinée et couverture restante. Plan recentré sur les travaux ouverts ; quinze lots réalisés documentés dans l’[audit](../audits/optimisation-generalisee/README.md). Conservation jusqu’à clôture ou transfert explicite des restes. |
| [processus-metier-internes-bpmn.md](processus-metier-internes-bpmn.md) | `partial` | Profil v2 réalisé : contrats locaux typés, URI sans transfert, intégration idempotente, jobs MCP/REST et convergence. IF binaires IA/code/humain selon l'acteur ; computations Python pures dans les workers Monty avec snapshot du Dataset. Restent le Python généraliste sur VM/hôte dédié, le broker de capacités, le worker Process distinct et les qualifications de charge/multi-harnais. |
| [amelioration-globale-memoire.md](amelioration-globale-memoire.md) | `partial` | Fidélité des acquisitions, attribution Task, descendants/Goals, réemploi des analyses de l'arbre, contexte protégé, origines et conflits livrés (0229). Comparaison sur 1 320 questions synthétiques et contrôle aval réel sur dix questions : gains d'injection, classement inchangé et coûts explicités. Restent embeddings réels indisponibles, analyses partielles, index PJ précis, qualifications générales et réaffectation des Topics après preuve de gain. |
| [analyse-documentaire-unifiee.md](analyse-documentaire-unifiee.md) | `partial` | XLS structurel réalisé et qualifié sur BIFF8 synthétique/LibreOffice ; variantes historiques et formules indécodables, formats non couverts, isolation réseau, contrôles sémantiques et qualification répétée des grandes sources. |
| [graphe-memoire-multiechelle.md](graphe-memoire-multiechelle.md) | `partial` | Graphe exclusivement 3D (0168), répertoires connus dès l'ouverture, fichiers paginés à l'approche, représentants des éléments masqués et actualisation sans perte de cadrage. Les états incompatibles reconstruisent le placement. Générations serveur, occurrences de fichiers, carte régionale préparée et qualification très grands volumes restent planifiées. |
| [fiabilisation-conversationnelle.md](fiabilisation-conversationnelle.md) | `partial` | Arbre Task/Process coordonné livré (0170), preuve distante tardive sans rejeu. Première mission sur Welcome et extraction ENRICH/CONTRADICT réalisées (0228). Le programme global identité, attribution et choix documentaire reste partiel ; restent Goal active, qualification des runtimes, mesures des prompts/capacités et qualification élargie. |
| [lab-evaluation-mecanismes-ia.md](lab-evaluation-mecanismes-ia.md) | `partial` | Rapports d'étalonnage humain et incertitude par cas réalisés (0230) ; restent campagnes annotées, séparation des variances, comparabilité/tendances, gardes et portabilité ; campagnes des modèles de décision et mocks d'applications Process. Le socle de campagnes Process avec Datasets natifs et runs réels est livré (0225). |
| [ordonnancement-llm-par-fournisseur.md](ordonnancement-llm-par-fournisseur.md) | `partial` | Admission partagée et configuration réalisées (0181) ; restent provenance exhaustive, priorités par opération, transports non tracés, coordination multi-backend et qualification de charge/fournisseur. |
| [convergence-pydantic-ai.md](convergence-pydantic-ai.md) | `partial` | Métadonnées OpenRouter, transport Codex alternatif, projection des réglages, surfaces supplémentaires et adaptateurs de décision différés. Extensions médias durables, futurs consommateurs du rejeu et mesures du journal regroupés ici. |
| [outils-mcp-multimedia.md](outils-mcp-multimedia.md) | `partial` | Accès officiel Suno, références/composition/annulation distante et extensions locales ; recettes des comptes dans le guide. |

## Conceptions

| Plan | Statut | Portée |
|---|---|---|
| [skills-personnels-agents.md](skills-personnels-agents.md) | `partial` | Tool unique Skills, MCP, File Share, harnais, portées usage/personal/team/all, conversions générique/personnel avec révocation des droits et reprise, et administration humaine réalisés. Reste la qualification de l'ensemble des harnais sur une installation dédiée. Portée équipe : union des agents de ses équipes, réévaluée à chaque appel. |
| [programmes-documentaires-json.md](programmes-documentaires-json.md) | `design` | Programmes dans les Documents, `document_exec` avec nom personnel et entrée/sortie JSON, dernier contenu sauvegardé au démarrage, moteur isolé, suivi Process et amélioration autonome. |
| [supervision-execution-llm.md](supervision-execution-llm.md) | `design` | Conversation conservée, petits exécuteurs et supervision par gros modèle à comparer ; corpus synthétiques, benchmarks de tâches complètes, escalade, coût par réussite et décision par famille. |
| [navigation-file-share-harnais.md](navigation-file-share-harnais.md) | `design` | Hypothèse à confirmer : premier essai non concluant, aucun chantier FUSE engagé avant un gain utile démontré par une comparaison MCP/répertoire fiable. |
| [infrastructure-plugins-galaris.md](infrastructure-plugins-galaris.md) | `design` | Bundle, SDK/TCK, activation par génération, frontend précompilé, permissions, conservation SQL, rollback et store signé. |
| [controle-distant-vnc.md](controle-distant-vnc.md) | `design` | Connexion VNC, captures MCP, simulation clavier/souris, sessions isolées et reprise humaine ; client RFB et compatibilité OS/serveurs à qualifier. |
| [consolidation-parametrique-lora.md](consolidation-parametrique-lora.md) | `design` | Gain à mesurer, corpus gouverné, trainer/serving à qualifier, invalidation et promotion dépendant des gardes du Lab. |
| [cible.md](cible.md) | `design` | Distribution publique, gouvernance d'effets, releases d'agents, autonomie événementielle, collaboration, interopérabilité, flotte et écosystème ; piste 3D optionnelle. |

## Plans retirés et suivi conservé

- **Portée et provenance d'exécution** : contrat v1, admission/héritage/amendement,
  validation du plan, préflight durable et activité réalisés dans
  [0170](../decisions/0170-execution-scope-and-durable-controls.md) ; cibles d'écriture
  contextuelles dans [0206](../decisions/0206-contextual-task-write-targets.md).
  Qualification élargie et pannes après effet dans le [plan conversationnel](fiabilisation-conversationnelle.md) ;
  extensions de cibles et descripteurs externes dans la [cible prospective](cible.md#gouvernance-des-effets).
- **Inférences durables** : cycle persistant, commandes, préparation, révisions et
  échéance globale réalisés dans [0097](../decisions/0097-durable-inference-lifecycle.md)
  et [0170](../decisions/0170-execution-scope-and-durable-controls.md).
  Extensions médias, réception des futurs consommateurs du rejeu et mesures du journal
  regroupées dans le [plan SDK/fournisseurs](convergence-pydantic-ai.md), sans chantier
  distinct pour le cycle livré.
- **Éditeur de code conversationnel** : intégration, reprise et profils réalisés ;
  contrat et limites dans [0173](../decisions/0173-conversational-code-workspaces.md),
  parcours dans le [guide utilisateur](../../docs/fr/user/code-editor.md).
  Thème synchronisé, terminal Console complet et identité Git humaine distincte restent
  des extensions facultatives décrites par la décision, sans maintenir le plan terminé.
- **Séparation Memory/Document** : documents et résumés autonomes, souvenirs privés,
  migration et consommateurs réalisés ; revue des dépendances et baselines acquise dans
  [0223](../decisions/0223-memory-document-independence.md). Les suites de frontière et de
  migration conservent les garanties ; le plan ne porte plus de travail ouvert.
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
