# Conversation — identité, qualité des contenus et qualification du parcours

- Statut : `partial`
- Revue des sources : 2026-10-11 pour les extensions de parcours ; 2026-10-22 pour le programme identité et qualité des contenus.
- Le programme ci-dessous est en conception, sans implémentation ni campagne lancée par ce plan.

Les corrections et contrats réalisés restent dans la
[matrice projet](../audits/2026-09-19-fiabilisation-transversale.md),
le [catalogue fonctionnel](../../docs/fr/dev/functional-tests.md) et les décisions
[0029](../decisions/0029-unified-conversation-rounds.md),
[0101](../decisions/0101-dispatch-without-action-judgment.md),
[0102](../decisions/0102-harness-dispatch-choices.md),
[0103](../decisions/0103-tool-errors-return-to-agent.md),
[0123](../decisions/0123-explicit-task-replacement.md).
Avant chaque extension, vérifier puis reproduire le manque actuel ; ces qualifications
ne sont pas une liste de défauts prouvés.

## Travaux restants

Le lot [0170](../decisions/0170-execution-scope-and-durable-controls.md) coordonne
les descendants Task et leur propriétaire Process. L'arbre est figé à l'admission et ne
s'élargit pas au redémarrage. Chaque run et lease doit être arrêté ; l'accusé seul reste
insuffisant. Le propriétaire Process peut confirmer tardivement l'arrêt du run exact
sans réécrire sa cancellation logique ni rejouer le processus. Les pauses utilisateur
et travaux indépendants restent préservés. Une Goal ou une attente inconnue est refusée
explicitement ; sa coordination ne fait pas partie de ce lot.

| Lot | Travail et réception |
|---|---|
| Mesures utilisateur/dispatcher | Corpus FR/EN humain/pair IA, question/action, racine/enfant et capacités variables ; admission, premier texte/outil, confirmation d'arrêt et successeur. Séparer réseau/provider, verrou, scheduler et temps local ; coûts et faux lancements, à configuration constante. |
| Arrêt des runtimes | Étendre la qualification synthétique du worker Hermès direct aux autres runtimes et effets distants : refus, accusé sans arrêt, perte réseau, crash/reprise. Preuve physique du bon run avant successeur, distincte du terminal logique. |
| Coordination des Goals | Définir l'arrêt d'une Goal avec son propriétaire et sa reprise ; le remplacement Task/Process et descendants est réalisé. Qualifier ensuite les propriétaires supplémentaires et la recette réelle. |
| Capacités des harnais | Construction, activation/révocation et redémarrage : outil autorisé distinct d'outil monté. Capacité absente jamais promise comme immédiate ; capacités différées/skills conformes, pas d'ajout à chaud sans contrat. |
| Diagnostics | Erreurs non HTTP, antibot et effet confirmé/rejeté/inconnu, dont panne après transfert réussi. Diagnostic FR/EN corrélable/expurgé, aucune incitation au rejeu incertain ; 403 seul sans cause antibot inventée. |
| Recherche/livraison | Corpus make check-search dans environnement cible après configuration autorisée ; image réelle téléchargée, droits/licence/attribution et lecture par destinataire. Alternatives autorisées ou échec explicite. |
| Langue/structure/effort | Plusieurs objets candidats dans une réponse fournisseur ; commentaires/objectifs/notifications/Topics/reprises FR/EN, préférences absentes ou demandeur différent. Préserver schémas historiques, forçages et résolution unique. |
| Frictions/parcours complet | Sujet proposé après salutation et répétition sans perdre choix en attente ; demande → capacité → activation → correction → remplacement → recherche → document illustré → partage → lecture après reconnexion. Témoin sans interruption et embeddings indisponibles. |

