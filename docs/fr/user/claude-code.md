<p align="right"><strong>Français</strong> · <a href="../../en/user/claude-code.md">English</a></p>

# Connecter Claude Code à Galaris

Un Claude Code installé sur votre poste peut utiliser les modèles des profils Galaris
via `https://galaris.example/api/profile/anthropic`. Tous les profils partagent cette
URL ; le champ `model` choisit le profil et le palier, par exemple `profil1/text/high`.
Les appels restent visibles dans **Suivi d’exécution → Appels LLM**.

## Préparer la connexion

Dans Galaris, créez un **jeton API utilisateur** depuis **Jetons API**. Votre compte
doit disposer du privilège **Accès à l’API LLM** (`LLM_API_ACCESS`). Utilisez ce jeton,
pas votre mot de passe ni un jeton système réservé aux runtimes gérés par Galaris.

Relevez le **Code API** du profil dans les usages LLM. Les exemples supposent un
profil `profil1` avec ses quatre paliers texte affectés à des modèles actifs prenant
en charge les appels d’outils. Remplacez ce code et `https://galaris.example` par vos
valeurs. Le [guide de l’API par profil](profile-api.md) décrit les sélecteurs disponibles.

## Configuration `.claude/settings.json`

Dans **Jetons API** (`/user/tokens`), le bouton **Configurer Codex / Claude Code**
permet de choisir un profil puis de copier cette configuration avec l’adresse de
votre serveur. Le jeton reste à compléter séparément. Si un palier est absent,
son alias Claude Code utilise le modèle de démarrage sélectionné.

Fusionnez cet exemple avec les réglages existants du projet. Il ne contient aucun secret :

```json
{
  "model": "profil1/text/high",
  "env": {
    "ANTHROPIC_BASE_URL": "https://galaris.example/api/profile/anthropic",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "profil1/text/ultra-low",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL_NAME": "Galaris · Ultra-économique",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL_DESCRIPTION": "profil1/text/ultra-low",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "profil1/text/low",
    "ANTHROPIC_DEFAULT_SONNET_MODEL_NAME": "Galaris · Économique",
    "ANTHROPIC_DEFAULT_SONNET_MODEL_DESCRIPTION": "profil1/text/low",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "profil1/text/standard",
    "ANTHROPIC_DEFAULT_OPUS_MODEL_NAME": "Galaris · Standard",
    "ANTHROPIC_DEFAULT_OPUS_MODEL_DESCRIPTION": "profil1/text/standard",
    "ANTHROPIC_DEFAULT_FABLE_MODEL": "profil1/text/high",
    "ANTHROPIC_DEFAULT_FABLE_MODEL_NAME": "Galaris · Haute capacité",
    "ANTHROPIC_DEFAULT_FABLE_MODEL_DESCRIPTION": "profil1/text/high",
    "CLAUDE_CODE_SUBAGENT_MODEL": "profil1/text/low",
    "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1"
  }
}
```

Cette correspondance est un choix de configuration du client : Claude Code envoie
les sélecteurs complets à Galaris. Les modèles sous-jacents peuvent venir d’autres
fournisseurs. Vous pouvez aussi utiliser des profils différents selon les alias.
La découverte alimente le menu `/model` depuis `/api/profile/anthropic/v1/models`.
Les variables d’alias et d’affichage sont décrites dans la
[configuration officielle des modèles Claude Code](https://code.claude.com/docs/en/model-config).

Conservez le jeton dans `~/.claude/settings.json` pour votre utilisateur, ou dans
`.claude/settings.local.json` pour ce projet. Si vous créez ce dernier à la main,
ajoutez-le à `.gitignore` avant d’y placer le jeton. Fusionnez ce bloc avec le fichier choisi :

```json
{
  "env": {
    "ANTHROPIC_AUTH_TOKEN": "<jeton-api-utilisateur-galaris>"
  }
}
```

`ANTHROPIC_AUTH_TOKEN` transmet `Authorization: Bearer …`, attendu pour un jeton
utilisateur Galaris ; `ANTHROPIC_API_KEY` utilise un autre en-tête. La portée des
fichiers et l’authentification sont détaillées dans le
[guide officiel de connexion à un gateway](https://code.claude.com/docs/en/llm-gateway-connect).
Pour une configuration entièrement personnelle, placez aussi le premier bloc dans
`~/.claude/settings.json`. L’URL de base s’arrête à `/anthropic`, sans `/v1/messages`.

## Vérifier et changer de modèle

Pour vérifier le catalogue depuis un terminal, exportez le jeton dans ce terminal
(les réglages JSON ne sont pas lus par `curl`) :

```bash
export ANTHROPIC_AUTH_TOKEN='<jeton-api-utilisateur-galaris>'
curl --fail-with-body 'https://galaris.example/api/profile/anthropic/v1/models' \
  -H "Authorization: Bearer $ANTHROPIC_AUTH_TOKEN" \
  -H 'anthropic-version: 2023-06-01'
claude --model profil1/text/high
```

Dans Claude Code, `/status` permet de vérifier la connexion. Demandez ensuite une
réponse courte pour vérifier l’inférence et sa trace dans Galaris. Pour une autre
session, utilisez par exemple `claude --model profil1/text/standard`.

Les paliers `text/high` et `text/standard` sélectionnent des affectations de profil ;
ils ne désignent pas l’effort de raisonnement. Cet exemple ne force donc pas
`effortLevel` ni les capacités de raisonnement du modèle. Si nécessaire, renseignez
`CLAUDE_CODE_MAX_CONTEXT_TOKENS` avec une fenêtre compatible avec tous les modèles
utilisés dans cette configuration ; voir la
[gestion officielle du contexte](https://code.claude.com/docs/en/model-config#correct-the-window-for-a-gateway-or-custom-model-id).

## Résoudre les erreurs

| Symptôme | Vérification |
|---|---|
| `401` ou `403` | Jeton utilisateur valide, variable `ANTHROPIC_AUTH_TOKEN`, privilège `LLM_API_ACCESS` |
| Modèle inconnu ou indisponible | Sélecteur exact du catalogue, **Code API** et palier affecté à un modèle actif |
| Mauvais fournisseur ou modèle au démarrage | Réglages utilisateur/projet/local et variables héritées ; vérifier `/status` |
| Catalogue absent du menu | Version du client prenant en charge la découverte, variable activée et éventuelle restriction `availableModels` |
| Échec des outils ou du raisonnement | Capacités du modèle affecté et options demandées par le client |

Cette connexion fournit l’inférence à votre client local. Elle ne crée pas de Task
ni d’Agent Galaris et ne configure pas de serveur MCP. Pour appeler directement un
modèle concret, l’ancienne base `/api/llm/anthropic` reste disponible avec son code LLM.
Pour OpenAI Codex, consultez le [guide Codex](codex.md).
