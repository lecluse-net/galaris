<p align="right"><strong>Français</strong> · <a href="../../en/components/deepseek-harness.md">English</a></p>

# DeepSeek Harness

Ce bridge provisionne une instance DeepSeek Harness par agent avec le gestionnaire générique
`bridge.harness`. L'exécution remonte exclusivement par le client Chat Completions commun de
`app.harnesses`; `app.agent` ne dépend donc ni du SDK Python ni du JSON-RPC natif de DSH.

Le profil Galaris utilise `llm-pi-ai` avec le protocole `openai-completions` pour la
passerelle LLM. Les adapters natifs DeepSeek, qui parlent exclusivement Messages,
sont désactivés. Le modèle courant est transmis au profil à chaque exécution.

Le conteneur construit la révision DSH épinglée par `harness_provider.py`, puis expose :

- `GET /v1/models` ;
- `POST /v1/chat/completions`, streamé ou non ;
- `GET /healthz` pour Compose.

DSH 0.2.1-rc.2 utilise Node 24.22.1 et pnpm 11.28.5 pour cette construction.
La version et le digest de Node sont épinglés pour rendre le runtime reproductible.

Le cache natif temporaire est désactivé dans l'image (`NARB_DISABLE_NATIVE_CACHE=1`) :
le SDK charge directement la bibliothèque fournie dans le paquet installé. Il n'essaie
donc pas de charger une copie depuis `/tmp`, qui reste non exécutable.

Le mode SSE souscrit au callback officiel `on_notification` du SDK. Il relaie immédiatement les
`assistant/chunk` comme deltas Chat Completions, les raisonnements terminés et `tool/result` comme
`galaris.agent-message/v1`, puis publie `galaris.agent-result/v1` avec la réponse finale exacte.
Les commentaires keepalive ne servent plus qu'aux périodes où le SDK ne produit réellement aucun
événement ; le contenu n'est jamais fabriqué en découpant la réponse après coup.

Le provisioner injecte deux secrets distincts dans `.env` sur l'hôte du harness manager : le
token de l'API du Harness, stocké chiffré par `app.harnesses`, et un token système MCP
conservé pendant les synchronisations. Une panne du manager après la préparation de la
configuration n'invalide donc pas l'identité du conteneur encore actif. La suppression du
runtime révoque ce token ; les autorisations de chaque run restent indépendantes.
Ce dernier authentifie à la fois `/api/mcp/{agent_code}` et le gateway
`/api/llm/openai`. Aucun credential de fournisseur LLM ou de connexion métier n'entre dans le
conteneur.

Avant tout appel au modèle, l'adaptateur exige un catalogue MCP Galaris chargé. Le SDK peut
contenir l'échec d'un plugin optionnel malgré `failOnStartupError` : l'adaptateur retente alors
son initialisation au plus trois fois, avant toute action métier. Sans catalogue, il retourne
une erreur explicite au lieu de laisser l'agent produire un faux résultat sans outils.
Ce contrôle nécessite la reconstruction de l'image des instances déjà provisionnées.

Un refus HTTP 401/403 lors du contrôle d'identité initial termine en erreur de configuration,
avant le SDK, avec absence d'effet confirmée. Il ne devient pas une issue d'envoi inconnue et
n'expose ni le secret ni le corps de la réponse distante.

Le contexte d'exécution MCP conserve le fournisseur `deepseek_harness` pour les autorisations.
Pendant une attente humaine, le proxy envoie immédiatement les en-têtes et des keepalives :
commentaires SSE pour un appel MCP, espaces JSON pour une autorisation native. Le client SDK
ne coupe donc pas l'appel après cinq minutes sans réponse. Une seule réponse finale reprend
l'appel initial après la décision ; aucun appel d'outil supplémentaire n'est créé par les keepalives.
Le délai RPC global du SDK est désactivé pour ces acteurs gérés : l'annulation du run et
l'expiration des autorisations bornent leur attente. Les appels non gérés conservent leur délai.
Les instances existantes doivent reconstruire leur image pour recevoir cette correction.

Le catalogue d'outils utilise le driver `openai_messages` de l'affectation validée ; la Task
provient du contexte serveur, ce qui permet aux activités Process de poser une question humaine
et d'enregistrer leur résultat dans leur propre exécution.

Le contexte technique rendu par l'adapter conserve les identifiants de Task et de run dans le
prompt envoyé au gateway ; ses extracteurs les rétablissent donc sur chaque `LLMCall`, y compris
lorsque le SDK DeepSeek ne permet pas d'ajouter des en-têtes HTTP arbitraires. À la terminaison, le
client commun agrège ces traces persistantes et leur coût qualifié ; les compteurs partiels du SDK
ne servent que de repli en l'absence d'appel corrélé.

Les compétences effectivement autorisées sont copiées sous `data/skills`; le provider filesystem DSH
est isolé avec `includeDefaultRoots: false`. La mémoire durable, les fichiers canoniques et les
effets externes passent par le MCP Galaris. Le workspace DSH local reste un espace de calcul : un
fichier n'est durable que lorsqu'un Tool Galaris enregistre son URI et son effet.

La première construction de l'image télécharge et compile la révision DSH épinglée ; elle peut
donc être longue. Depuis la supervision Galaris, **Redémarrer** ou **Mettre à jour** recrée
le runtime sélectionné avec ses credentials ; **Actualiser** ne demande que la projection
des compétences. Pour réparer un ancien conteneur dont le token est périmé, utiliser
**Redémarrer**, attendre sa disponibilité, puis réessayer la Task. Aucun envoi n'est relancé
par cette opération de gestion. Un seul run est admis simultanément par instance, conformément à la
sérialisation actuelle des Tasks par agent.
