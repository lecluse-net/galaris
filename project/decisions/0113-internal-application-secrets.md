# 0113 — Secrets applicatifs internes sans configuration opérateur

Statut : Accepted

## Décision

La clé de signature `AUTH_SECRET_KEY` est conservée chiffrée dans un paramètre interne.
DbAdmin génère une clé aléatoire lorsque le paramètre interne est absent, sans lire
l’ancienne variable d’environnement. Les synchronisations suivantes conservent la valeur.
Une valeur manquante dans une ligne existante ou impossible à déchiffrer arrête
le démarrage ; aucune rotation automatique ne remplace une clé persistée.

Les paramètres internes ne figurent pas dans la liste HTTP et ne sont pas modifiables,
même par un administrateur. Le processus charge la clé avant les services et les requêtes.
Cette valeur stable protège aussi les condensats MFA et les renouvellements de session.

Le secret du navigateur reste un secret partagé par fichier. Un conteneur d’initialisation
sans réseau, utilisant l’image du navigateur, crée atomiquement un fichier persistant dans
un volume dédié. Les deux consommateurs montent ce volume en lecture seule et disposent
du groupe technique 19998 ; le fichier est lisible uniquement par son propriétaire et ce
groupe. L’initialiseur génère son propre token et ne reçoit aucune ancienne variable.
Un fichier existant invalide arrête l’opération au lieu d’être écrasé.

`ENCRYPTION_MASTER_KEY` et WebRTC ne changent ni de valeur ni de stockage.
La décision 0115 applique aussi la génération interne à Web Push.
Les sauvegardes incluent toujours `.env`, la base et le nouveau volume navigateur.

Le router webhook générique obsolète ne déclare plus de routes. Le module et son contrat
restent déclarés pour conserver la traduction métier en vue d’une éventuelle modernisation. Les anciens tests
de parsing HTTP sont remplacés par la garantie que l’endpoint ne peut plus être appelé ;
les garanties d’idempotence du service métier restent testées.

Après un démarrage sain, une vérification en lecture seule valide les secrets persistés
avant de supprimer uniquement `AUTH_SECRET_KEY`,
`BROWSER_EXECUTOR_TOKEN` et `AUTH_WEBHOOK_TOKEN` du `.env`. Un échec conserve le fichier.

Le premier passage depuis l’ancienne configuration invalide les anciens jetons d’accès
et codes de secours MFA. Cette réinitialisation est acceptée pour l’unique instance
actuelle ; les mots de passe, le TOTP et les données chiffrées restent conservés.

## Validation

Les tests couvrent la génération indépendante du `.env`, la répétition sans rotation, les sessions
signées et codes MFA conservés, le déchiffrement de données préexistantes avec la même clé
maître, les refus de l’API Params, la disparition des routes webhook et les requêtes réelles
du navigateur authentifiées avec le fichier partagé.
