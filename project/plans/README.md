# Plans actifs de Galaris

Tri du **14 novembre 2026**, à partir du code, des contrats, des tests et des décisions.
Ce répertoire conserve les travaux et conceptions encore ouverts. Les lots réalisés
et leurs historiques sont retirés des plans ; leurs preuves restent dans les
[décisions](../decisions/README.md), les [audits](../audits/) et la
[documentation](../../docs/fr/README.md).
Cette revue ne rejoue ni les parcours applicatifs ni les benchmarks.

Un plan ne vaut ni ordre d'implémentation ni nouvelle priorité produit.

## Essai sur deux chantiers indépendants

À l’ouverture de chacune des deux prochaines demandes pouvant être livrées séparément,
inscrire ici son intitulé et le résultat attendu. À la réception, relier son compte rendu
habituel et y répondre brièvement à trois questions.

- A-t-on pu accepter ce résultat alors que l’autre chantier restait ouvert ? En cas
  de blocage, quelle dépendance a imposé d’attendre ?
- Quelle vérification a changé la décision de livrer ou levé une incertitude précise ?
- Quelle étape a demandé de refaire du travail, et pour quelle raison ?

Après la seconde réception, comparer les deux retours. Conserver les pratiques qui ont
aidé à décider, alléger les doublons et choisir en priorité une difficulté qui s’est
répétée. Consigner la décision dans le second compte rendu, puis retirer ce suivi temporaire.

## Campagne engagée le 15 novembre 2026

Les cinq chantiers demandés sont repris dans les suivis existants :

