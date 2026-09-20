<p align="right"><strong>Français</strong> · <a href="../../en/architecture/README.md">English</a></p>

# Architecture de Galaris

Ce répertoire complète le [guide développeur](../dev/README.md) avec deux formes de
connaissance : les invariants expliqués par des humains et une cartographie reconstruite
automatiquement depuis le code.

## Parcours conseillé

| Besoin | Document |
|---|---|
| Comprendre les règles non négociables | [Invariants](invariants.md) |
| Suivre une tâche et son driver | [Exécution agentique](flows/agent-execution.md) |
| Suivre un message et son bridge | [Messagerie](flows/messaging.md) |
| Auditer le Messenger interne | [Validation architecture et données](chat-validation.md) |
| Comprendre session, rappel et consolidation | [Mémoire](flows/memory.md) |
| Comprendre l’entretien opportuniste en arrière-plan | [Dream](flows/dream.md) |
| Suivre un outil ou une exécution longue | [Processus](flows/process.md) |
| Comprendre les calendriers et leurs déclenchements | [Calendriers](flows/calendar.md) |
| Comprendre les sessions et sorties du navigateur | [Navigateur](flows/browser.md) |
| Comprendre les fichiers, médias et ressources | [Médias et ressources](flows/media-resources.md) |
| Comprendre les scores, rubriques et biais du Lab IA | [Évaluation du Lab IA](ai-lab-evaluation.md) |
| Vérifier les états durables | [Machines d’état](state-machines.md) |
| Trouver modules, routes, tables et outils | [Cartographie générée](generated/project-map.md) |
| Comprendre pourquoi une frontière existe | [Décisions](../../../project/decisions/) |
| Évaluer une proposition encore non livrée | [Index des plans](../../../project/plans/README.md) |

## Ce qui fait foi

La cartographie générée est un index statique, pas une spécification métier. L’ordre de
confiance reste : contrats et tests, configuration, guide développeur et décisions acceptées,
cartographie générée, puis plans.

Les fichiers de `generated/` ne sont jamais édités à la main :

```bash
make project-context
make project-context-check
make architecture-check
```

Le premier reconstruit les sorties JSON et Markdown. Le deuxième détecte une dérive. Le
troisième vérifie également les frontières de dépendances, les skills, les documents requis
et l’index des plans.

Les capacités de module sont déduites des fichiers source. Les répertoires vides et caches
locaux ne changent pas la cartographie : un instantané Git doit produire les mêmes résultats.

Les sections de couplage de la cartographie exposent fan-in, fan-out, cycles directs et composantes
fortement connexes pour Python et TypeScript/Vue. Les plafonds backend revus par les humains vivent
dans `back/architecture.toml` ; la dette mécanique courante vit dans les baselines séparées
`back/architecture-baseline.json` et `front/architecture-baseline.json`. Après avoir supprimé un
import privé, une dépendance frontend ou scindé un cycle, `make architecture-baseline` réduit ces
baselines.
Une augmentation ne doit être acceptée qu'avec une justification d'architecture explicite dans
la revue et, si la frontière durable change, une décision.

## Maintenir cette connaissance

- Modifier un état ou une transition : mettre à jour `state-machines.md` et son test de matrice.
- Modifier un flux inter-domaines : mettre à jour le fichier de `flows/` correspondant.
- Changer une frontière durable : ajouter ou amender une décision dans `project/decisions/`.
- Ajouter un module, une route, un modèle, un outil MCP, un setting ou une page : régénérer la
  cartographie.
- Retirer une dépendance ou un import privé : réduire le manifeste et la baseline, sans rétablir
  leur ancien plafond.
- Faire évoluer une intention : mettre à jour le statut et la note de `project/plans/README.md`.
