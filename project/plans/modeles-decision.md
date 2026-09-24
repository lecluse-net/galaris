# Modèle de décision facultatif : dispatcher, topics et mémoire

- Statut : `partial`
- Date : 2026-09-24
- Périmètre accepté et branché : dispatcher, topics des messages/Tasks, rétention et
  dédoublonnage mémoire, classement immédiat des messages parallèlement à l'admission,
  Jev via OpenRouter et comparaison dans le Lab existant.
  Le pilote dispatcher a réussi 14 cas sur 14 ; qualification distante des nouveaux usages ouverte.
- L'acceptation du périmètre ne déclenche aucune activation ni intervention en production.
- Dépendances : [inférences durables](llm-calls-durables.md),
  [convergence SDK](convergence-pydantic-ai.md), [Lab](lab-evaluation-mecanismes-ia.md).

## 1. Garantie recherchée

Le contrat implémenté est décrit dans l'[ADR 0127](../decisions/0127-optional-dispatcher-decision-model.md)
et ses extensions [ADR 0129](../decisions/0129-shared-decision-model-workflows.md)
et [ADR 0130](../decisions/0130-live-message-topic-decisions.md).
Les sections suivantes conservent la conception et les pistes de qualification. Les campagnes
de candidat du Lab désactivent le repli ; le repli du système complet est observable dans les
traces des tâches. Les gains réels et les futurs adaptateurs locaux restent à qualifier.

Le dispatcher est branché directement sur la résolution commune : `decision_llm_id = null`
utilise son LLM texte actuel ; une sélection Jev utilise OpenRouter Decisions. Les deux
branches sont livrées ensemble, sans étape intermédiaire consacrée au seul chemin texte.
Le Lab existant permet de comparer les configurations ; aucune campagne préalable ni
nouvel outil de benchmark ne conditionne le démarrage de l'implémentation.

Les décisions sémantiques à réponses bornées peuvent employer un modèle spécialisé
facultatif. Sans sélection spécialisée, elles utilisent automatiquement le modèle texte
déjà prévu pour leur usage. Une installation locale peut donc conserver un unique modèle
génératif et un unique serveur d'inférence pour les conversations, décisions, plans et
exécutions. Plusieurs usages pointant sur le même modèle n'exigent pas plusieurs serveurs ;
la résidence mémoire et la concurrence restent contrôlées par le serveur local.

Cette garantie ne signifie pas qu'un modèle texte remplace les embeddings ou les modèles
multimédias. Elle concerne ici les usages texte et les décisions.

Les choix imposés, capacités des harnais, droits, budgets et transitions restent contrôlés
par le code. Une seule option admissible ne déclenche aucune inférence. Le modèle choisit
parmi les possibilités permises ; il ne crée ni autorisation ni effet d'outil.

## 2. Point de départ vérifié

- `app.llm.capabilities` distingue déjà les capacités spécialisées ; `decision` est absente.
- `LlmProfile` possède quatre niveaux texte et des colonnes spécialisées, dont `vector_llm_id`.
- `model_usages.DISPATCHER` et `CONVERSATION` partagent actuellement `TEXT_LOW`.
- `app.agent.dispatcher` filtre les couples route/effort et court-circuite le choix unique.
  Ses sorties inférées ne demandent aucune justification rédigée. Le résultat durable
  conserve séparément les diagnostics déterministes.
- Les appels du dispatcher traversent `run_structured` ou `run_prompted`, puis l'inférence
  durable. Les contrats persistés couvrent texte, sorties structurées et protocoles.
- `LLMInference` porte l'opération ; `LLMInferenceAttempt` porte la tentative et son lease ;
  `LLMCall` est la source des coûts des appels physiques.
- Le bridge OpenRouter existe, sans adaptateur Decisions. Les connexions Ollama existent
  pour le chemin texte local.

