# 0152 — Indexation par les paramètres standards des Tools

Statut : accepté. Date : 2026-10-01.

## Décision

Déclarer `tools.fileindexing` dans `connection_schema.params`, avec les choix fixes `excluded`
(défaut), `known_uris`, `recursive`, bornés par les capacités du provider. Utiliser exclusivement
les valeurs globales `Tool.global_params` et les surcharges EAV `ConnectionParam`, avec les mêmes
routes, permissions, validation, effacement et héritage que les autres paramètres. Une valeur
globale imposée gagne sur les surcharges locales. Console accepte cette configuration sans
autoriser l'édition de sa définition SSH ; la cible embarquée conserve ses credentials gérés.

Les définitions fournies par le logiciel portent `builtin=true` : leurs libellés et choix sont
traduits côté frontend, y compris sur un Tool personnalisé. Les autres libellés personnalisés
restent littéraux. Aucune liste déroulante ni route de configuration dédiée à l'indexation.

DbAdmin reprend une ancienne préférence `file_indexing_mode` dans le paramètre global uniquement
lorsque celui-ci est absent, sans écraser une valeur standard déjà enregistrée. L'ancienne colonne
est conservée comme source de compatibilité pendant cette transition ; aucun consommateur
d'indexation ne la lit. Sa suppression appartient à une contraction ultérieure, après vérification
de la reprise des données. La synchronisation des Tools intégrés conserve les valeurs globales.

Mail, les ressources Memory/Documents/Galaris/Web et les transports Messenger restent
hors du catalogue prévu. La préférence de fichiers d'un Tool mixte ne rend pas ses PJ
Messenger indexables. Les accès source restent vérifiés séparément pour chaque connexion.

Console propose actuellement les URI connues, Nextcloud le parcours reprenable, AFFiNE
et Grav les URI connues. Les consommateurs d'indexation doivent utiliser la valeur effective de chaque
connexion. Leurs règles d'admission restent fournies par File Share.

## Conséquences

Une préférence n'accorde aucun accès et n'atteste aucune couverture. Le défaut ne lance
aucune acquisition sur les installations existantes. Un nouveau provider doit annoncer
explicitement le parcours s'il le supporte. Les branches Messenger d'un Tool mixte doivent
être exclues lors de la résolution réelle des observations et racines du futur scanner.
