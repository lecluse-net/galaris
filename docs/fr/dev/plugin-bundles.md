<p align="right"><strong>Français</strong> · <a href="../../en/dev/plugin-bundles.md">English</a></p>

# Bundles de plugins

Le manifeste `1` prend en charge des fiches de
[Service](service-catalog.md). Une version peut contenir plusieurs fiches. La sélection
d'une version publie ses fiches dans le catalogue local en une transaction. L'ouverture
d'une fiche dans l'éditeur crée une copie indépendante lors de l'enregistrement.
Les Services existants, Connexions et droits suivent leurs parcours habituels.
Le [guide auteur](plugin-authoring.md) fournit les sources des Samples et la commande
de signature.

## Préparer une archive

Le ZIP contient un `manifest.json` UTF-8, sa signature Ed25519 binaire `manifest.sig`
et un fichier `services/<code>.yaml` autonome par contribution. Signer les octets
exacts du manifeste avec la clé privée de l'éditeur. Le SHA-256 de chaque fiche est
calculé sur ses octets et porté par son entrée dans le manifeste.

Le manifeste contient les champs suivants.

| Champ | Valeur |
|---|---|
| `format_version` | `1` |
| `code` | Code durable qualifié par l'éditeur, par exemple `example.studio` |
| `version` | Version stable `MAJEUR.MINEUR.CORRECTIF` |
| `label`, `description` | Objets avec les textes `en` et `fr` |
| `minimum_galaris_version`, `maximum_galaris_version_exclusive` | Bornes (incluse puis exclue) |
| `contributions` | Pour chaque fiche, `family: service_preset`, son `code`, son `label` FR/EN, `contract_version: 1` et son `sha256` hexadécimal |

La fiche YAML utilise le contrat du catalogue de Services, avec ses métadonnées
`catalog` et au moins un protocole disponible. Le code doit correspondre à celui de
la contribution. Galaris ajoute les informations d'origine à la fiche publiée.
L'archive est limitée à 2 Mio compressés, 4 Mio décompressés et 16 fiches.
Les fichiers sont lus directement sans extraction. Les contributions passent par
le validateur des Services portables.

Configurer `PLUGIN_TRUSTED_PUBLISHERS` dans l'environnement du backend. Cette
valeur JSON associe le premier segment du code de plugin à la clé publique Ed25519
brute de 32 octets encodée en hexadécimal. La clé privée reste chez l'éditeur.
Une liste vide désactive les imports. Le retrait d'une clé retire ses contributions du
catalogue au démarrage suivant.

## Installer et vérifier

1. Choisir l'archive et vérifier les capacités, l'empreinte du signataire et la compatibilité.
2. Installer la version inactive, puis l'activer. Dans **Configurer → Services & connexions**,
   choisir sa fiche avec **Nouveau service**, puis **Configurer une copie**. Adapter
   les réglages et enregistrer le Service.
3. Dans **Plugins**, désactiver la version puis confirmer sa désinstallation. Le catalogue
   retire la fiche et le Service déjà enregistré reste utilisable.

Sur une branche hors de la plage déclarée, le forçage n'est proposé qu'en
`APP_ENV=dev`. Il est lié à l'archive et à la révision de l'image. Après changement
de branche, mettre à jour l'image pour exposer la nouvelle révision. Une image sans
révision connue n'accepte cette dérogation que pendant la vie du processus courant.
L'installateur vérifie toujours l'intégrité, le signataire et le contrat des fiches.

## Ajouter des contributions exécutables

Utiliser `format_version: 2` pour réunir des fiches de Service et plusieurs contributions
exécutables dans un même ZIP. Les chemins et les empreintes sont déterminés par le type.

| Famille | Fichiers et contrat `1` |
|---|---|
| `document_format` | `backend/<code>.py` et `frontend/<code>.mjs`. Déclarer la version du format dans `version`, le SHA-256 Python dans `sha256` et celui du module web dans `frontend_sha256`. |
| `llm_provider` | `backend/<code>.py` et `sha256`. `plugin_provider(context)` renvoie un `ProviderProfile`. |
| `preview_converter` | `backend/<code>.py` et `sha256`. `plugin_converter(context)` renvoie un `PreviewConverter`. |
| `file_share_protocol` | `backend/<code>.py` et `sha256`. `plugin_file_share_protocol(context)` renvoie un `FileShareBridge` dont `service` est le code de la contribution. |
| `data_template` | `data/<code>.json` et `sha256`. Après activation, télécharger la source puis l'importer avec l'éditeur Documents. La copie possède ses droits et révisions. |

Le code d'une contribution exécutable est celui du plugin ou un sous-code séparé
par un point. `PLUGIN_EXECUTABLE_PUBLISHERS` est la liste JSON des éditeurs auxquels
l'opérateur accorde la confiance d'exécution du serveur et du navigateur Galaris.
Le code est chargé après vérification de signature et activation explicite.

Un protocole de partage de fichiers est sélectionnable dans Services sous
`<code>.file_share`. La fiche du même ZIP peut déjà le référencer. Le `FileShareBridge`
décrit les rôles et construit un transport avec l'URL du Service et les paramètres
résolus de la Connexion. Utiliser `writable=False` pour un transport en lecture seule
et refuser l'envoi dans l'adaptateur. La sonde standard peut utiliser `resource_list`
avec une limite d'une entrée. Désactiver le plugin retire le protocole du catalogue
et les opérations qui en dépendent. Services et Connexions conservent leurs paramètres.

