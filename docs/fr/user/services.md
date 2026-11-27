<p align="right"><strong>Français</strong> · <a href="../../en/user/services.md">English</a></p>

# Ajouter et partager des services

Un **Service** représente un fournisseur, comme Nextcloud ou GitLab, ou une fonction
intégrée de Galaris. Ses protocoles donnent accès aux fichiers, à la messagerie ou à une
API. Une **Connexion** relie un agent à ce service avec ses paramètres et ses identifiants.
Les fonctions MCP restent les opérations que l'agent peut appeler.

<a id="connect-service"></a>
## Connecter un agent à un Service du catalogue

1. Dans **Configurer → Services & connexions**, ouvrez l’onglet **Services** et choisissez **Nouveau service**. Recherchez le fournisseur puis sélectionnez **Configurer une copie**.
2. Dans l’éditeur, vérifiez le nom, l’adresse propre à votre installation et les protocoles dont vous avez besoin. Enregistrez le Service.
3. Dans **Connexions**, créez ou ouvrez la connexion de l’agent concerné à ce Service. Renseignez les paramètres du compte. Pour un test, sélectionnez cette connexion afin de vérifier les identifiants de cet agent.
4. Dans **Autorisations**, vérifiez la fonction que l’agent doit utiliser. Pour l’appeler directement depuis le Chat avec un Service personnalisé, activez-la aussi dans **Outils en conversation** sur la carte du Service.

Par exemple, une équipe peut configurer un Service GitLab pour son instance. Chaque agent utilise ensuite sa propre connexion. Pour vérifier le résultat, demandez à l’agent de lister ses projets et comparez la réponse avec les projets accessibles à son compte.

## Consulter et actualiser les fiches

Dans **Services & connexions → Services**, les cartes montrent l'icône, un extrait de
description, les capacités et le nombre de connexions existantes, actives ou désactivées.
Les commandes en bas de carte permettent l'export, les paramètres, l'édition et la suppression
selon vos droits. Les services internes reprennent autant que possible les icônes du menu,
en bleu, et ne sont pas exportables. Sans icône personnalisée, l'icône du menu Services est utilisée.
Cliquer sur le nom ou la description ouvre sa fiche complète.

La même icône accompagne le service dans la liste des connexions, les filtres et les
listes de sélection, notamment pour créer une connexion ou régler les autorisations.

Le catalogue initial propose Qonto, Nextcloud, GitLab, Matrix, n8n, Redmine et Telegram.
Les fiches expliquent les capacités proposées. Une API REST ne garantit pas toutes les
fonctionnalités du produit ; les droits et limites du fournisseur continuent de s'appliquer.
Pour une API auto-hébergée, le paramètre standard `url` contient sa racine API complète.
Pour Nextcloud et Matrix, compléter aussi les adresses des protocoles avant d'enregistrer.

**Actualiser depuis GitHub** récupère les fiches disponibles dans `main` du dépôt officiel.
Le catalogue embarqué fonctionne sans Internet. Si l'actualisation échoue, le dernier
catalogue disponible reste utilisable. Une fiche qui nécessite une version plus récente
ou un protocole absent ne peut pas servir à créer un service.

Une mise à jour du catalogue ne remplace pas vos services existants. Une autre version du
modèle est signalée ; **Configurer une copie** permet de la comparer sous un autre nom.
Les réglages, secrets et autorisations de la première copie restent conservés.

Dans la modale **Nouveau service**, **Créer un service personnalisé** ouvre une configuration vierge. Ajouter
une icône SVG, PNG ou GIF dans son formulaire ; elle est incluse dans l'export YAML, sans
fichier d'image séparé ni lien distant. Le fichier YAML peut être transmis puis importé
sur une autre installation. Les paramètres secrets des connexions ne sont pas exportés.
Les icônes sont limitées à 128 Kio ; PNG/GIF à 1024 pixels par côté et 100 images animées.
Les SVG actifs ou contenant des ressources externes sont refusés.

