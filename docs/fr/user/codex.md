<p align="right"><strong>Français</strong> · <a href="../../en/user/codex.md">English</a></p>

# Connecter Codex à Galaris

Un Codex CLI installé sur votre poste peut utiliser Galaris comme fournisseur de
modèles via `https://galaris.example/api/profile/openai`. Tous les profils partagent
cette URL : `profil1/text/high` sélectionne le palier `high` du profil dont le
**Code API** est `profil1`. L’identifiant interne du profil n’intervient pas.

## Préparer la connexion

Créez un **jeton API utilisateur** dans **Jetons API** avec un compte disposant du
privilège **Accès à l’API LLM** (`LLM_API_ACCESS`). Les jetons système des runtimes
Galaris ne sont pas destinés à cette connexion externe.

Le palier choisi doit pointer vers un modèle actif dont le fournisseur prend en
charge **Responses**, le streaming et les appels d’outils attendus par Codex.
La présence d’un modèle dans le catalogue ne garantit pas cette compatibilité :
le support de Chat Completions seul ne suffit pas. La compaction distante nécessite
aussi le support de `/responses/compact` par le fournisseur.

Remplacez `https://galaris.example` et `profil1` par votre serveur et le **Code API**
affiché dans les usages LLM. Voir le [contrat des modèles par profil](profile-api.md).

## Configuration `~/.codex/config.toml`

Dans **Jetons API** (`/user/tokens`), cliquez sur **Configurer Codex / Claude Code**,
choisissez un profil puis l’onglet **Codex**. La configuration utilise l’adresse de
votre serveur et se copie directement ; le jeton reste à compléter séparément.

Fusionnez les clés suivantes avec votre configuration utilisateur existante.
Placez les deux premières clés à la racine du fichier, avant les tables TOML :

```toml
model = "profil1/text/high"
model_provider = "galaris"

[model_providers.galaris]
name = "Galaris"
base_url = "https://galaris.example/api/profile/openai"
env_key = "GALARIS_API_TOKEN"
wire_api = "responses"
requires_openai_auth = false
supports_websockets = false
```

La base ne contient ni `/v1` ni `/responses` supplémentaire. Codex ajoute la route
Responses ; Galaris utilise ici HTTP et SSE pour le streaming. `env_key` désigne la
variable contenant le jeton envoyé en Bearer. Cette configuration utilise le
mécanisme officiel des [fournisseurs personnalisés Codex](https://developers.openai.com/codex/config-advanced/),
avec les clés de la [référence de configuration](https://developers.openai.com/codex/config-reference/).
Utilisez le fichier utilisateur pour déclarer le fournisseur.

Dans le terminal qui lancera Codex :

```bash
export GALARIS_API_TOKEN='<jeton-api-utilisateur-galaris>'
```

Le jeton reste hors du fichier TOML et du dépôt. Pour une utilisation régulière,
fournissez cette variable par votre environnement local ou votre gestionnaire de
secrets. Un client lancé depuis une autre application doit aussi recevoir la variable.

## Vérifier et lancer Codex

Vérifiez d’abord que le catalogue contient le sélecteur souhaité :

```bash
curl --fail-with-body 'https://galaris.example/api/profile/openai/models' \
  -H "Authorization: Bearer $GALARIS_API_TOKEN"
```

Puis lancez une session depuis votre répertoire de travail :

```bash
codex --model profil1/text/high
```

Demandez une réponse courte pour vérifier l’inférence et sa trace dans
**Suivi d’exécution → Appels LLM**. Pour changer de profil ou de palier, changez
seulement `model` ou l’argument `--model`, par exemple `profil1/text/standard`.
Le code du profil reste stable lorsqu’on renomme son libellé.

Pour conserver votre fournisseur habituel par défaut, gardez seulement la table
`[model_providers.galaris]` dans votre configuration et sélectionnez Galaris au lancement :

```bash
codex -c 'model_provider="galaris"' --model profil1/text/high
```

Les paliers Galaris ne sont pas des niveaux de raisonnement Codex : cet exemple
ne force pas `model_reasoning_effort`. `embedding/default` et `decision/default`
ne sont pas des modèles de conversation pour Codex ; leurs routes figurent dans
le [guide API](profile-api.md).

## Résoudre les erreurs

| Symptôme | Vérification |
|---|---|
| Jeton absent, `401` ou `403` | Variable `GALARIS_API_TOKEN` accessible au processus, jeton valide et privilège `LLM_API_ACCESS` |
| Modèle inconnu ou indisponible | Sélecteur exact du catalogue et palier affecté à un modèle actif |
| Appels envoyés au fournisseur habituel | `model_provider = "galaris"` et éventuelles surcharges de configuration |
| Échec Responses, outils ou compaction | Compatibilité du fournisseur affecté au palier ; conserver `wire_api = "responses"` et choisir une affectation compatible |

Cette connexion fournit les modèles à votre Codex local. Elle ne crée pas de Task
ni d’Agent Galaris et ne configure pas de serveur MCP. La base `/api/llm/openai`
reste utilisable pour appeler un modèle concret par son code LLM. Pour Claude Code,
consultez le [guide Claude Code](claude-code.md).