Sources : `back/app/llm/{capabilities,model_usages,profile_models,contracts,provider_facade}.py`,
`back/app/agent/{dispatcher,contracts}.py`, `back/bridge/openrouter/`,
[ADR 0095](../decisions/0095-pydantic-ai-request-ownership.md) et
[ADR 0097](../decisions/0097-durable-inference-lifecycle.md).

## 3. Architecture proposée

```text
Service métier : contexte pertinent, questions, options autorisées, usage
                  |
         app.llm.facade : décision
                  |
   Résolution du profil et gel de la stratégie
                  |
   Inférence durable et autorité du demandeur
                  |
        +---------+----------+
        |                    |
   Modèle spécialisé    Modèle texte existant
   Adaptateur provider  Pydantic AI / sortie structurée
        |                    |
        +---------+----------+
                  |
   Résultat typé validé, provenance, appels et coûts
                  |
   Service métier : application de la décision
```

### Responsabilités

| Surface | Responsabilité proposée |
|---|---|
| `app.llm` | Contrats de décision, résolution, validation, stratégie de repli, cycle durable et comptabilité |
| `app.llm.provider_facade` | Port public de fournisseur de décisions, enregistré au bootstrap |
| `bridge.openrouter` | Transport Decisions avec la connexion OpenRouter existante |
| `app.agent` | Questions du dispatcher, liste des choix autorisés, contraintes et application du résultat |
| `app.lab` | Évaluation du même parcours, choix explicite du candidat et mesure des replis |
| `front/app/llm` | Catalogue, sélection spécialisée facultative et politique de repli |

Seul le bridge OpenRouter reçoit un adaptateur dans ce périmètre. Aucun test du nom du
modèle ne choisit le protocole ; le port décrit les primitives et limites réellement
supportées. Un futur fournisseur local pourra implémenter ce port sans changer le dispatcher.

Pydantic valide les deux chemins. Pydantic AI construit seulement les appels du chemin texte,
conformément à 0095 ; le protocole décision possède son propre adaptateur. Pas de nouvel agent,
de nouveau harnais ni de serveur MCP pour cette fonction.

### Catalogue et profil

- Ajouter la capacité `decision` au catalogue de modèles existant, distincte de `chat`.
- Ajouter une sélection nullable `decision_llm_id`, vraie FK vers `llms.id`, au profil.
- Une valeur vide signifie « Utiliser le modèle texte de l'usage ». Elle ne désactive pas
  la décision. Le dispatcher conserve `TEXT_LOW` comme choix texte de secours.
- Préserver la résolution actuelle du profil effectif et de l'autorité ; ne pas chercher
  un autre modèle global lorsque le modèle du profil manque ou est interdit.
- Proposer `text_on_failure` ou `disabled` comme politique de repli après sélection spécialisée,
  avec `text_on_failure` par défaut. L'absence de modèle spécialisé utilise le texte dans les
  deux cas : ce chemin direct est distinct d'un repli après échec.
- Garder les sélecteurs texte limités aux capacités correspondantes. Le chemin texte de
  décision ne transforme pas tous les modèles de chat en fournisseurs natifs `decision`.
- Inclure création, copie, édition, import/export s'ils existent, purge de modèles, caches,
  préférences personnelles et profils préexistants dans l'inventaire des consommateurs.
- Convergence du schéma par DbAdmin ; aucun backfill vers un fournisseur externe. Les profils
  existants conservent leur comportement avec la sélection spécialisée vide.

## 4. Contrat commun de décision

Prévoir des contrats publics versionnés `DecisionRequest` et `DecisionResult` ; les noms
définitifs seront fixés avec l'implémentation. Les clés de questions et d'options sont des
clés de payload, pas de nouveaux identifiants de ressources SQL.

La requête contient un état textuel/JSON borné, les questions nommées, leurs critères,
les options ou niveaux admis, l'usage et sa version, les corrélations et la stratégie résolue.
Elle ne transporte aucun outil à exécuter. Les URI et restrictions d'accès du contexte
métier restent conservées. Les options ne sont pas tronquées silencieusement pour satisfaire
un fournisseur ; un contexte trop long provoque une stratégie explicite ou une erreur.

