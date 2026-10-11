<p align="right"><strong>Français</strong> · <a href="../../en/dev/process-engines.md">English</a></p>

# Intégrer un moteur de processus externe

Ce guide décrit les points d'extension actuels pour connecter un logiciel tiers à
`app.process` : conversion, calcul, export ou autre traitement métier suivi. Il ne crée
aucun moteur supplémentaire. Le contrat Python et les tests du dépôt restent l'autorité ;
les limitations ci-dessous font partie de l'intégration actuelle.

## 1. Choisir le parcours

| Besoin | Parcours |
|---|---|
| Appeler un logiciel depuis un workflow n8n existant | Utiliser le [guide n8n](../n8n/README.md) ; aucun nouveau moteur Galaris n'est nécessaire. |
| Exposer directement les opérations et jobs d'un logiciel | Ajouter un `bridge.<logiciel>` qui implémente `ProcessEngine`. |
| Obtenir immédiatement une sortie sans suivi durable métier | Exposer un outil MCP dans le domaine ou bridge concerné. |
| Effectuer une opération technique appartenant déjà à un domaine | Garder son état dans ce domaine ; la durée seule ne justifie pas un Process. |

Le logiciel n'a pas besoin de posséder des workflows. Une opération stable comme
`example:convert` peut servir de définition. Pour une intégration durable, il doit permettre
de retrouver l'issue d'un job après une interruption, par lecture distante ou notification
rejouable. Une réponse HTTP perdue ne prouve pas que le traitement n'a pas commencé.

## 2. Responsabilités et identités

`app.process` possède les définitions, runs, événements, jobs de démarrage, transitions,
attentes de Tasks et rétention. Le bridge possède la traduction du protocole externe,
l'authentification distante, la validation métier et la normalisation des résultats.
Il ne crée pas un second état canonique et ne modifie pas directement les tables Process.

| Identifiant | Contrat actuel |
|---|---|
| `engine.code` / `Tool.code` | Même code stable, par exemple `example` ; le registry sélectionne ce moteur. |
| `engine_process_id` / `workflow_id` | Opération externe ; `workflow_id` est le nom public utilisé au lancement et dans les URI. |
| `ProcessDefinition.id` | Identifiant SQL interne, utilisé par le CRUD administratif. |
| `run.id` | UUID Galaris canonique de l'exécution. |
| `run.engine_run_id` | Référence externe ; unique pour un moteur parmi les runs enregistrés. |
| `run.correlation_id` | Identité stable de livraison, à transmettre au logiciel pour dédupliquer ses effets. |
| `run.callback_token` | Secret propre au run pour ses callbacks et téléchargements ; jamais une sortie métier. |

La base impose l'unicité d'une définition active par `(tool_id, engine_process_id)`.
Les appels personnels résolvent pourtant `workflow_id` dans le périmètre de l'agent sans
paramètre moteur. Choisir des identifiants publics distincts entre moteurs, idéalement
avec un préfixe, évite une résolution ambiguë. Une même définition active porte une seule
affectation `agent_id`, éventuellement vide ; elle n'est alors pas lançable par un agent.

Sources : [contrat du moteur](../../../back/app/process/engine.py),
[schémas](../../../back/app/process/schemas.py),
[modèles](../../../back/app/process/models.py) et
[flux durable](../architecture/flows/process.md).

## 3. Implémenter le contrat

Un `ProcessEngine` déclare `code`, `supports_cancel` et `cancel_mode`
(`supported`, `best_effort` ou `unsupported`), puis ces méthodes asynchrones :

| Méthode | Entrée / sortie | Responsabilité |
|---|---|---|
| `health()` | `ProcessEngineHealth` | Vérifier accès et authentification sans lancer de traitement ; décrire l'annulation réellement disponible. |
| `sync_definitions()` | Liste de `EngineProcessDefinition` | Retourner les opérations découvertes ou un catalogue statique avec identifiant, libellé, description et état actif. |
| `start_run(operation, run, payload)` | `EngineStartResult` | Soumettre l'entrée validée et les fichiers, retourner l'acceptation et une référence récupérable. |
| `get_run(run)` | `EngineRunSnapshot` | Observer le job exact ; normaliser statut, sortie, erreur et diagnostic utile. |
| `cancel_run(run)` | `EngineRunSnapshot` | Demander l'arrêt ; distinguer demande en cours et terminal confirmé. |

