# 0163 — Une miniature courante par document

- Statut : Accepted
- Date : 2026-10-08

## Contrat

`Document.thumbnail_id` contient le UUID du fichier WebP courant. Ce nom explicitement
demandé désigne un fichier de cache, sans table de miniatures ni clé étrangère. Il n’existe
aucun JSON annexe ni historique de miniatures. Les révisions du contenu documentaire
conservent leur fonctionnement et ne stockent pas ce pointeur.

Le fichier tient dans 320 × 320, respecte les proportions et utilise WebP sans perte.
Les sous-répertoires répartissent les documents par préfixes de UUID. Une capture remplace
la précédente ; une mutation documentaire invalide le pointeur dans sa transaction.

L’identifiant dépend du contenu et de l’instantané d’impression fourni par le lecteur.
Le serveur contrôle les droits et la version courante, puis verrouille les lignes lors
de la publication. La capture ne modifie ni la révision ni la date d’édition documentaire.
Le nettoyage relit le pointeur sous verrou pour protéger une capture concurrente récente.

DbAdmin ajoute la colonne nullable et retire les anciens JSON de révision et captures
documentaires. Ces aperçus jetables sont régénérés à la demande. Les métadonnées de pages
web du cache partagé conservent leur rôle distinct.

## Vérification

Les tests d’intégration vérifient le pointeur durable, un seul fichier courant, les droits,
la reprise après erreur ou disparition du fichier, le remplacement, la suppression et
les captures concurrentes avec une modification pendant le rendu. Le nettoyage DbAdmin
est idempotent et conserve les autres aperçus et leurs métadonnées.
