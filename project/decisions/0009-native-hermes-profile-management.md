# ADR 0009 — Gestion native des profils Hermès

- Statut : Superseded par [ADR 0058](0058-hermes-per-agent-container-isolation.md)
- Date : 2026-07-21

## Contexte

Le bridge hôte historique crée un répertoire et un conteneur Docker Compose par agent. Il
injecte les fichiers, diffuse les gros binaires, lit les journaux et exécute les commandes de
cycle de vie. Ce service reste fonctionnel, mais duplique désormais plusieurs surfaces livrées
par Hermès Agent 0.19 (`v2026.7.20`) : profils, YAML brut, environnement, `SOUL.md`, démarrage,
arrêt, redémarrage, sessions et runs annulables.

L’API de fichiers officielle Hermès limite cependant chaque fichier géré à 100 Mio. Galaris
accepte déjà des médias et artefacts plus grands. Utiliser cette API comme repli introduirait
donc une régression fonctionnelle.

## Décision

Deux modes globaux sont conservés :

- `legacy`, valeur par défaut, utilise sans modification le bridge hôte et les conteneurs par
  agent ;
- `native`, explicitement activé, représente chaque agent Galaris par un profil d’un conteneur
  Hermès officiel partagé.

En mode natif, Galaris utilise exclusivement les API officielles pour créer et supprimer les
profils, remplacer `config.yaml`, synchroniser les clés d’environnement qu’il possède, écrire
`SOUL.md` et commander le cycle de vie. Les actions de gateway sont sérialisées, car Hermès
les suit sous des noms globaux. Chaque profil reçoit un port d’API explicite et unique.

Tous les fichiers de travail Hermès, médias, scripts et skills traversent directement le volume
`/opt/data` monté aussi dans le backend. Les copies sont atomiques, en flux et à mémoire
constante. Galaris n’applique aucune limite fixe de 100 Mio et ne se replie jamais sur
`/api/files` ; les seules bornes sont alors l’espace disque, le système de fichiers et les
limites fonctionnelles propres au domaine appelant. L’activation est refusée si le volume
n’est pas visible et inscriptible.

Le déploiement de l’image reste une responsabilité Docker externe. Une surcharge Compose par
agent est refusée en mode natif au lieu d’être ignorée. L’opération de mise à jour du bouton
historique ne prétend donc pas mettre à jour le conteneur partagé.

## Conséquences

- Une installation existante ne change pas de comportement tant que son mode reste `legacy`.
- Le mode natif supprime le service hôte et le pilotage du socket Docker par Galaris.
- Les profils isolent les données et processus logiques, mais n’offrent pas la même frontière
  de sécurité que des conteneurs distincts.
- Les droits UID/GID du backend et d’Hermès doivent permettre l’écriture atomique dans le même
  volume.
- Les anciens répertoires `BASE_DIR/<agent>/data` doivent être copiés vers
  `/opt/data/profiles/<agent>` avant une migration qui doit conserver mémoire, sessions et
  répertoire de travail. Les conteneurs historiques ne sont pas supprimés automatiquement et permettent
  un retour au mode `legacy`.
- L’arrêt natif `/v1/runs/{id}/stop` est exposé par le driver ; une annulation locale tente
  aussi d’arrêter le run distant.

## Preuves dans le code

`back/bridge/hermes/native.py`, `manager.py`, `client.py`, `executor.py`,
`docker-compose.hermes.yaml`, les paramètres `BRIDGE_HERMES_*` et les tests
`back/bridge/hermes/tests/test_native.py` et `test_executor_cancellation.py`.
