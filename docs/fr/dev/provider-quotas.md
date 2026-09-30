<p align="right"><strong>Français</strong> · <a href="../../en/dev/provider-quotas.md">English</a></p>

# Consommation, budgets et crédits des fournisseurs

Revue des 22 profils du catalogue et des connexions personnalisées Ollama au 30 septembre 2026.
L’état « intégré » décrit les lecteurs déclarés dans les bridges du dépôt. « Possible » décrit
une API officielle consultée, sans annoncer son intégration dans Galaris. « Non trouvé » signifie
qu’aucun contrat public adapté n’a été identifié dans les références consultées, pas que le
fournisseur ne pourra jamais le proposer. La revue s’appuie sur les contrats publics ; les
contrôles automatisés utilisent exclusivement des réponses synthétiques. Une lecture en
développement a vérifié l’authentification de la route de solde Fireworks ; seuls son statut
HTTP et la conclusion technique sont conservés, sans clé ni donnée individuelle.

Une jauge exige une consommation et un plafond portant sur la même période, la même devise et
le même périmètre. Un solde seul reste un montant. Les limites de débit dans les en-têtes ne
constituent pas un budget financier. Les coûts des appels Galaris ne permettent pas de reconstruire
le solde d’un compte utilisé par d’autres clients.

| Fournisseur | Disponibilité dans Galaris | Information récupérable et conditions | Référence |
|---|---|---|---|
| Fireworks AI | Solde non intégré ; aucun panneau affiché | Aucune route publique de solde prépayé identifiée. `monthly-spend-usd` fournit un plafond de dépenses et son usage, pas l’argent disponible. La route du portail `/api/billing/balance` refuse la clé API testée (401). Aucune jauge de plafond ne remplace le solde. | [Facturation](https://app.fireworks.ai/account/billing), [quotas du compte](https://docs.fireworks.ai/guides/quotas_usage/account-quotas), [Get Quota](https://docs.fireworks.ai/api-reference/get-quota) |
| ChatGPT / Codex | Intégré | Fenêtres du compte OAuth connecté et solde `credits.balance` en crédits, sans plafond ni pourcentage inventés ; propriété Galaris et rafraîchissement existants. Montants absents ou crédits illimités non présentés comme zéro. Interface spécifique à ChatGPT, distincte de l’API OpenAI et de ses crédits. | [Contrat et tests du bridge](../../../back/bridge/openai/tests/test_quota.py), [crédits ChatGPT](https://learn.chatgpt.com/docs/pricing#what-are-tokens-and-credits) |
| OpenAI API | Possible, non intégré | Usage et dépenses d’organisation avec une clé Admin distincte ; ces rapports ne donnent pas à eux seuls le solde prépayé ou un plafond comparable. | [Usage et Cost API](https://developers.openai.com/cookbook/examples/completions_usage_api) |
| Anthropic API | Possible, non intégré | Usage et coûts par l’Admin API ; credentials administratifs, pas une clé d’inférence limitée à un workspace. API indisponible pour les comptes individuels. Distinguer Claude Platform de Claude Enterprise. | [Usage and Cost API](https://platform.claude.com/docs/en/manage-claude/usage-cost-api) |
| OpenRouter | Intégré | Montant restant pour la clé via `/key` ; solde du compte via `/credits` avec la clé de gestion facultative. Affichage du montant seul, sans jauge basée sur le cumul des achats. | [Crédits](https://openrouter.ai/docs/api/api-reference/credits/get-remaining-credits) |
| Mammouth AI | Intégré, schéma à confirmer en réel | `/key/info` : consommation et budget de clé lorsqu’ils sont fournis. Le schéma du lecteur reste vérifié avec des réponses synthétiques ; les quotas de l’application sont distincts. | [Décision et limite de validation](../../../project/decisions/0146-provider-usage-snapshots.md), [documentation du service](https://info.mammouth.ai/docs/api/) |
| DeepSeek | Intégré | `/user/balance` : solde USD/CNY ; pas de plafond initial pour un pourcentage. | [Balance](https://api-docs.deepseek.com/api/get-user-balance) |
| ElevenLabs | Intégré | `/v1/user/subscription` : consommation, plafond de crédits et prochain renouvellement ; permission `User → Read`. | [Subscription](https://elevenlabs.io/docs/api-reference/user/subscription/get) |
| SunoAPI.org | Intégré | `/api/v1/generate/credit` : crédits restants du service tiers, pas de plafond. | [Remaining credits](https://docs.sunoapi.org/suno-api/get-remaining-credits) |
| Mistral | Possible, non intégré | Admin API beta : `/v1/admin/usage` et `/v1/admin/spend-limit`, avec une clé Admin. Vérifier les montants réellement renvoyés avant de calculer une jauge ; un indicateur de plafond atteint ne suffit pas. | [Admin Billing](https://docs.mistral.ai/api/endpoint/beta/admin/billing) |
| Together AI | Possible sous condition, non intégré | `/v1/billing/usage` beta, activé par organisation sur demande ; 404 sinon. Dépenses USD paginées, sans solde/plafond. Clé de l’organisation, identifiant d’organisation recommandé ; données retardées. | [Billing usage](https://docs.together.ai/reference/billing-usage) |
| xAI | Possible, non intégré | Management API : `/v1/billing/teams/{team}/prepaid/balance` et rapports de facturation. Clé de gestion séparée et identifiant d’équipe ; montants en cents à normaliser. | [Billing Management](https://docs.x.ai/developers/rest-api-reference/management/billing), [authentification](https://docs.x.ai/developers/management-api-guide) |
| Gemini | Possible via infrastructure Cloud, non intégré | Usage dans AI Studio / Cloud Billing. Pas de route de solde documentée avec la seule clé Gemini ; coûts via exports Cloud Billing et droits Cloud supplémentaires. | [Billing](https://ai.google.dev/gemini-api/docs/billing), [exports Cloud Billing](https://cloud.google.com/billing/docs/how-to/export-data-bigquery) |
| Google Cloud TTS | Possible via infrastructure Cloud, non intégré | Facturation du projet via Cloud Billing / BigQuery ; authentification IAM et export activé. La clé TTS seule ne donne pas un solde de compte. | [Exports Cloud Billing](https://cloud.google.com/billing/docs/how-to/export-data-bigquery) |
| Azure AI Speech | Possible via infrastructure Azure, non intégré | Coûts par l’API Cost Management Query, avec scope de souscription/facturation, jeton Entra et droits correspondants. La clé Speech et sa région ne suffisent pas. | [Cost Management Query](https://learn.microsoft.com/en-us/rest/api/cost-management/query/usage) |
| Groq | Budget public non trouvé | Facturation et plafonds dans la console. Metrics API Enterprise pour débit et tokens, sans solde ni plafond financier documentés dans ce contrat. | [Billing](https://console.groq.com/docs/billing-faqs), [metrics Enterprise](https://console.groq.com/docs/prometheus-metrics) |
| Cerebras | Non trouvé | Solde et crédits dans Cloud Console ; aucune route publique de solde/plafond trouvée dans le catalogue API consulté. | [Account & Billing](https://inference-docs.cerebras.ai/console/account-billing) |
| Cohere | Non trouvé | Tokens facturés par appel et suivi/plafond dans le dashboard ; pas de route publique de budget de compte identifiée. | [FAQ](https://docs.cohere.com/v2/docs/cohere-faqs) |
| Hugging Face | Non trouvé | Crédits et dépenses sur la page de facturation ; aucune route publique de solde adaptée identifiée. Une clé fournisseur personnelle est facturée chez ce fournisseur. | [Pricing and Billing](https://huggingface.co/docs/inference-providers/en/pricing) |
| Perplexity | API financière du profil non trouvée | Console de projets pour usage/facturation. L’Analytics API Enterprise documentée concerne Computer et une clé dédiée, pas le solde de la clé Sonar/Agent du bridge. | [Projects & Billing](https://docs.perplexity.ai/docs/getting-started/projects), [Computer Analytics](https://docs.perplexity.ai/docs/admin/computer-analytics-api) |
| NVIDIA | Non trouvé | Aucune route publique de solde du profil `integrate.api.nvidia.com` identifiée. Ne pas déduire un budget des réponses d’inférence ou de la gestion Cloud Functions. | [API reference](https://docs.api.nvidia.com/nim/reference) |
| BytePlus LAS | À confirmer | Aucune route de budget utilisant la clé LAS du bridge identifiée. La facturation Cloud/ModelArk ne suffit pas à établir ce contrat ; une intégration séparée demande sa propre vérification. | [LAS](https://docs.byteplus.com/en/docs/byteplus_las/video_gen_enhanced) |
| Ollama personnalisé | Sans budget externe pour l’exécution locale | Le serveur local n’a pas de compte financier à interroger. Un éventuel service Cloud exige son contrat propre. | [API locale](https://docs.ollama.com/api/introduction) |

`bridge.models_dev` enrichit les métadonnées de modèles ; ce n’est pas un compte fournisseur
facturé dans ce catalogue. Les connexions OpenAI compatibles personnalisées ne permettent pas
de deviner une API de facturation : elles ont besoin d’un lecteur explicitement déclaré.

L’intégration initiale du plafond Fireworks a été retirée : calculer plafond moins dépenses
présentait à tort une autorisation de dépenses comme un montant disponible. Un plafond
synthétique d’un million a reproduit ce défaut avant correction. Le catalogue ne déclare
plus de lecteur Fireworks ; aucun panneau de solde ni lien dédié n’est affiché dans sa
configuration. L’interface ignore aussi l’ancien indicateur de prise
en charge pour ne pas réafficher une jauge issue d’un ancien backend. Les anciens tests de
découverte de compte et de quota mensuel sont remplacés par la garantie qu’aucun plafond ne
substitue le solde. Aucun fallback vers des dépenses estimées ou une session web privée
n’est utilisé. Voir la
[décision 0146](../../../project/decisions/0146-provider-usage-snapshots.md) et le
[parcours utilisateur](../user/navigation.md).

Les lecteurs sont couverts par `back/app/llm/tests/test_provider_quotas.py` et la couverture
ChatGPT dans `back/bridge/openai/tests/test_quota.py`. La présence et les types des champs de
crédits ont été confirmés en développement, sans conserver le solde, les identifiants ni les
données personnelles du compte. Les scénarios de composants couvrent le solde supplémentaire
et les fenêtres simultanément, zéro, les erreurs, la reprise et les réponses tardives. Le parcours assemblé
`e2e/specs/provider-usage.spec.mjs` couvre Fireworks sur ordinateur et mobile : absence de
panneau de solde ou de jauge de dépenses, configuration accessible et réouverture. Il couvre
aussi les crédits ChatGPT à côté des fenêtres, leur actualisation, les erreurs et la reprise.
