# Diagnostics manuels

Ces scripts sont exclus de la collecte pytest. Ils servent à observer une installation,
un fournisseur, un harnais ou un canal configuré. Des sorties console ne constituent pas
un test automatisé réussi.

Après lecture du script et configuration de ses entrées, lancer depuis la racine du dépôt :

```bash
docker compose exec backend python scripts/manual_test.py tests/manual/<script>.py
```

Elle utilise le backend de développement et ses connexions : certains scripts appellent
un fournisseur, déclenchent un agent ou envoient des messages. Ils ne sont pas exécutés
par les suites isolées. Pour des garanties reproductibles, écrire un test dans le domaine
concerné et le lancer avec `make tests` sur PostgreSQL éphémère.

`test_message_history.py` compare deux appels avec/sans historique par inspection des
résultats ; ce n'est pas une assertion de pertinence générale du modèle. Le squelette vide
`test1.py` a été retiré. L'ancien diagnostic frontend 3D est désormais automatisé dans
`front/browser-tests/model3d.spec.mjs` via `make tests-front-components` et la CI.

Voir [les couches et limites de validation](../../../docs/fr/dev/testing.md).

`memory_relevance.py` utilise un agent choisi explicitement par `MEMORY_PROBE_AGENT_ID` et
un jeu de requêtes choisi par `MEMORY_PROBE_CASES`. Le fichier fourni
`memory_relevance_examples.json` contient uniquement des exemples inventés et des UUID de
démonstration : préparer un corpus de test dédié et adapter ses ancres dans un fichier
`*.local.json`, ignoré par Git. Le script ne crée aucun contenu et n'enregistre aucun accès LLM.
Ses résultats JSON ne contiennent que des nombres, rangs, durées et indicateurs d'erreur ; ni requêtes,
ni titres, ni extraits, ni identifiants de ressources ne sont exportés.
Le lanceur et les bibliothèques peuvent aussi émettre des journaux techniques : une capture
brute de la console reste un diagnostic local, pas un export public.

Les anciens scripts et jeux de questions issus du corpus privé ont été retirés. Les rapports
historiques conservent seulement leurs mesures agrégées et conclusions techniques. Les
exemples synthétiques ne reproduisent pas ces campagnes et ne reprennent pas leurs scores.
Les garanties de recherche, de passage lisible et d'isolation restent couvertes par
`app/memory/tests/test_document_retrieval.py` et les tests de droits du domaine.

Les diagnostics Talk exigent `TALK_ROOM_TOKEN` ; `TALK_CONNECTION_ID` permet de choisir la
connexion. `executor.py` exige `MANUAL_TASK_ID`. Ne jamais enregistrer les identifiants réels
dans le code. Les traces audio sont écrites sous `/tmp/galaris-diagnostics/` dans le conteneur,
hors du dépôt ; elles peuvent contenir des données privées et ne sont pas des artefacts publics.
Les fichiers `*.log`, `*.jsonl` et `*.local.json` de ce répertoire sont ignorés par Git.
