# Containerized Harness Manager / Gestionnaire de harnais conteneurisés

## Installation depuis Galaris

Prérequis : Linux, Docker Engine avec Compose, GNU Make, Python 3 et curl. Utiliser le
compte qui possède les instances Docker, dans un répertoire permanent.

Dans **Préférences → Harnais → Harnais managés**, enregistrer la configuration du manager,
adapter les options à la machine cible, puis télécharger le **ZIP prêt à installer**.
Cette archive privée contient le code et le `.env` avec la clé partagée enregistrée.
Après extraction, entrer dans `harness_manager`, protéger `.env` avec `chmod 600 .env`
et créer le répertoire absolu indiqué par `BASE_DIR`, accessible au compte du service.

```bash
make install
make service-install
make service-status
```

Pour un lancement ponctuel, utiliser `make start` puis `make stop`. `make install` préserve
un `.env` existant. Le ZIP du code seul ne contient pas de `.env` ; dans ce cas,
l'installation génère une clé à reporter dans les préférences Galaris.

## Mise à jour

La version fixe est déclarée dans `pyproject.toml` et annoncée par l'API du manager.
Galaris compare la version installée à celle de son archive et signale les différences.
Depuis ce répertoire, avec le même compte que le service :

```bash
make update
```

`GALARIS_UPDATE_URL` dans `.env` désigne l'adresse de mise à jour fournie par Galaris,
joignable depuis cet hôte. Elle est incluse dans le ZIP préparé par les préférences.
Une surcharge ponctuelle est possible :

```bash
make update UPDATE_URL=https://galaris.example/api/harness-manager/updates
```

La commande authentifie le téléchargement avec la clé partagée, vérifie le manifeste
signé et l'empreinte du ZIP, puis sauvegarde le code sous `.local/backup-<version>-…`.
Elle remplace uniquement les fichiers distribués, synchronise les dépendances verrouillées
et redémarre le manager s'il tournait déjà (systemd utilisateur ou `make start`). Elle
vérifie alors la version annoncée. En cas d'échec, elle tente de restaurer le code et
l'environnement précédents ; si cette restauration échoue, le chemin de sauvegarde est affiché.
Un manager arrêté reste arrêté. Les versions antérieures sont refusées.

Le `.env`, les données des instances et les autres fichiers locaux sont conservés.
Cette commande ne reconstruit pas les conteneurs des harnais. Prévoir une courte interruption
de l'API du manager et éviter les opérations de gestion pendant sa mise à jour.

Pour un ancien manager sans `make update`, arrêter son service, extraire une première fois
le **ZIP du code seul** dans son répertoire existant, puis lancer `make install` et relancer
le service. Ajouter l'adresse affichée par Galaris dans `GALARIS_UPDATE_URL` du `.env`
existant pour les mises à jour suivantes. Ne pas remplacer sa clé ou son `BASE_DIR`.

## English quick start

On a Linux host with Docker Compose, GNU Make, Python 3 and curl, download the configured ZIP
from **Preferences → Harnesses → Managed harnesses** after saving the manager configuration.
It contains your private `.env`, including the saved shared key and update endpoint. Extract
it into a permanent directory, enter `harness_manager`, run `chmod 600 .env` and create the
configured `BASE_DIR` with permissions for the service account. Run `make install`, then
`make service-install` (or `make start` for a background process).

Run `make update` as the same user to fetch the release from `GALARIS_UPDATE_URL`. It verifies
the authenticated manifest and checksum, backs up source files, installs locked dependencies
and restarts an already running manager. It attempts rollback on failure and reports the
backup directory if recovery fails. Configuration, instance data and other local files are
preserved; harness containers are not rebuilt. Downgrades are refused. An older installation
without this command needs one manual source-only ZIP extraction while stopped, `make install`,
a restart, and `GALARIS_UPDATE_URL` added to its existing `.env`.

In a full Galaris checkout, detailed documentation lives in
`docs/fr/components/harness-manager.md` and `docs/en/components/harness-manager.md`.

### Concurrent lifecycle and raw transfers

Instance creation, deletion and lifecycle commands reserve their identity with an inter-process
lock. Conflicting work returns HTTP 409. Failed Docker cleanup preserves the instance directory
and prevents identity reuse. Instance-root symlinks are refused. File operations hold safe parent
descriptors without following symlinks; streamed downloads retain the inode opened before headers.
Raw uploads default to 512 MiB (`MAX_RAW_FILE_SIZE_MB=512`) and preserve the old file when a transfer
fails. Command deadlines terminate the whole process group and bound captured output to 1 MiB.