Pour contribuer une fiche au dépôt, consulter le [contrat du catalogue](../dev/service-catalog.md).
Pour déléguer la configuration, consulter [l'administration des services](../admin/service-administration.md).

## Choisir les fonctions et leur portée

Chaque agent dispose des connexions **Contact** et **Tâches**. Dans **Autorisations**,
sélectionner le service qui porte l’outil à régler. **Multimédia** regroupe les outils audio,
image et vidéo. **Navigateur** contient aussi `search_web`. Les équipes se règlent dans
**Agent**, les outils `document_*` dans **Documents** et les `process_*` dans
**Processus**. **Chat** regroupe le canal interne, les appels et les choix en attente.
Dans le Chat, **Agenda** expose `calendar_list` et `calendar_events`. **Agent** expose
`agent_list`, `agent_get`, `team_list`, `team_members` et `agent_team_list`. La liste de **Chat** exclut
`chat_round_get` et `voice_turn_get`. **Documents** expose `document_show`, `document_sharing`
et `document_share`. **Compétences** expose `skills_list` et `skill_read`. **Multimédia** expose
`image_read`, `audio_read` et `audio_transcribe`. **Partage de fichiers** expose `file_schemes`,
`file_list`, `file_info`, `file_search`, `file_read` et `dataset_query`. Les permissions et le
contexte d’exécution de chaque outil continuent de s’appliquer. **Services** expose
`services_list` et, selon la portée de gestion, `service_connection_list`. **Sujets** expose `topic_list` et
`topic_items_list` lorsque la connexion Sujets est active. Utilisez les URI retournées
par ces outils et par le catalogue des processus pour lire un sujet, une définition ou une
exécution avec `file_read`. Le
[guide des services intégrés](../admin/service-administration.md)
indique où régler les permissions et les portées.

Les outils Contact accèdent au carnet de l’agent par défaut. Un gestionnaire global peut
étendre le périmètre aux agents de ses équipes ou à tous les agents dans **Permissions →
Contact**. Chaque outil conserve sa permission. Pour consulter ou modifier un carnet
délégué, utilisez les fonctions Contact.

Les connexions **Documents** et **Tâches** disposent elles aussi de leur propre portée.
Les outils Documents exigent les droits du document en plus du périmètre de la connexion.
Dans **Permissions → Tâches**, accordez la portée **Équipe** pour que l'agent puisse
déléguer du travail aux membres de ses équipes.
Dans **Autorisations**, `task_get` règle la consultation d'une tâche précise et
`task_cancel` règle son arrêt, en conversation comme pendant l'exécution d'une tâche.
`task_run` couvre la soumission dans le Chat et la délégation à un collègue pendant l'exécution.

## Authentifier une connexion MCP

Pour un Service MCP HTTP ou SSE, choisissez le type d’authentification dans la fiche du
Service. Le choix **OAuth 2.0** affiche **Connecter le compte** dans la connexion de l’agent.
Si vous changez ensuite de méthode, la confirmation indique quels identifiants seront effacés.
Suivez le [parcours d’autorisation OAuth](../admin/service-administration.md#mcp-oauth).

## Utiliser une API REST depuis un agent

Quand vous ajoutez le protocole REST, l’éditeur sélectionne **Aucune authentification**.
Si l’API exige un identifiant, associez-le à un paramètre de connexion déclaré.
Voir [Activer une API REST](../admin/service-administration.md#rest-api).

Dans l’onglet **REST** d’un Service enregistré, **Générer une compétence** confie une tâche
à l’agent Galaris. Il recherche la documentation publique du fournisseur, y compris OpenAPI ou
Swagger si disponible, et crée une compétence générique avec des exemples d’utilisation du Service.
**Suivre la tâche** ouvre son avancement et son résultat. Retrouvez la compétence dans la bibliothèque
**Compétences** et attribuez-la aux agents concernés. La génération utilise les autorisations de
recherche web et de création de compétences de l’agent Galaris.

Pour demander à un agent de lire les projets GitLab, par exemple, activez sa connexion
au Service GitLab et renseignez le jeton. L’agent retrouve cette connexion avec
`services_list`, puis appelle `rest_request` avec le `service_code` affiché (par exemple `gitlab`) et la requête
`{"method":"GET","path":"projects","params":{"membership":true}}` si la base configurée
se termine par `/api/v4`. Galaris ajoute le jeton et l’agent peut exploiter la liste reçue.

Pour joindre un fichier, donnez à l’agent son URI Galaris. Il peut envoyer les octets
comme corps HTTP avec `request.file_uri` ou joindre plusieurs fichiers dans `request.files`
avec les champs de formulaire de `request.form`. Par exemple, pour une API qui attend un fichier
dans le champ `document`, les arguments de `rest_request` peuvent prendre cette forme.

```json
{
  "service_code": "archives",
  "request": {
    "method": "POST",
    "path": "imports",
    "form": {"category": "invoice"},
    "files": [{"field": "document", "uri": "file://<uuid>"}]
  }
}
```

Utilisez le code du Service connecté et l’URI exacte retournée par l’outil de fichiers.
Si l’API attend directement le PDF dans le corps d’un PUT, la requête devient
`{"method":"PUT","path":"imports/facture.pdf","file_uri":"file://<uuid>"}`.
Les réponses de cet outil sont du JSON ou du texte. Pour les champs répétés, les limites et
la correspondance avec Axios, consultez la [référence de `rest_request`](../admin/service-administration.md#rest-request).

<a id="service-access"></a>
## Quand un agent ne peut pas utiliser un outil

| Symptôme | Où vérifier |
|---|---|
| La fiche existe, mais l’agent ne trouve pas le Service | Ouvrez **Connexions**, sélectionnez l’agent et vérifiez que sa connexion est active. |
| L’outil fonctionne en tâche, mais manque en discussion | Consultez **Outils en conversation** sur la carte du Service, puis l’autorisation effective sur la connexion. |
| L’appel atteint l’API, qui refuse l’accès | Vérifiez le compte sélectionné et ses droits sur la ressource chez le fournisseur. |
| L’agent attend votre accord | [Examinez la demande d’autorisation](tasks.md#action-approval) et vérifiez la cible avant de répondre. |
