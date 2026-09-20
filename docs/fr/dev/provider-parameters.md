<p align="right"><strong>Français</strong> · <a href="../../en/dev/provider-parameters.md">English</a></p>

# Compatibilité des paramètres des providers

Audit du 12 septembre 2026. Les sources de vérité sont les politiques sous `back/bridge/`,
le contrat `back/app/llm/request_parameters.py` et les scénarios HTTP
`back/tests/test_provider_parameters.py`. La décision structurelle est
[l’ADR 0088](../../../project/decisions/0088-provider-request-parameters.md).

## Contrat courant — 14 septembre 2026

[L’ADR 0097](../../../project/decisions/0097-durable-inference-lifecycle.md) remplace la fermeture
du vocabulaire et les tables locales de noms décrites dans l’audit historique ci-dessous.
Les profils SDK et les politiques d’endpoint font autorité. Les extensions inconnues sont
transmises ; un HTTP 400/422 nommant explicitement un réglage optionnel non supporté permet
de retirer ce champ puis de réessayer. Budgets, outils, contenu et schémas sont conservés.
Un timeout, un 429 ou un stream partiel ne déclenchent pas cette négociation.

Les routeurs génériques ne déduisent plus un profil d’un namespace ou suffixe. Perplexity
utilise le repli Responses/Chat du SDK après les refus HTTP déclarés par le bridge. Les
anciens plafonnements par version de modèle ne sont plus garantis : le fournisseur peut
refuser un effort explicite, qui relève alors de la négociation des paramètres optionnels.
Les fixtures restent un inventaire de scénarios ; leurs anciennes listes de champs bloqués
ne constituent plus une interdiction runtime des extensions natives.

Les appels et événements sont durables, avec pause, arrêt, reprise, relecture et comptabilité
par tentative. Les tests `test_protocol_inference.py` complètent la matrice historique en
vérifiant la négociation et la conservation des exigences fonctionnelles.

## Historique de migration — 13 septembre 2026

Le premier lot de [l’ADR 0095](../../../project/decisions/0095-pydantic-ai-request-ownership.md)
retire le constructeur Chat et le lecteur SSE copiés. Pydantic AI 2.43 construit les appels
internes Chat/Responses ; son profil assure la fusion des messages système. Le transport
commun garde l’authentification et la comptabilité du proxy, transmet les timeouts et conserve
les statuts HTTP ainsi que `Retry-After`. L’effort d’origine n’est plus réinjecté dans une
requête déjà construite par le SDK. L’annulation avant en-têtes clôt trace et client.

Le second lot confie les restrictions de l’endpoint Codex au profil officiel du SDK :
streaming, `store=false` et retrait des réglages génériques refusés avant construction.
Groq utilise le résolveur de profil officiel ; DeepSeek lit les capacités de raisonnement
du SDK dans sa politique de paramètres, sans tests de nom dans cette politique. La reprise
du raisonnement chiffré Codex et la compaction restent couvertes par les tests.

Cette description du second lot concerne l'étape du 13 septembre. La
[décision 0097](../../../project/decisions/0097-durable-inference-lifecycle.md) décrit la
suppression des règles locales concernées au lot suivant. Le
[plan de convergence](../../../project/plans/convergence-pydantic-ai.md) conserve uniquement
les extensions et qualifications ouvertes. Il ne faut pas ajouter de nouvelles heuristiques de nom.

## Garantie commune

Le proxy adapte encore les contrôles après sélection du modèle. Il résout l’effort du run
pour les clients externes ; les appels internes ont déjà remis leurs réglages au SDK.
Cette protection couvre les Goals, les appels structurés, le harnais interne et les clients
externes passant par le gateway. Un harnais qui contacte directement son fournisseur reste
hors de cette frontière.

La matrice autorise les réglages communs par endpoint, traduit l’effort et les plafonds de
tokens, retire les combinaisons incompatibles et garde les messages, outils et formats de
sortie. Une compaction n’hérite pas des réglages de génération. Un alias de routeur inconnu
n’hérite pas arbitrairement des capacités OpenAI. Une incompatibilité fonctionnelle connue
(par exemple les outils Astra sur Chat Completions) produit une erreur explicite avant envoi.

Le champ de trace `reasoning_effort` conserve le choix canonique Galaris ; la valeur envoyée
peut être plafonnée ou traduite. Sans niveau réglable documenté, elle est omise. Les extensions
natives et les capacités multimodales restent régies par leurs builders et contrats propres.

## Garde-fous pour les nouveaux paramètres

