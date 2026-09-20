# 0109 — Mise à jour Compose ciblée et construction backend séparée

Statut : Accepted

## Décision

La mise à jour depuis les sources prépare les secrets et SearXNG, puis termine les builds
avant de modifier les conteneurs actifs. Elle recrée systématiquement le backend pour relancer
DbAdmin, ainsi que le frontend pour renouveler la résolution du backend par Nginx. Un unique
`docker compose up --wait` fait ensuite converger la stack, sans `down` global.

PostgreSQL, SearXNG et les exécuteurs inchangés conservent leurs conteneurs. Les services
facultatifs PostgreSQL et TURN devenus externes ou désactivés sont retirés par leurs labels
de projet et de service, sans supprimer leurs volumes ni les autres conteneurs du projet.
Les erreurs de build, de retrait des conteneurs et de disponibilité remontent à Make.
Le chemin de promotion des images qualifiées via `RELEASE_DIR` conserve son contrat distinct.

Les sondes HTTP frontend et SearXNG rendent leur disponibilité observable par `--wait`.
PostgreSQL utilise la politique `unless-stopped`, comme les autres services persistants.

Le Dockerfile backend conserve `builder` pour le développement et les tests. Un
`prod-builder` installe les seules dépendances de production, puis l’environnement Python
est copié dans `prod-stage`. Les compilateurs restent dans les stages de construction.
Le stage backend `dev-stage`, utilisé par aucun Compose du dépôt, est supprimé.

## Garanties et validation

Les montages et l’isolation des données restent identiques. Le backend de production reste
non-root, son environnement Python reste dans `/opt/venv` et son entrypoint synchronise
la base avant de servir les requêtes. Les sources applicatives sont copiées après les manifests
de dépendances afin de réutiliser leur couche lors d’une modification du code.

`make tests-update` vérifie l’absence d’arrêt global, le redémarrage ciblé, la propagation
des erreurs et les changements de modes facultatifs. Les vérifications sur conteneurs isolés
couvrent les sondes HTTP, le démarrage de l’image de production et deux mises à jour successives.
