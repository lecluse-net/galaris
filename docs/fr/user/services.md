<p align="right"><strong>Français</strong> · <a href="../../en/user/services.md">English</a></p>

# Ajouter et partager des services

Un **Service** représente un fournisseur, comme Nextcloud ou GitLab, ou une fonction
intégrée de Galaris. Ses protocoles donnent accès aux fichiers, à la messagerie ou à une
API. Une **Connexion** relie un agent à ce service avec ses paramètres et ses identifiants.
Les fonctions MCP restent les opérations que l'agent peut appeler.

Dans **Services & connexions → Services → Catalogue**, rechercher le fournisseur puis
choisir **Configurer une copie**. La fiche s'ouvre dans l'éditeur habituel : vérifier le
nom, compléter les adresses propres à votre installation, choisir les protocoles utiles
et enregistrer. Créer ensuite les connexions des agents et régler leurs autorisations.
L'ajout d'une fiche n'accorde aucun accès et n'active aucune connexion automatiquement.

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

**Nouveau service** reste disponible pour créer une configuration personnalisée. Ajouter
une icône SVG, PNG ou GIF dans son formulaire ; elle est incluse dans l'export YAML, sans
fichier d'image séparé ni lien distant. Le fichier YAML peut être transmis puis importé
sur une autre installation. Les paramètres secrets des connexions ne sont pas exportés.
Les icônes sont limitées à 128 Kio ; PNG/GIF à 1024 pixels par côté et 100 images animées.
Les SVG actifs ou contenant des ressources externes sont refusés.

Pour contribuer une fiche au dépôt, consulter le [contrat du catalogue](../dev/service-catalog.md).
Pour déléguer la configuration, consulter [l'administration des services](../admin/service-administration.md).
