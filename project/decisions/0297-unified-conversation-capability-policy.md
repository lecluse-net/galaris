# 0297 — Politique unifiée des capacités conversationnelles

Statut : accepté — 16 novembre 2026.

## Problème

Le choix de passer en Task était exprimé dans la politique administrable, le générateur
conversationnel, le guide opérationnel et l'annonce des Services. Une restriction du round
pouvait être confondue avec une incapacité globale. Le texte et la voix par tours recevaient
une projection des Services exclus du dialogue, contrairement à la voix temps réel.

## Décision

`ai.conversation-action-policy` possède seul le choix entre réponse, effet conversationnel,
Process affecté et Task. Le traitement des limites est intégré à ce même choix : lorsqu'un
travail dépasse le round, une Task peut explorer la méthode et tenter le résultat. L'inventaire
incomplet, une fonction absente du round et une ancienne affirmation de l'IA ne prouvent pas
l'impossibilité en Task. Une limite vérifiée, les ACL, refus et accords en attente restent
opposables. Les inconnues techniques relèvent de l'exécution ; les choix humains indécidés
et demandes ambiguës relèvent d'une clarification.

Le guide commun renvoie à cette politique. Les règles de transport gardent style, identité,
fraîcheur et preuves de lancement. Les inventaires décrivent leur portée et les Services
connectés sans décider une admission ni garantir les fonctions d'un autre contexte.
La même projection locale est utilisée par texte, voix par tours et voix temps réel ; elle
n'appelle aucun fournisseur distant et n'élargit pas leurs outils montés.

Le flux reste dispatch → run. Aucun nouveau classificateur, appel décisionnel, contrôle lexical,
format de sortie imposé ou jugement après réponse n'est ajouté. Les décisions 0101 et 0194
conservent leur périmètre. Les personnalisations administratives sont préservées ; les valeurs
effectives doivent être inspectées avant une qualification ou une mise en service.

## Qualification

Le bench seul utilise une comparaison appariée des prompts complets avant/après. Modèle,
effort, entrées, outils simulés, réponses et oracles sont figés et contrôlés avant les appels.
Les nouveaux cas FR/EN couvrent moyens connus ou inconnus, refus historique, demande mixte,
interdiction vérifiée, choix humain, Process prioritaire et lecture bornée ; ils sont aussi
évalués sous le prompt voix. Les oracles examinent les appels et reçus réels de la simulation,
pas une détection lexicale des refus. Les réponses et objectifs nécessitent également une
revue sémantique. Ces mesures ne s'exécutent jamais dans le chemin conversationnel.

Les tests déterministes couvrent l'injection et la personnalisation, la portée des inventaires,
les reçus et la capacité des oracles à rejeter une tentative manquante ou une Task interdite.
Ils ne prouvent pas à eux seuls la conformité d'un modèle réel ni la réussite métier d'une Task.