`plugin_format(context)` renvoie un `DocumentFormatDefinition` binaire dont le code,
le fournisseur et la version correspondent au manifeste. Le module web exporte
`createFormat(host)` et renvoie `editor`, `snapshot` et éventuellement `preview`.
`host` fournit `vue`, `useI18n`, `solaire`, `saveBlobAsResource` et les composants
`QBanner`, `QBtn`, `QBtnToggle`, `QSpace`, `QSpinner` sous `host.quasar`. L'éditeur reçoit
`DocumentContentSource`. Le module web est public pendant l'activation.
La [façade frontend](../../../front/app/document/pluginHost.ts) liste les fonctions Vue
fournies par l'hôte et chargées à la demande.

Les plugins qui utilisent la barre commune prennent le composant dans
`host.DocumentToolbar`. Déclarer une version minimale de Galaris qui fournit
ce composant et vérifier l'ouverture de l'éditeur sur cette version.
[Contrat de la barre d'outils](document-formats.md)

`python_requirements` accepte les dépendances préinstallées à version exacte.
Les entrées `runtime_requirements` déclarent `code` et `image` épinglée par digest.
L'opérateur démarre le service correspondant et configure `PLUGIN_RUNTIME_BINDINGS`
avec la même `image` et une `url` par code. Avant le chargement, Galaris attend HTTP 200
sur `/health` et fournit les URL résolues dans `context.endpoints`. Le forçage dev
porte uniquement sur la version de Galaris.

L'API publie les registres préparés après la transaction. Le worker Process relit
la sélection dans PostgreSQL au démarrage et la réconcilie toutes les deux secondes.
Il retire les contributions obsolètes avant de préparer leurs remplaçantes. Les
opérations déjà engagées peuvent se terminer.

Avant la sélection, Chromium charge chaque module autonome dans un contexte neuf,
sans accès à l'application ni requêtes réseau, et vérifie l'export `createFormat`.
Un échec d'import conserve la sélection précédente et ajoute un événement au journal.
L'appel de `createFormat(host)`, le montage et les interactions de l'éditeur restent
à qualifier dans le frontend assemblé. Les diagnostics de `/data/update-diagnostics`
gardent l'étape, la version et la cause expurgée des échecs de chargement et d'installation.
Au démarrage, l'API vérifie les archives sélectionnées et leurs dépendances avant de servir les requêtes.
La désactivation retire les contributions et leurs modules. Elle conserve les documents,
leurs révisions et les configurations locales.

## Alimenter le catalogue

Déposer les ZIP signés approuvés dans `PLUGIN_CATALOG_DIRECTORY`, par défaut
`/data/plugins/catalog`. **Administrer → Plugins → Catalogue** affiche ces versions
et réutilise l'aperçu signé de l'import manuel avant l'installation inactive. Ce miroir
est géré par l'opérateur.

### Catalogue distant administré

`PLUGIN_CATALOG_REMOTE_URL` pointe vers un répertoire HTTPS administré. Configurez sa
clé publique Ed25519 avec `PLUGIN_CATALOG_REMOTE_PUBLIC_KEY` en hexadécimal. Le catalogue
sert `index.json`, `index.sig` et `archives/<sha256>.zip`. L'index a `format_version: 1`,
un `sequence` entier croissant, `issued_at` et `expires_at` en UTC (validité maximale de
sept jours), `releases` avec `manifest`, `digest` et `signer` obtenus lors de l'inspection
des ZIP approuvés, et `revoked`, la liste cumulative des digests retirés. Signez les octets
de l'index avec une clé distincte des clés éditeur.

```bash
python -m plugins.sample.package sign-index catalogue.pem index.json index.sig
```

Publiez d'abord les archives par empreinte, puis le nouvel index et sa signature. Galaris
garde le dernier index accepté dans le volume du catalogue. Un ancien numéro d'index ou
une révocation retirée ne peut le remplacer. L'index en cache reste utilisable jusqu'à
expiration. Le téléchargement vérifie à nouveau l'index, l'empreinte et la signature
de l'éditeur. L'API relève les révocations du catalogue chaque minute et désactive
les versions concernées. Le registre conserve le blocage par empreinte même après
l'expiration de l'index, une panne du catalogue ou la désinstallation. Une empreinte
révoquée ne peut plus être importée manuellement ni réactivée. Les documents, révisions,
Services locaux et Connexions conservent leurs données.

### Préparer une publication déclarative

Le préparateur utilise les clés éditeur de `PLUGIN_TRUSTED_PUBLISHERS` pour vérifier
les ZIP. Pour chaque `<nom>.zip`, fournir `<nom>.qualification.json` et sa signature
Ed25519 binaire `<nom>.qualification.sig`, émise par une autorité distincte de l'éditeur
et du catalogue. L'attestation a `format_version: 1`, `digest` (SHA-256 du ZIP),
`source_repository` (HTTPS), `source_commit` (empreinte Git), `report_digest`
(SHA-256 du rapport conservé par le qualificateur) et les contrôles
`bundle`, `compatibility`, `permissions`, `localization` et `lifecycle` dans `checks`.

```bash
python -m app.plugin.publication ./candidats ./catalogue-suivant \
  --catalogue-key catalogue.pem --qualification-key qualification-public.hex \
  --previous ./catalogue-courant --revoke "$revoked_digest"
```

Pour la première publication, omettre `--previous` et `--revoke`. Le préparateur crée
un nouveau répertoire signé, conserve la séquence et les révocations du précédent,
et fournit les archives indexées par empreinte avec leurs attestations. L'opérateur
publie `index.json`, `index.sig` et `archives/` après contrôle. Les contributions
exécutables sont réservées au circuit des éditeurs explicitement approuvés par
l'opérateur. L'isolation des éditeurs tiers et l'hébergement officiel sont suivis
dans le [plan des plugins](../../../project/plans/infrastructure-plugins-galaris.md).
