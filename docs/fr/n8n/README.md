<p align="right"><strong>Français</strong> · <a href="../../en/n8n/README.md">English</a></p>

# Relier n8n à Galaris

Galaris traite n8n comme un moteur de processus externe. Il découvre les workflows,
déclenche leur webhook, conserve chaque exécution dans PostgreSQL puis relit son état avec
l’API publique n8n. Le fichier [`invoice_recording.json`](invoice_recording.json) est un
gabarit minimal importable ; ce n’est pas une intégration comptable prête pour la production.

```text
Agent Galaris ──► processus Galaris ──► webhook n8n
       ▲                                      │
       └──── résultat, état et événements ◄───┘
```

## 1. Configurer les deux services

Créez une clé API dans n8n, puis ouvrez **Préférences → Processus → Connecter n8n**.
Renseignez **URL de n8n** et **Clé API n8n**, puis cliquez sur **Tester la connexion**.
Le bouton enregistre les modifications avant de vérifier l’accès à l’API et de lire la liste
des workflows. Aucun workflow n’est lancé ; les webhooks, le suivi d’exécution et les callbacks
ne sont pas validés par ce test. **Enregistrer** permet aussi de sauvegarder sans tester.

Les adresses calculées sont affichées sous les deux champs. Dans **Adresses et authentification
avancées**, vous pouvez les remplacer et générer un secret webhook. Copiez ce secret dans la
credential Header Auth de n8n avant d’enregistrer : les secrets enregistrés ne sont jamais
réaffichés. Un champ secret vide conserve sa valeur ; le bouton de suppression permet de
demander son effacement, effectif à l’enregistrement.

Les paramètres correspondants sont :

```text
PROCESS_ENGINE_DEFAULT=n8n
PROCESS_N8N_BASE_URL=https://n8n.example.net
PROCESS_N8N_API_TOKEN=<clé API n8n>
PROCESS_N8N_WEBHOOK_BASE_URL=https://n8n.example.net
PROCESS_GALARIS_BASE_URL=https://galaris.example.net
PROCESS_N8N_WEBHOOK_AUTH_HEADER=X-Galaris-Webhook-Token
PROCESS_N8N_WEBHOOK_AUTH_TOKEN=<secret entrant n8n>
PROCESS_N8N_CALLBACK_AUTH_HEADER=X-Galaris-Callback-Token
```

`PROCESS_N8N_BASE_URL` doit être visible depuis le backend Galaris.
`PROCESS_N8N_WEBHOOK_BASE_URL` est facultatif : utilisez-le lorsque l’URL publique des
webhooks diffère de l’URL de l’API. `PROCESS_GALARIS_BASE_URL` doit être visible depuis n8n
si le workflow télécharge un fichier ou envoie un callback.

Utilisez **Ouvrir les processus**, puis synchronisez les workflows dans l’administration
des processus. Aucun redémarrage n’est nécessaire. Une définition Galaris associe ensuite un
workflow, un outil et un agent ; ces
trois valeurs sont immuables après création.

## 2. Importer le gabarit

Dans n8n :

1. importez `invoice_recording.json` ;
2. créez une credential **Header Auth** dont le nom et la valeur correspondent à
   `PROCESS_N8N_WEBHOOK_AUTH_HEADER` et `PROCESS_N8N_WEBHOOK_AUTH_TOKEN` ;
3. affectez cette credential au nœud `Galaris Webhook` ;
4. remplacez `Record invoice` par les vraies opérations métier ;
5. conservez le nœud `Return execution ID` et sa réponse immédiate ;
6. activez le workflow, puis relancez la synchronisation dans Galaris.

Le webhook du gabarit répond sous cette forme :

```json
{ "executionId": "12345" }
```

Galaris accepte aussi `execution_id` ou `id`. Sans identifiant, le démarrage est considéré
comme un échec non récupérable, car Galaris ne pourrait pas suivre le run distant.

## 3. Contrat d’entrée

Le corps JSON reçu par le webhook est l’objet `input` fourni au lancement. Galaris n’ajoute
pas d’enveloppe métier :

```json
{
  "invoice_number": "INV-2026-0042",
  "amount": 120.5
}
```

