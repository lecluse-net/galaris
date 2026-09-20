# 0120 — Sélection Git et cycle de vie des conteneurs

Statut : Accepted — 2026-09-18.

## Décision

Cette décision complète 0109 : seul un `VERSION` explicite déclenche une récupération Git
avant la construction et exige la présence locale de `.git`, répertoire ou fichier de worktree.
Sans `VERSION`, les sources présentes sont construites sans récupération ni sélection Git,
y compris avec des changements locaux, un HEAD détaché ou sans upstream.
Avec `VERSION`, après fetch des branches et tags du remote de la branche
courante (ou `origin`), un tag exact prime sur une branche distante exacte. Une branche
existante avec des commits absents du remote n’est jamais réinitialisée.

Lors d’une sélection explicite, les sources modifiées localement, une référence inconnue ou
un échec Git arrêtent la commande avant toute action sur les conteneurs. Le checkout et le merge
protègent aussi les fichiers ignorés, notamment `.env` et les overrides Compose. Il n’y a
ni stash automatique, ni reset forcé.

Après sélection, Make est relancé avec `GIT_UPDATE=0` pour charger le Makefile et les
scripts de la version choisie sans nouvelle récupération Git. Sans `.git`, le chemin de construction locale
reste disponible, mais `VERSION` est refusé. Aucune distribution Docker Hub n’est ajoutée.
Le chemin de promotion `RELEASE_DIR` conserve ses images qualifiées, ignore Git et refuse
un `VERSION` simultané.

`install` prépare la configuration avant personnalisation : PostgreSQL intégré par défaut,
puis un port TCP libre (8484 par défaut) écrit dans `APP_HOST` et l’override nouvellement créés.
Les ports écoutés sur l’hôte et publiés par Docker sont vérifiés ; les fichiers existants
sont conservés. L’opérateur peut ensuite adapter `.env`, les ports, volumes et réseaux de
l’override, puis lancer `make start`. `start` réutilise les conteneurs
arrêtés ou sains ; une stack absente, incomplète ou en échec déclenche au plus un
`update GIT_UPDATE=0`. Une erreur d’inspection Docker n’est pas une installation absente.
`stop` conserve les conteneurs ; `uninstall` retire conteneurs et réseaux sans leurs volumes
ni la configuration ; `clean` retire aussi les volumes. `build` ne modifie pas les conteneurs.

Avant de démarrer les services après construction ou chargement d’une release, un conteneur
éphémère prépare la racine de `/data` pour l’utilisateur `app` de l’image backend sélectionnée.
Un répertoire témoin garde le volume non vide pour empêcher Docker de réappliquer les droits
de l’image SSH lors de sa création. Les propriétaires des données existantes et des répertoires
privés de l’exécuteur ne sont pas modifiés récursivement.

## Validation

`make tests-update` exerce les recettes Make avec Docker remplacé à la frontière du processus.
La sélection de version utilise de vrais dépôts Git éphémères et un remote local : avance
de branche, priorité des tags, worktree, Makefile mis à jour, changements locaux, divergence,
configuration ignorée, erreurs de fetch et absence de Git. Une relance Docker réelle isolée
a également vérifié la conservation des conteneurs arrêtés et des initialiseurs terminés.
`make tests-install` exerce une installation réelle sur volumes neufs, la disponibilité HTTP
à travers le frontend et la conservation des conteneurs après arrêt et démarrage.