`ProcessStartPayload` contient `input`, `files` et `launch_snapshot`.
Ce dernier est un checkpoint Galaris, pas une enveloppe à transmettre intégralement au
logiciel : il peut contenir des métadonnées internes d'autorisation.
`EngineRunReference` fournit seulement le UUID, la référence externe, la corrélation et
le token. Le bridge reconstruit le transport à partir de sa configuration serveur.

Une sortie est un objet JSON, éventuellement avec des URI de résultats.
`EngineError` porte `code`, `message` et un `node_name` facultatif.
`raw` est un diagnostic borné, assaini avant stockage ; ne jamais y recopier tokens,
corps HTTP sensibles ou fichiers binaires. Les codes d'erreur doivent rester stables.

Le contrat optionnel `IntegratedProcessEngine` ajoute `prepare_input(agent_id,
workflow_id, input_data)`, `start_timeout_seconds` et `refresh_timeout_seconds`.
Il est utilisé par Multimedia et Lab pour préparer des opérations intégrées.
Ce n'est pas une interface dédiée à n8n ni une obligation pour un bridge externe.
Son activation change aussi la déduplication et le traitement des autorisations différées ;
ne pas l'implémenter uniquement pour changer un timeout. Pour les moteurs ordinaires,
les délais viennent de `PROCESS_START_TIMEOUT_SECONDS` et
`PROCESS_REFRESH_TIMEOUT_SECONDS`.

## 4. Exemple minimal indépendant de n8n

L'exemple suivant implémente l'adaptateur d'un **service fictif**. Ses routes ne sont pas
des endpoints Galaris ni un protocole standard à attendre d'un logiciel tiers :

| Route du service fictif | Réponse attendue |
|---|---|
| `GET /health` | HTTP 2xx sans effet métier. |
| `POST /jobs` | Accepte `operation`, `input`, `files`, `callback` ; déduplique atomiquement `Idempotency-Key` et renvoie le même job. |
| `GET /jobs/{reference}` | Retourne le job, y compris après redémarrage. |
| `POST /jobs/{reference}/cancel` | Demande idempotente d'arrêt et retourne l'état observé. |

Un job est un objet comme `{"external_id": "job-42", "operation": "convert",
"state": "processing"}`. Une réussite ajoute par exemple
`"output": {"result_uri": "https://processor.example/results/report.pdf"}`.
Cette URI doit être durable et lisible avec les droits requis ; un chemin disque distant
n'est pas une ressource Galaris. Pour publier dans un provider Galaris, utiliser
`app.file_share` et son contexte autorisé.

Placer l'adaptateur dans `back/bridge/example/engine.py`. Les imports sont les exports
publics actuels ; `Any` reste limité au JSON métier dynamique. La configuration et les
messages de cet exemple doivent être intégrés aux paramètres et catalogues i18n avant
d'en faire un bridge livré. Le paramètre `transport` permet les vérifications avec
`httpx.MockTransport`, sans contacter un service réel.

