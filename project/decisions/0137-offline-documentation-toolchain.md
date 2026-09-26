# 0137 — Outillage documentaire hors ligne et confiné

Statut : accepté. Date : 2026-09-25.

## Garantie

Les commandes documentaires hors ligne produisent les mêmes cartes déterministes FR/EN
à partir du checkout courant, sans accès aux secrets, aux volumes applicatifs ni au
réseau, et sans dépendre de la stack applicative. Le générateur de navigation évalue du
TypeScript du dépôt : il est traité comme du code exécutable, jamais comme une entrée
inerte. Une préparation documentaire en échec bloque la mise à jour avant le build
applicatif plutôt que de publier un état partiel.

## Décision

`bin/documentation.sh` est l'unique point d'entrée des opérations documentaires
hors ligne : préparation, génération, contrôle des cartes, contrôle complet, révision,
inventaire, contrôle d'architecture et mise à jour explicite des baselines. Il ne
réutilise ni le Compose applicatif ni son `.env`.

Deux images minimales, construites depuis `tooling/documentation/python` et
`tooling/documentation/node`, portent les seules dépendances nécessaires : Markdown côté
Python, TypeScript côté Node, avec des versions alignées sur les verrous existants et des
contextes de build ne contenant que leurs manifestes. Les téléchargements ont lieu à la
construction de ces images ; une installation neuve n'a besoin ni du backend ni de ses
images pour préparer sa documentation.

Chaque exécution monte un instantané temporaire de sources sélectionnées par liste
positive, en lecture seule, à la place de la racine du dépôt : code analysé, déclarations
de modules, scripts de contrôle, manifestes et baselines, corpus documentaire, skills et
`AGENTS.md`, avec `.env.example` comme unique exception parmi les fichiers d'environnement.
Git, configurations locales, secrets, caches, dépendances, données et artifacts en sont
exclus. Seuls des fichiers réguliers sont retenus ; les liens symboliques sélectionnés et
leurs parents sont refusés sans être déréférencés. Les modifications, ajouts et suppressions
non committés du working tree sont pris en compte, et le contrôle des skills reste possible
à partir de la seule liste des chemins versionnés, sans `.git`.

Le code exécuté s'exécute sans réseau, avec un système de fichiers racine en lecture
seule, aucune capability, `no-new-privileges`, l'UID/GID de l'opérateur, un tmpfs borné et
des limites de mémoire et de processus ; aucun secret, volume applicatif, socket Docker ni
variable applicative ne lui est transmis, et l'entrypoint est explicite. En génération, seule
une destination temporaire est inscriptible ; les contrôles n'ont aucun montage inscriptible
persistant.

Après succès, seuls les huit fichiers attendus `project-map.{json,md}` et
`navigation.{json,md}` FR/EN sont publiés, après contrôle des liens, de la régularité des
fichiers et des destinations, par remplacement atomique et sans chmod/chown global. La
commande `architecture-baseline` possède sa propre liste de deux sorties JSON ; aucune autre
opération ne peut modifier les baselines. Une préparation travaillant sur un instantané
unique, toute modification concurrente des sources est détectée avant publication et refuse
de qualifier un état obsolète.

`bin/refresh-documentation.sh` calcule la révision via ce lanceur, puis la compare à celle du
backend actif avant de rafraîchir son index : ce dernier accès à la base reste légitime. Les
contrôles statiques et la qualification de release exécutent les mêmes contrôles confinés,
sans régénération silencieuse.

## Limites

Docker constitue la frontière d'isolation ; le TypeScript analysé n'est pas rendu sûr par
`new Function`. Ce choix ne protège pas contre un daemon Docker compromis, une modification
malveillante du lanceur lui-même, ni un secret écrit volontairement dans une source autorisée.
Il ne crée aucune ACL documentaire par page et ne change pas le déploiement de production.

## Vérification

`bin/test-documentation.sh` vérifie les contrats de fichiers avec Docker remplacé à sa
frontière de processus : instantané filtré, absence de secrets, refus des sorties
inattendues et des liens, conservation du checkout après échec, propriété des sorties et
changements non committés. `bin/test-documentation-confinement.sh`, exécuté par la
qualification statique et par `make tests-documentation`, construit des fixtures entièrement
synthétiques et un générateur hostile qui tente lectures interdites, écritures des sources
et connexion réseau : chaque tentative doit être refusée, l'instantané ne doit contenir que
les sources sélectionnées et les sorties doivent appartenir à l'opérateur.
