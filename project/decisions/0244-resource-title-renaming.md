# 0244 — Renommage des ressources sans remplacement de contenu

Statut : acceptée. Date : 2026-10-26.

## Contexte

Les outils de fichiers génériques permettent d'écrire le corps d'un Document ou Dataset,
mais pas son titre. Un déplacement ne convient pas aux ressources dont l'URI porte un UUID.

## Décision

Exposer `file_rename(uri, name, expected_lock_version)` sous le Tool `file_sharing`.
Pour `document://` et `data://`, déléguer aux opérations de métadonnées du domaine propriétaire.
L'URI, le contenu, les révisions de contenu, les pièces jointes et les droits sont conservés.
Le jeton de métadonnées `lock_version` est obligatoire et publié par `file_info` ; la révision
de contenu seule ne protège pas contre deux renommages concurrents.

La capacité `rename` est annoncée pour les ressources éditables ; les titres pilotés par
un Goal restent protégés. Le contrôle du périmètre traite le renommage comme une mutation
`file.write` de l'URI existante, sans nouvelle autorisation ni livraison.
Pour les providers à chemins mutables, renommer conserve le parent, refuse l'écrasement
et retourne la nouvelle URI. Les autres providers restent refusés.

## Vérification

Les scénarios synthétiques de `app/file_share/tests/test_resource_rename.py` exercent le
chemin MCP et la persistance, les droits et conflits, les titres protégés, la conservation
du contenu, des révisions et des pièces jointes, et les collisions de noms à chemins.
Le skill Galaris distingue titre de ressource, titre HTML, contenu et référence stable.
