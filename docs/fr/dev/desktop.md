<p align="right"><strong>Français</strong> · <a href="../../en/dev/desktop.md">English</a></p>

# Client desktop Electron

Le package indépendant `desktop/` réutilise l’interface du serveur et embarque seulement
le sélecteur de serveur Vue/Quasar et le moteur Electron. Il n’ajoute aucun module métier,
serveur local, accès Node à l’interface distante ou configuration CORS.
Voir la décision [0292](../../../project/decisions/0292-desktop-client.md) et le
[parcours utilisateur](../user/desktop.md).

## Construire et vérifier

```bash
make desktop-deps     # créer/actualiser package-lock.json dans Docker
make desktop-build    # types stricts et builds du lanceur/main/preload
make tests-desktop    # build, règles unitaires, parcours Electron sous Xvfb
make desktop-package  # AppImage et .deb x64 dans desktop/release/
make desktop-package-windows # installateur Windows x64 non signé, Docker/Wine
```

Ces commandes n’utilisent pas la stack applicative ni ses secrets. Les dépendances sont
conservées dans un volume Docker identifié par le verrou. Les diagnostics et captures
synthétiques sont sous `artifacts/desktop/`. Les tests désactivent le sandbox Chromium
uniquement dans leur conteneur isolé ; le client livré conserve `sandbox: true`.

Le lanceur réutilise les composants natifs Quasar de la référence graphique et la palette
Solaire partagée. Il suit le thème du système et propose les catalogues en/fr/zh selon sa
langue. L’interface distante conserve sa propre langue et ses réglages utilisateur.

`server.json` contient seulement l’origine du serveur dans le répertoire utilisateur Electron.
L’écriture atomique de ce petit fichier ne cède pas la main à une annulation concurrente.
Les cookies, caches et stockages web vivent dans une partition persistante distincte pour
chaque origine. L’HTTP est accepté uniquement en développement pour les adresses loopback.
Une connexion échouée conserve le dernier serveur enregistré et laisse le lanceur utilisable.

Le protocole local `galaris-desktop:` sert seulement les assets embarqués. Le preload expose
cinq opérations bornées et un abonnement ; chaque invocation vérifie la fenêtre, le frame
principal et l’URL exacte. Les fenêtres distantes et les aperçus n’ont aucun preload.
Les permissions refusent les frames et origines tierces et demandent un accord natif pour
les capacités prises en charge. Les schémas de programmes locaux ne sont jamais transmis
à `shell.openExternal`. Les certificats invalides restent refusés.

## Distribution et mises à jour

`electron-builder` produit NSIS Windows, AppImage et Debian Linux. `electron-updater`
consulte exclusivement les publications publiques `lecluse-net/galaris`, avec des tags
SemVer sans `v`. L’URL du serveur choisi ne peut pas modifier le canal de mise à jour.
Windows et AppImage téléchargent automatiquement et proposent un redémarrage explicite ;
la fermeture seule n’installe rien. Le paquet Debian reste une mise à niveau manuelle.
Les sessions utilisateur sont conservées pendant une mise à jour.

Les échecs de mise à jour et de démarrage sont conservés localement dans
`desktop-update.log`, à côté de `server.json`, avec étape, version, cause, code d’erreur,
statut de sortie lorsqu’il est fourni et pile. Deux fichiers bornés sont conservés ; les
identifiants et paramètres sensibles des URL sont retirés avant écriture. Une erreur de
stockage du diagnostic est signalée dans le lanceur sans masquer l’erreur initiale.
Aucune télémétrie externe n’est ajoutée par le client.

Le workflow `Desktop client` vérifie et construit des aperçus sur les runners natifs Linux
et Windows. Le workflow gardé `Publish release` qualifie le commit exact avec `release-check`,
puis construit les deux plateformes à ce commit. Il utilise la version du tag
comme version du client, attache les installateurs, blockmaps et `latest*.yml` à un brouillon,
puis le publie seulement lorsque tous les fichiers sont présents. Un échec conserve un
brouillon non publié ; une publication existante reste inchangée. Aucun build ne publie
directement via electron-builder.

Les tests fonctionnels restent dans `Desktop client`, séparément de la publication des
sources ; ils n’ajoutent pas de verrou fonctionnel à son garde de sécurité.

Pour une publication Windows signée, configurer les secrets GitHub
`DESKTOP_WINDOWS_CERTIFICATE` (PFX encodé base64 ou URL reconnue par electron-builder) et
`DESKTOP_WINDOWS_CERTIFICATE_PASSWORD`. Le workflow de publication exige la signature et
échoue si elle manque ; les builds de prévisualisation peuvent rester non signés.
Le certificat et son identité d’éditeur doivent rester cohérents pour les mises à jour.
Ne jamais placer de certificat ou jeton GitHub dans le dépôt ou les assets distribués.

Avant livraison, vérifier sur Windows et Linux réels : installation, relance, connexion,
micro/caméra, appels, téléchargements, notifications et passage d’une version publiée à la
suivante avec conservation de session. Les tests synthétiques de mise à jour couvrent les
contrôles concurrents, l’échec/réessai, la progression et le redémarrage choisi. Le vrai
moteur télécharge un fichier synthétique, refuse une empreinte corrompue et réussit au réessai ; ils ne
prouvent pas l’installation signée sur un poste réel ni les périphériques physiques.
