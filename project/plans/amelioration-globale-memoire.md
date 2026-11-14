# Mémoire — extensions et expériences restantes

- Statut : `partial`
- Tri documentaire : 2026-11-14 ; campagnes historiques non rejouées.

## Contrats et preuves à réutiliser

Les acquisitions, leur attribution, les conflits et les budgets de contexte relèvent
de [0229](../decisions/0229-memory-evidence-and-context-budgets.md).
La recherche Dataset, les preuves complémentaires et la continuité du rappel sont
documentées dans [0249](../decisions/0249-memory-evidence-and-dataset-retrieval.md)
et [0258](../decisions/0258-contextual-resource-identity-recall.md).
Les mesures restent dans les audits du
[24 octobre](../audits/2026-10-24-memory-evidence-and-context.md),
du [29 octobre](../audits/2026-10-29-memory-and-dataset-retrieval.md),
de [continuité conversationnelle](../audits/2026-10-29-memory-conversation-continuity.md)
et du [30 octobre](../audits/2026-10-30-memory-context-recall.md).
Ces corrections et campagnes ciblées ne sont plus des lots à réaliser.

Réutiliser le [benchmark synthétique](../../back/scripts/memory_benchmark/README.md)
et les suites du [catalogue fonctionnel](../../docs/fr/dev/functional-tests.md).
Le raccordement des campagnes de rappel au Lab reste à concevoir.
Documents Texte/Données, souvenirs privés, Process et skills conservent leurs
frontières actuelles ; aucune réaffectation automatique de Topic sans gain mesuré.

## MEM-018 / MEM-011 — Acquisition des pièces jointes et provenance

Les analyses réussies, transcriptions et reçus tardifs sont déjà acquis et revalidés
selon [0169](../decisions/0169-conversation-memory-acquired-evidence.md).
Restent :

- propager la couverture et les troncatures des analyses partielles ou échouées ;
- qualifier les contenus illisibles, la vidéo et les limites atteintes ;
- rechercher précisément dans l'index des pièces jointes et comparer résumé seul /
  résumé + passages sur PDF longs et tableaux, sans modifier les notes manuelles
  ni dupliquer la fiche.

Définir déclenchement, budgets, rétention et modèles configurés avant toute nouvelle
acquisition automatique. Ne pas analyser systématiquement chaque fichier reçu.
Un résumé et sa source ne sont pas deux corroborations indépendantes.
Réutiliser `test_dream_attachments.py`, `test_document_structure.py` et le
[guide de qualification documentaire](../../docs/fr/dev/document-qualification.md).

## MEM-006 / MEM-007 / MEM-009 — Pertinence et contexte utile

Comparer au moteur courant sain, à modèle d'embeddings configuré constant :

- paraphrases, alias, homonymes, références implicites, dates historiques et langues non couvertes ;
- sélection au niveau du passage, fusion lexicale/vectorielle, diversité et signaux de portée,
  d'autorité ou de structure ; conserver une voie globale indépendante du Topic ;
- apports propres des Topics et liens du graphe, avec ablations et placebos ; compter
  les pertinents ajoutés et ceux chassés, notamment les sources rares et anciennes ;
- calendrier saturé versus demandes ordinaires, historique utile et budget réellement injecté ;
- suffisance des extraits, puis qualité de la réponse finale et utilité dans une Task.

La normalisation lexicale et le corpus synthétique ne sont plus à créer.
La recherche finale reste sans seuil de pertinence ; un résultat présent ne prouve pas
qu'il répond. Un reclasseur ou une reformulation générative reste une expérience séparée,
avec capacité explicitement configurée et gain hors échantillon.

Mesurer candidats, résultats et injection séparément : rappel complet des faits nécessaires,
Recall@k, précision, MRR/nDCG, redondance, erreurs, coût SQL, latence et volume de contexte.
Le corpus conversationnel actuel emploie des gabarits, des mondes isolés et un calendrier
volontairement saturé. Compléter par des labels humains revus, passages profonds, négatifs,
instructions citées et cas documentaires ; sa latence par monde ne qualifie pas un index
unique de 56 000 souvenirs ni les embeddings réels.

Pour la conversation, reprendre les questions du plan de prompts absorbé : préférences du
contact face au profil de l'agent, capture volontaire sans sur-capture, Process pertinent
au-delà de dix affectations, ancien document hors fenêtre récente, identité après outil
contradictoire et capacités immédiates/de fond. Les mesures par section du prompt et le
parcours complet restent coordonnés avec la
[fiabilisation conversationnelle](fiabilisation-conversationnelle.md).
Les sessions de Task conservent leur contrat propre.

