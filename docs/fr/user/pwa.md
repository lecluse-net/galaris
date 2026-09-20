<p align="right"><strong>Français</strong> · <a href="../../en/user/pwa.md">English</a></p>

# Installer et utiliser Galaris comme application mobile

[Retour au guide utilisateur](README.md)

Galaris est une Progressive Web App (PWA). Un navigateur compatible peut l’installer depuis
le site existant : aucun paquet APK, compte de store ou passage par l’App Store n’est nécessaire.
Une fois installée, elle possède sa propre icône et s’ouvre dans une fenêtre autonome.

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
