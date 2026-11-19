<p align="right"><strong>Français</strong> · <a href="../../en/dev/plugin-authoring.md">English</a></p>

# Construire un plugin Galaris

Choisir la façade du domaine qui possède l'opération. Pour un Service HTTP ou MCP
déjà pris en charge, l'archive contient une fiche et des liaisons de paramètres.
Pour un nouveau format de document, le plugin apporte le codec et les rendus.
Galaris fournit les droits, les transactions, les révisions et les commandes
de bibliothèque. La [conception du chargeur](../../../project/plans/infrastructure-plugins-galaris.md)
décrit les autres familles et leur état de réalisation.

Le [contrat du bundle](plugin-bundles.md) définit ce que le chargeur accepte. L’[API Plugins](plugin-api.md)
documente l’aperçu, l’installation et l’activation des versions signées.

## Samples à reproduire

En `APP_ENV=dev`, **Administrer → Plugins** affiche les trois Samples du dépôt.
L'interrupteur **Activation** sur chaque carte commande la publication du format
ou de la fiche de Service. Son état est conservé dans l'instance.
Pour Dessin, créez un document **Dessin (Sample)** dans Documents. Pour REST et MCP,
créez un Service à partir de la fiche correspondante, qui préremplit l'URL de démonstration.
La Connexion REST utilise le jeton `sample-token`. La route REST `GET /status` et
la fonction MCP `sample_value` renvoient `sample-ok`.

Pour tester l'installation et le retrait avec le registre, utilisez les ZIP signés
ci-dessous. Une version gérée par le registre prend la priorité sur la fiche de
développement du même code, y compris après retrait.

| Sample | Sources | Exécution |
|---|---|---|
| **Sample REST** | `plugins/sample/rest/` | Bundle signé dans **Administrer → Plugins**. La Connexion fournit l'URL et le jeton, via le protocole intégré `rest.api`. |
| **Sample MCP** | `plugins/sample/mcp/` | Bundle signé dans **Administrer → Plugins**. La Connexion fournit l'URL du serveur MCP HTTP de qualification. |
| **Dessin (Sample)** | `plugins/sample/drawing/` | Contribution native de développement. Créer le format **Dessin (Sample)** dans Documents. |
| **Dessin (ZIP)** | `plugins/sample/drawing/` | Archive exécutable signée. Créer le format **Dessin (ZIP)** après activation. |
| **Sample Fournisseur IA** | `plugins/sample/provider/` | Archive exécutable. Configurer le profil OpenAI-compatible en dev avec `sample-token`. |
| **Sample Conversion** | `plugins/sample/preview/` | Archive exécutable. Après activation, demander un aperçu d'une pièce jointe UTF-8 `.sample-note`. |
| **Sample Données** | `plugins/sample/data/` | Modèle JSON signé. Télécharger le modèle sur la carte puis l'importer dans Documents. |
| **Sample Partage de fichiers** | `plugins/sample/file_share/` | Protocole et fiche de Service dans le même ZIP. En dev, activer, créer le Service depuis la fiche puis renseigner `sample-token` dans la Connexion. La sonde et `file_read` sur `sample-storage://note.txt` utilisent la Connexion choisie. |

Un plugin a un dossier source et une archive par version. Le même dossier réunit
le backend, le frontend et les données que le plugin fournit. Le script commun
de signature des fiches dépend de Python et de `cryptography`.

```text
plugins/sample/
├── rest/                     manifeste et services/sample-rest.yaml
├── mcp/                      manifeste et services/sample-mcp.yaml
├── provider/                 profil du fournisseur et manifeste signé à préparer
├── preview/                  convertisseur d'aperçu et manifeste signé à préparer
├── data/                     modèle JSON déclaré et versionné
├── drawing/
│   ├── __init__.py            codec, PNG initial, register()
│   ├── index.ts               enregistrement et instantané inerte
│   ├── manifest.json          identité du Sample et capacité documentaire
│   ├── bundle.json             manifeste de la version installable
│   ├── build.mjs               compilation Vue depuis les mêmes sources
│   ├── DrawingEditor.vue     éditeur de dessin
│   ├── DrawingPreview.vue    lecteur des révisions
│   └── messages.ts           textes de l’interface en FR, EN et ZH
├── native.py                 exemples de fournisseur et de conversion
├── inventory.py              publication des Samples en développement
├── fixtures.py               cibles locales REST et MCP
└── package.py                empreintes, manifeste signé et ZIP déterministe
```

