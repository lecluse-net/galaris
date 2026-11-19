# Plans actifs de Galaris

Tri du **14 novembre 2026**, à partir du code, des contrats, des tests et des décisions.
Ce répertoire conserve les travaux et conceptions encore ouverts. Les lots réalisés
et leurs historiques sont retirés des plans ; leurs preuves restent dans les
[décisions](../decisions/README.md), les [audits](../audits/) et la
[documentation](../../docs/fr/README.md).
Cette revue ne rejoue ni les parcours applicatifs ni les benchmarks.

Un plan ne vaut ni ordre d'implémentation ni nouvelle priorité produit.

## Campagne engagée le 15 novembre 2026

Les cinq chantiers demandés sont repris dans les suivis existants :

| Chantier | Suivi | Première réception |
|---|---|---|
| Réussite des missions | Lab IA | Campagne synthétique avec modèle réel, revue des échecs et de la cohérence des références. |
| Arrêt et reprise | Fiabilisation conversationnelle | Contrats durables puis qualification des runtimes isolés, sans arrêter de travaux utilisateurs. |
| Précision mémoire | Amélioration globale de la mémoire | Pièces jointes, droits vivants et recherche dans des PDF synthétiques, dont les pages scannées. |
| Performance | [Travaux ouverts de l’audit d’optimisation](../audits/optimisation-generalisee/README.md#travaux-ouverts) | Lectures SQL Process/MCP jusqu'à 500 résultats, permissions Services ciblées et annuaires canoniques de 501/1 001 destinataires ; contenu, droits et fraîcheur préservés. |
| Première mission | Frictions du parcours conversationnel | Accueil, édition, partage et réouverture dans l'application assemblée ; observation de nouveaux utilisateurs encore à organiser. |

L'autorisation porte sur les qualifications, les corrections démontrées et les
simplifications des mécanismes existants. **Tout nouveau mécanisme applicatif exige
l'accord explicite de l'utilisateur.** Les propositions de gardes ou de contrôle de
dérive présentes dans les plans ne sont pas autorisées par cette reprise. Réutiliser
les outils et tests existants ; ne pas ajouter de dispositif de supervision automatique.
Les qualifications ciblées ne clôturent ni les plans entiers ni les essais de charge,
les comptes distants réels ou la réserve indépendante encore manquants.

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
| [cartes-mentales-documentaires.md](cartes-mentales-documentaires.md) | `partial` | Type Document, édition de branches, MCP et échanges disponibles. Contenus riches, thèmes, intégration Texte et qualifications externes restent ouverts. |
| [affichage-des-references-documentaires.md](affichage-des-references-documentaires.md) | `partial` | Socle Lien, Carte et Intégré dans Texte et Carte mentale. Lecteurs des autres formats et couverture des exports par format à étendre. |
| [migration-progressive-rust.md](migration-progressive-rust.md) | `design` | Prototypes de runtimes, protocole d'hôte et qualification sans régression ; Pydantic AI conservé comme référence. Aucun driver Rust intégré ni gain démontré. |
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