Si l’appel contient des fichiers, une propriété `files` est ajoutée. Chaque entrée fournit
notamment un nom, un type MIME, une taille, une URL temporaire et une date d’expiration. Pour
télécharger un fichier, réutilisez dans la requête HTTP la valeur du header entrant nommé par
`PROCESS_N8N_CALLBACK_AUTH_HEADER`.

Galaris ajoute aussi les headers suivants :

| Header | Utilité |
|---|---|
| `Idempotency-Key` | corrélation stable d’une livraison réessayée |
| `X-Galaris-Run-Id` | UUID du run Galaris |
| `X-Galaris-Callback-Url` | URL facultative de notification d’événement |
| `PROCESS_N8N_CALLBACK_AUTH_HEADER` | token unique limité à ce run |

Le nom du dernier header est configurable ; sa valeur ne doit jamais être copiée dans un
journal ou un résultat métier.

## 4. Idempotence obligatoire

L’outbox livre les démarrages **au moins une fois**. Un timeout peut survenir après que n8n a
accepté le webhook mais avant que Galaris reçoive sa réponse. La tentative suivante porte
alors la même `Idempotency-Key`.

Avant tout effet irréversible, le workflow doit :

1. enregistrer cette clé dans un stockage partagé avec une contrainte d’unicité ;
2. réutiliser le résultat d’une exécution déjà connue ;
3. ne créer la facture, le paiement ou le message qu’après cette vérification.

Le gabarit montre le contrat, mais le stockage d’idempotence dépend de votre système métier.
Une variable statique dans un worker n8n ne suffit pas lorsque plusieurs workers ou
redémarrages sont possibles.

## 5. Résultat, suivi et callback

Sans callback, Galaris interroge périodiquement l’exécution avec l’API n8n. À la réussite, il
retient le premier objet JSON produit par le dernier nœud exécuté. Faites donc terminer le
workflow par un nœud qui émet explicitement le résultat utile.

Pour réduire le délai, un workflow peut envoyer un événement à l’URL reçue dans
`X-Galaris-Callback-Url`, avec le token entrant dans le header configuré. Exemple de corps :

```json
{
  "event_id": "12345-completed",
  "status": "success",
  "engine_run_id": "12345",
  "event_type": "workflow.completed",
  "output": { "invoice_id": "INV-2026-0042" },
  "occurred_at": "2026-07-14T10:30:00Z"
}
```

`event_id` rend les callbacks idempotents. Les statuts acceptés sont `running`, `waiting`,
`success`, `error` et `cancelled`. Pour une erreur, envoyez un objet `error` contenant au
moins `code` et `message`.

L’ancienne route `/api/processus/...` reste acceptée comme alias déprécié, mais toute
nouvelle intégration doit utiliser `/api/processes/...`.

## 6. Annulation et limites

Galaris tente `POST /api/v1/executions/{id}/stop`. Selon la version et la configuration n8n,
cette API peut ne pas être disponible. L’interface indique alors que l’exécution distante
peut continuer malgré l’annulation locale. Concevez les étapes longues pour qu’elles soient
interruptibles et idempotentes.

Les snapshots n8n sont nettoyés et bornés avant stockage. Réglez leur rétention avec les
variables `PROCESS_RETENTION_*`, sans conserver indéfiniment des données métier sensibles.

## 7. Diagnostic

| Symptôme | Vérification |
|---|---|
| aucun workflow découvert | URL API, clé `X-N8N-API-KEY`, workflow actif |
| « no webhook » | présence d’un nœud Webhook avec un chemin non vide |
| 401/403 au lancement | credential Header Auth et secret entrant |
| run sans identifiant | réponse immédiate contenant `executionId` |
| double effet métier | stockage durable de `Idempotency-Key` absent ou non atomique |
| état bloqué | accès à l’API d’exécution, callback, délai de rafraîchissement |
| fichier inaccessible | `PROCESS_GALARIS_BASE_URL`, expiration et token de run |
| annulation seulement locale | endpoint d’arrêt indisponible dans cette version n8n |

La configuration d’exploitation complète figure dans le
[guide administrateur](../admin/README.md#7-messageries-outils-et-processus). Le
contrat du moteur et les règles de contribution figurent dans le
[guide développeur](../dev/README.md).