```python
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.process import (
    EngineError, EngineProcessDefinition, EngineRunReference,
    EngineRunSnapshot, EngineStartResult, ProcessEngineError,
    ProcessEngineHealth, ProcessStartPayload,
)
from app.process.schemas import ProcessStatus


class ConversionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["pdf"]


class RemoteJob(BaseModel):
    external_id: str = Field(min_length=1)
    operation: Literal["convert"]
    state: str
    output: dict[str, Any] | None = None


class ExampleProcessEngine:
    code = "example"
    supports_cancel = True
    cancel_mode = "supported"

    def __init__(
        self, base_url: str, api_token: str, callback_base_url: str,
        *, transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.callback_base_url = callback_base_url.rstrip("/")
        self.transport = transport

    async def _request(
        self, method: str, path: str, *,
        body: dict[str, object] | None = None,
        idempotency_key: str | None = None,
    ) -> bytes:
        headers = {"Authorization": f"Bearer {self.api_token}"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=4.0,
                follow_redirects=False, transport=self.transport,
            ) as client:
                async with client.stream(
                    method, path, json=body, headers=headers,
                ) as response:
                    if not 200 <= response.status_code < 300:
                        status = response.status_code
                        raise ProcessEngineError(
                            "unauthorized" if status in {401, 403} else "remote_http_error",
                            f"External service HTTP {status}",
                            retryable=status == 429 or status >= 500,
                        )
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(data) + len(chunk) > 64_000:
                            raise ProcessEngineError("response_too_large", "Response exceeds 64 kB")
                        data.extend(chunk)
                    return bytes(data)
        except httpx.HTTPError as exc:
            raise ProcessEngineError(
                "engine_unreachable", "External service unavailable", retryable=True,
            ) from exc

    @staticmethod
    def _job(data: bytes) -> RemoteJob:
        try:
            return RemoteJob.model_validate_json(data)
        except ValidationError as exc:
            raise ProcessEngineError("invalid_response", "Invalid job response") from exc

    @staticmethod
    def _snapshot(job: RemoteJob) -> EngineRunSnapshot:
        statuses: dict[str, ProcessStatus] = {
            "pending": "queued", "processing": "running", "paused": "waiting",
            "done": "success", "failed": "error", "stopped": "cancelled",
        }
        status = statuses.get(job.state, "unknown")
        return EngineRunSnapshot(
            status=status, engine_run_id=job.external_id,
            output=job.output if status == "success" else None,
            error=EngineError(code="remote_failed", message="External processing failed")
                if status == "error" else None,
            raw={"workflowId": f"example:{job.operation}"},
        )

    async def health(self) -> ProcessEngineHealth:
        try:
            await self._request("GET", "/health")
        except ProcessEngineError as exc:
            return ProcessEngineHealth(
                tool_code=self.code, status="error",
                reachable=exc.code != "engine_unreachable",
                authenticated=exc.code != "unauthorized",
                supports_cancel=True, cancel_mode="supported",
                message=exc.message, checked_at=datetime.now(timezone.utc),
            )
        return ProcessEngineHealth(
            tool_code=self.code, status="healthy", reachable=True, authenticated=True,
            supports_cancel=True, cancel_mode="supported",
            message="External service available", checked_at=datetime.now(timezone.utc),
        )

    async def sync_definitions(self) -> list[EngineProcessDefinition]:
        return [EngineProcessDefinition(
            engine_process_id="example:convert", label="Convert a file",
            description="Input: format=pdf; files: one text/plain source URI. Output: result_uri.",
            active=True,
        )]

    async def start_run(
        self, engine_process_id: str, run: EngineRunReference,
        payload: ProcessStartPayload,
    ) -> EngineStartResult:
        if engine_process_id != "example:convert":
            raise ProcessEngineError("invalid_operation", "Unknown conversion operation")
        try:
            validated = ConversionInput.model_validate(payload.input)
        except ValidationError as exc:
            raise ProcessEngineError("invalid_input", "Expected format=pdf") from exc
        if len(payload.files) != 1 or payload.files[0].content_type != "text/plain":
            raise ProcessEngineError("invalid_files", "Expected one text/plain source file")
        body: dict[str, object] = {
            "operation": "convert", "input": validated.model_dump(),
            "files": [item.model_dump(mode="json", exclude={"uri", "runtime", "task_id"})
                for item in payload.files],
            "callback": {
                "url": f"{self.callback_base_url}/api/processes/runs/{run.id}/events",
                "headers": {"Authorization": f"Bearer {run.callback_token}"},
            },
        }
        job = self._job(await self._request(
            "POST", "/jobs", body=body, idempotency_key=run.correlation_id,
        ))
        return EngineStartResult(accepted=True, engine_run_id=job.external_id)

    async def get_run(self, run: EngineRunReference) -> EngineRunSnapshot:
        if not run.engine_run_id:
            return EngineRunSnapshot(status="unknown")
        job = self._job(await self._request(
            "GET", f"/jobs/{quote(run.engine_run_id, safe='')}",
        ))
        return self._snapshot(job)

    async def cancel_run(self, run: EngineRunReference) -> EngineRunSnapshot:
        if not run.engine_run_id:
            raise ProcessEngineError("cancel_unsupported", "Remote job identity is unknown")
        snapshot = self._snapshot(self._job(await self._request(
            "POST", f"/jobs/{quote(run.engine_run_id, safe='')}/cancel",
            idempotency_key=f"{run.correlation_id}:cancel",
        )))
        if snapshot.status not in {"success", "error", "cancelled"}:
            return EngineRunSnapshot(status="cancelling", engine_run_id=run.engine_run_id)
        return snapshot
```

L'exemple accepte uniquement `format=pdf` et une source `text/plain` avant le POST.
Pour une vraie conversion, adapter cette validation aux formats réellement pris en charge.
Les DTO du service réel, ses limites et ses garanties d'idempotence remplacent ceux
de l'exemple. Ne pas annoncer `cancel_mode="supported"` si l'arrêt physique n'est
pas confirmé par ce service.

