# 0063 — Origine API dédiée aux runtimes managés

Statut : Accepted

La politique d'attachement réseau ci-dessous est remplacée par [0064](0064-shared-harness-compose.md).

## Contexte

Un runtime sur le réseau Docker interne ne peut pas dépendre du DNS public pour joindre
Galaris. L'ancien nom de réseau dérivé d'APP_NAME dans Compose divergeait en outre du nom
configuré pour les providers, isolant le backend de ses agents.

## Décision

En local, `HARNESS_MANAGER_DOCKER_NETWORK=${APP_NAME:-galaris}-net` sélectionne le réseau
applicatif de Compose. Le réseau interne des exécuteurs SSH/navigateur reste séparé ;
les harnais disposent des accès du réseau applicatif. L'origine API injectée
dans les runtimes est `HARNESS_MANAGER_GALARIS_API_URL`, avec repli compatible sur `APP_HOST/api`
lorsqu'elle est vide. Le déploiement local utilise `http://backend:8000/api`; un manager
distant conserve une origine qu'il peut effectivement joindre. L'URL publique du navigateur,
les autorisations et les tokens ne changent pas. Aucun accès Internet n'est ajouté au réseau
interne pour contourner une panne de résolution.

## Application

Changer l'environnement impose son rechargement dans le backend puis une resynchronisation
explicite des runtimes. Le correctif de code ne prétend pas modifier les configurations déjà
chargées par les processus Hermès.
