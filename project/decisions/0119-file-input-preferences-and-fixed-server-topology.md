# 0119 — Préférences des fichiers entrants et topologie serveur interne

Statut : Accepted

`MESSENGER_MAX_INLINE_MB` et `PYDANTIC_AI_BINARY_INPUT_MAX_BYTES` deviennent des
paramètres persistés, administrables dans Messagerie et Harnais → Réglages avancés.
Les défauts restent 4 Mio et 20 Mio. Les bornes sont 1–1000 Mio et 1024–1 048 576 000
octets. Chaque traitement lit la limite courante ; les runtimes déjà créés ne gardent
pas de copie de configuration. Les exclusions multimédias et références restent inchangées.

DbAdmin reprend une ancienne valeur d’environnement valide uniquement si la ligne est
absente. Une valeur persistée, y compris un reset, reste prioritaire. La mise à jour
vérifie les paramètres persistés avant de retirer les anciennes variables du `.env`.

Le démarrage standard fixe explicitement Uvicorn à un worker, supprime l’influence de
`WEB_CONCURRENCY` et continue de refuser les arguments CLI multiworkers. Ceci remplace
le refus d’une ancienne variable d’environnement décrit dans la décision 0073.
La sonde de disponibilité appelle exclusivement `http://127.0.0.1:8000/api/health/ready` ;
`HEALTHCHECK_URL` n’est plus une option. Ces deux anciennes variables sont nettoyées
lors de la mise à jour. Le contrôle de disponibilité conserve son échec sur erreur HTTP
ou transport, et ne dépend ni du frontend ni d’une URL publique.

Les autres réglages d’infrastructure restent documentés dans `.env.example`, avec les
options facultatives commentées. `ENCRYPTION_MASTER_KEY` et son fonctionnement restent inchangés.
