<p align="right"><strong>Français</strong> · <a href="../../en/components/ssh-executor.md">English</a></p>

# Exécuteur SSH embarqué

Ce service Debian fournit l'environnement Linux persistant standard des agents `internal`.
Il n'expose aucun port sur l'hôte : le backend y accède via le réseau Docker privé pour SSH/SFTP
et via un socket Unix privé pour les seules opérations de management autorisées.

Le volume applicatif unique `galaris_data` est monté dans `/data` par le backend et cet exécuteur.
Les données de la Console embarquée sont regroupées sans montage supplémentaire :

- `/data/ssh-executor/home` conserve les homes et les dépôts Git des agents ;
- `/data/ssh-executor/state` conserve le registre des UID, les clés hôte et les clés publiques ;
- `/data/ssh-executor/run` porte le socket privé partagé avec le backend.

Le montage `/data` de ce service est déclaré avec celui du backend dans `compose.override.yaml`.
Le service lui-même est toujours défini et démarré par le `compose.yaml` standard, afin que chaque
installation puisse proposer la Console locale sans migration d’infrastructure ultérieure. Les
connexions Console vers des hôtes SSH externes restent également disponibles.

Un compte n'est créé qu'au provisionnement explicite d'un agent depuis la page Console. Son login
est exactement `Agent.code`; un code incompatible avec Debian est refusé sans transformation.
Les mots de passe SSH sont désactivés et les clés publiques, contrôlées par root, restent hors du
home. La clé privée correspondante demeure chiffrée dans Galaris.

Commandes usuelles :

```sh
make status-executor
make logs-executor
docker compose exec ssh-executor bash
make restart-service SERVICE=ssh-executor
make backup-executor
```

Pour utiliser une autre machine, il suffit de créer ou modifier la connexion `console` de l'agent
avec ses paramètres SSH, SFTP et sa clé hôte épinglée. Aucun composant du driver ne change.
Le mode est détecté automatiquement : une cible reste en mode standard tant qu'un
`galaris-exec --version` fonctionnel n'est pas trouvé. Après un test SSH réussi,
l'interface peut installer ou mettre à jour le helper versionné dans
`~/.galaris/bin/galaris-exec`, sans droit root, puis vérifier la capacité de reprise
`operation_recovery_available`. Le bouton reste disponible pour un helper v1, même en mode
enhanced. La détection préfère un helper v2 disponible à une installation utilisateur v1.
La cible externe doit fournir `/bin/bash` et Python 3.11 ou ultérieur ; le helper conserve
cette compatibilité indépendamment de la version Python du backend.

Les commandes courtes utilisent `console_exec`. Séparer les modifications des suites de tests
ou compilations longues, lancées par `console_start` et suivies avec `console_poll` sur le même
identifiant. À la reprise, un reçu `running` confirme le lancement de `console_start`, mais ne
termine pas un `console_exec` interrompu. Une issue inconnue reste bloquée ; la mise à jour du
helper ne peut pas recréer les reçus absents des anciennes opérations.