La première version expose uniquement le choix fermé, nécessaire au dispatcher. Les
propositions booléennes et niveaux ordinaux restent des extensions éventuelles, sans
implémentation anticipée de contrats inutilisés.

Le résultat comprend la valeur validée, la provenance (`specialized`, `text` ou
`deterministic`), le modèle effectif et le motif éventuel de repli. Distribution et confiance
sont facultatives, avec origine et sémantique explicites. Une confiance absente reste absente ;
aucun pourcentage autorapporté par le LLM n'est présenté comme une probabilité calibrée.
Ne pas assimiler la probabilité de l'option gagnante à la confiance du fournisseur.

Valider les clés, les valeurs, les bornes et les distributions selon le contrat du protocole.
Le service métier revalide l'appartenance aux choix permis. La façade ne demande aucune
justification générée et ne fabrique aucune justification attribuée au modèle spécialisé.

## 5. Résolution et repli

| Situation | Comportement cible |
|---|---|
| Un seul choix admissible | Résultat déterministe, aucun appel |
| Aucun choix admissible | Erreur métier, aucun appel |
| Aucun modèle spécialisé configuré | Chemin texte existant de l'usage |
| Modèle spécialisé disponible et compatible | Chemin spécialisé |
| Erreur fournisseur, indisponibilité, réponse invalide ou limite incompatible | Un passage au texte si autorisé et dans le budget restant |
| Incertitude mesurée | Passage au texte uniquement selon une politique qualifiée pour cet usage, modèle et version |
| Annulation, pause, perte du lease, budget épuisé ou refus d'autorisation | Aucun repli ; appliquer l'état ou l'erreur correspondant |
| Aucun modèle utilisable | Comportement métier explicite ; aucun fournisseur implicite |

Le dispatcher possède déjà certains comportements sans modèle : les inventorier et les
préserver dans le lot de compatibilité, sans généraliser ce comportement aux autres usages.
Une erreur de configuration doit rester visible même lorsqu'un repli réussit.

Un succès valide est accepté sans seuil universel par défaut. Le Lab doit qualifier les
seuils par modèle, version, langue et usage avant leur activation ; une confiance élevée
ne dispense pas de vérifier les garanties métier. Si la confiance requise par une politique
manque, traiter le résultat comme non qualifié, sans inventer une valeur.

Le repli utilise uniquement la connexion texte résolue dans le profil. Une installation
locale reste locale si ses sélections le sont ; aucun cloud n'est ajouté automatiquement.
Afficher le modèle texte effectif dans la configuration pour rendre ce comportement lisible.

## 6. Cycle durable et appels physiques

Ajouter un type versionné de requête décision au contrat durable, sans réinterpréter les
requêtes historiques. Adapter les projections de requêtes/résultats qui supposent du texte ;
éviter de refondre l'enveloppe de toutes les inférences pour ce seul consommateur.

À l'admission, figer questions, choix autorisés, version du contrat, modèles/connexions
sélectionnés, paramètres texte, stratégie et limites. Ne pas persister de secret. Les
autorisations sont encore vérifiées à l'exécution ; une révocation reste effective.
Le raisonnement du profil et la surcharge Task s'appliquent à la branche texte, sans être
envoyés comme paramètres inventés au fournisseur de décisions.

Une opération décision possède une tentative courante et peut contenir un appel spécialisé
puis un appel texte. Le second n'est pas une reprise utilisateur. Journaliser les étapes et
les appels physiques séparément, avec leurs coûts, sans créer une seconde inférence autonome
imbriquée pour le repli. Réutiliser le moteur structuré dans le contexte de la tentative.
Le résultat métier accepté est publié une seule fois, après la validation finale.

Un propriétaire unique borne les essais et le repli ; désactiver les retries cachés des SDK.
Le chemin complet partage la limite d'appels et le budget autorisé. Prévoir un délai total
borné pour ce parcours, en coordination avec l'extension d'échéance du plan d'inférences
durables, sans en faire une refonte globale préalable. Un timeout ne prouve pas l'arrêt
du calcul distant : tracer l'incertitude et rejeter tout résultat devenu tardif.

