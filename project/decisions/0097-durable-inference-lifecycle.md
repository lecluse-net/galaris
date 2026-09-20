# ADR 0097 — Cycle de vie durable des inférences

- Statut : Accepted
- Date : 2026-09-14
- Complète [0095](0095-pydantic-ai-request-ownership.md) et précise les changements de compatibilité de [0088](0088-provider-request-parameters.md).

## Contrat réalisé

`app.llm.facade` expose `start_inference`, `read_inference`, `control_inference` et
`stream_inference`. Les requêtes texte, structurées et de protocole sont versionnées dans
`app.llm.contracts`. Une inférence est admise et committée avant son exécution autonome.
Une identité d’admission réutilisée doit conserver la même requête et la même autorité.

`LLMInference` possède la requête figée, l’autorité du demandeur et la génération courante.
`LLMInferenceAttempt` possède le lease, le résultat terminal et les appels physiques associés.
`LLMInferenceCommand` conserve les reçus idempotents. `LLMCall` reste l’autorité de facturation ;
`LLMCallEvent` conserve requêtes, messages, résultats et trames de protocole. Ces tables sont
déclaratives et convergent par DbAdmin. La rétention des traces diagnostiques exclut les appels
attachés à une inférence durable pour préserver sa relecture.

Le worker est supervisé au démarrage de l’application. Ses transactions d’admission, heartbeat
et journalisation sont indépendantes et courtes. Il restaure l’autorité et la corrélation
enregistrées, sans hériter du contexte du premier appelant. La perte du lease ferme les appels
abandonnés et invalide les écritures tardives ; elle ne relance jamais implicitement le fournisseur.

Le stream d’une tentative publie les messages persistés puis un unique `AIResult` terminal.
Le curseur permet une reconnexion sans nouvelle génération. Fermer cet abonnement laisse le
worker travailler. Les adaptateurs synchrones et HTTP conservent en revanche leur contrat
d’annulation : abandonner leur appel demande l’arrêt et conserve les fragments déjà écrits.

`pause` et `stop` interrompent aussi un fournisseur silencieux. `resume` crée une nouvelle
tentative d’une inférence suspendue ou interrompue ; il soumet de nouveau la requête figée et
ne prétend pas reprendre le calcul interne du fournisseur. `replay` crée une autre inférence
liée à l’originale. Les anciennes tentatives et leurs résultats restent immuables.
Cette couche ne réalise aucun effet d’outil ; les harnais et leurs checkpoints conservent ce rôle.

Les sorties structurées utilisent un registre de types et validateurs possédé par le code.
La requête conserve la clé versionnée, le schéma, le mode et le contexte de validation JSON.
Un contrat inconnu ou un schéma incompatible est refusé ; les validateurs contextuels sont
reconstruits pour chaque demande. Dispatcher, Briefing et le pilote Memory du Lab utilisent
ces adaptateurs en préservant les retries de validation, les URI et les coûts.

Les routes sous `/api/llm/openai/inferences` exposent création, lecture, commandes et SSE.
Elles exigent l’authentification LLM et vérifient le demandeur ou le périmètre de gestion.
La création autonome HTTP refuse les corrélations de runtime ; celles-ci passent par le
gateway existant. Les réponses Chat/Responses portent `X-Galaris-Inference-Id`.

## Paramètres et protocoles

Les tables locales de familles et versions supprimées sont remplacées par les profils SDK
et les politiques d’endpoint. Un routeur sans résolveur officiel ne reçoit plus un profil
déduit d’un préfixe ou emprunté à un autre fournisseur. Les extensions inconnues passent au
fournisseur ; cela remplace volontairement leur rejet local systématique et les plafonnements
d’effort propres aux versions de modèles. Les assertions de ces anciennes tables ne sont plus
un contrat ; les tests conservent les garanties de contenu, budgets, outils et sorties structurées.

Après un HTTP 400/422 contenant un code de paramètre non supporté et son chemin explicite,
le gateway peut retirer ce réglage optionnel puis réessayer. Chaque essai retire un champ
existant : cette négociation est bornée. Elle ne retire ni budget, ni outil, ni schéma et ne
se déclenche pas sur un timeout, un 429 ou un stream partiel. Le repli Perplexity Responses
vers Chat est confié au `FallbackModel` SDK sur les statuts de refus déclarés par le bridge,
sans découper le nom du modèle. Les contraintes propres aux endpoints restent actives.

## Limites et preuves

Ce lot ne réalise pas toutes les signatures prospectives du plan initial : création différée,
révision attendue, échéance globale et généralisation aux médias restent des extensions séparées.
La reprise est une nouvelle tentative, potentiellement facturable ; ce n’est pas une garantie
de reprise token par token. Les comptes fournisseurs réels restent à qualifier dans leur contexte.

Les scénarios `test_text_inference`, `test_structured_inference`, `test_protocol_inference`,
`test_inference_lifecycle`, `test_dispatcher_inference` et `test_briefing_inference` vérifient
la persistance PostgreSQL, les refus d’accès, les sorties SDK, les annulations, la concurrence,
les erreurs, la reprise, la relecture et la conservation des coûts. Les transports externes
sont simulés ; les services internes du parcours et la base sont réels. La qualification finale
est le rapport de `make validate` sur l’instantané du code courant.
