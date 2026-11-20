# Conversations Deep

Statut `design` · 20 novembre 2026.

Un même agent peut avoir plusieurs conversations Deep ouvertes et actives. Chaque
message va directement au harnais de sa conversation. Le Chat affiche le texte, les
appels et résultats d’outils ainsi que les demandes d’autorisation au fil du tour.
Pour développer Galaris, l’éditeur et Codex travaillent sur le même worktree autorisé.

## Modèle proposé

| Objet | Propriétaire proposé | Identité et état |
|---|---|---|
| Mode de conversation | `app.conversation` | Configuration durable liée au salon du Chat interne. Le mode ordinaire est celui des salons existants. Deep est choisi pour un salon donné. |
| Session Deep | `app.conversation` | Identifiant Galaris, salon, agent, affectation du harnais, référence persistante de session native, référence facultative au checkout et état de la session. Une seule session courante par salon. |
| Tour Deep | `app.conversation` | Message d’entrée du journal Messenger, session, identité d’exécution, référence du tour natif, curseur d’événements, résultat et état durable. Une seule exécution active par session. |
| Checkout | `app.code` | Référence canonique au checkout et droits existants. Le runtime résout cette référence en répertoire de travail dans le périmètre attribué. |
| Adaptateur de session | `app.agent` et provider du harnais | Contrat d’ouverture/reprise, de soumission, d’événements et d’interruption. Chaque provider conserve les particularités du protocole natif. |

Le premier lot propose Deep à la création d’une conversation privée du Chat interne.
Un changement de harnais ou de checkout ouvre explicitement une nouvelle session,
avec conservation du fil et de l’historique consultable. La session native est gardée
côté runtime. Galaris conserve sa référence, les événements visibles et les identités
nécessaires à la reconnexion. Un deuxième onglet sur le même salon retrouve la même
session. Deux salons du même agent obtiennent deux identifiants natifs.

## Flux d’un tour

1. Le Chat enregistre le message dans le journal canonique. Le contrôleur Deep vérifie
   les droits du salon, du harnais et du checkout, puis transmet le contenu et les
   pièces jointes prises en charge au harnais. La boucle du harnais décide des actions.
   Le tour porte sa propre identité durable et se déroule dans le fil.
2. Le runtime charge les skills attribués et utilise les outils MCP autorisés. Le
   contexte d’exécution vérifié par Galaris identifie le tour pour les appels LLM, les
   reçus d’outils et les approbations. L’évolution du proxy accepte alors un round
   Deep authentifié, avec `task_id` vide et `conversation_round_id` renseigné.
3. Le Chat restitue les événements dans l’ordre, reprend au curseur après reconnexion
   et affiche le résultat terminal du runtime. La fermeture de l’onglet laisse le
   travail continuer. Après interruption d’un processus, la session reprend depuis
   l’état natif disponible et les reçus durables. Un effet incertain est affiché
   comme tel et doit être réconcilié avant tout rejeu.
4. Pendant un tour, une consigne est envoyée au tour actif si le harnais le permet.
   Dans les autres cas, elle est affichée comme message en attente du prochain tour.
   L’arrêt vise l’identifiant du tour. Le Chat distingue demande d’arrêt et arrêt
   confirmé. Entrées et commandes sont idempotentes.

Les états proposés pour un tour sont **en attente**, **en cours**, **en attente
d’autorisation**, **arrêt demandé** et les issues **terminé**, **interrompu** ou
**échoué**. Une issue terminale est immuable. Une nouvelle tentative a une identité
distincte et conserve les reçus applicables. Les identifiants de session native sont
isolés par salon, agent et affectation. Les limites d’exécution du harnais s’appliquent
à l’admission des tours concurrents.

## Développement de Galaris

Le panneau Code et le harnais résolvent la même référence de checkout. La
qualification doit couvrir la découverte des `AGENTS.md`, les éditions, les commandes
de test dans l’environnement Docker de développement et la visibilité des changements
Git. Plusieurs chantiers d’écriture peuvent utiliser des worktrees distincts du même
dépôt. Le droit d’accès à un checkout est revérifié avant la reprise. Une session
ne permet pas d’écrire sur le serveur de production. Pour modifier le Chat ou le
harnais, le premier parcours utilise une instance de développement distincte de
l’instance qui porte la session.

## Lots et critères de réception

1. **Session Codex.** Qualifier l’App Server embarqué, ouvrir un fil persistant dans le
   worktree autorisé, acheminer les événements et interrompre un tour. Exercer une
   correction réelle de Galaris avec lecture des consignes, édition, tests et revue du
   diff dans le panneau Code. Poursuivre après réouverture du Chat.
2. **Durabilité et concurrence.** Avec le même agent, faire tourner cinq fils sur
   des worktrees distincts. Rediriger et arrêter un seul tour pendant que les autres
   continuent. Vérifier l’isolation des messages, coûts, approbations et outils.
   Tester une reconnexion en cours de tour, un redémarrage du runtime, une révocation
   d’accès et une réponse d’approbation tardive. Contrôler la conservation des
   décisions après compaction sur une longue session.
3. **Autres harnais.** Qualifier Hermès et Claude Agent sur le même contrat de reprise,
   de flux et d’arrêt. Vérifier la consigne en cours de tour séparément pour chaque
   version. Qualifier ensuite DeepSeek sur la reprise native persistante. Un endpoint
   générique devient sélectionnable quand il démontre ce contrat.

La réalisation s’appuie sur la corrélation explicite des appels par exécution,
la qualification du transport des événements de session et la liaison sécurisée
entre le runtime et le checkout. Le schéma SQL final et le mécanisme d’exposition
du checkout au harnais seront confirmés sur le premier parcours Codex.