## Signer et essayer un bundle déclaratif

Effectuer la signature dans l'environnement de l'éditeur. Pour les Samples, les
commandes suivantes utilisent le backend Docker de développement courant. Le ZIP
contient uniquement des fiches déclaratives et leur manifeste signé.

```bash
backend="${APP_NAME:-galaris}-back"
work=$(docker exec "$backend" mktemp -d /tmp/galaris-plugin.XXXXXX)
docker exec "$backend" python -m plugins.sample.package init-key "$work/publisher.pem"
docker exec "$backend" python -m plugins.sample.package public-key "$work/publisher.pem"
docker exec "$backend" python -m plugins.sample.package build "$work/publisher.pem" plugins/sample/rest "$work/sample-rest.zip"
docker exec "$backend" python -m plugins.sample.package build "$work/publisher.pem" plugins/sample/mcp "$work/sample-mcp.zip"
docker cp "$backend:$work/sample-rest.zip" .
docker cp "$backend:$work/sample-mcp.zip" .
```

Le code `sample.rest` appartient à l'espace d'éditeur `sample`. Faire approuver
la clé publique correspondante dans `PLUGIN_TRUSTED_PUBLISHERS` avant import.
La clé privée reste chez l'éditeur. La configuration de confiance d'une instance
relève de son opérateur. Le guide [des bundles](plugin-bundles.md) décrit les
contraintes ZIP, les versions de manifeste, le forçage dev et le retrait.
Conserver la même clé d'éditeur pour les prochaines versions du même code. Réserver
une clé de test et un registre isolé aux essais jetables.

Vérifier dans **Administrer → Plugins** le code, la version, les contributions
nommées et la compatibilité. Installer inactif, activer, puis suivre **Nouveau
service → Configurer une copie** dans Services. Renseigner les paramètres de
Connexion dans l'éditeur standard. Utiliser un serveur synthétique dans un
environnement isolé pour tester REST ou MCP. La désinstallation retire la
fiche du catalogue. Le Service enregistré conserve sa configuration locale.

## Implémenter un format et son éditeur

Le [contrat des formats](document-formats.md) est normatif. Le Sample Dessin
enregistre `sample.drawing`, fournisseur `sample.drawing`, version de format `1`
des deux côtés. La composition backend appelle `register()` au démarrage.
La composition frontend appelle `registerDrawingSample()`. La façade
`register_document_format` reçoit la validation, le MIME, les octets initiaux
et la liste des capacités. Le format est binaire avec une seule image PNG,
limitée à 2048 pixels par côté et 8 Mio. Le test de qualification utilise
de vrais octets PNG et des entrées invalides.

Dans l'éditeur, `DocumentContentSource.load(signal)` ouvre le fichier autorisé
et `save(blob, expectedRevision, signal)` le publie. La source indique aussi
le mode lecture seule. Dessin enregistre automatiquement à la fin d'un tracé,
après une courte pause. `flush` enregistre le brouillon en attente avant de quitter
l'éditeur. `discardDraft` permet l'abandon explicite. En cas de
réponse tardive ou de conflit, il conserve le brouillon et évite de sauver
dans un autre contexte. Le lecteur historique charge la révision fournie.
L'instantané PDF contient une image PNG inerte. Les intégrations et miniatures
utilisent les replis de Galaris. Les révisions et originaux appartiennent à
Documents, y compris si le format est retiré.

