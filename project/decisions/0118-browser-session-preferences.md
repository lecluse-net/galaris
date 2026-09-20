# 0118 — Limites des sessions Browser dans les préférences

Statut : Accepted

## Décision

`BROWSER_SESSION_TTL_SECONDS` et `BROWSER_MAX_SESSIONS` rejoignent `params` et
Préférences → Navigateur, avec les mêmes conditions de visibilité et droits que les
autres réglages du Tool. Leurs défauts sont 120 secondes (10–3600) et 32 sessions (1–256).
Cette décision remplace leur maintien dans `.env` prévu par la décision 0005.

Le backend les transmet avec chaque opération authentifiée. Le sidecar vérifie la
capacité au moment d’admettre une création, en comptant celles déjà en cours ; abaisser
la limite ne détruit aucune session. Chaque session conserve le délai de sa dernière
opération. Les actions en cours ou acceptées dans la file empêchent son expiration.
Le nettoyage passe toutes les dix secondes. Les exports PDF restent indépendants.

DbAdmin initialise les lignes absentes et peut reprendre une ancienne valeur valide ;
une valeur déjà persistée, y compris un reset, reste prioritaire. Après vérification
du stockage durable, `make update` retire ces deux variables devenues obsolètes.

Les réglages WebRTC restent de la configuration de déploiement, car coturn et Compose
les utilisent. Le modèle `.env.example` commente leurs valeurs par défaut ; le secret
partagé généré et l’adresse de relais calculée restent actifs. Aucun changement de
valeur, de stockage ou de lecture d’`ENCRYPTION_MASTER_KEY` n’est introduit.
