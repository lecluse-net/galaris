<p align="right"><strong>Français</strong> · <a href="../../en/dev/plugin-api.md">English</a></p>

# API d’administration des plugins

L’API HTTP gère les archives signées et les versions installées. Pour produire l’archive,
voir le [guide auteur avec exemples](plugin-authoring.md) et le [contrat du bundle](plugin-bundles.md).
Les schémas de requête et de réponse sont dans les [contrats du registre](../../../back/app/plugin/contracts.py)
et les routes dans le [routeur plugins](../../../back/app/plugin/router.py).

## Routes et autorisations

| Méthode et route | Autorisation | Entrée et résultat |
|---|---|---|
| `GET /api/plugins` | `PLUGIN_ACCESS` ou `PLUGIN_EDIT` | Inventaire des versions et Samples de développement. |
| `GET /api/plugins/{code}` | `PLUGIN_ACCESS` ou `PLUGIN_EDIT` | Versions et événements de l’identité demandée. |
| `POST /api/plugins/preview` | `PLUGIN_EDIT` | Multipart `file`. Vérifie l’archive et renvoie son manifeste, son empreinte, son signataire et sa compatibilité. |
| `POST /api/plugins/install` | `PLUGIN_EDIT` | Multipart `file`, `digest`, `host_identity`, `force` facultatif. Enregistre la version inactive lors de sa première installation. |
| `POST /api/plugins/{code}/{version}/{operation}` | `PLUGIN_EDIT` | `activate`, `deactivate` ou `remove` avec un corps JSON `{"host_identity":"…"}` pour une archive. Pour un Sample de développement, envoyer `{"source":"development_sample"}` pour activer ou désactiver. |
| `GET /api/plugins/catalog` | `PLUGIN_EDIT` | Versions du catalogue administré avec leurs informations d’aperçu. |
| `GET /api/plugins/catalog/{digest}` | `PLUGIN_EDIT` | Télécharge le ZIP du catalogue à l’empreinte indiquée. |
| `GET /api/plugins/{code}/templates/{template_code}` | `PLUGIN_ACCESS` ou `PLUGIN_EDIT` | Télécharge la source JSON d’un modèle actif. |

Le navigateur récupère le module frontal d’un plugin actif sur
`GET /api/plugins/assets/{digest}/{code}.mjs`. Ici `code` est celui de la contribution
documentaire. Le module public contient uniquement du code statique. L’éditeur obtient le
contenu utilisateur via la source documentaire autorisée fournie par l’hôte.

## Vérifier et installer une archive

Exemple pour une instance de qualification. Fournir une URL d’API se terminant par `/api`,
un jeton utilisateur autorisé et le chemin du ZIP via les variables indiquées. L’aperçu
vérifie l’archive. Relire le code éditeur, le signataire, les contributions et la compatibilité
avant d’effectuer les mutations suivantes.

```bash
set -euo pipefail
: "${GALARIS_API:?}" "${GALARIS_PLUGIN_TOKEN:?}" "${PLUGIN_ZIP:?}"
auth="Authorization: Bearer $GALARIS_PLUGIN_TOKEN"
preview=$(curl -fsS -H "$auth" -F "file=@$PLUGIN_ZIP" "$GALARIS_API/plugins/preview")
printf '%s\n' "$preview" | jq '{manifest, digest, signer, compatibility, host_version, can_force}'
```

Réutiliser les valeurs de cet aperçu avec les mêmes octets du ZIP. Cet exemple exige une
compatibilité normale et n’utilise pas la dérogation de développement.

```bash
printf '%s\n' "$preview" | jq -e '.compatibility == "supported"' >/dev/null
digest=$(printf '%s\n' "$preview" | jq -er '.digest')
host=$(printf '%s\n' "$preview" | jq -er '.host_identity')
code=$(printf '%s\n' "$preview" | jq -er '.manifest.code')
version=$(printf '%s\n' "$preview" | jq -er '.manifest.version')

curl -fsS -H "$auth" -F "file=@$PLUGIN_ZIP" -F "digest=$digest" \
  -F "host_identity=$host" "$GALARIS_API/plugins/install" |
  jq '{installed, selected, active}'
```

Après autorisation de l’activation, envoyer la confirmation. Qualification et production utilisent
les mêmes routes. La dérogation `force=true` est réservée à un écart de version de l’hôte
en développement si l’aperçu renvoie `can_force=true`. Elle ne modifie pas la confiance
accordée à l’éditeur.

```bash
confirmation=$(jq -cn --arg host "$host" '{host_identity: $host}')
curl -fsS -H "$auth" -H 'Content-Type: application/json' -d "$confirmation" \
  "$GALARIS_API/plugins/$code/$version/activate" | jq '{installed, selected, active}'
curl -fsS -H "$auth" "$GALARIS_API/plugins/$code" | jq '.events'
```

Pour retirer le plugin de l’instance de qualification, utiliser le même corps pour
`deactivate`, puis `remove`. Un modèle de données déjà importé ou un Service déjà copié
reste une ressource locale. Les documents et leurs révisions conservent leur source.

## Lire les résultats et reprendre après une erreur

- `digest` est le SHA-256 du ZIP. `signer` est l’empreinte de la clé de signature.
  `host_identity` identifie la construction courante, notamment pour la dérogation dev.
- Distinguer `installed`, `selected` et `active`. Une version sélectionnée peut perdre sa
  compatibilité ou son chargement effectif. Lire l’état et les événements après une réponse perdue.
- Un nouveau ZIP sous le même code et la même version est refusé (`version_conflict`).
  Après `preview_changed`, refaire l’aperçu. L’installation répétée du même bundle réutilise
  sa version. Une archive révoquée ne peut plus être activée.
- `detail` peut contenir un code métier ou le détail de validation des paramètres. Un ZIP hors
  limite donne HTTP 413. Une archive invalide ou non signée par un éditeur approuvé donne HTTP 422.
  Consulter aussi les événements du plugin en cas d’échec d’activation.

L’inventaire [MCP natif](../architecture/generated/project-map.md) et les outils montés
pour l’agent font foi. Les routes ci-dessus nécessitent une identité autorisée pour l’API HTTP.
