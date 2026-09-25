<p align="right"><strong>Français</strong> · <a href="../../en/user/profile-api.md">English</a></p>

# Appeler les modèles par profil

Dans les usages LLM, chaque profil affiche son **Code API**. Ce code est généré à
la création et reste stable si le profil est renommé. Par exemple, « Profil1 »
devient `profil1`. Les profils existants reçoivent leur code lors de la
synchronisation habituelle de la base.

Configurez votre client avec une URL de base commune à tous les profils :

| Protocole | URL de base | Catalogue |
|---|---|---|
| OpenAI | `https://galaris.example/api/profile/openai` | `GET /models` |
| Anthropic | `https://galaris.example/api/profile/anthropic` | `GET /v1/models` |

Utilisez un jeton API utilisateur ayant le droit **Accès à l'API LLM**, transmis
avec `Authorization: Bearer …` pour les deux protocoles. Pour un client Anthropic,
configurez son jeton d'authentification Bearer (`auth_token`).
`GET /api/profile/models` liste tous les usages disponibles, décisions incluses.
Chaque catalogue comprend tous les profils, y compris ceux qui ne sont pas courants.

Le journal des appels LLM affiche le nom du jeton API utilisé. Ce nom est conservé
tel qu'il était lors de l'appel, même si le jeton est ensuite renommé ou supprimé.
Un jeton sans libellé apparaît comme « Jeton API sans nom ». Les anciens appels
sans cette information conservent leur affichage précédent.

Le modèle demandé suit la forme `<code-profil>/<usage>/<niveau>` :

| Exemple | Affectation |
|---|---|
| `economique/text/ultra-low` | Palier texte ultra-économique |
| `economique/text/low` | Palier texte économique |
| `profil1/text/standard` | Palier texte standard |
| `profil1/text/high` | Palier texte haute capacité |
| `local/embedding/default` | Modèle vectoriel |
| `profil1/decision/default` | Modèle de décision |

`text/default` est un alias de `text/standard`. Un palier texte et son effort de
raisonnement sont deux réglages distincts du profil. Changer une affectation
s'applique aux prochains appels, sans changer le modèle d'un appel déjà admis.
Un usage absent ou indisponible renvoie une erreur ; il n'utilise pas un autre profil.

## Clients de développement externes

Les guides [Codex CLI](codex.md) et [Claude Code](claude-code.md) fournissent les
fichiers de configuration, le placement du jeton utilisateur et les commandes de
vérification. Ils utilisent les mêmes URL communes et des modèles tels que
`profil1/text/high`. Codex utilise Responses ; Claude Code utilise Messages.

Avec un jeton utilisateur, les références à des tâches ou modèles dans les
messages et résultats d'outils restent du contenu : elles ne changent pas le
modèle sélectionné et ne rattachent pas automatiquement l'appel à une tâche Galaris.

## Texte

```http
POST /api/profile/openai/chat/completions
Authorization: Bearer <jeton>
Content-Type: application/json

{
  "model": "profil1/text/high",
  "messages": [{"role": "user", "content": "Résume cette proposition."}],
  "stream": true
}
```

Les routes `/responses` et `/responses/compact` sont également disponibles selon
le support du fournisseur. Côté Anthropic, utilisez `/v1/messages` et
`/v1/messages/count_tokens` avec le même sélecteur de modèle.

## Embeddings

```http
POST /api/profile/openai/embeddings
Authorization: Bearer <jeton>
Content-Type: application/json

{
  "model": "local/embedding/default",
  "input": ["Premier texte", "Deuxième texte"],
  "encoding_format": "float"
}
```

L'entrée accepte un texte ou une liste de 1 à 2 048 textes non vides. Les entrées
pré-tokenisées ne sont pas prises en charge. `encoding_format` accepte `float`
ou `base64`. `dimensions` est optionnel, sous réserve du support du fournisseur.
Les vecteurs restent dans l'ordre des entrées ; l'usage est retourné lorsque le
fournisseur le fournit. L'en-tête `X-Galaris-LLM-Call-Id` référence la trace.

## Décisions

```http
POST /api/profile/decisions
Authorization: Bearer <jeton>
Content-Type: application/json

{
  "model": "profil1/decision/default",
  "prompt": "La demande concerne une facture fournisseur.",
  "questions": {
    "category": {
      "instructions": "Choisis la catégorie adaptée.",
      "criteria": {"billing": "Facturation", "other": "Autre demande"}
    }
  }
}
```

La réponse contient `answers` et indique `source: specialized` ou `source: text`.
Si la politique du profil autorise le repli et que son `text/standard` est
disponible, un échec récupérable du modèle spécialisé peut utiliser ce palier.
`fallback_reason` explique ce repli ; les probabilités ne sont jamais inventées.
Embeddings et décisions sont des appels utilisateurs autonomes.

Les routes `/api/llm/openai` et `/api/llm/anthropic` continuent d'accepter les codes
des modèles concrets.