Une expérience aval commence en shadow, puis A/A et canari borné : affectation stable
des missions racines et descendants, horizon et succès préenregistrés, inconnues conservées
au dénominateur. Publier succès, activité, échec, coût et bornes pour les inconnues.
Pas de conclusion causale depuis les seuls accès, citations ou résultats de rappel.

## MEM-013 / MEM-014 / MEM-015 — Observation et coûts

Les métriques de rappel/contexte et le suivi opérationnel des fichiers existent.
Compléter seulement les diagnostics manquants : couverture par contenu/version,
retard, blocages et action de réparation ; puis observation détaillée de l'exécution.

Distinguer candidats, admission, injection après troncature, lecture, citation, correction
et résultat de Task. Une réussite ne crédite pas tous les souvenirs injectés ; une absence
d'exposition ne prouve pas leur inutilité. Aucun renforcement automatique de popularité.

Borner collecte, coût et cardinalité ; panne de télémétrie sans effet sur le classement.
Ne pas journaliser requêtes/extraits bruts ; définir pseudonymisation et rétention avant
persistance (anciennes pistes : 90 jours de détails, 400 jours d'agrégats anonymes, à qualifier).
L'oubli purge les références identifiantes sans FK bloquante. Tester panne, redelivery,
fermeture concurrente, purge et non-exposition des données privées.

Pour Dream, qualifier utilité par effet durable et coût, empreintes d'entrée, reçus vides,
reprise sans nouvel appel et deltas d'UUID déclenchant les traitements déterministes.
Réutiliser les budgets, checkpoints et préemption existants avant tout nouvel ordonnanceur.

## MEM-001 — Granularité des Topics

Évaluer le réemploi d'un sujet durable de portée comparable : thème général, projet et
activité ne sont pas équivalents. Comparer politique courante et candidat sur conversations
FR/EN successives, catalogue figé, retours A → B → A, pronoms et changements de sujet.

Ce premier lot n'ajoute ni modèle, colonne, type de lien ni hiérarchie ; conserver
`DREAM_TOPIC_CREATION_MODE=propose`. Corpus initial proposé : 60 conversations work,
30 validation, 30 holdout, cinq répétitions de baseline.

Mesurer précision/rappel/F1 des paires correctement regroupées, frontières, créations,
réemploi, singletons, coût et durée. Cibles initiales à geler après calibration :
gain F1 ≥ 5 points avec borne basse positive, recul précision/rappel ≤ 2 points,
précision/rappel des créations ≥ 90 %/80 %, réemploi ≥ 95 %, singletons ≤ 5 %,
surcoût < 15 %, aucune fuite. Canari proposé de deux à quatre semaines en mode
`propose`, avec rollback du prompt et de son snapshot. Un prompt modifié seul ne clôture pas le lot.

## MEM-010 — Organisation courante et réaffectation

`topic_maintenance.py` propose déjà rattachements, anomalies, fusions et scissions ;
`test_topic_maintenance.py` protège l'absence de mutation des appartenances canoniques.
La convergence automatique vers un meilleur Topic demeure à concevoir.

Avant implémentation, arrêter une ADR séparant provenance historique, organisation
courante, liens dérivés et décisions manuelles/épinglées. Un simple déplacement de
`topic_contains` serait annulable par sa reconstruction depuis les sources.

Le candidat utilise k-NN borné, marge relative, hystérésis, stabilité sur plusieurs sweeps,
égalité déterministe et politique versionnée. Les anciens exemples de seuils 0,65/0,10
sont des hypothèses à calibrer, pas des constantes universelles.
Une panne d'embeddings conserve les affectations courantes.
Le LLM peut proposer un contenu nouveau ; le calcul et l'application des associations
de ce lot restent déterministes, sans appel génératif.

Chaque mouvement revérifie empreintes et politique, respecte les pins, ne retire que les
liens qu'il possède, conserve sources, contact, ACL, contenu et révisions, puis journalise
assez d'information pour restaurer l'affectation. Réconciliation ciblée après delta ;
rebuild versionné et reprenable après changement de modèle ou de politique.

Réception : snapshots successifs (Topic générique puis précis), item à maintenir, marge
insuffisante, multi-source, pin, fusion/scission concurrente, suppression du Topic, panne,
interruption et seconde exécution idempotente. Mesurer précision des mouvements/cibles,
cohésion, churn, rappel, requêtes et écritures. Cibles initiales : précision et cible ≥ 95 %,
churn après convergence < 1 %, recul Recall@5/précision@5 ≤ 2 points, aucune mutation
canonique ou fuite, reprise identique à une exécution continue.

Introduire simulation → shadow → suggestion → canari → généralisation après preuve.
La hiérarchie sémantique demande davantage qu'un cosinus ; elle reste un sous-lot distinct,
comme dormance, redirections, forces adaptatives et circuits de preuve ET/OU.
Le rollback restaure l'organisation sans réécrire les sources.

## Autres axes conservés

Le [programme identité et qualité des contenus](fiabilisation-conversationnelle.md#contexte-et-prompts--travail-regroupé)
coordonne la décision rechercher/enrichir/créer et la rédaction sans journal d'édition.
Les lots MEM-002/003/004/005 ci-dessous portent son volet Memory/Dream :

- Préserver l'auteur et le sujet de chaque fait, y compris citations, résultats de Tasks
  et profils d'agents ; ne pas convertir une auto-description d'agent en fait humain.
- Pour un fait déjà intégralement couvert, réutiliser la ressource et sa provenance selon
  les contrats existants. LINK n'enrichit pas le contenu : un complément important ou une
  contradiction ne doit pas être absorbé par un rattachement qui perdrait son sens.
- Qualifier les faits présents dans un document, son éventuelle synthèse et les souvenirs
  autonomes sans multiplier les copies. L'acquisition ne devient pas un éditeur de Documents.
- Mesurer doublons et omissions ensemble. Aucune réduction des critères de rétention,
  expiration supplémentaire, désactivation d'extraction ou fusion/purge du stock n'est
  décidée par ce programme. La provenance, les ACL et l'oubli restent prioritaires.

Les campagnes générales de sélectivité, de déduplication et d'identité restent
coordonnées avec le plan conversationnel ; les mesures ciblées de rappel et de
contrôle factuel des audits ne les remplacent pas.

| ID | Question encore ouverte |
|---|---|
| MEM-002 | Sélectivité de capture : faits utiles ignorés et détails ponctuels retenus. |
| MEM-003 | Doublons et faux LINK ; campagnes communes aux modèles de décision dans le Lab. |
| MEM-004 | Contradictions, autorité et temporalité des faits rappelés. |
| MEM-005 | Vieillissement, consolidation et oubli sans perte de faits utiles. |
| MEM-012 | ACL, partage, scellement par contact et oubli physique : gardes de tous les lots. |

Les identifiants MEM sont conservés pour le suivi. Une piste n'est pas une solution retenue.

## Qualifications regroupées et clôture

La qualification du catalogue File Share est suivie ici depuis le retrait de son plan réalisé :

- démarrage à froid, statistiques SQL et grande arborescence ; les mesures synthétiques
  à 100 000 entrées ne promettent pas une latence provider réelle ;
- installations réelles, notamment Nextcloud : le pair WebDAV synthétique avec 503 entrées,
  reprise et révocation qualifie l'adaptateur, pas un compte réel ;
- capacités de découverte AFFiNE et nouveaux providers, événements/deltas fiables
  et validation ACL groupée seulement si leurs contrats et les mesures le permettent ;
- reprise des anciennes descriptions admissibles non vérifiées : ne pas inventer une version
  source ; préserver notes et révisions et vérifier les capacités actuelles avant extension.

Chaque expérience part d'un manque reproduit ou d'une baseline, avec une variable candidate,
partitions par origine, métriques, seuils avant holdout et retour arrière.
Toutes les fixtures versionnées sont entièrement synthétiques ; les diagnostics restent sous
`artifacts/`. Réutiliser le [Lab](lab-evaluation-mecanismes-ia.md) pour étalonnage et comparaison.
Aucun modèle d'embeddings alternatif automatique, assouplissement d'ACL, mélange de versions
ou résurrection après oubli n'est admis pour gagner un score.

Ordre : compléter les campagnes sur le moteur courant ; réaliser les acquisitions et leur
provenance ; qualifier observation/utilité aval ; expérimenter capture et organisation.
Retirer chaque lot lorsqu'il est démontré ou transféré, en conservant ses preuves dans les
tests, décisions, guides ou audits. Les recettes usuelles avant publication ne constituent
pas de nouveaux lots permanents.
