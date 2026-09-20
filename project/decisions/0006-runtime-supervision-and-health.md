# ADR 0006 — Supervision du runtime et santé

- Statut : Accepted
- Date : 2026-07-20

## Contexte

Les tâches, messages et processus disposent de garanties durables de reprise, mais plusieurs
boucles racines vivent en mémoire : scheduler de tâches, réconciliation des listeners de
messagerie et listeners d’appels vocaux. Chaque domaine savait arrêter sa boucle et souvent
absorber ses erreurs, sans vue commune lorsqu’une tâche racine se terminait malgré tout.

L’ancien endpoint `/api/health` confirmait seulement qu’une requête HTTP recevait une réponse.
Le healthcheck Docker du backend passait en outre par le frontend, ce qui mélangeait la santé du
processus backend et celle du proxy. Un backend ou un frontend terminé ne possédait pas non plus
de politique de redémarrage en production.

## Décision

`core.runtime` fournit un superviseur générique sans import vers `app` ou `bridge`. La racine de
composition `main.py` lui enregistre les services avec quatre informations : nom, démarrage,
arrêt, sonde `is_running` et criticité.

Le superviseur :

- démarre les services dans l’ordre déclaré et les arrête dans l’ordre inverse ;
- détecte une tâche racine terminée et la relance après un backoff exponentiel borné avec jitter ;
- nettoie le service précédent avant toute relance afin de ne pas créer deux listeners ;
- ne possède aucun état métier et ne remplace ni leases, ni idempotence, ni reprise PostgreSQL ;
- expose uniquement des états et compteurs non sensibles à la readiness publique.

Le scheduler de tâches est critique. Les listeners de messagerie et de voix sont facultatifs :
leur indisponibilité rend le runtime `degraded` sans bloquer l’API. PostgreSQL est une sonde
critique bornée par un timeout.

Les contrats HTTP sont séparés :

- `/api/health` reste compatible avec les consommateurs historiques ;
- `/api/health/live` confirme que le processus ASGI répond ;
- `/api/health/ready` renvoie `503` lorsqu’un composant ou une dépendance critique manque,
  `200` pour `ready` ou `degraded`.

Le healthcheck Docker interroge directement la readiness locale du backend. Les conteneurs
backend et frontend utilisent `restart: unless-stopped` pour récupérer après la fin du processus.

## Conséquences

- Une panne partielle d’une boucle racine devient visible et récupérable automatiquement.
- Une panne d’un bridge optionnel ne provoque pas une boucle de redémarrage globale.
- Les domaines restent propriétaires du nettoyage de leurs enfants et de leur reprise durable.
- Ajouter un nouveau service long exige un petit contrat de cycle de vie plutôt qu’un import de
  son implémentation dans `core`.
- Les probes externes doivent rester rapides, bornées et dépourvues de secrets dans leur réponse.

## Preuves dans le code

`core.runtime`, le lifespan de `back/main.py`, `core.api`, les fonctions `is_running` de
`app.task`, `app.messenger` et `app.voice`, `back/scripts/healthcheck.py`,
`compose.yaml` et les tests de supervision et de santé.
