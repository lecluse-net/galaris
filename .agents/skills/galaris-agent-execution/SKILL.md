---
name: galaris-agent-execution
description: Architecture d’exécution agentique propre à Galaris — app.agent, app.harness, app.task, goals, drivers, dispatcher, planner, briefing, streaming, leases et reprise. À utiliser pour tracer, diagnostiquer ou modifier une tâche, un driver, une politique d’effort, une transition ou un résultat agentique.
---

# Maîtriser l’exécution agentique Galaris

## Charger le contexte minimal

Lire dans cet ordre :

1. `docs/fr/architecture/flows/agent-execution.md` ;
2. `docs/fr/architecture/state-machines.md` ;
3. la section agentique de `docs/fr/dev/README.md` ;
4. les contrats et tests des fichiers réellement touchés.

Utiliser `docs/fr/architecture/generated/project-map.md` pour trouver modules, routes et arêtes,
mais vérifier toute règle métier dans le code.

## Garder les responsabilités séparées

| Domaine | Responsabilité |
|---|---|
| `app.agent` | Contrats, registre, politique, dispatcher, planner, briefing, résolution du modèle, façade, streaming et application du résultat |
| `app.harness` | Harnais interne concret Pydantic AI, historique, toolsets, médias et adaptation de stream |
| `app.task` | Modèles durables, transitions, leases, tentatives, commandes et scheduler |
| `app.goal` | Objectif durable, cycles de jugement et décision de continuation |
| `bridge.hermes` | Adaptation du runtime Hermès au contrat `AgentDriver` |

`app.agent` ne dépend jamais de `app.task`. Utiliser le port de tâche enregistré par
`app.task.agent_adapter`. Un driver ne sélectionne pas silencieusement un second modèle et
ne décide pas à nouveau du planner ou du briefing.

## Tracer un run

Suivre cette séquence sans sauter de couche :

1. La tâche durable est convertie en contrat `AgentTask`.
2. Le workflow et le dispatcher choisissent la route autorisée par la politique du driver.
3. Planner et briefing s’exécutent uniquement si la politique figée les active.
4. Le modèle est résolu une fois et incorporé à l’`AgentRunRequest`.
5. La façade invoque le driver enregistré.
6. Le driver produit des messages puis un unique résultat terminal.
7. `app.agent` applique le résultat ; le port `app.task` le persiste et reprend le workflow.

Lors d’un diagnostic, relever l’identifiant de tâche, le driver, l’effort, la phase, la
tentative, le lease, la décision du dispatcher et l’événement terminal avant de conclure.

## Préserver le contrat de stream

Les champs éditoriaux du run suivent `docs/fr/dev/editorial-html.md` : l'agent lit et rédige
du HTML pour les objectifs Task, les descriptions/suivis Goal, sa personnalité/fiche de poste,
les contenus Memory et les documents HTML. Les documents de type immuable `dataset` contiennent
du JSON valide, créé avec `file_create(..., document_type="dataset")`, sans normalisation HTML.
Les formulaires et petites applications sont du HTML ordinaire avec `form`, `style` et
`script`, décrit dans `docs/fr/dev/document-apps.md`. Le runtime les isole sans ajouter de
mode d'édition ou d'habillage ; seul Source affiche le code. Les lecteurs génériques restent inertes.
Conserver les métadonnées de format dans les projections
et expliciter ce format dans les prompts qui font produire ces champs. L'enveloppe du prompt,
le stream conversationnel et les arguments non éditoriaux gardent leur propre contrat.
Les tests vérifient la sémantique HTML et les profils, sans réintroduire une attente Markdown.

Quand le résultat appelle un contenu rédigé durable à conserver, réviser ou partager, et que
Memory et les opérations nécessaires sont disponibles, privilégier un document `document://`
pertinent existant. Une Task ne nécessite pas à elle seule un document ; ne pas en ajouter pour
attester une action ou remplacer une ressource métier. Réutiliser son URI entre
recherche, rédaction, revue, délégation et conversation ; conserver les sources et liens dans
le document. Les messages portent la discussion et le renvoi au contenu. Ne pas remplacer ce
document par un fichier `.md` ou `.html` à cause d'une erreur temporaire. Préserver la politique
conversation/Task et le partage explicite avant transmission à un collaborateur. Memory et
File Sharing sont des services système obligatoires, comme Galaris et Conversation ; les ACL
des ressources et les restrictions de contexte restent prioritaires.
Voir `docs/fr/dev/editorial-html.md`, section « Documents comme pivot de l'information ».

Un stream valide contient zéro ou plusieurs événements non terminaux, exactement un
`ExecutionResult`, puis se ferme. Refuser et tester :

- un stream sans résultat ;
- plusieurs résultats ;
- un événement après le résultat ;
- une annulation annoncée par un driver qui ne déclare pas cette capacité.

## Modifier une politique ou une transition

1. Identifier l’unique propriétaire de la décision.
2. Écrire le test de matrice driver × effort × route ou le test de transition durable.
3. Modifier le contrat et l’implémentation dans la même responsabilité.
4. Vérifier reprise, erreur, annulation, suspension et redémarrage du scheduler.
5. Mettre à jour `state-machines.md` si l’ensemble d’états ou de transitions change.

Ne pas utiliser un texte final du modèle comme preuve qu’un outil a réellement été exécuté.
S’appuyer sur les événements et résultats structurés.

Le Working Set conserve des URI de ressources canoniques (`console://` seulement si une console
est active, `document://`, `galaris://`, schémas exacts de Tool), jamais des chemins relatifs,
chemins hôte ou contenu. Sans console, il n'existe aucun fallback local. Une livraison n'est
prouvée que par un artefact final et un reçu enregistrés après succès du transport.

Les arguments fichier des outils spécialisés sont eux aussi des URI canoniques. Un agent passe la
référence source exacte à l'image, l'audio ou Messenger ; `app.file_share` effectue en interne le
transfert temporaire borné requis par la bibliothèque ou le bridge. Le planner ne doit pas ajouter
une étape de copie locale uniquement pour rendre le fichier consommable. Il planifie
`file_copy` seulement lorsqu'une copie persistante dans un autre provider fait partie du résultat.

L'inspection agentique ordinaire des Tasks et des rounds passe par `file_list`, `file_search` et
`file_read` sur `galaris://task/`, `galaris://text/` et `galaris://voice/`. `task_get` reste la vue
opérationnelle compacte d'une Task (progression, attentes, pause et amendabilité), tandis que
`file_read` fournit son snapshot complet. Garder les autres outils métier dédiés aux commandes
(`task_run`, `task_stop`) et aux surfaces administratives enrichies.

Une Task présentée à un humain ou à un modèle est toujours référencée par son URI canonique
complète `galaris://task/<uuid>`. L'UUID nu reste réservé aux champs techniques internes, aux clés
étrangères et aux contrats de persistance. Les sorties copiables, prompts, skills et résultats
d'outils doivent exposer ou privilégier l'URI complète.

L'historique conversationnel conserve chaque fichier dans son message d'origine sous forme de
référence `<tool.code>://<room-locator-provider>/<file-uuid-local>`. Les runtimes doivent garder un message qui ne
contient qu'un fichier et rendre cette référence au modèle ; ils ne reconstruisent ni chemin local,
ni URL de provider, ni liste parallèle détachée de la chronologie.

## Valider

Exécuter les tests ciblés du domaine, les tests AST d’architecture, puis `make typecheck` et
`make architecture-check`. Ajouter un test d’intégration DB pour toute nouvelle persistance
ou sémantique de lease/reprise.
