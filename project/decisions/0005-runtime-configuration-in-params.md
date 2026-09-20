# ADR 0005 — Configuration fonctionnelle dans `params`

- Statut : Accepted
- Date : 2026-07-19

## Contexte

Les réglages de langue, localisation, messagerie, voix, tâches, processus, recherche et
drivers étaient lus depuis `.env`. Chaque modification imposait un accès au serveur et un
redémarrage, les secrets étaient dispersés, et le frontend ne pouvait pas guider un
administrateur selon le bridge sélectionné.

## Décision

La table `params` est la source durable des réglages fonctionnels `DEFAULT_LANGUAGE`,
`LOCALIZATION`, `MESSENGER_*`, `VOICE_*`, `TASK_*`, `PROCESS_*`, `HARNESS_*`,
`SEARCH_DEFAULT_LANGUAGE` et `SEARCH_TIMEOUT`. Les noms en base restent identiques aux
anciens noms d’environnement.

`params_service.sync` ne consulte jamais l’environnement : une ligne absente reçoit la valeur
par défaut déclarée par l’application et une ligne existante est préservée. Le service valide
les valeurs avec `RuntimeSettings`, un modèle Pydantic qui n’est pas un `BaseSettings`, puis
met à jour son cache et la vue typée en mémoire utilisée par le runtime. Les listeners de
messagerie et de voix réconcilient leur configuration et redémarrent leurs clients lorsque sa
signature change. Le scheduler de tâches relit les limites typées aux frontières d’action et
est réveillé lors d’une mise à jour pour appliquer immédiatement un changement de capacité
aux nouvelles actions.

Le mécanisme transitoire qui importait une ancienne valeur d’environnement lors de la création
initiale d’une ligne a été retiré après son passage en production. PostgreSQL est désormais
l’unique source durable de ces réglages.

### Limites HTTP, stockage et navigateur — 17 septembre 2026

`HTTP_RATE_LIMIT_PER_MINUTE` devient une préférence système (1 000 par défaut), lue en
mémoire à chaque requête, par IP et chemin HTTP. Les routes de connexion conservent leur
limite distincte de 10 tentatives par minute. Les quotas `GALARIS_INTERNAL_MESSENGER_MAX_BYTES`
et `MEMORY_RESOURCE_MAX_BYTES` sont administrables dans les préférences Messagerie et Mémoire.

Les huit réglages d’opération du navigateur (délai, contenu, HTML, bandes de capture,
octets et viewport) rejoignent `params`. Le client transmet un instantané validé avec
chaque requête authentifiée ; le sidecar valide ses propres bornes et conserve cet
instantané dans l’opération, sans modifier les requêtes concurrentes. Un viewport par
défaut modifié concerne les nouvelles fenêtres. La page Navigateur n’est disponible que
lorsqu’au moins une connexion `browser` est active, sous les droits `PARAMS_ACCESS` ou
`PARAMS_EDIT`. Aucun historique d’appels n’est nécessaire pour configurer un Tool activé.

Pour ces dix paramètres déplacés uniquement, le dataset DbAdmin reprend une ancienne
valeur d’environnement validée si la ligne est absente. Une ligne existante, y compris
un reset explicite, est toujours préservée. Cette reprise de mise à niveau ne constitue
pas une source de configuration runtime ; les anciennes variables peuvent ensuite être
retirées. Les défauts déclarés s’appliquent en l’absence de valeur historique.

Les `WEBRTC_*` restent dans `.env`. La [décision 0118](0118-browser-session-preferences.md)
déplace ensuite la durée d’inactivité et le nombre maximal des sessions Chromium en préférences.
La [décision 0113](0113-internal-application-secrets.md) internalise
la clé de signature dans un paramètre chiffré et le token navigateur dans un volume dédié ;
`ENCRYPTION_MASTER_KEY` reste inchangée dans `.env`.
La [décision 0115](0115-internal-web-push-identity.md) internalise ensuite les clés Web Push
et déplace leur contact et délai dans les préférences du Chat.

Revue des frontières du nouveau module frontend `app/browser` : ses dépendances publiques
sont `core/api` (statut), `core/authorize` (droits), `core/user` (changement de session),
`core/navigation` et `core/util` (présentation), `core/params` (champs et sauvegarde) et
`app/connection` (notification après mutation durable). Aucun import privé ni cycle n’est
ajouté. La baseline frontend enregistre ces sept dépendances du nouveau module ; les
préférences génériques ne dépendent pas de `app/browser`.

Les secrets sont chiffrés en base et ne sont jamais relus en clair par l’API : celle-ci
expose uniquement leur état configuré, une opération de remplacement et un effacement
explicite.

Le frontend introduit une couche `front/bridge`. Chaque intégration externe y possède sa
contribution de réglages, son guide et ses traductions. La page générique de préférences les
découvre avec `import.meta.glob`.

Les valeurs nécessaires avant le démarrage de PostgreSQL ou des conteneurs restent dans
`.env` : clés racines, base de données, ports et limites d’infrastructure. Le secret interne
SearXNG est généré directement dans son fichier privé et n’est pas un paramètre applicatif.

## Conséquences

- Un administrateur configure l’instance depuis Préférences sans modifier le serveur.
- L’ajout d’un bridge conserve une ownership symétrique `back/bridge` et `front/bridge`.
- Les identifiants propres à un agent restent dans sa connexion à l’outil Messagerie ; ils
  ne deviennent pas des paramètres globaux.
- Les anciennes variables fonctionnelles présentes dans `.env` sont ignorées.

## Preuves dans le code

`core.params.consts`, `core.params.runtime_settings`, `params_service`, la page
`front/core/params`, les contributions
`front/bridge/*/settings.ts`, les superviseurs de `app.messenger`, `bridge.nextcloud` et
`bridge.matrix`, ainsi que `.env.example`.
