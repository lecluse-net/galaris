# Conversation — extensions et qualification du parcours

- Statut : `partial`
- Revue des sources : 2026-10-08.

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

| Lot | Travail et réception |
|---|---|
| Mesures utilisateur/dispatcher | Corpus FR/EN humain/pair IA, question/action, racine/enfant et capacités variables ; admission, premier texte/outil, confirmation d'arrêt et successeur. Séparer réseau/provider, verrou, scheduler et temps local ; coûts et faux lancements, à configuration constante. |
| Arrêt des runtimes | Étendre la qualification synthétique du worker Hermès direct aux autres runtimes et effets distants : refus, accusé sans arrêt, perte réseau, crash/reprise. Preuve physique du bon run avant successeur, distincte du terminal logique. |
| Remplacement coordonné | Concevoir Task/Goal/Process et descendants avec leurs propriétaires : périmètre, preuves, admission unique, fin naturelle concurrente, redelivery, ancien worker et effet incertain. Préserver travaux indépendants et pauses utilisateur. |
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
pour rappel/capture. Le contrat des sessions de Task demeure séparé.

- Mesurer identité/règles, message, historique, Memory, continuité, travaux et outils :
  volume, troncature, coût, latence, qualité, petits modèles et voix transcrite.
  Décider capture depuis traces ou ventilation persistée selon besoin.
- Qualifier recherche bloquée/longue mais productive, droits corrigés, sources valides,
  anciens documents, plusieurs livrables et demandes sans document.
  Mesurer répétitions improductives et réutilisation réelle des ressources.
- Vérifier création/amendement/statut, interactions en attente, priorités de Process
  compatibles et capacités immédiates/de fond après filtrage des droits.
  Un travail annoncé doit être admis ; pas de lancement ou progression inventés.
- Préserver chronologie native, paires tool/résultat, provenance et révisions,
  budgets, structure sûre du prompt et rôle/identité/langue après outil contradictoire.
  Les ressources rappelées ne deviennent jamais des instructions privilégiées.
- Comparer pertinence de sélection de documents/travaux hors fenêtre récente avant ajout
  d'une nouvelle sélection ; une représentation détaillée par ressource, sans corps répété.
  Aucun classificateur de salutation par mots-clés ni correctif de prompt par cas particulier.

Réception : gain mesuré sur corpus figé, erreurs critiques visibles, configuration antérieure
restaurable, aucune perte de contenu ni faux refus de capacité. Un prompt plus court seul
ne prouve pas une amélioration. Audit éventuel des répétitions de rôle dans les prompts Task
à cadrer séparément si ce constat historique est repris.

## Méthode et clôture

Réutiliser le [Lab](lab-evaluation-mecanismes-ia.md), ses témoins et snapshots,
sans second moteur d'évaluation. Comparer avant/après sous les mêmes conditions ;
source externe remplacée dans les tests, puis recette réelle distincte.
Pas de juge ajouté après réponse réussie ni seuil arbitraire d'abandon.
Retirer chaque lot démontré/transféré et publier limites dans guides, tests et audits.
