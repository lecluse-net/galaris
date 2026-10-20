<p align="right"><strong>Français</strong> · <a href="../../en/user/pwa.md">English</a></p>

# Installer et utiliser Galaris comme application mobile

[Retour au guide utilisateur](README.md)

Galaris est une Progressive Web App (PWA). Un navigateur compatible peut l’installer depuis
le site existant : aucun paquet APK, compte de store ou passage par l’App Store n’est nécessaire.
Une fois installée, elle possède sa propre icône et s’ouvre dans une fenêtre autonome.

L'interface est disponible en français, anglais et chinois simplifié. Au premier
chargement d'une langue, Galaris attend son catalogue avant d'afficher les nouveaux
libellés. Une erreur de téléchargement conserve la langue utilisable et permet de
réessayer. La langue de l'interface ne traduit pas les documents enregistrés.

## Avant de commencer

Vous avez besoin :

- de l’adresse HTTPS de Galaris fournie par votre administrateur ;
- d’un compte Galaris actif ;
- de Chrome sur Android ou de Safari sur iPhone ;
- d’une connexion réseau pour utiliser les données et les actions de Galaris.

La PWA conserve des éléments statiques de l’interface, mais ne met pas en cache les conversations,
les tâches ni les réponses des API. Elle ne remplace donc pas une connexion réseau.

## Installation sur Android

1. Ouvrez l’adresse de Galaris dans **Chrome**.
2. Ouvrez le menu **⋮** en haut à droite.
3. Choisissez **Installer l’application**. Selon la version de Chrome, le libellé peut être
   **Ajouter à l’écran d’accueil**.
4. Confirmez l’installation.
5. Fermez l’onglet, lancez Galaris depuis sa nouvelle icône et connectez-vous une première fois.

Chrome peut aussi afficher directement une proposition d’installation. Si Galaris est déjà
installé, l’option n’est plus proposée.

## Installation sur iPhone

1. Ouvrez l’adresse de Galaris dans **Safari**.
2. Touchez le bouton **Partager** — le carré avec une flèche vers le haut.
3. Faites défiler les actions et choisissez **Sur l’écran d’accueil**.
4. Conservez le nom proposé, puis touchez **Ajouter**.
5. Lancez Galaris depuis sa nouvelle icône et connectez-vous une première fois.

Utilisez Safari pour cette installation : un autre navigateur iOS peut ne pas présenter la même
action ou le même parcours.

## Connexion persistante

Après cette première connexion, Galaris restaure automatiquement la session au lancement. La
durée par défaut est de 30 jours depuis la dernière utilisation ayant renouvelé la session ;
l’administrateur peut choisir une autre durée.

La session prend fin lorsque :

- vous utilisez **Déconnexion** dans Galaris ;
- vous changez votre mot de passe ;
- votre compte est désactivé ;
- la durée d’inactivité configurée est dépassée ;
- les données du site sont effacées par le navigateur ou le système.

La désinstallation de l’icône ne constitue pas une déconnexion garantie. Sur un appareil partagé,
perdu ou revendu, déconnectez-vous d’abord. Si l’appareil n’est plus accessible, changez votre mot
de passe depuis un autre appareil afin de révoquer les sessions persistantes.

## Mises à jour

La PWA recherche et installe automatiquement les nouvelles versions de son interface. Une mise à
jour devient généralement visible après avoir fermé complètement l’application puis l’avoir
rouverte. Les conversations et tâches sont stockées côté serveur et ne dépendent pas de la
réinstallation de l’icône.

N’effacez les données du site qu’en dernier recours : cette action supprime la session locale et
impose une nouvelle connexion.

L’interface web et la fenêtre Android installée ont des cycles de mise à jour distincts.
Galaris déclare un fond de lancement et une couleur native de secours sombres dans son manifeste.
Ce repli reste sombre même lorsque l’interface est claire, pour conserver un fond lisible derrière
les boutons Android. La page transmet aussi sa couleur actuelle à Chrome au changement de thème
et au retour au premier plan. Cette indication ne garantit pas que la barre native change avec
l’interface : Chrome peut utiliser la couleur du manifeste pour la navigation à trois boutons.
Voir le [fonctionnement déclaré par Chromium](https://chromium.googlesource.com/chromium/src/+/0a6ab4f0e2ce17e572b05400ae6eacd7fc5389f0).
Une ancienne installation peut conserver les anciennes couleurs après le rechargement de
l’interface : Chrome doit aussi actualiser son manifeste et son paquet d’installation (WebAPK).
Ce renouvellement est géré par Chrome et peut être différé ; il ne peut pas être forcé par un
rechargement de Galaris.
Voir les [conditions de mise à jour Android décrites par Chrome](https://web.dev/articles/manifest-updates).
Si la barre reste claire en mode sombre, relever les versions de Chrome et d’Android, les thèmes
du système et de Galaris, et si le problème apparaît au lancement ou après un retour au premier
plan. Une réinstallation seule ne prouve pas que le problème est résolu. N’effacez pas les données
du site ; les conversations restent stockées sur le serveur.

## Dépannage

| Problème | Vérifications |
|---|---|
| l’option d’installation est absente | ouvrir l’URL HTTPS dans Chrome ou Safari, quitter la navigation privée, recharger la page et vérifier que l’application n’est pas déjà installée |
| l’icône ouvre un onglet ordinaire | supprimer uniquement l’ancienne icône, puis refaire l’installation depuis le navigateur compatible |
| Galaris demande le mot de passe à chaque lancement | ouvrir l’application depuis son icône, autoriser les cookies et vérifier que le navigateur ne supprime pas automatiquement les données du site |
| l’interface semble ancienne | fermer complètement la PWA puis la rouvrir ; attendre quelques secondes avec le réseau actif |
| les pages s’ouvrent mais les données ne chargent pas | vérifier la connexion réseau : les API et données métier ne sont pas disponibles hors connexion |

Si le problème persiste, transmettez à l’administrateur l’adresse utilisée, le modèle du téléphone,
la version du système et le navigateur. Ne transmettez jamais votre mot de passe ni les cookies du
navigateur.