Le vocabulaire des requêtes est fermé. Tout nouveau champ de premier niveau ou sous-champ de
`reasoning`, `text`, `stream_options` ou `thinking` doit être classifié avant utilisation.
Un champ inconnu, y compris fourni par `extra_body`, est refusé avant l’appel HTTP. Le gateway
retourne une erreur de validation indiquant les noms des champs, sans exposer leurs valeurs.
Les propriétés des schémas JSON utilisateur et le contenu des messages ne sont pas parcourus.
Le contrôle est répété après transformation par le bridge et lors d’un renouvellement
d’authentification ; un refus tardif termine la trace en erreur.

`back/tests/fixtures/provider_parameters.json` contient des exemples pour chaque contrôle et
des listes de champs acceptés par les endpoints simulés. Ce fichier est indépendant des
politiques de production : ne jamais le régénérer depuis leurs listes d’autorisation. Les tests
échouent si un contrôle n’a pas d’exemple, si une sortie contient un champ non revu ou si un
provider du catalogue n’est pas représenté. Un provider du catalogue sans politique explicite
ne peut pas inférer sa compatibilité depuis le nom de son modèle.

L’inventaire des champs Chat/Responses du SDK OpenAI installé est également figé dans cette
fixture. Une mise à jour qui ajoute ou retire un champ impose une revue, même si Galaris ne
l’émet pas encore. Les champs connus du SDK mais non pris en charge ont un motif de refus
explicite dans `sdk_blocked_fields` ; ils restent refusés à l’exécution.

Chaque exemple est exécuté sur toute la matrice provider/modèle/protocole, avec et sans
streaming, via les vrais proxys. Des tests vérifient aussi que les garde-fous détectent un
contrôle ajouté sans exemple, une autorisation globale accidentelle et une injection tardive.
Les transports HTTP réels sont interdits dans cette suite : aucune clé ni souscription externe
n’est nécessaire. Le coût est uniquement celui des conteneurs de tests locaux.

Pour ajouter un paramètre :

1. Vérifier les contrats des endpoints et classer le champ dans `CONTROL_PARAMETERS`, ou le
   sous-champ dans `NESTED_PARAMETERS`. Un champ de contenu relève de `PAYLOAD_PARAMETERS`.
2. Vérifier d’abord sa prise en charge par les settings, profils ou intégrations de Pydantic AI.
   Garder les contraintes d’endpoint indépendantes du nom dans la configuration du provider.
   Une lacune du SDK doit être consignée dans le plan de convergence ; ne pas la contourner
   par une nouvelle heuristique de nom. Une capacité fonctionnelle ne doit pas être supprimée.
3. Ajouter son exemple et les autorisations justifiées dans la fixture indépendante. Toute la
   matrice l’exercera automatiquement ; ajouter un cas spécifique pour ses contraintes croisées.
4. Exécuter `make tests-providers`, puis les contrôles habituels. Cette suite est aussi collectée
   par `make tests`, `make tests-coverage` et les jobs backend des CI GitHub/GitLab.

Cette fermeture remplace l’ancien passage libre d’extensions natives non déclarées sur le
gateway texte. Une extension légitime doit désormais recevoir un contrat et un scénario.

## Matrice auditée

Les lignes décrivent les adaptations principales ; les ensembles complets et les familles
reconnues sont définis dans le code, sans appel réseau de découverte à chaque génération.