| Chantier | Suivi | Première réception |
|---|---|---|
| Réussite des missions | Lab IA | Campagne synthétique avec modèle réel, revue des échecs et de la cohérence des références. |
| Arrêt et reprise | Fiabilisation conversationnelle | Contrats durables puis qualification des runtimes isolés, sans arrêter de travaux utilisateurs. |
| Précision mémoire | Amélioration globale de la mémoire | Pièces jointes, droits vivants et recherche dans des PDF synthétiques, dont les pages scannées. |
| Performance | [Travaux ouverts de l’audit d’optimisation](../audits/optimisation-generalisee/README.md#travaux-ouverts) | Lectures SQL Process/MCP jusqu'à 500 résultats, permissions Services ciblées et annuaires canoniques de 501/1 001 destinataires ; contenu, droits et fraîcheur préservés. |
| Première mission | [Observation de la première mission](#observation-de-la-première-mission) | Accueil, édition, partage et réouverture dans l'application assemblée. Prochaine étape ouverte : observer une personne qui découvre Galaris. |

L'autorisation porte sur les qualifications, les corrections démontrées et les
simplifications des mécanismes existants. **Tout nouveau mécanisme applicatif exige
l'accord explicite de l'utilisateur.** Les propositions de gardes ou de contrôle de
dérive présentes dans les plans ne sont pas autorisées par cette reprise. Réutiliser
les outils et tests existants ; ne pas ajouter de dispositif de supervision automatique.
Les qualifications ciblées ne clôturent ni les plans entiers ni les essais de charge,
les comptes distants réels ou la réserve indépendante encore manquants.

### Observation de la première mission

Sur une instance de développement avec un compte de démonstration, proposer à la personne
une consigne avec un résultat reconnaissable : « Demandez à un agent de préparer une liste
pour un pique-nique. Quittez la conversation, puis retrouvez sa réponse. » La laisser choisir
son chemin. Si elle hésite, lui demander ce qu’elle pense que l’application est en train de
faire. Noter à quelle étape une aide a été nécessaire, le cas échéant.

Critère de réussite de cette séance : la personne retrouve la réponse à sa demande initiale
sans guidage. Consigner ici le résultat, la première difficulté observable et le moyen de
vérifier sa cause, sous forme anonymisée. En cas de relance, par exemple, relever l’état
affiché avant le second envoi et tenter de le reproduire avec la même demande synthétique.
Si le parcours aboutit directement, consigner la réussite. La fréquence d’une difficulté
se vérifie lors d’autres séances.

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
| [processus-metier-internes-bpmn.md](processus-metier-internes-bpmn.md) | `partial` | Endurance en VM, réconciliation File Sharing et n8n Data Tables, aller-retour réel n8n et parcours BPMN local avec le SDK Claude Agent vérifiés. Restent l'infrastructure cible et les campagnes avec les comptes et charges représentatifs. |
| [amelioration-globale-memoire.md](amelioration-globale-memoire.md) | `in-progress` | Embeddings réels, analyses partielles/échouées, recherche précise dans les pièces jointes, campagnes générales de rappel/acquisition et organisation des Topics après preuve de gain. |
| [graphe-memoire-multiechelle.md](graphe-memoire-multiechelle.md) | `partial` | Générations serveur, occurrences de fichiers, placement préparé, lecture régionale et qualification des très grands volumes. |
| [fiabilisation-conversationnelle.md](fiabilisation-conversationnelle.md) | `in-progress` | Identité sémantique, réserve indépendante, qualification multi-contextes/harnais, comptes externes, coordination de l'arrêt des Goals et parcours natifs restants. |
| [lab-evaluation-mecanismes-ia.md](lab-evaluation-mecanismes-ia.md) | `in-progress` | Campagnes annotées réelles, séparation des variances, comparabilité/tendances, gardes, portabilité, campagnes de modèles de décision et mocks d'applications Process. |
| [ordonnancement-llm-par-fournisseur.md](ordonnancement-llm-par-fournisseur.md) | `partial` | Provenance exhaustive en amont, priorités par opération, transports non tracés, coordination multi-backend et qualification fournisseur/charge. |
| [programmes-documentaires-json.md](programmes-documentaires-json.md) | `partial` | Parcours d'autorisation des nouvelles applications avec données et qualification création/utilisation/persistance/partage/amélioration par un agent. |
| [infrastructure-plugins-galaris.md](infrastructure-plugins-galaris.md) | `partial` | Archives signées, formats binaires, profils IA, aperçus, modèles Données, protocoles File Share et catalogue HTTPS administré. Autres protocoles, isolation tierce, schéma propre et publication officielle restent ouverts. |

## Conceptions

| Plan | Statut | Portée |
|---|---|---|
| [deux-harnais-internes.md](deux-harnais-internes.md) | `in-progress` | Chaque harnais embarqué gère sa conversation. DSH et Codex confient leurs rounds à Claude. Filiation exacte des appels LLM, parité et benchmark pour décider du maintien de Pydantic AI, indépendamment du portage Rust. |
| [fluidite-droits-et-montee-en-charge.md](fluidite-droits-et-montee-en-charge.md) | `in-progress` | Montage MCP, streaming et contrôle des droits de dialogue. Admission Chat testée avec une seule connexion SQL, charge mixte à 30 et 50 comptes avec mesure dans Chromium. Restauration des ressources et endurance à qualifier. |
| [travaux-et-fusion-des-objectifs.md](travaux-et-fusion-des-objectifs.md) | `design` | Pilotage des Travaux, orientation des entrées, reprise des attentes, articulation avec Process, coûts et fusion des Objectifs. |
| [declencheurs-evenementiels-et-dream.md](declencheurs-evenementiels-et-dream.md) | `design` | Dream comme gestionnaire d’événements, catalogue, graphe de branchement, tableau de bord et historique. Pilote Mail et Fichier avant l’automatisation des Travaux. |
| [conversations-deep.md](conversations-deep.md) | `partial` | Basculement, reprise du flux, rattachement LLM et redirection Codex implémentés. Intégration du terminal natif sur le checkout Code et attachement à un terminal existant à compléter. |
| [cartes-mentales-documentaires.md](cartes-mentales-documentaires.md) | `partial` | Type Document, édition de branches, MCP et échanges disponibles. Contenus riches, thèmes, intégration Texte et qualifications externes restent ouverts. |
| [affichage-des-references-documentaires.md](affichage-des-references-documentaires.md) | `partial` | Socle Lien, Carte et Intégré dans Texte et Carte mentale. Lecteurs des autres formats et couverture des exports par format à étendre. |
| [migration-progressive-rust.md](migration-progressive-rust.md) | `design` | Prototypes de runtimes, protocole d'hôte et qualification sans régression ; Pydantic AI conservé comme référence. Aucun driver Rust intégré ni gain démontré. |
| [persistance-agentique-async-native.md](persistance-agentique-async-native.md) | `design` | Retrait progressif de Greenlet, pilote du journal d’inférence à huit flux et contrats réutilisables pour le portage Rust. |
| [supervision-execution-llm.md](supervision-execution-llm.md) | `design` | Pilote petit/gros exécuteur, vérification métier indépendante, attente fournisseur, parcours persistant, puis supervision et escalade expérimentales. |
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