## 5. Enregistrer, configurer et affecter

1. Ajouter le package bridge à `back/modules.py`. Son `__init__.py` enregistre une
   instance configurée avec `registry.register(engine)`, comme
   [le bridge n8n](../../../back/bridge/n8n/__init__.py). Le chargement ne doit pas
   effectuer d'appel réseau ni créer de job. Tous les moteurs doivent être enregistrés
   avant `register_scheduler_jobs()` au bootstrap.
2. Fournir les URL et secrets côté serveur. Utiliser les paramètres chiffrés existants,
   avec déclaration et interface de configuration adaptées. Les noms `base_url`,
   `api_token` et `callback_base_url` de l'exemple sont des arguments Python, pas de
   nouveaux réglages déjà disponibles. Ne pas placer un secret dans la définition,
   `input`, le snapshot de lancement ou une description visible au modèle.
3. Créer un Tool dont `code` correspond au moteur. Pour une contribution livrée,
   déclarer la donnée avec le mécanisme DbAdmin du propriétaire ; pour une installation,
   utiliser le CRUD Tool autorisé. Une ligne Tool ne charge pas le code du moteur,
   et l'enregistrement Python ne crée pas cette ligne.
4. Avec les droits d'administration, lire `GET /api/processes/tools`, vérifier
   `GET /api/processes/tools/example/health`, puis appeler
   `POST /api/processes/definitions/sync?tool_code=example`.
   La « synchronisation » retourne le catalogue externe ; elle ne crée ni n'affecte
   automatiquement de `ProcessDefinition`.
5. Créer explicitement la définition par `POST /api/processes/definitions` :
   `{"tool_id": 123, "engine_process_id": "example:convert", "label": "Convert",
   "description": "Input format; one source file; output result_uri.", "agent_id": 7}`.
   Ces nombres sont synthétiques : prendre le Tool et l'agent réels autorisés.
   Le CRUD utilise `PROCESS_ADMIN` et le périmètre de gestion ; la découverte HTTP
   globale requiert également le périmètre global.
6. L'agent utilise `process_list`, `process_get`, puis `process_start` du package
   socle `galaris`. Ces fonctions et l'affectation doivent être autorisées.
   Le contrôleur conversationnel utilise `conversation_process_start`.
   Le package optionnel `process_admin`, inactif par défaut, fournit les équivalents
   administratifs ; préciser `tool_code="example"` car plusieurs valeurs par défaut
   restent `n8n`.
7. Régénérer et vérifier la documentation et l'architecture. En développement,
   `make sync-db` applique les données déclarées. L'ajout d'un module ou de sa
   configuration d'activation nécessite son chargement au bootstrap ; le simple hot
   reload d'une méthode déjà chargée ne remplace pas cette étape.

Voir le [guide développeur](README.md) et le [guide DbAdmin](dbadmin.md).

Dans `__init__.py`, après avoir résolu et validé les trois valeurs côté serveur :

```python
from app.process import registry
from .engine import ExampleProcessEngine

registry.register(ExampleProcessEngine(base_url, api_token, callback_base_url))
```

Les endpoints humains suivent le RBAC et le périmètre de gestion ; les outils personnels
filtrent l'agent appelant. La présence d'un moteur ne donne pas accès à toutes ses opérations.
L'affectation, le Tool et l'identifiant de la définition sont modifiables par le CRUD
autorisé, avec validation d'unicité ; ne pas les changer pendant une exécution en cours.

## 6. Lancement, reprise et erreurs réseau

L'admission écrit un run `queued` et un `ProcessStartJob` avant tout effet externe.
Elle déduplique par clé explicite ou, en son absence, par empreinte d'entrée dans la
fenêtre `PROCESS_IDEMPOTENCY_WINDOW_SECONDS` (300 secondes par défaut).
Une clé explicite est unique par agent et définition. La corrélation de livraison reste
la même lors de la reprise du job.

Les workers prennent des leases récupérables avec verrous SQL et traitent jusqu'à quatre
démarrages concurrents par moteur, en répartissant les agents. La persistance du job
survit au redémarrage ; elle ne garantit pas qu'un POST externe n'a été exécuté qu'une fois.
Le service distant doit dédupliquer **avant** tout effet et conserver sa référence et son
résultat. Un registre d'idempotence en mémoire ne suffit pas.