| Provider | Adaptation principale | Référence |
|---|---|---|
| OpenAI API | Astra : pas de sampling ; GPT-5 : contraintes selon version/effort ; budgets natifs | [OpenAI](https://developers.openai.com/api/docs/guides/latest-model), [GPT-5.1](https://developers.openai.com/api/docs/models/gpt-5.1), [GPT-5.6](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-5.6) |
| ChatGPT (`openai-codex`) | Restrictions d’endpoint supplémentaires, dont température, top-p et plafond de sortie | `back/bridge/openai/codex.py`, `back/tests/test_codex_provider.py` ; rejet production reproduit |
| Anthropic API | Compatibilité OpenAI sans effort réglable ; sampling restreint selon génération, température ≤ 1, pas de température avec top-p | [Compatibilité Claude](https://platform.claude.com/docs/en/cli-sdks-libraries/libraries/openai-sdk) |
| DeepSeek | V4 : effort et activation distincts en Chat ; sampling retiré en thinking ; outils forcés refusés en thinking | [Thinking](https://api-docs.deepseek.com/guides/thinking_mode/), [Responses](https://api-docs.deepseek.com/api/create-response/) |
| Gemini | Échelle d’effort Gemini ; désactivation limitée aux modèles concernés ; température conservée | [Compatibilité Google](https://ai.google.dev/gemini-api/docs/openai) |
| xAI | Effort Grok, pénalités et stop retirés en raisonnement ; température conservée | [Raisonnement Grok](https://docs.x.ai/developers/model-capabilities/text/reasoning) |
| Groq | Retrait logprobs, logit_bias et pénalités ; efforts GPT-OSS/Qwen distincts | [Compatibilité](https://console.groq.com/docs/openai), [API](https://console.groq.com/docs/api-reference) |
| Cerebras | Retrait logit_bias ; efforts GPT-OSS, désactivation GLM documentée | [API](https://inference-docs.cerebras.ai/api-reference/chat-completions) |
| Mistral | Effort binaire des familles réglables ; absence des contrôles OpenAI non déclarés | [Raisonnement](https://docs.mistral.ai/studio/conversations/reasoning) |
| Cohere | Effort binaire Command A ; retrait des contrôles absents du contrat de compatibilité | [Compatibilité](https://docs.cohere.com/docs/compatibility-api) |
| Together | Efforts GPT-OSS et DeepSeek V4 propres au service | [Raisonnement](https://docs.together.ai/docs/inference/chat/reasoning) |
| Fireworks | Énumérations d’effort selon famille servie | [Chat](https://docs.fireworks.ai/api-reference/post-completions), [Responses](https://docs.fireworks.ai/api-reference/post-responses) |
| NVIDIA NIM | Contrôles communs NIM ; effort GPT-OSS reconnu, autres efforts omis | [API NIM](https://docs.nvidia.com/nim/large-language-models/latest/api-reference.html) |
| Ollama | Contrat Chat compatible ; niveaux thinking seulement pour familles reconnues | [Compatibilité](https://docs.ollama.com/api/openai-compatibility) |
| OpenRouter | Politique de famille et objet `reasoning` unifié, y compris budget Claude | [Raisonnement](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens) |
| Hugging Face | Politique d’auteur, suffixe de routage reconnu, budget dans le champ du routeur | [Responses](https://huggingface.co/docs/inference-providers/en/guides/responses-api) |
| Mammouth | Modèles reconnus : politique de famille ; presets opaques : réglages conservateurs | [API](https://info.mammouth.ai/docs/api-quick-start/) |
| Perplexity | Sonar Chat distinct des modèles qualifiés de l’Agent API ; `/responses` reste un alias | [Agent API](https://docs.perplexity.ai/docs/agent-api/quickstart) |

ElevenLabs, Google Cloud TTS, Azure Speech, Suno et BytePlus ne passent pas par la génération
texte des Goals : leurs payloads sont construits par les services média propres à chaque bridge.
Les embeddings envoient leur contrat dédié ; `models_dev` fournit des métadonnées sans inférence.
L’inspection de ces chemins n’est pas une qualification en ligne de chaque API média.

## Validation et maintenance

La construction SDK et la validation HTTP utilisent la même politique fournisseur. Les
restrictions de choix d'outil avec raisonnement sont projetées dans les profils internes
Chat et Responses avant la construction. Une sortie structurée conserve son schéma et ses
validateurs même lorsque le SDK doit laisser le choix d'outil automatique.

La matrice passe par les vrais proxys et un transport HTTP simulé, avec et sans streaming.
Elle vérifie les paramètres envoyés et le contenu préservé. Les suites LLM et Goals couvrent
les parcours métier ; les tests du modèle interne protègent aussi contre la suppression de
paramètres valides par le SDK. Aucune requête payante n’est nécessaire pour ces tests.

La matrice de composition fait construire les requêtes par le SDK installé : protocoles Chat
et Responses, efforts automatique/none/high/max, sorties outil/JSON demandé/texte. Elle exige
la correction d'une réponse structurée invalide et la conservation des URI. Le parcours DB
d'admission vérifie la tâche persistée, la redelivery sans doublon et l'absence de tâche lors
d'un échec. `make tests-providers` publie `artifacts/provider-contracts.xml` ; les CI et
`make validate` exigent son succès. Une mutation indexée dans `project/regressions.json`
vérifie que retirer l'adaptation SDK fait effectivement échouer la suite.

Lors d’un ajout de provider ou d’une nouvelle famille, vérifier la documentation de l’endpoint,
ajouter sa politique et un scénario de requête sortante. Les possibilités réelles d’un routeur
ou d’un NIM peuvent varier selon le modèle et le déploiement : les essais simulés ne prouvent
pas l’acceptation par tous les comptes distants. Les erreurs HTTP externes restent visibles.
