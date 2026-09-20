<p align="right"><strong>Français</strong> · <a href="../../en/components/deepseek-harness.md">English</a></p>

# DeepSeek Harness

Ce bridge provisionne une instance DeepSeek Harness par agent avec le gestionnaire générique
`bridge.harness`. L'exécution remonte exclusivement par le client Chat Completions commun de
`app.harnesses`; `app.agent` ne dépend donc ni du SDK Python ni du JSON-RPC natif de DSH.

Le profil Galaris fixe explicitement `llm-deepseek.protocol: chat-completions` pour la
passerelle LLM. DSH 0.1.6 utilise Messages par défaut ; ce protocole natif ne correspond pas
à l'URL OpenAI injectée par le provisioner.

Le conteneur construit la révision DSH épinglée par `harness_provider.py`, puis expose :

- `GET /v1/models` ;
- `POST /v1/chat/completions`, streamé ou non ;
- `GET /healthz` pour Compose.

Le mode SSE souscrit au callback officiel `on_notification` du SDK. Il relaie immédiatement les
`assistant/chunk` comme deltas Chat Completions, les raisonnements terminés et `tool/result` comme
`galaris.agent-message/v1`, puis publie `galaris.agent-result/v1` avec la réponse finale exacte.
Les commentaires keepalive ne servent plus qu'aux périodes où le SDK ne produit réellement aucun
événement ; le contenu n'est jamais fabriqué en découpant la réponse après coup.

Le provisioner injecte deux secrets distincts dans `.env` sur l'hôte du harness manager : le
token de l'API du Harness, stocké chiffré par `app.harnesses`, et un token système MCP tournant.
Ce dernier authentifie à la fois `/api/mcp/{agent_code}` et le gateway
`/api/llm/openai`. Aucun credential de fournisseur LLM ou de connexion métier n'entre dans le
conteneur.

Le contexte technique rendu par l'adapter conserve les identifiants de Task et de run dans le
prompt envoyé au gateway ; ses extracteurs les rétablissent donc sur chaque `LLMCall`, y compris
lorsque le SDK DeepSeek ne permet pas d'ajouter des en-têtes HTTP arbitraires. À la terminaison, le
client commun agrège ces traces persistantes et leur coût qualifié ; les compteurs partiels du SDK
ne servent que de repli en l'absence d'appel corrélé.

Les skills effectivement autorisés sont copiés sous `data/skills`; le provider filesystem DSH
est isolé avec `includeDefaultRoots: false`. La mémoire durable, les fichiers canoniques et les
effets externes passent par le MCP Galaris. Le workspace DSH local reste un espace de calcul : un
fichier n'est durable que lorsqu'un Tool Galaris enregistre son URI et son effet.

La première construction de l'image télécharge et compile la révision DSH épinglée ; elle peut
donc être longue. `update` reconstruit l'image, `refresh` resynchronise modèle, token MCP et skills,
puis redémarre l'instance. Un seul run est admis simultanément par instance, conformément à la
sérialisation actuelle des Tasks par agent.
