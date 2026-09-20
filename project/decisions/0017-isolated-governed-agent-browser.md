# 0017 — Navigateur agentique isolé et gouverné

- Statut : Accepted
- Date : 2026-07-30

La restriction des destinations privées ou réservées décrite ci-dessous est remplacée par
[0055 — Navigateur agentique ouvert aux réseaux de développement](0055-agent-browser-development-network-access.md).

## Contexte

Les agents ont besoin d’interagir avec des pages dynamiques et, selon la tâche, de lire leur
contenu accessible ou d’en observer le rendu complet. Utiliser directement le navigateur natif de
chaque runtime créerait plusieurs politiques d’accès, plusieurs profils et des comportements
différents entre le harnais interne et Hermès. Lancer un processus Chromium complet par agent
augmenterait en outre fortement la consommation au repos.

## Décision

Galaris fournit un Tool `browser`, inactif par défaut et activable par agent. Un sidecar unique
héberge un processus Chromium partagé. Chaque session utilise toutefois son propre
`BrowserContext`, appartient au couple agent/tâche, expire automatiquement et ne partage aucun
état web avec les autres sessions.

Le sidecar est la seule composante dotée d’une sortie Internet. Il reçoit les commandes du backend
sur un réseau interne authentifié et force tout trafic Chromium à travers un proxy local qui
refuse les destinations privées ou réservées après résolution DNS. Les redirections et
sous-ressources suivent la même règle.

La sortie normale est un snapshot accessible paginable. La sortie visuelle est une capture de
page complète découpée en bandes verticales bornées; chaque bande est renvoyée comme contenu image
MCP et, lorsqu’une console est active, déposée sous une URI `console://`. Sans console, aucune
destination locale implicite n’existe. Une troncature est toujours explicite.

Quand ce Tool est actif pour Hermès, son toolset navigateur natif est désactivé. La connexion
Galaris et ses états de fonctions restent ainsi l’unique décision d’autorisation.

## Conséquences

- Le coût au repos reste celui d’un navigateur par instance Galaris, pas par agent.
- Les cookies et sessions sont éphémères; les profils persistants ne font pas partie de ce
  contrat.
- Une perte du sidecar invalide les sessions en cours sans affecter la disponibilité générale du
  backend.
- Les limites de ressources et de sortie sont des réglages d’infrastructure et ne peuvent pas
  être augmentées par un appel de modèle.
