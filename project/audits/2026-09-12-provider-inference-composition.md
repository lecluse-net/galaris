# Composition SDK, politiques fournisseurs et admission Task

## Incident et garantie

Un round conversationnel a échoué lors de la construction de
l'objectif Task : le SDK inférait un choix d'outil obligatoire, refusé par la politique
DeepSeek V4 avec raisonnement. Le contrôle avait été introduit par `8430ed72`.
La suite HTTP existante construisait ses propres requêtes sans ce choix d'outil.

Garantie : une requête automatique construite par le SDK respecte les restrictions du
fournisseur final, conserve les ressources et le raisonnement, et valide toujours la sortie.
Une création réussie persiste une seule Task ; une sortie invalide ou une indisponibilité
du fournisseur n'en crée aucune et ne déclenche pas le scheduler.

## Consommateurs et invariants

| Surface | Consommateurs | Garanties à conserver |
|---|---|---|
| `run_structured` | Objectif conversationnel, dispatcher Task, briefing, planner/synthèse, Goal, résumés Audio, Lab | Schéma et validateurs, limites d'essais, modèle/effort choisi, coût et corrélation |
| `run_prompted` | Dispatcher conversationnel, Topic, Dream, Lab | JSON validé localement, absence d'outils d'effet, limites d'essais |
| Modèles internes Chat/Responses | Façades structurées et harnais | Protocoles, historique/URI, profils de fournisseur, corrélation, choix explicites refusés s'ils sont incompatibles |
| Proxy HTTP | Modèles internes et clients externes | Contrôles revus, traduction des budgets/efforts, erreurs explicites, aucun envoi d'un champ inconnu |

## Preuves exécutables

- `test_sdk_inference_composes_with_provider_contract` reprend les scénarios fournisseurs
  revus : Chat et Responses, raisonnement automatique/none/high/max, sorties outil/JSON
  demandé/texte. Le SDK construit la requête ; le vrai proxy applique sa politique ; seul
  le transport externe et l'infrastructure de persistance du test protocolaire sont remplacés.
- Les schémas, ressources et résultats sont contrôlés à la frontière HTTP. Une première
  réponse structurée invalide doit être corrigée avant de rendre le résultat. Les transports
  HTTP réels sont interdits. Le catalogue texte doit rester couvert.
- Le scénario DB `test_internal_messenger_turn_exposes_background_task_admission` conserve
  les services réels d'admission, génération et persistance. Seuls le fournisseur et le
  réveil autonome du scheduler sont remplacés. Il couvre succès, redelivery, réponses invalides
  et indisponibilité ; les appels LLM du succès restent corrélés au round.
- La mutation `provider-sdk-ignores-thinking-tool-restriction` contourne la restriction SDK dans
  une copie temporaire : le scénario du round doit redevenir rouge. Elle est indexée dans
  `project/regressions.json` et exécutée par la qualification complète.

`make tests-providers` produit `artifacts/provider-contracts.xml`. Les configurations CI
et `make validate` exigent cette suite, en complément du backend complet, des mutations et
des parcours navigateur. Les résultats d'une qualification portent sur son instantané exact.

Les endpoints sont simulés : ces preuves n'établissent ni la disponibilité des fournisseurs
distants ni l'acceptation de toute version ou de tout déploiement non représenté.

### Actualisation du 14 septembre 2026

Avec [0097](../decisions/0097-durable-inference-lifecycle.md), les routeurs ne déduisent plus
une politique DeepSeek du nom du modèle. La mutation suit donc la route DeepSeek native,
dont le profil SDK déclare la restriction. Elle force la capacité interdite à `True` dans
la copie temporaire : la requête structurée doit échouer tout en conservant la même garantie.
Supprimer seulement la projection locale n'est plus une faute observable lorsque le profil
SDK porte déjà cette restriction. Les scénarios OpenRouter restent dans la matrice de transport.
Le rejet systématique des extensions inconnues décrit dans le tableau historique est également
remplacé par le contrat de paramètres de 0097.

## Diagnostic de la qualification globale

La qualification a aussi révélé une contrainte accessoire dans le test PWA : après une
mise à jour simultanée de deux onglets, il attendait un renouvellement HTTP dans le premier
onglet exclusivement. Les traces des échecs montrent un renouvellement 200 dans le second ;
le premier réutilise son jeton via le verrou de session, conformément au contrat existant.
L'observation porte désormais sur le contexte des deux onglets et commence avant le
déploiement simulé. Les garanties restent inchangées : renouvellement réussi, conversation
et session conservées dans les deux onglets et après réouverture, ancienne version du cache
supprimée. Cette correction du test ne modifie pas l'authentification de production.

La campagne du 14 septembre a révélé deux autres courses. Dans le Lab, le chargement du
contrat déplaçait le bouton de création pendant le clic Firefox. La création attend désormais
la fin du chargement initial ; le scénario composant existant retient volontairement cette
réponse, vérifie l'indisponibilité temporaire, puis l'ouverture et l'annulation du dialogue
avant de poursuivre ses garanties de sauvegarde. Il échoue avant correction.

Dans le scénario PWA, l'horloge de page avançait alors que l'enregistrement du worker,
son installation et la visibilité de l'onglet se règlent de façon asynchrone dans le navigateur.
Le test attend l'état visible et fait progresser les contrôles périodiques pendant
sa vérification bornée. Il ne force ni `registration.update()` ni rechargement. La mise à jour
automatique des deux onglets, la conservation de session/conversation et le remplacement du
cache restent requis ; aucun délai d'assertion ni retry de scénario n'est augmenté.

Une reproduction WebKit GTK a ensuite isolé la cause du blocage : `navigator.onLine` reste
`false` avant et après `setOffline(false)`, alors qu'un `fetch` de disponibilité passe de
l'échec réseau à HTTP 200. Le contrôleur PWA ne conditionne donc plus ses tentatives à cet
indicateur heuristique. Il reste borné aux onglets visibles et au contrôle périodique, absorbe
les échecs réseau sans supprimer le cache et reprend au prochain contrôle. Le scénario
unitaire reproduit le blocage avant correction et prouve la tentative puis la reprise malgré
un indicateur hors ligne. L'E2E conserve la vraie coupure réseau et les garanties de mise à jour.

La répétition complète a également capturé un clic WebKit sur le bouton desktop du Lab
pendant son remplacement par la carte mobile, juste après le changement de viewport.
Le test de réouverture vise désormais le contrôle de la vue mobile : l'attente porte sur
la transition responsive réelle, sans pause arbitraire ni nouvelle tentative de clic.
Les mêmes assertions conservent le texte et l'historique précédemment enregistrés.