Pause, stop, perte du lease et arrêt du worker interdisent de commencer le repli. Conserver
le contrat 0097 : lecture/reconnexion sans appel, reprise explicite créant une tentative,
rejeu lié à l'original, aucune relance implicite après interruption. Une reprise peut
réémettre la requête et coûter un nouvel appel ; elle ne promet pas la reprise du calcul distant.

## 7. Parcours retenu et travaux différés

**Dispatcher Task uniquement** : choisir parmi les couples route/effort déjà filtrés et
résoudre la langue parmi les langues supportées lorsque nécessaire. Conserver contraintes
du harnais, choix forcés, phase durable et trace actuels. Regrouper les questions de route
et de langue indépendantes dans la même requête plutôt qu'ajouter un aller-retour.

**Lab existant** : comparer le même dispatcher en configurant le modèle de décision vide
ou sur Jev via OpenRouter, sans second mécanisme métier ni interrupteur de mode distinct.
Adapter ses bindings/surcharges de candidat pour qu'ils respectent cette sélection au lieu
de forcer systématiquement un modèle texte. Figer la configuration effective dans chaque
run pour qu'un changement de profil ultérieur ne modifie pas la comparaison.

Les campagnes de modèle pur désactivent explicitement le repli après échec ; les campagnes
du système complet le mesurent et distinguent les résultats par provenance. Réutiliser
les corpus et mesures existants et renforcer seulement les garanties manquantes.

**Différé** : porte de réponse conversationnelle entre agents, classement de ressources,
compétences et outils, Goal, planner, briefing, API TypeSafe directe, Laya et autres modèles
locaux, services Docker spécialisés, essais CPU/GPU et entraînement. L'intérêt à terme pour
le local est conservé ; aucun matériel local n'est disponible pour cette première étape.

## 8. Lots de réalisation proposés

| Lot | Contenu | Critère de réception |
|---|---|---|
| 1 — Contrats et profil | ADR, capacité, sélection nullable, API/IHM et matrice des replis | Profils existants compatibles, configuration utilisable |
| 2 — Branchement complet du dispatcher | Contrat durable, OpenRouter Decisions, branche texte si null et repli borné | Les deux branches fonctionnent dans le même parcours, avec traces, coûts et annulation |
| 3 — Tests et Lab | Tests ciblés, adaptation des bindings du Lab, comparaison par configuration | Qualité, latence, coûts et replis comparables sur le même corpus |

Le socle de la capacité expose d'abord `choice`. Les autres primitives s'ajoutent lorsqu'un
consommateur concret et sa sémantique de repli sont arrêtés. Une nouvelle ADR complétera
0095/0097 pendant l'implémentation ; l'approbation du plan ne décrit pas un runtime réalisé.

## 9. Objectif prioritaire : accélération de bout en bout

L'objectif utilisateur est de réduire au maximum la latence des traitements, avec un intérêt
ultérieur pour le local. Le critère de réussite de cette étape est un gain mesuré
sur le parcours complet à qualité métier acceptable, et pas uniquement sur le calcul du modèle.

- Décomposer préparation du contexte, admission/persistance, attente du worker, transport,
  attente du serveur de modèles, inférence, validation et application. Mesurer le temps
  jusqu'au début de l'exécution utile et, sur des scénarios bornés, jusqu'au résultat final.
- Comparer dans le Lab existant la sélection vide et Jev, sur le même corpus synthétique
  représentatif. Ces mesures accompagnent les premiers tests du branchement complet.
- Garder les courts-circuits déterministes en premier. Borner le contexte à la matière
  nécessaire, sans perdre les contraintes ni tronquer silencieusement les données.
- Regrouper les questions indépendantes partageant le même état dans un appel lorsque
  le protocole le permet ; ne pas sérialiser inutilement route et langue. Ne pas attendre
  un lot de plusieurs utilisateurs pour accélérer une requête interactive.
