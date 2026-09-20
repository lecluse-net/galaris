<p align="right"><strong>Français</strong> · <a href="../../en/user/claude-code.md">English</a></p>

# Utiliser Claude Code avec Galaris

Claude Code, l’assistant de ligne de commande d’Anthropic, peut utiliser Galaris comme
fournisseur de modèles grâce à l’API compatible Anthropic exposée par Galaris sous
`/api/llm/anthropic`. Les appels transitent alors par les LLM configurés dans Galaris :
tracés, coûts et erreurs restent visibles dans **Suivi d’exécution → Appels LLM**, comme pour
tout autre canal.

Deux éléments suffisent :

- l’adresse du serveur Galaris, communiquée par votre administrateur ;
- un **jeton système Hermès** créé dans l’administration, ou un **compte utilisateur disposant
  du droit d’accès à l’API LLM**.

Ne recopiez jamais un jeton dans une conversation ou un canal partagé. Il se configure dans
l’environnement prévu à cet effet, comme les autres secrets.

## Première connexion

Dans le fichier de réglages de Claude Code (`~/.claude/settings.json`), déclarez l’adresse et
le jeton dans le bloc `env` :

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://<votre-serveur>/api/llm/anthropic",
    "ANTHROPIC_AUTH_TOKEN": "<jeton Hermès ou identifiant de connexion>"
  }
}
```

Le bloc `env` de ce fichier a priorité sur les variables du shell : c’est l’endroit fiable pour
configurer la même machine durablement. Le jeton est envoyé en en-tête `Authorization: Bearer` ;
les clients Anthropic qui passent par `x-api-key` (SDK, autres outils) sont acceptés de la même
manière.

## Choisir le modèle : la correspondance Opus, Sonnet, Fable…

Chaque profil Galaris configure quatre niveaux texte. Le gateway accepte leurs noms canoniques et
les familles Claude correspondantes : Haiku → `ultra-low`, Sonnet → `low`, Opus → `standard` et
Fable → `high`. Un code de LLM Galaris configuré garde toujours priorité sur ces alias.

| Usage | Réglage |
|---|---|
| Essayer ponctuellement | `claude --model <code Galaris ou niveau>` |
| Fixer pour un dépôt | `.claude/settings.json` → `"model": "<code Galaris ou niveau>"` |
| Fixer pour la machine | `~/.claude/settings.json` → `"model": "<code Galaris ou niveau>"` ou `ANTHROPIC_MODEL` |
| Nommer quatre niveaux dans le sélecteur `/model` | variables `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL`, `ANTHROPIC_DEFAULT_HAIKU_MODEL`, `ANTHROPIC_DEFAULT_FABLE_MODEL` (avec `_NAME` et `_DESCRIPTION` pour l’affichage) |

Les quatre variables de niveau constituent exactement « l’équivalent d’Opus, de Fable… » : le
menu `/model` de Claude Code affiche ces entrées nommées, et choisir l’une d’elles envoie l’alias
que Galaris résout dans le profil effectif. Le choix `/model` reste limité à la session ; « set as
default » l’enregistre dans les réglages utilisateur.

### Deux précisions pratiques

- Un code Galaris étant inconnu de Claude Code, celui-ci suppose une fenêtre de contexte de
  200 000 jetons. Indiquez la vraie valeur du LLM (champ *contexte* de sa fiche) avec
  `CLAUDE_CODE_MAX_CONTEXT_TOKENS`, ou ajoutez `[1m]` au nom dans `--model` pour un million —
  ce suffixe n’est jamais envoyé à Galaris.
- Le sélecteur `/model` n’accepte que les noms reconnus. Pour un code Galaris, passez par
  `--model`, les variables d’environnement ou les réglages, pas par le menu. Avec
  `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` (et le trafic non essentiel autorisé),
  Claude Code peut aussi récupérer la liste des codes depuis `GET /v1/models` et les proposer
  dans le menu comme options supplémentaires.

## Ce que Galaris fait à chaque appel

Chaque appel, en flux continu ou non, est traduit vers les fournisseurs configurés, tracé et
facturé comme un appel ordinaire. Les erreurs remontent dans le format attendu par Claude
Code. Si un en-tête de corrélation est fourni (par exemple `X-Galaris-Task-Id`), l’appel est
rattaché à la tâche indiquée ; sinon Galaris corrèle comme pour ses autres surfaces.

Un refus d’authentification ou un privilège manquant affiche une erreur explicite dans Claude
Code : vérifiez alors le jeton et le droit d’accès à l’API LLM.
