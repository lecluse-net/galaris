<p align="right"><strong>Français</strong> · <a href="../../en/components/hermes.md">English</a></p>

# Bridge Hermès backend

Ce package contient uniquement les spécificités Hermès : client des sessions et runs, driver
`app.agent`, génération de la configuration, intégration LLM/MCP/mémoire/voix et
transport des fichiers propres au runtime.

Le MemoryProvider embarqué appelle les endpoints privés `/memory/provider/*`, également possédés
par ce bridge. Le brief éphémère déjà classé par `app.memory` est lié au run Hermès courant dans
le processus backend ; les écritures explicites repassent par la façade gouvernée de `app.memory`.

La gestion hôte des répertoires, conteneurs Docker Compose et fichiers appartient au service
générique [`harness_manager`](harness-manager.md). Chaque agent Hermès consomme
une instance nommée comme son code, avec son propre Compose, son volume et son conteneur
`<code>-agent`. Le manager peut être partagé entre plusieurs harnais, mais les runtimes ne le
sont jamais.

## Gestion des instances

Le package génère le Compose et tous les fichiers Hermès, puis appelle le harness manager
générique pour créer, démarrer, arrêter, mettre à jour et supprimer l'instance. Les données sont
projetées dans `BASE_DIR/<code>/data` côté manager et montées dans `/opt/data` du seul conteneur de
cet agent.

L'exécution passe par les API structurées Hermès (`/api/sessions`, `/v1/runs` et arrêt du run).
Le harness manager ne reçoit jamais une commande Hermès, un payload Kanban ou une décision
d'exécution agentique.

## Configuration du harness manager

Configurez l’URL du manager, l’URL API facultative et le secret partagé dans
**Préférences → Harnais → Harnais managés → Configurer le Harness Manager**. Ces Params sont communs à tous les harnais ;
le secret est chiffré. Aucune variable manager n’est nécessaire dans le `.env` de Galaris.
L’IHM prépare aussi le `.env` du service hôte, à copier sur la machine locale ou distante.
Voir le [guide du manager](harness-manager.md) pour l’installation et la reprise de l’existant.

Le fichier `compose.yaml` est configuré dans **Préférences → Harnais**, pour tous les
providers conteneurisés. Aucun réseau n'est ajouté après les réglages opérateur.
`config.yaml` et les secrets Hermès restent dans la page propre à Hermès. Les surcharges
Compose individuelles restent prioritaires sur la configuration commune.
Les adresses API doivent être joignables depuis les conteneurs ; l'accès backend → runtime
doit également être assuré par la topologie du déploiement.

Chaque déploiement Galaris provisionne explicitement cette configuration et le secret par un
canal sûr. Il ne lit jamais le `.env` du manager, qui peut résider sur une autre machine. Après
prise en compte du nouvel environnement par le backend, `make test-harness-management` vérifie le
contrat générique sans charger les paramètres Hermès.

Hermès sélectionne ce client générique déjà configuré. L’URL Galaris injectée dans les conteneurs
est donc commune à tous les runtimes managés et n’est pas un paramètre Hermès.

Le client `back/bridge/harness` envoie un nonce Fernet court dans `X-Harness-Token`. Les routes consommées vivent sous
`/instances/{agent.code}`. La création produit volontairement un répertoire vide : `_sync_config`
projette ensuite `Makefile`, Compose, `.env`, `data/config.yaml`, `data/SOUL.md`, les scripts,
plugins et skills Hermès. Les surcharges Compose restent propres à l’agent concerné.

## Outils natifs

La synchronisation conserve un seul point d'autorité pour les capacités déjà fournies par
Galaris. Lorsque les fonctions MCP `image_generate` ou `image_read` sont effectivement visibles
pour l'agent Hermès, les toolsets natifs `image_gen` ou `vision` correspondants sont ajoutés à
`agent.disabled_toolsets`. Leur retrait est réversible si la fonction Galaris est désactivée, et
une surcharge explicite dans la configuration globale ou celle de l'agent reste respectée.

Les skills natives Hermès restent disponibles à la demande, en complément des skills assignées
et projetées par Galaris sous `skills/galaris/`. Galaris ne les désactive pas globalement et
préserve les désactivations explicites de l'opérateur dans `skills.disabled`.

## Console externe et terminal SSH

Lorsqu'un agent possède une connexion **Console** active en mode externe, sa synchronisation
configure le backend `ssh` du terminal natif Hermès avec cette même cible. Le terminal, les
opérations de fichiers natives et `execute_code` travaillent ainsi dans le home SSH distant au
lieu du conteneur Hermès. Une Console embarquée (`ssh-executor`) ne déclenche pas cette projection.

La clé privée est déchiffrée seulement pendant la synchronisation, exportée sans passphrase pour
le client OpenSSH non interactif, puis écrite en `0600` dans le répertoire géré
`data/.galaris/ssh/`. Elle n'est jamais inscrite dans `config.yaml`. Un `known_hosts` propre à
l’instance et des wrappers `ssh`/`scp` imposent `StrictHostKeyChecking=yes`, la clé d'hôte
configurée dans Galaris et le timeout de connexion. Hermès les lit sous
`/opt/data/.galaris/ssh` dans son conteneur dédié.

Si la connexion externe est désactivée, supprimée ou remplacée par l'exécuteur embarqué, les
credentials matérialisés sont supprimés et les valeurs terminal antérieures sont restaurées. Un
échec de matérialisation interrompt la synchronisation afin qu'Hermès ne puisse pas retomber
silencieusement sur une console locale.

## Kanban

L'exécution `high` par Kanban est désactivée par ADR 0013. Le harness manager n'expose aucune
traduction CLI Kanban et le bridge n’a plus de backend partagé pour ce transport. Un ancien
checkpoint Kanban est donc refusé explicitement au lieu d’être converti en run direct ou de
réintroduire une commande spécifique dans le serveur générique.