Lever `ProcessEngineError(code, message, retryable=...)` pour une erreur attendue.
Classer les erreurs de validation/authentification comme définitives et les indisponibilités
transitoires selon le protocole. Les démarrages récupérables utilisent un backoff borné
et `PROCESS_START_MAX_RETRIES`. Un effet soumis sous autorisation différée dont la réponse
est perdue peut être classé `unknown` avec `authorization_outcome_unknown`, au lieu
d'être rejoué automatiquement : il faut réconcilier l'issue.

Un échec d'observation ne prouve pas l'échec du job distant. Le polling conserve ses
possibilités de reprise, ajoute un diagnostic et peut passer à `unknown` après dégradation.
`get_run` doit être une lecture répétable ; si une observation déclenche de nouveaux
effets, utiliser les protections d'autorisation et les checkpoints durables appropriés.
Les délais, limites de réponse et diagnostics doivent être bornés dans le client du bridge.

## 7. Statuts, callbacks et annulation

| Statut Galaris | Sens |
|---|---|
| `queued` | Admis ; démarrage ou exécution encore en attente. |
| `running` | Traitement en cours. |
| `waiting` | Job distant en attente d'un événement ou d'une dépendance. |
| `unknown` | Issue ou observation incertaine ; pas un terminal. |
| `cancelling` | Arrêt demandé ; confirmation encore attendue. |
| `success`, `error`, `cancelled` | Terminaux ; sortie et état ne sont pas remplacés par une observation tardive. |

