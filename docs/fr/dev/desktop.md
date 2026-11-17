<p align="right"><strong>Français</strong> · <a href="../../en/dev/desktop.md">English</a></p>

# Client desktop Electron

Le package indépendant `desktop/` réutilise l’interface du serveur et embarque seulement
le sélecteur de serveur, la barre d’onglets Vue/Quasar et le moteur Electron. Il n’ajoute aucun module métier,
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
Son titre HTML suit le titre de `PageHeader` via Quasar Meta, avec les libellés de navigation
autorisés et traduits en repli et la route parente la plus précise pour une page imbriquée.
Electron reprend les changements de
ce titre pour chaque onglet, y compris lorsqu’il est en arrière-plan.

`server.json` contient seulement l’origine du serveur dans le répertoire utilisateur Electron.
L’écriture atomique de ce petit fichier ne cède pas la main à une annulation concurrente.
Les cookies, caches et stockages web vivent dans une partition persistante distincte pour
chaque origine. L’HTTP est accepté uniquement en développement pour les adresses loopback.
Une connexion échouée conserve le dernier serveur enregistré et laisse le lanceur utilisable.

Le protocole local `galaris-desktop:` sert seulement les assets embarqués. Le preload expose
les opérations bornées du lanceur et des onglets ; chaque invocation vérifie la fenêtre,
le frame principal et l’URL exacte, avec des autorisations distinctes pour les deux interfaces.
Les onglets distants sont des `WebContentsView` sans preload ; seule la barre locale en
possède un. Chaque vue conserve son état pendant la sélection d’une autre vue, avec une
partition serveur commune. Les nouvelles fenêtres de même origine deviennent des onglets ;
les aperçus blob/data restent des fenêtres isolées. Les vues sont fermées explicitement
avec `beforeunload` avant de détruire la fenêtre, y compris pour un changement de serveur
ou une installation. Un refus conserve la vue concernée ; les onglets déjà fermés ne sont
pas restaurés. Aucune liste d’onglets n’est persistée.
La session active les dictionnaires Hunspell `fr` et `en-US` sur Windows/Linux ; les mots
restent traités localement. Electron télécharge les dictionnaires depuis son CDN par défaut.
Le menu contextuel expose les suggestions, l’ajout au dictionnaire et les actions d’édition.
Les éditeurs `rich-text` conservent leur menu spécifique ; Maj+clic droit laisse passer
le menu natif sans modifier la sélection. Les liens internes ouverts en onglet sont isolés
de leur fenêtre d’origine, conformément aux consommateurs `noopener` existants.
Les aperçus n’ont aucun preload.
La barre locale est une vue native placée au-dessus des vues distantes. Dans le shell
Galaris (`.page-container`), un adaptateur isolé réserve sa hauteur dans le contenu et
observe le retrait gauche, le thème et la surface de la page. Il transmet uniquement
ces valeurs de présentation via des messages console bornés du frame principal de
l’origine sélectionnée, sans exposer d’API distante. Le processus principal borne le
retrait et recalcule les vues au changement d’onglet, au zoom et au redimensionnement.
Le menu latéral garde toute sa hauteur. En dessous de 1024 pixels CSS, ou sans ce shell
(connexion externe, ancienne interface), la barre reprend toute la largeur au-dessus
de la vue. L’adaptateur et ses observateurs disparaissent avec le document ; le serveur
n’a pas besoin d’être recompilé pour cette disposition.
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
