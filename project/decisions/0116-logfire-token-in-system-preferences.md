# 0116 — Token Logfire dans les préférences Système

Statut : Accepted

## Décision

`LOG_LEVEL` reste un réglage de bootstrap dans le `.env` : les logs doivent être disponibles
au niveau choisi avant tout accès à PostgreSQL. Les consommateurs console, SQL, WebSocket
et filtrage Logfire conservent ce réglage.

`LOGFIRE_TOKEN` devient un paramètre administrable chiffré, masqué à la lecture, dans
Préférences → Système. Il est facultatif et vide par défaut. C’est un identifiant fourni
par Logfire, pas un secret que Galaris peut générer : sa valeur historique est reprise une
seule fois si le paramètre est absent. Les préférences existantes ont ensuite priorité.
Le nettoyage de mise à jour retire cette variable après vérification du stockage durable.

L’instrumentation démarre localement avant la base. Après chargement des paramètres, elle
active l’export si un token est configuré. Un listener réagit aux modifications : la
reconfiguration du SDK Logfire remplace les providers derrière leurs proxies, sans doubler
les instrumentations. L’opération est sérialisée dans un thread pour ne pas bloquer la
boucle API lors de l’arrêt des anciens exporteurs. Les spans en cours de changement peuvent
être incomplets ; les logs locaux restent disponibles.

Un token vide force `send_to_logfire=False` : aucune ancienne variable ni credentials
Logfire ne peut réactiver cet export implicitement. Une erreur de reconfiguration est
journalisée sans token ni traceback de variables locales ; réenregistrer le token ou
redémarrer retente l’application. La réussite du stockage ne valide pas le token auprès
du service Logfire ; cette vérification appartient au SDK.

`ENCRYPTION_MASTER_KEY` reste strictement inchangée. Les tests remplacent la frontière
SDK pour ne transmettre aucune télémétrie externe. Ils couvrent le démarrage sans base,
la confidentialité, la persistance, les droits, l’activation, le remplacement, l’effacement
et la reprise après erreur sans réinstaller les instrumentations.