La matrice effective figure dans [les machines d'état](../architecture/state-machines.md)
et `process_service.TRANSITIONS`. Un callback peut terminer le run avant la réponse du
POST initial ; le worker conserve ce terminal. Le polling récupère son état sous verrou
après l'appel distant. La fin résout l'éventuelle Task d'attente, avec reprise idempotente
de cette résolution.

Un service peut envoyer `POST /api/processes/runs/{UUID}/events` avec
`Authorization: Bearer <token du run>`. Le header configuré
`PROCESS_N8N_CALLBACK_AUTH_HEADER` est aussi accepté, malgré son nom spécifique à n8n ;
s'il est présent, il est prioritaire sur Bearer. L'adaptateur décide comment transmettre
l'URL et le token au logiciel ; il n'existe pas d'enveloppe réseau universelle imposée
par `ProcessEngine`.

```json
{
  "event_id": "job-42-completed",
  "status": "success",
  "engine_run_id": "job-42",
  "event_type": "conversion.completed",
  "output": {"result_uri": "https://processor.example/results/report.pdf"},
  "occurred_at": "2026-10-01T10:00:00Z"
}
```

Les callbacks acceptent uniquement `running`, `waiting`, `success`, `error` et
`cancelled`, même si les snapshots de polling ont davantage de statuts.
Pour une erreur, fournir `error: {"code": "conversion_failed", "message": "..."}`.
Conserver le même `event_id` pour la redelivery du même événement : l'unicité est par run.
Les UUID et références de job ne remplacent pas le token.
L'ancien préfixe `/api/processus` est un alias déprécié.

Une annulation d'un job encore non soumis peut être locale. Sinon, le moteur reçoit la
demande ; une acceptation HTTP d'arrêt n'est pas une preuve d'arrêt physique.
Si l'annulation est indisponible, le socle ordinaire peut marquer le run localement
`cancelled` avec `remote_may_continue=true`. Les opérations intégrées peuvent refuser
cette annulation et conserver le suivi. Un remplacement de Task reste bloqué tant que
l'arrêt distant reste incertain. Voir [le flux Process](../architecture/flows/process.md).

## 8. Fichiers et provenance

Les entrées utilisent `files=[{"uri": "https://source.example/report.txt",
"description": "Source to convert"}]`. Une URI peut aussi provenir d'un provider
Galaris autorisé ; elle n'accorde pas de droit par elle-même.
Le snapshot conserve l'URI et le nom de la source. Le bridge reçoit des
`ProcessFileRef` avec nom, type, taille, expiration et `download_url`.

Le logiciel télécharge cette URL avec le token du run dans Bearer ou dans le header
configuré. L'accès est limité au fichier, au run et à son expiration, et réutilise le
contexte autorisé de l'agent. La source est matérialisée à la demande dans un temporaire
borné, supprimé après la réponse. La limite Process actuelle est de 512 Mio par fichier ;
le TTL vaut 3 600 secondes par défaut et ne se renouvelle pas automatiquement à chaque
tentative. Ne pas transmettre de chemin hôte ou de credentials provider.

Les sorties volumineuses restent dans un provider adapté ; la sortie JSON conserve leurs
URI et métadonnées, sous les limites du sanitizer. Voir
[les médias et ressources](../architecture/flows/media-resources.md).
Si le logiciel appelle les gateways LLM ou Agent de Galaris, transmettre la corrélation
du ProcessRun selon [le flux Process](../architecture/flows/process.md) et les droits
du token Agent : le token de callback ne donne pas accès à ces gateways.

Une exécution commencée ailleurs peut être rattachée avec
`POST /api/processes/workflows/{workflow_id}/runs/{engine_run_id}/sync`.
Le moteur doit alors pouvoir lire la référence externe sans checkpoint local préalable.
Le service vérifie `raw.workflowId` lorsqu'il est fourni ; le bridge doit également
garantir que le job appartient à l'opération et au périmètre attendus.

## 9. Vérifier l'intégration

| Garantie à vérifier | Scénario |
|---|---|
| Isolation | Agent affecté autorisé, autre agent refusé ; découverte et lecture sans fuite. |
| Validation avant effet | Entrée, fichier ou opération invalide : aucun POST distant. |
| Déduplication distante | Même corrélation, soumissions concurrentes et réponse perdue : un seul effet métier. |
| Reprise | Redémarrer le worker après soumission, avant reçu local et après terminal avant reprise de Task. |
| Ordre des événements | Callback terminal avant réponse de départ ; redelivery ; observation tardive sans mutation du terminal. |
| Observation dégradée | Timeout, 429, réponse invalide, panne prolongée puis retour : aucune réussite ni erreur métier inventée. |
| Annulation | Job non soumis, demande distante en attente, arrêt confirmé, API indisponible et fin concurrente. |
| Fichiers | URI autorisée, téléchargement avec token, mauvais token/run, expiration, limite et nettoyage. |
| Exploitation | Santé sans lancement, journal sans secret, références corrélables et résultat accessible. |

Remplacer la frontière réseau dans les tests du bridge avec `httpx.MockTransport`.
Utiliser les tests DB de Process pour les workflows durables, puis exercer un traitement
synthétique complet avec le logiciel réel : fichier source, sortie, reprise et annulation.
Un test de santé ou un transport simulé ne valide pas cette intégration réelle.

```bash
make tests ARGS='bridge/n8n/tests app/process/tests'
make typecheck
make architecture-check
APP_ENV=dev make docs-prepare
git diff --check
```

La commande de tests ci-dessus vérifie les références existantes ; ajouter les tests du
nouveau bridge au ciblage. Consulter
[le catalogue de tests fonctionnels](functional-tests.md) avant de dupliquer une garantie.
Avant publication sans CI, exécuter `make validate` sur les sources finales.
`APP_ENV=dev make docs-update` propage la documentation préparée à la recherche partagée
de développement ; le déploiement normal `make update` indexe les sources préparées.

## 10. Limites actuelles et points de référence

- Le registry accepte plusieurs moteurs et le scheduler crée des jobs par moteur.
  Le réglage du moteur par défaut reste limité à `n8n` ; un nouveau moteur est choisi
  par le Tool de sa définition, pas en changeant ce réglage.
- Il n'existe pas de connexion/instance de moteur dans `ProcessDefinition`.
  Plusieurs installations du même logiciel nécessitent une stratégie explicite dans
  le bridge et des identités sans collision ; ce n'est pas un réglage multi-instance prêt à l'emploi.
- Le catalogue ne publie pas de schémas d'entrée/sortie par définition. Documenter
  l'entrée dans la description et la valider dans l'adaptateur.
- La découverte ne constitue pas une autorisation ni un import automatique.
  Les définitions supprimées ne sont plus lançables ; leurs runs historiques restent suivis.
- Le bridge n8n choisit le premier nœud webhook et attend une référence d'exécution ;
  ces contraintes sont celles de ce bridge, pas celles de `ProcessEngine`.

Références concrètes :
[adaptateur n8n](../../../back/bridge/n8n/engine.py),
[moteur Multimedia](../../../back/app/multimedia/engine.py),
[moteur Lab](../../../back/app/lab/engine.py),
[workers](../../../back/app/process/workers.py),
[service Process](../../../back/app/process/process_service.py),
[tests de reprise](../../../back/app/process/tests/test_recovery.py) et
[tests de crash](../../../back/app/process/tests/test_crash_recovery.py).
