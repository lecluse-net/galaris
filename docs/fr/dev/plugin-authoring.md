<p align="right"><strong>Français</strong> · <a href="../../en/dev/plugin-authoring.md">English</a></p>

# Construire un plugin Galaris

Choisir la façade du domaine qui possède l'opération. Pour un Service HTTP ou MCP
déjà pris en charge, l'archive contient une fiche et des liaisons de paramètres.
Pour un nouveau format de document, le plugin apporte le codec et les rendus.
Galaris fournit les droits, les transactions, les révisions et les commandes
de bibliothèque. La [conception du chargeur](../../../project/plans/infrastructure-plugins-galaris.md)
décrit les autres familles et leur état de réalisation.

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

Un agent travaillant sur le dépôt utilise ces skills dans son espace de travail.
Pour les proposer à des agents Galaris, importer les deux fichiers `SKILL.md`
ou leurs ZIP individuels via **Configurer → Compétences → Importer**, puis les
affecter aux agents auteurs et qualificateurs. Donner aux agents concernés l'accès
au dépôt et aux outils de test nécessaires. Les liens vers les contrats et les Samples
pointent vers le dépôt. Voir le [guide des compétences](../user/skills.md) pour les droits.

```bash
make tests ARGS='app/plugin/tests app/document/tests/test_sample_drawing.py app/document/tests/test_formats.py'
make tests-front-components ARGS='document-formats.spec.mjs plugins.spec.mjs --project chromium'
make typecheck
make docs-prepare
```
