<p align="right"><strong>Français</strong> · <a href="../../en/dev/file-share-navigation.md">English</a></p>

# Comparer la navigation File Share avec un vrai harnais

Cette expérience compare les outils MCP actuels et une copie locale du même corpus,
avec le SDK Hermes amont épinglé par le Dockerfile du bridge. Elle n'installe aucun
montage FUSE et ne crée ni Task ni ressource métier dans l'instance.

## Préparer puis mesurer

Utiliser la stack de développement active et un modèle Chat Completions OpenRouter
configuré avec sa clé facturée. Le code du modèle est celui de cette installation ;
le dernier argument sélectionne explicitement un endpoint OpenRouter, sans repli
automatique. Les garde-fous du compte fournisseur restent appliqués.

```bash
make file-share-navigation ARGS="pilot $NAVIGATION_MODEL_CODE deepinfra"
make file-share-navigation ARGS="decision $NAVIGATION_MODEL_CODE deepinfra"
```

Le pilote utilise deux missions, une répétition et les deux accès. La décision
exige un pilote intégralement réussi avec les mêmes sources, images, modèle et corpus.
Elle réserve douze autres missions, cinq répétitions par accès et un ordre apparié
figé avant les résultats. Le lanceur et les conteneurs exécutent une copie figée des
sources ; une édition du checkout ne modifie pas les runs déjà préparés. Le rapport
refuse des sources exécutées ou des octets de corpus qui ont changé.

La commande produit un nouveau répertoire sous `artifacts/file-share-navigation/` :
`manifest.json`, `source.tar.gz`, `results/`, `metrics/`, `scores.json` et `summary.json`. Une campagne
interrompue conserve les preuves acquises et ne produit pas de décision qualifiée.
Repartir d'une campagne neuve après correction d'une erreur d'infrastructure ; ne
pas remplacer des résultats défavorables par une reprise sélective.
L'archive conserve les sources du backend et du lanceur sans les fichiers ignorés par Git ;
elle permet de retrouver le calcul correspondant à l'empreinte du manifeste.

## Isolation et preuves

Chaque exécution utilise un conteneur neuf, sans historique. Seule la variante
répertoire reçoit le corpus en lecture seule. Le harnais dispose des mêmes outils
fichier et terminal dans les deux variantes ; A ne peut pas lire le corpus sur disque.
Les cinq outils MCP sont découverts avant l'inférence. Leur traitement appelle les
fonctions `app.file_share.mcp`, la façade et un transport externe synthétique.
Les réponses attendues et le manifeste ne sont jamais montés dans le harnais.

Le harnais n'accède qu'au réseau Docker interne. Le relais est seul à recevoir la
clé fournisseur, dans un temporaire privé supprimé à la sortie. Il n'a aucun accès
à la base applicative. La lecture initiale de la configuration vérifie `is_dev` et
ne lit aucune conversation, aucun document ni profil d'agent. Les traces conservent
uniquement des missions et fichiers inventés, les résultats d'outils et les mesures.
L'UID root du SDK n'a aucune capability ; les sources et le corpus sont en lecture
seule, avec des tmpfs bornés pour le travail et le home.

Les champs requis sont comparés exactement, y compris types, valeurs et URI.
Une explication autour d'un objet JSON unique n'invalide pas une réponse correcte ;
des objets contradictoires, une identité erronée ou une collection inaccessible
annoncée complète échouent. Les accès MCP sont vérifiés dans les appels réellement
exécutés. Le relais conserve les tokens et coûts rendus par le fournisseur, y compris
ceux des échecs. Une comptabilité absente ou partielle empêche une décision qualifiée.

Les seuils sont figés dans le manifeste : gain de réussite de 10 points, ou baisse
du coût par réussite de 20 % avec non-dégradation de réussite à 5 points ; intervalles
appariés à 95 % par rééchantillonnage des missions. Les répétitions d'une mission ne
deviennent pas des missions indépendantes. Toute confusion d'identité ou erreur
d'accès silencieuse interdit la poursuite. Aucune seconde campagne favorable n'est
recherchée après lecture des résultats.

## Limites et vérification

Les snapshots Task et les arborescences Mail/Messenger sont des fichiers inventés
du provider de campagne : ils ne qualifient pas les ACL ni les adapters de ces
domaines. Les latences du répertoire local sont optimistes. Les caches fournisseur
sont observés, sans remise à zéro. Les gros binaires, les lectures vidéo, FUSE et
les transports distants réels ne sont pas qualifiés par cette expérience.
Les dates métier sont explicites et l'horloge de référence est fournie dans les
consignes ; l'horloge système du conteneur n'est pas virtualisée.

```bash
make tests ARGS='tests/test_file_share_navigation.py'
```

Ces tests vérifient l'instrumentation, la pagination, les lectures bornées, les
erreurs, l'isolation des accès, les coûts et les calculs de décision. Ils n'appellent
aucun vrai modèle et ne remplacent pas la campagne ci-dessus.