Dessin utilise `DocumentToolbar` pour déclarer ses outils, leurs états et les
paramètres de pinceau. Le même composant s'affiche depuis le dépôt et depuis le ZIP.
[Contrat de la barre d'outils](document-formats.md)

Les deux points d'entrée de Dessin sont assemblés depuis le même dossier en
`APP_ENV=dev`. Depuis la racine du dépôt, créer un ZIP source qui réunit le codec
et l'interface avec la commande suivante.

```bash
zip -X -r sample-drawing-source.zip plugins/sample/drawing -x '*/__pycache__/*'
```

Le ZIP source sert à la revue. Pour créer le ZIP installable avec le même éditeur,
réutiliser `backend`, `work` et la clé de l'exemple de signature ci-dessus.

```bash
frontend="${APP_NAME:-galaris}-front"
staging=$(mktemp -d)
docker exec "$frontend" node plugins/sample/drawing/build.mjs /tmp/sample-drawing-build
docker cp "$frontend:/tmp/sample-drawing-build" "$staging/drawing"
docker cp "$staging/drawing" "$backend:$work/drawing"
docker exec "$backend" python -m plugins.sample.package build "$work/publisher.pem" "$work/drawing" "$work/sample-drawing.zip"
docker exec "$backend" python -m plugins.sample.package build "$work/publisher.pem" plugins/sample/provider "$work/sample-provider.zip"
docker exec "$backend" python -m plugins.sample.package build "$work/publisher.pem" plugins/sample/preview "$work/sample-preview.zip"
docker exec "$backend" python -m plugins.sample.package build "$work/publisher.pem" plugins/sample/data "$work/sample-data.zip"
```

Copier les ZIP comme pour REST et MCP. Faire approuver `sample` dans la liste
`PLUGIN_EXECUTABLE_PUBLISHERS` de l'instance de qualification. Après activation de
**Dessin (ZIP)**, ouvrir Documents, créer ce format, dessiner puis rouvrir le PNG.
Désactiver et désinstaller la release, puis vérifier le téléchargement de l'original.
Dessin (Sample) garde son code de développement distinct de Dessin (ZIP).

## Choisir une façade

| Besoin | Façade ou contrat | Sample ou référence vérifiable |
|---|---|---|
| Définir un Service REST ou MCP | [Catalogue de Services](service-catalog.md), `ServiceCreate` | Bundles Sample REST et Sample MCP. |
| Réutiliser Mail ou Calendrier dans un Service | [Capacités et protocoles](../../../project/decisions/0274-provider-tool-protocols.md) | [Épreuve Mail/Calendrier](../../../back/app/services/tests/test_protocols.py). |
| Ajouter un fournisseur IA | [ProviderProfile et ports provider](../../../back/app/llm/provider_facade.py) | Archive `plugins/sample/provider/`. Le profil utilise le protocole OpenAI-compatible présent dans l'hôte. |
| Ajouter un format documentaire | [Façade Documents](document-formats.md) | Sample Dessin pour le stockage fichier et [format structuré synthétique](../../../back/app/document/tests/test_formats.py) pour le stockage texte. |
| Lire une ressource externe | `registerResourceViewer`, `ResourceViewerSource` | `front/test-support/browser/ResourceViewerHarness.vue` dans les tests Chromium de formats. Le lecteur reçoit un Blob autorisé. |
| Convertir une ressource | [PreviewConverter](../../../back/core/preview/contracts.py) | Archive `plugins/sample/preview/` et [test de préservation de la source](../../../back/core/preview/tests/test_conversion.py). |
| Installer un protocole de fichiers | [`FileShareBridge`](../../../back/app/file_share/bridges.py) | Sample Partage de fichiers. Les Connexions et le contrôle des droits restent chez Galaris. |
| Adapter une messagerie | [Façade Messenger](../../../back/app/messenger/facade.py) | [Configuration de bridges](../../../back/app/messenger/tests/test_bridge_configuration.py). Les événements rejoignent le journal canonique. |
| Brancher un moteur métier | [ProcessEngine](process-engines.md) | [Moteur synthétique](../../../back/app/process/fake_engine.py). Process conserve l'état durable et les transitions. |
| Fournir un driver d'agent | [Contrats agent](../../../back/app/agent/contracts.py) | [Driver testkit](../../../back/app/agent/tests/test_driver_testkit.py) pour le flux, les erreurs et la fin unique. |
| Distribuer des skills ou données | [Développement Galaris](README.md), [DbAdmin](dbadmin.md) | Sample Données livre un modèle importable. Les packs de skills et les jeux permanents gérés par le registre restent prévus. |
| Ajouter un panneau, un éditeur de fichiers externe ou un nouveau protocole | [Plan d'extension](../../../project/plans/infrastructure-plugins-galaris.md) | Les ports de publication correspondants restent à définir. |

## Exemples à adapter

### Distribuer un modèle de données

Placer ce `manifest.json` dans le dossier de préparation. Adapter la plage à la version de
Galaris que vous qualifiez. Le packager calcule `sha256` avant de signer le manifeste.

```json
{
  "format_version": 2,
  "code": "example.inventory",
  "version": "1.0.0",
  "label": {"fr": "Inventaire de démonstration", "en": "Demo inventory"},
  "description": {"fr": "Modèle JSON importable.", "en": "Importable JSON template."},
  "minimum_galaris_version": "0.3.2",
  "maximum_galaris_version_exclusive": "1.0.0",
  "contributions": [{
    "family": "data_template",
    "code": "example.inventory",
    "label": {"fr": "Inventaire", "en": "Inventory"},
    "contract_version": 1
  }]
}
```

Dans le même dossier, créer `data/example.inventory.json`.

```json
[
  {"sku": "DEMO-001", "quantity": 3, "available": true},
  {"sku": "DEMO-002", "quantity": 0, "available": false}
]
```

Construire le ZIP avec la clé de l’éditeur `example` en réutilisant la commande de signature
du guide. Après activation, télécharger le modèle sur sa carte ou via l’API. Dans
**Documents → Nouveau document depuis…**, importer le JSON. Modifier la quantité dans la copie
et vérifier que le modèle téléchargé garde ses valeurs.

### Connecter un Service REST ou MCP

Pour REST, créer un dossier avec ce `manifest.json`. La contribution `service_preset`
porte le code de la fiche YAML.

```json
{
  "format_version": 1,
  "code": "example.stock",
  "version": "1.0.0",
  "label": {"fr": "Stock", "en": "Stock"},
  "description": {"fr": "Connecteur REST.", "en": "REST connector."},
  "minimum_galaris_version": "0.3.2",
  "maximum_galaris_version_exclusive": "1.0.0",
  "contributions": [{
    "family": "service_preset",
    "code": "example-stock",
    "label": {"fr": "Service Stock", "en": "Stock service"},
    "contract_version": 1
  }]
}
```

Créer `services/example-stock.yaml` avec le même code de contribution.

```yaml
code: example-stock
label: Example Stock
catalog:
  format_version: 1
  version: 1.0.0
  summary:
    en: Read stock from a configured connection.
    fr: Lire le stock via une connexion configurée.
capabilities:
  - rest.api
rest_config:
  base_url: ${connection:url}
  auth:
    type: bearer
    param: token
connection_schema:
  params:
    url: {type: string, label: URL, required: true}
    token: {type: password, label: Token, required: true}
```

Configurer une copie du Service après activation. Dans sa Connexion, renseigner l’URL et le
jeton d’un serveur synthétique. Utiliser une route de lecture connue, par exemple `GET /status`.
Pour MCP, garder la même structure de manifeste avec une nouvelle identité, par exemple
`example.inventory-tools`, et le code de contribution `example-inventory-tools`. Placer cette
fiche dans `services/example-inventory-tools.yaml`.

```yaml
code: example-inventory-tools
label: Example Inventory Tools
catalog:
  format_version: 1
  version: 1.0.0
  summary:
    en: Connect to an inventory MCP server.
    fr: Connecter un serveur MCP d’inventaire.
capabilities:
  - http.mcp
mcp_config:
  type: http
  auth:
    type: none
    url_param: url
connection_schema:
  params:
    url: {type: string, label: URL, required: true}
```

Renseigner dans la Connexion l’adresse MCP Streamable HTTP du serveur synthétique. Vérifier
la découverte des fonctions et appeler une fonction de lecture de la fixture. Si la cible
exige une authentification, choisir le mode documenté par le [catalogue de Services](service-catalog.md).

En développement, le même serveur propose `sample_inventory`. Utiliser
`http://127.0.0.1:8000/api/plugin-samples/mcp/` depuis le backend, autoriser le Service
dans les conversations et affecter une Connexion active à l’agent. Pour essayer **Filtrer**
dans le Chat interne, mettre l’outil `sample_inventory` et la ressource
`ui://sample/inventory.html` en mode **Actif** dans la Connexion. Demander à l’agent
d’utiliser l’outil Sample MCP pour afficher le stock. Le filtre **Lyon** doit donner deux
lignes dont les quantités sont 18 et 7. Le serveur de démonstration utilise des réponses
JSON sur Streamable HTTP.

Le tableau est fourni par `structuredContent.table` avec un `title`, entre 1 et
16 `columns` et jusqu’à 100 `rows`. Chaque ligne contient une valeur scalaire JSON
ou `null` par colonne. Le formulaire utilise `_meta.ui.resourceUri` et une ressource HTML
autonome de type `text/html;profile=mcp-app`. L’outil déclare `annotations.readOnlyHint`
et autorise les appels depuis l’application. Galaris vérifie les droits courants sur la
Connexion et autorise le formulaire à rappeler le même outil. Les secrets de Connexion
restent côté serveur. [Parcours dans le Chat](../user/documents.md#mcp-tables)

### Implémenter une contribution exécutable

| Cas | Exemple à reproduire et scénario à vérifier |
|---|---|
| Document signé | Le build du Sample Dessin place le codec derrière `plugin_format(context)` et exporte `createFormat(host)` côté navigateur. Le document créé ouvre un PNG autorisé, enregistre avec sa révision lue et propose un aperçu historique. Tester le téléchargement de l’original après retrait. |
| Éditeur de document avec références | Utiliser `host.DocumentLink`, `host.DocumentCard` et `host.DocumentEmbed` dans le module Vue pour composer les références. L’éditeur choisit les modes par type. Pour permettre à d’autres documents d’intégrer ce format, déclarer la capacité Embed des deux côtés et fournir un lecteur complet en lecture seule. [Contrat des références](document-references.md) |
| Fournisseur IA | Le Sample Fournisseur IA renvoie un `ProviderProfile` depuis `plugin_provider(context)` et utilise le transport OpenAI-compatible de l’hôte. Vérifier une réponse avec une connexion synthétique et ses paramètres. |
| Conversion de pièce jointe | Le Sample Conversion renvoie un `PreviewConverter` depuis `plugin_converter(context)`. Il reconnaît `.sample-note`, borne la lecture, valide UTF-8 et produit un aperçu temporaire. Vérifier que le téléchargement normal conserve les octets originaux. |
| Protocole de fichiers | Le Sample Partage de fichiers publie `plugin_file_share_protocol(context)` et une fiche dans le même ZIP. Tester la liste et la lecture de `note.txt` avec les paramètres de Connexion, puis le refus d’écriture du transport en lecture seule. |

## Recette pour un agent auteur

1. Choisir la ligne de la matrice et lire son contrat, son Sample et son test.
2. Identifier les codes, versions, droits, données et points d'entrée livrés.
3. Tester avec des ressources synthétiques. En cas d'erreur d'écriture ou
   d'interruption, vérifier l'état qui reste visible et ce qui peut être rejoué.
4. Vérifier les limites de la façade et documenter le comportement après retrait.
5. Donner les commandes reproductibles, les résultats API et navigateur, et les
   capacités restant à qualifier. Associer les preuves à l'empreinte du bundle.

Les skills `galaris-plugin-author` et `galaris-plugin-qualification` sont dans
`.agents/skills`. Ils guident respectivement la construction et la vérification
sous le contrôle de l'opérateur.

L’agent Galaris fourni avec l’application reçoit le skill système
`galaris-plugin-development` par défaut. Il le charge à la demande. Pour un autre agent,
l’affecter dans **Configurer → Compétences → Autorisations**. Le skill peut lire ces
guides via les fonctions de documentation autorisées. La construction et la qualification
d’un ZIP demandent aussi un espace de travail, les outils adéquats et un accès aux sources
ou aux exemples. La clé privée reste dans l’environnement de signature de l’éditeur.
Voir le [guide des compétences](../user/skills.md) pour les droits.

```bash
make tests ARGS='app/plugin/tests app/document/tests/test_sample_drawing.py app/document/tests/test_formats.py'
make tests-front-components ARGS='document-formats.spec.mjs plugins.spec.mjs --project chromium'
make typecheck
make docs-prepare
```
