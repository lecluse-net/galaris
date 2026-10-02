# 0154 — Catalogue privé des ressources rencontrées

Statut : accepté. Date : 2026-10-01.

## Décision

File Share possède les identités par agent, connexion, empreinte SHA-256 de configuration
persistée et runtime. L'empreinte inclut les paramètres globaux et locaux chiffrés ; aucun
credential déchiffré ne rejoint le catalogue. Les observations sont prises dans la façade
Python publique, sous contrôle du mode d'indexation du Tool et du transport réellement
résolu. Mail, Documents, Memory, Galaris, Web et Messenger sont exclus.

Un port Memory transactionnel crée des projections privées, gérées, protégées de l'oubli
ordinaire, de nature `file`/`directory`. Le lexical est immédiatement disponible sans appel
de modèle. Les notes passent par un port explicite et sont conservées lors des mises à
jour. Le titre et le contenu sont aussi éditables dans l'éditeur Memory existant. Les champs
modifiés manuellement sont préservés lors des observations suivantes ; l'identité et les
références source restent gérées par le catalogue. Une réconciliation idempotente rend les
anciennes fiches éditables sans annuler un verrouillage ultérieur choisi par l'utilisateur.
Les listes directes prouvent des relations `parent_of`, jamais la suppression des
absents. Les octets externes restent chez leur provider.

Une suppression réussie crée une tombe datée au début de l'opération, même si la source
n'était pas cataloguée. Les anciennes réponses ne ressuscitent pas une source supprimée.
Une réapparition crée une nouvelle identité sans reprendre ses anciennes notes. Un
renommage prouvé dans le même binding conserve l'identité ; un écrasement ou transfert
entre bindings ne fusionne pas les notes.

Memory reçoit des contrôles source enregistrés à la composition : prédicat SQL pour
connexion/configuration/présence, puis vérification distante à la lecture et à l'admission
des résultats. Memory ne résout pas lui-même les transports. Les inspections administratives
explicites conservent leur accès aux projections retenues.

## Limites

L'observation est synchrone et coalescée ; une panne retourne un statut distinct sur le
résultat de fichier réussi, sans refaire la mutation externe. Le parcours périodique,
la réparation durable, Dream et les diagnostics sont définis par la
[décision 0155](0155-durable-file-indexing.md). La couverture dépend des capacités réelles
du provider et des budgets ; une observation seule ne prouve aucune complétude.
