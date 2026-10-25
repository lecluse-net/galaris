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
| [graphe-memoire-multiechelle.md](graphe-memoire-multiechelle.md) | `partial` | Graphe exclusivement 3D (0168), répertoires connus dès l'ouverture, fichiers paginés à l'approche, représentants des éléments masqués et actualisation sans perte de cadrage. Les états incompatibles reconstruisent le placement. Générations serveur, occurrences de fichiers, carte régionale préparée et qualification très grands volumes restent planifiées. |
| [fiabilisation-conversationnelle.md](fiabilisation-conversationnelle.md) | `partial` | Mission/Goals : consignes, 12 familles FR/EN et contrôles de contenu/effets réalisés. Contrat de cycle ciblé : question humaine FR 0/10 → 10/10, EN 2/10 → 10/10, appels 97 → 26 ; consommateurs Goal 60/60, droits/Process/injection 18/18, transfert/reprise 50/50 après correction du faux positif EUR/€. Aucun échec apparié nouveau observé. Constructeur réel : réussite conservée 6/6, appels 17 → 7. Parcours Goal natif : 12/12 → 12/12 ; C8 retire 12 écritures et 14 autorisations redondantes, appels 86 → 64 ; livraison requise 6/6. Historiques interne/Hermes/OpenAI : attribution corrigée et sept reproductions vérifiées ; quatre SDK réels testés hors réseau extérieur. Premier message corrigé : quatre lectures invalides → zéro, parcours assemblé 3/3 navigateurs. Quartz : les deux défauts initiaux sont absents du nouvel essai (deux contributions, 20 appels, 0,05559 USD) ; classement court après précision finale 8/9 → 9/9, vrais conflits conservés 3/3. Recette et limites dans la [qualification élargie](../audits/2026-10-24-conversation-qualification.md). Autres contextes, réserve indépendante et autres parcours natifs restent ouverts. Première mission sur Welcome et extraction ENRICH/CONTRADICT réalisées (0228). Identité sémantique, comptes externes et coordination de Goal restent ouverts. |
| [lab-evaluation-mecanismes-ia.md](lab-evaluation-mecanismes-ia.md) | `partial` | Rapports d'étalonnage humain et incertitude par cas réalisés (0230), répétabilité du juge sur sorties fixes par API et interface (0236) ; restent expériences réelles, campagnes annotées, séparation des variances, comparabilité/tendances, gardes et portabilité ; campagnes des modèles de décision et mocks d'applications Process. Le socle de campagnes Process avec Datasets natifs et runs réels est livré (0225). |
| [ordonnancement-llm-par-fournisseur.md](ordonnancement-llm-par-fournisseur.md) | `partial` | Admission partagée, configuration et contexte typé réalisés (0181) ; rotation Task/run/Process/source serveur/agent/demandeur couverte. Restent provenance exhaustive en amont, priorités par opération, transports non tracés, coordination multi-backend et qualification de charge/fournisseur. |
| [outils-mcp-multimedia.md](outils-mcp-multimedia.md) | `partial` | Accès officiel Suno, références/composition/annulation distante et extensions locales ; recettes des comptes dans le guide. |
| [programmes-documentaires-json.md](programmes-documentaires-json.md) | `partial` | Objectif précisé : petites applications créées par les agents et utilisables dans Galaris. HTML/JavaScript et Datasets indépendants réalisés ; restent le parcours d'autorisation des nouvelles applications avec données et la qualification création/utilisation/amélioration. Catalogue de programmes et moteur serveur retirés des prérequis. |

## Conceptions

