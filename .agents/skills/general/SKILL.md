---
name: general
description: Principes de travail transversaux du dépôt Galaris — environnement Docker, commandes Make, hot reload, dépendances, sécurité du worktree et validation. À utiliser pour toute modification, investigation ou documentation dans ce projet.
---

# Travailler dans Galaris

## Préserver le contexte

1. Lire `git status --short` avant toute édition.
2. Considérer les modifications présentes comme appartenant à l’utilisateur.
3. Inspecter les contrats, tests et surfaces publiques avant de proposer une structure.
4. Consulter `AGENTS.md`, `docs/fr/dev/README.md` et la cartographie générée du projet.
5. Limiter le diff à la demande ; ne pas profiter d’un changement pour réécrire un domaine.

## Utiliser Docker et Make

La machine hôte ne fournit pas la toolchain du projet. Exécuter Python, uv, Node, npm, Atlas
et PostgreSQL dans leurs conteneurs. Préférer les cibles réelles de `Makefile` :

| Commande | Usage |
|---|---|
| `APP_ENV=dev make start` | Démarrer la stack de développement |
| `make logs-back` / `make logs-front` | Diagnostiquer un service |
| `make tests` | Exécuter les tests backend avec une base éphémère |
| `make tests ARGS='app/task/tests/test_workflow.py -k transition'` | Cibler un test |
| `make typecheck` | Pyright strict, vue-tsc et parité i18n |
| `make architecture-check` | Vérifier frontières et documentation générée |
| `make project-context` | Régénérer la cartographie déterministe |
| `make sync-db` | En développement, faire converger schéma et datasets avec DbAdmin sans redémarrer |
| `make update` | Reconstruire les images avec cache, redémarrer, synchroniser la base et attendre les services |

Ne jamais lancer `pytest` dans le backend de développement : les tests doivent passer par la
base isolée créée par `make tests`.

## Respecter le hot reload

Les changements Python et Vue sont rechargés automatiquement en mode développement. Ne pas
faire `make restart` après une simple édition. Redémarrer seulement après un changement de
configuration, de compose ou de dépendances qui l’exige.

## Gérer les dépendances

- Backend : déclarer dans `back/pyproject.toml`, puis utiliser `make upgrade-deps-back`.
- Frontend : déclarer dans `front/package.json`, puis utiliser `make upgrade-deps-front`.
- Conserver `back/uv.lock` et `front/package-lock.json` cohérents avec les manifestes.
- Ne pas installer une dépendance directement sur l’hôte.

## Gérer configuration et données

- Ajouter toute variable permanente à `.env.example` et à la classe de settings concernée.
- Ne jamais exposer le contenu de `.env` ni un secret dans les logs, tests ou réponses.
- Utiliser `core.dbadmin` via `make sync-db` en développement ; Atlas reste interne et Galaris
  n’utilise pas Alembic.
- En production, ne pas lancer la synchronisation séparément : `make update` redémarre le backend,
  dont l’entrypoint applique le schéma et les données avant de servir le trafic.
- Traiter `make clean` comme destructif : il supprime les volumes.

## Respecter les formats éditoriaux

Lire `docs/fr/dev/editorial-html.md` pour tout champ éditorial. Documents HTML, contenus Memory,
objectifs Task, description/suivi Goal et personnalité/fiche de poste Agent utilisent des
fragments HTML et leur profil versionné. Les prompts, exemples d'outils et tests doivent porter
ce contrat. Ne pas généraliser la conversion aux titres, messages de transport, JSON, code,
fichiers Markdown ou `SKILL.md`. Pour les agents connectés, maintenir aussi
`back/app/skill/system_skills/galaris/SKILL.md`.

Un Dataset est un document (`node_kind=document`, URI `document://`) de type immuable
`document_type=dataset`, au contenu JSON UTF-8 validé. Il conserve titre, icône, classement,
partage et révisions ; CodeEditor JSON remplace CKEditor. Ne pas le convertir en HTML.
Le défaut `html` conserve les documents existants. Aucun autre type n'est encore activé.

Les documents HTML acceptent directement formulaires, CSS et JavaScript. La barre d'outils
et l'édition normales restent présentes ; seul le bouton Source montre le code. Ne pas ajouter
de mode lecture/édition, de manifeste à rédiger ou d'assistant de formulaire. Lire
`docs/fr/dev/document-apps.md` pour l'isolation interne, le pont Dataset et les lecteurs inertes.
L'accès applicatif aux Datasets exige un accord personnel côté serveur pour la révision
courante, distinct des ACL et du HTML généré. Cet accord se gère depuis la barre du document,
jamais depuis le SDK ou MCP. Les quotas d'écriture serveur sont partagés entre applications.

Lorsqu'un résultat appelle un contenu rédigé durable à conserver, réviser ou partager,
les documents Galaris en sont le support canonique. Une Task ne nécessite pas à elle seule
un document ; les échanges restent dans la conversation et l'état dans la ressource métier.
Privilégier le document pertinent existant :
une URI `document://` stable, enrichie au fil du travail, plutôt que des fichiers Markdown
ou HTML concurrents. Galaris, Conversation, Memory et File Sharing sont des services système
obligatoires, aux connexions et autorisations non modifiables. Les ACL des ressources et les
restrictions de contexte restent applicables. Le contrat complet est dans
la section « Documents comme pivot de l'information » de `docs/fr/dev/editorial-html.md`.

## Valider proportionnellement

Exécuter les tests ciblés, puis les contrôles du domaine. Pour une livraison complète, lancer
`make typecheck`, `make architecture-check`, les tests pertinents et `git diff --check`.
Régénérer la cartographie si les modules, routes, modèles, outils MCP ou settings changent.
