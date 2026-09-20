# ADR 0028 — Référentiel Messenger local et réconciliation bornée

- Statut : Accepted
- Date : 2026-08-08
- Remplace partiellement : ADR 0011 pour le caractère éphémère des résultats d'annuaire

## Contexte

Les bridges retournaient directement des rooms, utilisateurs et historiques issus des systèmes
distants. Le reste de Galaris pouvait ainsi manipuler des objets sans identité locale durable, et
les mêmes données externes étaient reconstruites à plusieurs endroits. Une simple absence dans une
réponse distante ne prouve toutefois pas une suppression : la réponse peut être filtrée, paginée
ou volontairement limitée aux derniers messages.

## Décision

`app.messenger` possède les référentiels `messenger_rooms`, `messenger_users` et
`messenger_messages`, ainsi que `messenger_files` pour les métadonnées de pièces jointes. Chaque
donnée obtenue d'un bridge est synchronisée idempotemment avant d'être rendue au reste de Galaris,
puis la réponse canonique est reconstruite depuis la base locale. Les modèles `Room`,
`MessengerUser`, `Message` et `File` portent leurs UUID Galaris internes. Les observations privées
des bridges conservent uniquement les identifiants distants nécessaires au transport.

Le contenu binaire et le contenu extrait des pièces jointes ne sont jamais copiés dans ces tables.
`messenger_files` conserve uniquement leur UUID Galaris, leur connexion source, leur référence
distante, leur nom, leur type MIME, leur taille, leur catégorie et l'URL distante éventuelle.
La relation N↔N non historisée `messenger_message_files`, représentée par `Attachment`, rattache
les fichiers aux messages et conserve leur position dans chacun. Le bridge télécharge le contenu
à la demande depuis la messagerie d'origine.

Une room est unique par `(connection_id, external_id)` et un utilisateur par
`(tool_id, external_id)`. `messenger_room_users` représente l'appartenance courante entre leurs
UUID ; cette association n'utilise pas `HistoryMixin`. Rooms, utilisateurs, messages et fichiers
l'utilisent.
Une identité avec `agent_id` est nécessairement marquée `is_ai`, tandis qu'un agent IA externe
peut avoir `is_ai = true` sans lien vers un agent Galaris.

La réconciliation destructive est interdite par défaut. Une absence ne peut poser
`deleted_at = now()` et `deleted_by = NULL` que si le bridge certifie que la réponse est un
instantané exhaustif de la portée concernée. Une recherche filtrée, une page non terminale, une
liste partielle de membres ou une fenêtre des N derniers messages n'est jamais exhaustive. Une
ligne historisée qui réapparaît avec la même clé est restaurée, pas dupliquée.

Les autres domaines peuvent lire les modèles ORM `messenger_*`, les joindre à leurs propres
tables et renseigner leurs annotations métier locales. Ils ne contactent jamais une messagerie
source et ne réimplémentent pas son import. La création, le rafraîchissement, la réconciliation et
l'historisation des données observées à distance appartiennent exclusivement à `app.messenger` et
sont déclenchés automatiquement par sa façade.

Le bridge Nextcloud Talk certifie la liste complète des rooms visibles et les participants chargés
par l'endpoint complet d'une room. Aucun annuaire utilisateur par connexion n'est actuellement
autoritatif à l'échelle d'un Tool potentiellement partagé par plusieurs connexions : même une liste
OneBot complète pour un compte ne prouve pas qu'un utilisateur a disparu des autres comptes du
Tool. La réconciliation exhaustive des utilisateurs devra agréger toutes les sources de cette
portée avant d'activer explicitement l'historisation des absences.

## Conséquences

- Les frontières applicatives reçoivent des modèles adossés à des lignes locales.
- Les synchronisations répétées n'ajoutent ni rooms, ni utilisateurs, ni messages en double.
- Un filtre réduit enrichit la base sans historiser les lignes hors filtre.
- Les associations obsolètes sont retirées seulement après une liste complète des membres ; les
  utilisateurs eux-mêmes restent historisés séparément.
- Les autres domaines gardent des requêtes SQL simples sur `messenger_*`, sans pouvoir contourner
  le propriétaire des synchronisations distantes.
- Les colonnes textuelles historiques des messages restent transitoires jusqu'à une contraction
  Atlas distincte et vérifiée sur les données de production.

## Preuves dans le code

`back/app/messenger/models.py`, `interface.py`, `facade.py`, `journal.py`, `room_service.py`,
`user_service.py`, `back/bridge/nextcloud/messenger.py`, `back/bridge/one_bot/messenger.py` et
`back/app/messenger/tests/test_sync.py`.