- Réutiliser les clients HTTP et connexions OpenRouter, avec concurrence bornée. Relever
  p50/p95, débit et impact sur les autres traitements sous charge. Les mesures mémoire,
  démarrage à froid et contention CPU/GPU des modèles locaux sont différées.
- Mesurer le coût temporel du repli dans le résultat global. Un taux élevé peut annuler
  le gain du spécialisé ; adapter les délais et seuils à partir des mesures. Aucun double
  appel spéculatif systématique : il pourrait saturer le modèle texte que l'on veut libérer.
- Un coupe-circuit de disponibilité est différé sauf si les premiers tests en démontrent
  la nécessité ; le premier périmètre conserve des délais et un repli bornés.
- Ne pas introduire de cache sémantique de décisions dans le premier lot : les contraintes,
  droits et contextes changent. Optimiser d'abord les appels évitables et le transport.
- Préserver le journal durable et la comptabilité. Toute optimisation de leurs délais doit
  garder les garanties de commit, d'annulation et de non-publication des résultats tardifs.

Fixer les objectifs chiffrés à partir des comparaisons du Lab : baisse de latence
p50/p95, tolérance sur les erreurs métier et impact maximal sur le LLM principal. Comparer
sur le même corpus tenu à l'écart du réglage. Une décision plus rapide qui sous-estime
l'effort et rallonge le travail final n'est pas une amélioration qualifiée.

## 10. Validation et réception

Renforcer les suites existantes : `test_dispatcher_planning`, `test_llm_profiles`, sorties
structurées, cycle durable, profils providers et évaluations Lab. Ajouter les scénarios
au niveau de leur garantie, avec des données entièrement synthétiques.

- Profils existants inchangés ; aucun modèle spécialisé requis, même avec toutes les
  sélections texte pointant sur le même endpoint/modèle. Aucun test matériel local requis.
- Choix entièrement déterminé par les contraintes ou unique sans appel ; route interdite impossible ; langue et contraintes
  du harnais préservées ; refus d'accès inchangé sur le primaire et le repli.
- Modèle spécialisé réussi, erreurs, résultat invalide, limite de contexte, repli activé
  et désactivé, modèle texte absent, confiance absente ou non qualifiée.
- Vraie persistance isolée : admission, retour après reconnexion, arrêt avant repli,
  réponse tardive, crash entre les étapes, reprise/rejeu, coûts sans double comptage.
- IHM réelle : ouvrir, changer, sauvegarder et rouvrir le profil ; revenir au texte ;
  changer de contexte personnel ; erreurs et réponses tardives sans écraser la sélection.
- Lab : cas FR/EN, ambiguïtés, livrable cohérent versus travail décomposable, difficultés,
  changements d'ordre des options et contenu tentant d'influencer le choix. Corpus de
  réglage et corpus de qualification séparés, sans données individuelles de production.
- Mesures par provenance dans le Lab : exactitude métier, escalades inutiles,
  sous-estimation de l'effort, latence p50/p95, coûts physiques et taux de repli.

Tests ciblés puis `make typecheck`, `make architecture-check` et suites proportionnées.
Régénérer la cartographie lors des changements réels. Avant publication demandée,
`make validate` sur l'instantané final et lecture de son résumé. Aucun de ces travaux,
ni installation, synchronisation DB ou déploiement, n'est engagé par ce document.

## Références externes de conception

Ces documents décrivent les candidats ; vérifier leur version lors de l'implémentation.

- [TypeSafe : primitives](https://docs.typesafe.ai/primitives)
  et [API System One](https://docs.typesafe.ai/api).
- [OpenRouter : accès Jev et API Decisions](https://openrouter.ai/blog/insights/what-is-jev/).
- [Laya : code et serveur compatible](https://github.com/NandhaKishorM/laya)
  et [limites du checkpoint multilingue](https://huggingface.co/convaiinnovations/laya-multilingual).
