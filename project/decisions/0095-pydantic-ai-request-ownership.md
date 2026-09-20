# ADR 0095 — Construction des appels internes confiée à Pydantic AI

- Statut : Accepted
- Date : 2026-09-13
- Complète l’ADR 0088 ; sa politique de compatibilité demeure transitoirement active.

## Décision appliquée

Pydantic AI construit les requêtes Chat et Responses et lit les réponses du SDK OpenAI.
`InternalLLMChatModel` ne recopie plus le constructeur Chat, le choix d’outils, les schémas,
le mappage des messages ni le décodage SSE. Les messages système consécutifs sont fusionnés
par le profil public du SDK. Les instructions JSON proviennent de `PromptedOutput`.

La dépendance minimale passe à Pydantic AI 2.43, qui connaît notamment les contraintes
de sampling d’Astra. Le verrou conserve les versions effectivement vérifiées.
Lorsqu’un bridge fournit un profil Responses, le modèle Chat emploie également ce résolveur
de profil plutôt qu’un profil OpenAI générique. Les restrictions de forçage d’outils et
l’orthographe du plafond Chat restent projetées dans le profil avant construction.

Un transport HTTP en mémoire commun fait passer les requêtes SDK par les proxys existants :
autorisation du demandeur, credentials, corrélation, comptabilité et renouvellement de jeton
restent à leur frontière actuelle. L’effort réglé est fourni au SDK avant construction.
Pour ces requêtes, le proxy n’injecte plus l’effort d’origine s’il a été omis par le SDK ou
retiré par les réglages de l’appel. Les clients externes conservent leur résolution de run.

Le transport transmet les timeouts SDK, garde les statuts HTTP et les en-têtes `Retry-After`,
`Retry-After-Ms` et `X-Request-Id`. Il traduit les exceptions de transport entre les versions
HTTPX utilisées par le proxy et le SDK. Les erreurs restent interprétables par Pydantic AI.
Le client SDK a `max_retries=0` : aucune couche supplémentaire d’essais payants n’est ajoutée.
Une annulation avant les en-têtes clôt la trace et le client avec un nettoyage borné protégé.

Le comptage préalable reste une estimation locale, distincte de la facturation. Il utilise
les messages publics sérialisables, les instructions et les schémas d’outils/sortie ; il
n’appelle plus les sérialiseurs privés du SDK et n’envoie pas d’appel de comptage payant.
Le Chat continue de consommer un stream même pour rendre un résultat final unique, afin de
conserver la trace progressive pendant les longues générations.

Le second lot branche le profil officiel `openai_codex_model_profile` pour le provider
ChatGPT/Codex. Le SDK impose le streaming, `store=false` et le retrait des réglages génériques
refusés (`temperature`, `top_p`, `max_tokens`), même pour un identifiant opaque. La trace d’un
appel interne Codex reflète désormais ce transport streaming, y compris pour un résultat final
unique. L’API OpenAI garde son profil distinct. Le bridge conserve OAuth et l’adaptation des
clients externes qui ne passent pas par Pydantic AI.

Le résolveur de familles Groq recopié est supprimé au profit de `GroqProvider.model_profile`.
L’extra officiel `pydantic-ai[groq]` rend cette API disponible sans changer les endpoints
OpenAI compatibles utilisés. Pour DeepSeek, les capacités de raisonnement proviennent aussi
du profil officiel : raisonnement obligatoire, réglable et compatibilité du forçage d’outils.
La politique de paramètres DeepSeek ne teste plus les noms de modèles ; les valeurs d’effort
de l’endpoint restent transitoirement adaptées par Galaris.

## Limite explicite de cette étape

Cette section décrit l’étape du 13 septembre. Le lot suivant, décrit par
[0097](0097-durable-inference-lifecycle.md), remplace les règles locales de noms concernées,
introduit la négociation des paramètres optionnels et ajoute le cycle de vie durable.

Cette décision **ne déclare pas la migration terminée**. Les politiques de paramètres du
gateway continuent d’adapter les requêtes après le SDK. Leurs règles par nom de modèle,
les sélecteurs de protocole DeepSeek/Perplexity et certains profils de routeurs existent
encore. La cible est de les supprimer, sans déplacer les mêmes heuristiques ailleurs.
Leur suppression immédiate ferait perdre des protections que Pydantic AI 2.43 ne reproduit
pas encore dans cette étape du 13 septembre. L'évolution du 14 septembre est décrite par
[0097](0097-durable-inference-lifecycle.md) ; les seules extensions et qualifications
restantes sont suivies dans [le plan de convergence](../plans/convergence-pydantic-ai.md).

L’adoption d’une intégration native qui change le protocole, la compaction, l’authentification
ou la restitution des éléments de raisonnement doit être qualifiée séparément. Les harnais
de tâches, checkpoints et garanties de non-rejeu d’effets restent nécessaires.
L’enregistrement distinct des réglages demandés et envoyés, ainsi que le découplage de la
publication UI de la comptabilité, ne sont pas réalisés dans cette étape.

## Preuves

- `test_chat_sdk_applies_profile_before_internal_transport` reproduisait le contournement
  du profil sur le constructeur copié ; le scénario emploie un identifiant opaque.
- La matrice `test_provider_parameters.py` conserve les contraintes existantes des endpoints,
  les outils, URI, plafonds et retries de validation des résultats.
- Ses scénarios de transport passent par le SDK et les vrais proxys, avec uniquement les
  frontières externes remplacées : 429, timeout, annulation et effort retiré avant l’appel.
- Les tests qui appelaient `_internal_completions_create` ou remplaçaient `_map_messages`
  sont remplacés par des appels SDK publics : instructions JSON, fusion des messages et
  budget des outils sont les garanties reprises, pas la présence d’une phrase ajoutée maison.
- Le refus d’une enveloppe d’erreur sous HTTP 200 reste testé au proxy ; le modèle teste
  maintenant la conservation des véritables erreurs HTTP, au lieu d’un faux proxy qui ne
  respectait pas la normalisation en 502 du proxy réel.
- Les nouveaux scénarios à identifiant opaque reproduisent avant correction l’absence de
  prise en compte des capacités DeepSeek et du profil d’endpoint Codex.
- La reprise Responses est qualifiée sur API OpenAI et Codex, avec conservation des
  signatures, identifiants d’outils et tokens. Les streams simulés comportent les événements
  de création, d’items et de deltas du protocole ; l’événement terminal peut omettre les items.
  Les tolérances du gateway externe aux streams réduits restent testées séparément.

Les tests avec serveur simulé ne constituent pas une qualification des comptes providers.