Les courts-circuits déterministes du dispatcher, révocation à l'appel et reprises simples
ne sont plus des lots à implémenter. Les mesures viennent de
[0094](../decisions/0094-task-timing-and-delivery-observations.md) et du
[protocole Lab](../../docs/fr/dev/lab-reference-corpus.md#campagne-délai-coût-et-qualité) ;
admission simulée et E2E Chat ne prouvent pas seuls le parcours illustré complet.

## Contexte et prompts : travail regroupé

Le plan `optimisation-prompts-agentiques.md` est absorbé ici pour ses mesures du
contexte conversationnel et dans le [plan mémoire](amelioration-globale-memoire.md)
pour rappel/capture. Le programme suivant coordonne conversations, Tasks et rédaction ;
il conserve les contrats propres des sessions et ne recrée pas un plan de prompts séparé.

### Garantie et limites du programme

Traiter toutes les informations importantes de la demande, les attribuer aux bonnes
personnes et enrichir les ressources adaptées avant d'en créer de nouvelles. Le document
présente le contenu actuel ; ses révisions portent son historique d'édition.
La réussite se mesure par la qualité, la complétude et la facilité de réutilisation,
avec moins de copies évitables. Un texte plus court ou moins de documents ne suffit pas.

Le périmètre comprend le Chat interne, les conversations Messenger, les Tasks racines,
leurs délégations, la préparation des objectifs, le planner et ses synthèses, le rappel
Memory et l'acquisition Dream. Appliquer les mêmes règles sémantiques aux chemins voix
qui partagent ces constructeurs ; qualifier séparément la voix temps réel et chaque
harnais effectivement pris en charge. Une preuve sur l'interne ne qualifie pas Hermès,
Codex, Claude Agent ou DeepSeek.

Ce cadrage ne réduit pas les critères de rétention, ne désactive pas Dream et n'introduit
ni quota de documents, ni taille maximale de rédaction supplémentaire, ni purge ou fusion
automatique du stock existant. Ne pas créer un nouveau juge, outil ou modèle de décision
sans manque démontré. Les informations métier restent dans leur domaine : Documents
éditoriaux, Datasets JSON, Process BPMN et état Task/Goal conservent leurs propriétaires.

### Constats à reproduire et sources à inspecter

La revue du 22 octobre est statique. Aucun exemple réel de confusion de genre ni de
surproduction n'a été reproduit ; les prompts personnalisés de l'instance n'ont pas été
lus. Distinguer défaut de représentation, faiblesse de consigne et comportement mesuré.

| Constat dans le code | Source et conséquence pour le premier lot |
|---|---|
| Le profil de l'agent est explicite, mais aucune règle commune n'interdit de transférer son genre ou ses traits à l'interlocuteur. | [Constructeurs partagés](../../back/app/agent/executor_prompts.py), [conversation](../../back/app/harness/conversation.py). Comparer le profil et les participants réellement envoyés au modèle. |
| Le contrat Task emploie un jeu de rôle répété dans son message d'entrée ; la conversation utilise une identité directe. | [Prompt Task](../../back/app/agent/executor_service.py). Unifier la sémantique sans perdre personnalité, mission ou langue. |
| La conversion interne prend `msg.is_ai` comme preuve que l'auteur est l'assistant courant. Le repli Hermès applique aussi IA → assistant. | [Runtime interne](../../back/app/harness/runtime.py), [exécuteur Hermès](../../back/bridge/hermes/executor.py). Reproduire avec deux agents distincts et un humain. |
| La normalisation distante peut attribuer l'identifiant de l'agent courant à tout auteur IA. Les métadonnées de certains messages sont textuellement absentes sans horodatage. | [Session Messenger](../../back/app/messenger/session.py), [enveloppe des messages](../../back/app/agent/conversation_context.py). Préserver l'auteur avant de renforcer le prompt. |
| Recherche, réutilisation, intégration des corrections et révisions sont déjà demandées. | [Contrat éditorial](../../docs/fr/dev/editorial-html.md), [catalogue d'outils](../../back/app/tools/agent_registry.py), [skill connecté](../../back/app/skill/system_skills/galaris/SKILL.md). Mesurer leur application avant d'ajouter des consignes redondantes. |
| Dream demande de détecter activement chaque fait durable ; LINK ajoute de la provenance sans enrichir le contenu cible. | [Extraction](../../back/app/dream/mechanisms/memory_extraction.py), [acquisition](../../back/app/memory/acquisition_service.py). Distinguer doublon exact, fait complémentaire et contradiction ; ne pas confondre LINK et réécriture. |

Inventorier aussi l'enveloppe commune des harnais et ses adaptateurs : rôles natifs ou
transcription textuelle, champs `text`/`content`, données présentées comme système,
révisions des skills, suffixes configurables et reprise de checkpoints. Relever les écarts
observés avant de choisir une modification ; la présente liste ne prouve pas chaque chemin.

### Contrat d'identité et d'attribution proposé

Une même règle s'applique en conversation, en Task et dans les synthèses :

- Le profil décrit exclusivement l'agent exécutant. Son nom, genre grammatical, métier,
  préférences et relations ne décrivent ni le demandeur ni un autre participant.
- Distinguer agent exécutant, auteur de chaque message, demandeur initial, délégant,
  destinataire et sujet du texte. Ils peuvent différer ; un demandeur peut être un agent.
- Dans une citation, un souvenir ou un résultat, « je » appartient à son auteur d'origine.
  Une ancienne réponse de l'agent ne constitue pas une déclaration humaine sur l'utilisateur.
- Le rôle fournisseur `assistant` est réservé aux messages de l'agent courant identifiés
  comme tels. Un autre agent reste un participant externe attribué, sans être présenté
  comme humain ni recevoir une autorité système. Une identité inconnue reste inconnue.
- Ne pas déduire le genre de l'interlocuteur du profil de l'agent ou de son seul prénom.
  Sans information explicite fiable, utiliser une formulation sans accord genré ; ne pas
  demander systématiquement son genre pour une réponse qui peut s'en passer.
- Distinguer réponse propre de l'agent et rédaction demandée au nom d'un tiers. Une
  lettre ou biographie au nom du demandeur ne reçoit pas l'identité ni la signature de l'agent.

Composer un socle commun court : identité de l'exécutant ; participants connus et règles
d'attribution ; mission et politiques d'action ; contexte historique et ressources sourcées ;
demande courante ; sortie attendue. Conserver les rôles natifs lorsque le runtime les
supporte et une enveloppe explicite lorsqu'il exige une transcription. Le format seul
ne corrige pas une mauvaise attribution. Conserver la demande originale hors réécriture
du modèle lors du passage conversation → Task et résoudre les personnes dans le complément
de contexte. Des ressources ou résultats rappelés ne deviennent pas des instructions.

Préserver la configuration existante des suffixes et personnalités ; identifier les
contradictions et leur traitement avant toute migration. Une suppression de la répétition
du jeu de rôle ne doit pas supprimer la personnalité, la voix propre ou la mission.

### Décision documentaire : rechercher, enrichir ou créer

La recherche intervient lorsqu'un contenu durable est à produire, avant de créer son
support. Une réponse ponctuelle ou une confirmation ne déclenche pas une recherche ou
une écriture de fin de tâche. Une cible explicitement demandée conserve sa priorité.

1. Identifier les éléments importants à traiter : faits, exigences, décisions, sources,
   dates métier, nuances, contradictions et questions ouvertes ; identifier leur domaine.
2. Inspecter la ressource explicitement visée, affichée ou transmise et les références utiles.
   Si aucune cible n'est fixée, rechercher les documents accessibles par sujet, formulation
   sémantique et finalité, puis lire les passages des meilleurs candidats. Ne pas s'arrêter
   au titre exact, au premier résultat ou aux seuls documents récents.
3. Choisir selon la matrice ci-dessous. Un résultat de recherche n'est pas une preuve
   d'adéquation ; l'absence de résultat après une erreur n'est pas une preuve d'absence.
   Garder une recherche bornée et des relances motivées. Si elle reste indisponible,
   signaler la limite et ne pas prétendre avoir vérifié l'absence d'un document.
4. Lire la révision actuelle avant écriture, intégrer le contenu et vérifier sa conservation.
   Rendre dans la conversation un bref résultat et l'URI utile ; ne pas créer un document
   supplémentaire pour justifier le choix ou consigner l'achèvement.

| Situation | Décision attendue |
|---|---|
| Même sujet, finalité compatible, place naturelle et droits adaptés | Enrichir le document existant ; fusionner les répétitions et corriger les passages concernés. |
| Plusieurs candidats | Choisir le plus adapté par finalité, portée, autorité et public ; la proximité sémantique seule ne tranche pas. Ne pas dupliquer l'information partout. |
| Information déjà couverte sans correction ni complément utile | Réutiliser la référence ; ne pas effectuer une écriture vide. |
| Sujet ou finalité distincts, contenu autonome, séparation d'accès nécessaire ou aucun support adapté après recherche | Créer un document cohérent et relier les ressources complémentaires lorsque leurs droits le permettent. |
| Proximité thématique mais intégration qui dénaturerait le document | Créer un support distinct plutôt qu'accumuler des sujets dans un document géant. |
| Cible adaptée connue mais non modifiable | Expliquer la limite ; ne pas créer silencieusement une copie concurrente ni élargir les droits. Un support distinct exige un besoin et une autorisation compatibles avec la demande. |

La recherche ne vaut pas autorisation de modifier un document voisin, partager ou révéler
des contenus privés. Respecter la portée de la demande et les ACL. La décision ordinaire
ne demande pas une confirmation humaine à chaque création. Une demande de plusieurs
livrables indépendants reste satisfaite dans son intégralité.

### Rédaction intégrée et révisions

Le corps présente l'état utile du sujet. Remplacer ou préciser les passages concernés,
regrouper les répétitions et créer une section quand l'information le nécessite. Ne pas
ajouter « nouvelle information », « ajout du jour », « modification de la section » ou
un journal de versions pour raconter l'édition. L'historique Galaris assure ce suivi.
Ces expressions ne sont pas une liste de mots interdits : une nouveauté produit, une date
d'effet ou une évolution historique peuvent appartenir au sujet lui-même.

Préserver les sources, unités, dates de validité, exceptions, incertitudes, raisons des
décisions et contributions utiles. Une synthèse doit intégrer l'essentiel, pas s'ajouter
à une accumulation inchangée. Ne pas effacer une contradiction non résolue : l'attribuer,
la dater et expliciter ce qui demeure incertain. Conserver la chronologie métier des
journaux, comptes rendus et audits, distincte de leur historique d'édition.

Les délégations transmettent la même URI et un périmètre d'intervention clair. Avant une
écriture, relire les passages nécessaires et la révision actuelle ; après conflit,
réconcilier les contributions sans écraser un ajout concurrent ni créer une copie de repli.
Une reprise ou une livraison répétée ne doit pas ajouter un nouveau paragraphe de suivi.
Ne pas réécrire automatiquement l'ensemble du fonds documentaire dans ce programme.

### Lots et dépendances

| Lot | Travail prévu | Preuve de sortie |
|---|---|---|
| 0 — Établir la référence | Inventorier consommateurs, prompts réellement composés, réglages et tests ; reproductions entièrement synthétiques ; définir corpus et grille d'informations à conserver. | Parcours conversation → Task → document → retour relu, état initial figé et limites documentées. Aucun diagnostic fondé sur une supposition seule. |
| 1 — Préserver les auteurs | Corriger d'abord normalisation et projections d'historique ; distinguer soi, humain, pair IA et auteur inconnu jusque dans les adaptateurs. | Tests de contrat avant/après : auteurs, rôles, chronologie, pièces jointes et reprises conservés. Aucun rôle privilégié déduit du texte. |
| 2 — Unifier les prompts | Socle d'identité commun, participants explicites, pronoms attribués, complément Task autonome, rédaction au nom d'un tiers ; rationaliser les répétitions et le skill connecté. | Matrice conversation/Task/délégation/voix partagée, profils différents, suffixes présents/absents et outils contradictoires ; attribution correcte dans des sorties évaluées. |
| 3 — Consolider les documents | Recherche avant création, lecture des candidats, choix enrichir/créer, rédaction intégrée et absence de journal d'édition dans le corps. | Un parcours complet avec ressources et services réels, puis familles de cas ; informations attendues, révisions, droits et créations vérifiés. |
| 4 — Aligner Memory/Dream | Appliquer les lots MEM-002/003/004/005 du plan mémoire à l'attribution et aux copies évitables ; distinguer réutilisation, complément et contradiction sans abaisser la rétention. | Pas de duplication d'un fait déjà couvert ni de faux LINK absorbant une information distincte ; pas de trait d'agent mémorisé comme trait humain. |
| 5 — Qualifier et intégrer | Comparaison appariée, parcours assemblés, documentation FR/EN, décision structurelle si nécessaire, activation réversible et revue du diff. | Gain démontré avec complétude préservée ; couverture effective par harnais publiée, limites et retour arrière vérifiés. |

Après le lot 0, traiter 1 avant 2 : des mots plus clairs ne réparent pas un auteur perdu.
Le lot 3 peut avancer sur des scénarios d'attribution déjà fiables ; le lot 4 réutilise
ses critères sans fusionner les contrats Documents et souvenirs. Chaque lot reste une
modification bornée ; un résultat favorable sur un harnais ne généralise pas les autres.

### Corpus, mesures et réception

Réutiliser le [Lab](lab-evaluation-mecanismes-ia.md) et le
[catalogue fonctionnel](../../docs/fr/dev/functional-tests.md). Renforcer les tests existants
de prompts/historique, sessions Messenger, objectifs Task, documents, acquisitions et
provenance. Les tests déterministes vérifient données et effets ; une assertion sur un
fragment de prompt ne démontre pas le comportement rédactionnel d'un modèle.

| Famille synthétique FR/EN | Garantie vérifiée |
|---|---|
| Agent femme/homme, humain de genre différent ou inconnu, plusieurs participants et homonymes | Aucun transfert de caractéristiques ; pronoms et personnes correctement attribués, y compris sans horodatage. |
| Citations à la première personne, outil contradictoire, souvenir, lettre au nom d'un tiers, délégation et retour de Task | Auteur, sujet et voix rédactionnelle distincts ; exigences et demande originale conservées. |
| Document ancien sous un autre titre, candidat récent peu pertinent, information dans un passage profond | Recherche et lecture conduisent à la ressource adaptée ; absence de copie concurrente. |
| Aucun document adapté, plusieurs sujets indépendants, publics/droits distincts | Créations nécessaires maintenues ; aucun fait important ignoré ni document géant imposé. |
| Répétition, correction, contradiction et nouvelles sources | Contenu intégré, sources et nuances conservées ; pas de suivi de rédaction dans le corps ni d'écriture sans effet. |
| Audit chronologique, date de validité et historique d'une décision | Chronologie métier préservée ; absence de suppression fondée sur des mots-clés. |
| Recherche vide, indisponible ou refusée ; lecture partielle ; conflit de révision ; interruption et reprise | Limites honnêtes, pas de perte concurrente, double effet, copie de repli silencieuse ou élargissement de droits. |

Comparer sur le même corpus, modèles, outils, droits, contexte et état initial, en séparant
correction des rôles, modification du prompt et politique documentaire. Mesurer par famille :
erreurs d'attribution ; informations requises traitées/manquantes ; choix enrichir/créer ;
créations évitables et nécessaires ; faux regroupements ; répétitions ; journaux d'édition
indus ; recherches/lectures, écritures et révisions ; tokens, coût, latence et troncatures
par section (identité, règles, message, historique, Memory, continuité, travaux et outils).
Mesurer le volume logique et les révisions séparément : moins de documents n'implique pas
moins d'octets si les réécritures sont nombreuses. Garder les diagnostics bruts sous
`artifacts/`, sans créer de rapports utilisateur par tâche pour cette mesure.

Calibrer la grille et les marges de comparaison avant le holdout, répéter les cas génératifs
et publier variabilité et limites. La complétude et les créations nécessaires sont des
critères de réception à part entière ; une baisse du nombre de documents ne compense pas
des omissions, des faits fusionnés à tort ou des erreurs de personne. Aucun incident
critique de droits, perte de contenu ou faux succès dans les scénarios de réception.
Ne pas promettre l'absence universelle d'erreur à partir de ce corpus.

Conserver aussi les qualifications déjà ouvertes : recherches longues mais productives,
capacités absentes/rétablies, Process au-delà de dix affectations, interactions en attente,
création/amendement/statut et budgets. Aucun faux lancement, progression inventée ou refus
de capacité introduit pour économiser du contexte ; aucun classificateur par mots-clés.

Pendant l'implémentation, exécuter tests ciblés, contrôles statiques pertinents et parcours
assemblés ; mettre à jour les sources FR/EN et lancer `make docs-prepare`, puis terminer
par `git diff --check`. `make validate` reste réservé à l'utilisateur. Pour ce plan seul,
ne pas modifier les guides utilisateur pour présenter un comportement encore non réalisé.
Les campagnes de modèles, mutations de données, commits et déploiements ne sont pas lancés
par la rédaction du plan. Conserver une configuration et des prompts antérieurs restaurables ;
un retour arrière ne doit pas effacer les contributions documentaires produites.

## Méthode et clôture

Réutiliser le [Lab](lab-evaluation-mecanismes-ia.md), ses témoins et snapshots,
sans second moteur d'évaluation. Comparer avant/après sous les mêmes conditions ;
source externe remplacée dans les tests, puis recette réelle distincte.
Pas de juge ajouté après réponse réussie ni seuil arbitraire d'abandon.
Retirer chaque lot démontré/transféré et publier limites dans guides, tests et audits.
