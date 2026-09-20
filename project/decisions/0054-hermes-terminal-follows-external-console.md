# ADR 0054 — Le terminal Hermès suit la Console externe gouvernée

- Statut : Accepted
- Date : 2026-08-26

## Contexte

Hermès possède un backend terminal SSH natif, tandis que Galaris possède déjà une connexion
Console par agent avec hôte, utilisateur, clé privée, passphrase, clé d'hôte et timeouts. Laisser
les deux configurations indépendantes crée deux autorités, expose le risque d'exécuter sur la
mauvaise machine et oblige l'opérateur à dupliquer des secrets.

Le client SSH natif d'Hermès fonctionne en mode non interactif et accepte une clé par chemin. Il
utilise toutefois `accept-new` par défaut, moins strict que la clé d'hôte explicitement approuvée
par Galaris.

## Décision

Pour un agent Hermès, une connexion Console active dont la cible est externe devient l'autorité du
backend terminal natif. Le bridge force `terminal.backend=ssh`, projette hôte, utilisateur, port et
timeouts après les surcharges opérateur, et place le terminal dans le home du compte distant.
L'exécuteur Console embarqué ne déclenche pas cette politique.

Le bridge déchiffre et, si nécessaire, déverrouille la clé privée pendant la synchronisation. Il
matérialise une copie OpenSSH sans passphrase et un `known_hosts` propres à l’instance avec le mode
`0600`. Des wrappers `ssh` et `scp` propres à l’instance imposent `StrictHostKeyChecking=yes`,
`IdentitiesOnly=yes`, le fichier de confiance Galaris et le timeout de connexion. Aucun contenu de
clé n'entre dans `config.yaml`, les logs ou le prompt.

La projection est réversible : l'absence d'une Console externe supprime son répertoire de secrets
et restaure les valeurs terminal présentes avant la projection. Une erreur de clé ou d'écriture
fait échouer la synchronisation au lieu d'autoriser un repli local silencieux.

## Conséquences

- l'agent travaille sur la même machine distante via les outils Console Galaris et le terminal
  natif Hermès ;
- la rotation de la connexion prend effet au prochain démarrage, redémarrage ou sync Hermès ;
- chaque conteneur Hermès conserve ses credentials dans son propre volume ;
- le harness manager générique accepte des modes de fichiers explicites afin de matérialiser les
  secrets en `0600` dans l’instance de l’agent ;
- la clé temporairement déverrouillée existe dans le volume du runtime et doit rester réservée au
  compte qui exécute Hermès.

## Preuves dans le code

`back/bridge/hermes/manager.py`, `back/bridge/harness/manager.py` et
`harness_manager/main.py`.
