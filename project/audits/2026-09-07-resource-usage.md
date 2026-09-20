# Réduction des ressources au repos — 7 septembre 2026

## Périmètre

Hot reload conservé. Aucun réglage de concurrence des Tasks, de base de données, de conservation
ou de cache des fichiers n’est modifié. Le worktree contient d’autres travaux en parallèle.

- Exécuteur navigateur : lancement paresseux de Chromium, fermeture lorsque le nettoyage ne
  trouve plus de session occupée, réveil sérialisé. Les créations en attente comptent comme
  occupées ; les actions restent protégées par la file de leur session.
- Frontend : rafraîchissements périodiques des statuts et journaux de harnais, des deux panneaux
  d’évaluation Lab et de l’activité LLM suspendus lorsque `document.hidden` est vrai. Reprise
  immédiate à la visibilité, sans chevauchement des appels périodiques. Les requêtes en cours
  terminent normalement. Les mises à jour websocket de l’activité LLM restent reçues, mais leur
  relecture de l’historique attend la visibilité. Les actions explicites restent disponibles.
- Fermeture d’un écran : suppression des timers et listeners, y compris si la réponse à un
  chargement initial de la page Agents arrive après sa destruction.

## Mesure comparative isolée

Deux conteneurs temporaires de la même image `galaris-browser-executor`, sans réseau externe,
avec les sources navigateur d’avant modification et celles du worktree montées en lecture seule.
Le service installé n’a pas été redémarré. Les conteneurs temporaires ont été supprimés.

Scénario identique : attente du `/health`, mesure `docker stats --no-stream`, cinq rendus HTML
statiques successifs via `/v1/render-html` suivis de `/v1/close`, nouvelle mesure, puis 22 secondes
sans requête et dernière mesure. TTL fixé à 10 secondes dans les deux conteneurs pour raccourcir
le test ; le défaut de l’application reste 120 secondes.

| Mesure RAM Docker | Avant | Après |
|---|---:|---:|
| Démarrage, aucun rendu | 132,8 Mio | 88,26 Mio |
| Après cinq rendus | 141,7 Mio | 142,6 Mio |
| Après nettoyage au repos | 141,7 Mio | 93,19 Mio |

Gain au repos dans ce scénario : 48,51 Mio, soit 34,2 % de la mémoire de cet exécuteur.
Ce pourcentage ne concerne pas l’application entière. Le CPU était proche de zéro des deux côtés ;
aucun gain CPU global n’est établi par cette mesure. Une seule exécution comparative ne permet
pas de conclure sur les percentiles de latence ou un comportement en charge.

Durées render + close, en ms :

- avant : 1133, 1111, 1098, 1099, 1101 ;
- après : 1198, 1113, 1100, 1099, 1101.

Le lancement paresseux ajoute ici 65 ms au premier rendu ; les quatre suivants sont comparables.
Le contrôle de rafraîchissement est également mesuré avec une horloge simulée : 30 appels sur
une minute visible à intervalle de 2 secondes, aucun appel sur la minute masquée suivante,
puis exactement un appel immédiat au retour. Ces nombres mesurent les callbacks du mécanisme,
pas la consommation CPU ni le trafic réel de l’ensemble des écrans.

## Non-régression

- Tests Chromium HTTP réels : admission concurrente, capacité libérée, expiration, arrêt effectif
  du processus navigateur, réveil après veille et récupération après crash forcé.
- Tests de cycle de vie : lancement partagé, fermeture pendant une nouvelle demande, échec
  de lancement puis nouvelle tentative, arrêt pendant un lancement et protection des sessions.
- Tests frontend : visibilité initialement masquée, requête lente, aller-retour de visibilité
  pendant la requête, réponse après fermeture, erreur réseau puis reprise.

Résultats : `make tests-browser` (17/17), suite frontend (391/391), `npm run type-check`,
`npm run lint`, `npm run i18n-check` et `npm run build` réussis. `make typecheck` est bloqué par huit erreurs
dans `back/app/lab/mechanism_evaluation_service.py` et `back/core/runtime.py`, tous deux déjà
modifiés hors de ce travail. Après régénération, `make architecture-check` reste bloqué par
les liens de langue et frontières du module de prévisualisation en cours de refonte, ainsi
que la suppression d’une ancienne entrée de baseline. Aucune baseline n’a été élargie.

La partie frontend profite du hot reload. Les sources de l’exécuteur navigateur sont copiées
dans son image : la veille sera effective sur le service installé après reconstruction et
recréation de ce seul conteneur. Cette opération n’a pas été imposée aux sessions en cours.