| Plan | Statut | Portée |
|---|---|---|
| [supervision-execution-llm.md](supervision-execution-llm.md) | `design` | Comptabilité par appel, bilan Task et coût par réussite du benchmark implémentés (0238). Restent pilote petit/gros exécuteur, vérification métier indépendante, attente fournisseur, parcours persistant, puis supervision et escalade expérimentales ; aucun gain de cette répartition démontré. |
| [infrastructure-plugins-galaris.md](infrastructure-plugins-galaris.md) | `design` | Bundle, SDK/TCK, activation par génération, frontend précompilé, permissions, conservation SQL, rollback et store signé. |
| [controle-distant-vnc.md](controle-distant-vnc.md) | `design` | Connexion VNC, captures MCP, simulation clavier/souris, sessions isolées et reprise humaine ; client RFB et compatibilité OS/serveurs à qualifier. |
| [consolidation-parametrique-lora.md](consolidation-parametrique-lora.md) | `design` | Gain à mesurer, corpus gouverné, trainer/serving à qualifier, invalidation et promotion dépendant des gardes du Lab. |
| [cible.md](cible.md) | `design` | Distribution publique, gouvernance d'effets, releases d'agents, autonomie événementielle, collaboration, interopérabilité, flotte et écosystème ; piste 3D optionnelle. |

## Plans retirés et suivi conservé

- **Skills personnels des agents** : fonctionnalité réalisée et plan retiré le 25 octobre 2026.
  Contrat conservé dans [0222](../decisions/0222-personal-skill-package-boundary.md),
  parcours dans les guides utilisateur [FR](../../docs/fr/user/skills.md) et
  [EN](../../docs/en/user/skills.md), garanties dans les tests existants.

- **Navigation File Share par harnais** : expérience terminée sur 120 exécutions ;
  gain de coût du répertoire, mais non-dégradation de réussite non établie. Piste FUSE
  arrêtée dans [0237](../decisions/0237-file-share-navigation-experiment.md), preuves et
  limites dans l'[audit](../audits/2026-10-25-file-share-navigation.md). Le plan est
  retiré des travaux actifs ; sa conception conditionnelle reste dans l'historique Git.

- **Analyse documentaire unifiée** : préparation commune, Chat/Responses, reprise et
  cache autorisé réalisés dans [0149](../decisions/0149-transient-document-preparation.md)
  et [0151](../decisions/0151-resumable-document-analysis.md). Formats non qualifiés,
  absence de confinement réseau explicite, limites sémantiques et critères des campagnes
  répétées sont regroupés dans le [guide de qualification](../../docs/fr/dev/document-qualification.md).
  Le retrait du plan ne qualifie pas ces extensions ; acquisition et rappel restent
  dans le plan mémoire, comparaisons dans le Lab.
- **Réorganisation RBAC** : garde central, 24 droits fonctionnels, menus/onglets,
  paramètres par domaine, transports et projection unique des rôles réalisés ; contrat dans
  [0233](../decisions/0233-functional-domain-privileges.md), conclusions dans
  [l'audit](../audits/2026-10-24-rbac-reorganisation.md) et garanties dans le
  [catalogue de tests](../../docs/fr/dev/functional-tests.md). Aucun rôle ou regroupement
  personnalisé n'est remplacé par un modèle imposé.
- **Portée et provenance d'exécution** : contrat v1, admission/héritage/amendement,
  validation du plan, préflight durable et activité réalisés dans
  [0170](../decisions/0170-execution-scope-and-durable-controls.md) ; cibles d'écriture
  contextuelles dans [0206](../decisions/0206-contextual-task-write-targets.md).
  Qualification élargie et pannes après effet dans le [plan conversationnel](fiabilisation-conversationnelle.md) ;
  extensions de cibles et descripteurs externes dans la [cible prospective](cible.md#gouvernance-des-effets).
- **Inférences durables** : cycle persistant, commandes, préparation, révisions et
  échéance globale réalisés dans [0097](../decisions/0097-durable-inference-lifecycle.md)
  et [0170](../decisions/0170-execution-scope-and-durable-controls.md).
  Le journal et la supervision bornés sont décrits par
  [0207](../decisions/0207-bounded-stream-supervision.md).
- **Convergence SDK/fournisseurs** : plan retiré le 25 octobre 2026. Les contrats livrés
  restent décrits par [0095](../decisions/0095-pydantic-ai-request-ownership.md),
  [0097](../decisions/0097-durable-inference-lifecycle.md) et
  [0170](../decisions/0170-execution-scope-and-durable-controls.md).
  Les mises à jour des dépendances sont qualifiées sur les contrats existants, sans
  réglages locaux par famille ou version de modèle. Les extensions prospectives ne
  constituent plus un chantier de convergence à réaliser.
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
