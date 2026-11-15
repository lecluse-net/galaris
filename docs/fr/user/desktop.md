<p align="right"><strong>Français</strong> · <a href="../../en/user/desktop.md">English</a></p>

# Installer Galaris sur Windows ou Linux

[Retour au guide utilisateur](README.md)

Le client desktop ouvre votre serveur Galaris dans une fenêtre dédiée. Le serveur et
une connexion réseau restent nécessaires ; l’installateur n’installe pas le serveur.
La PWA et l’accès navigateur restent disponibles.

## Installer et se connecter

Lorsqu’une [publication officielle](https://github.com/lecluse-net/galaris/releases)
contient les fichiers desktop, choisir le fichier adapté à votre système x64 :

- **Windows :** lancer `Galaris-<version>-x64.exe`, puis ouvrir Galaris depuis le menu Démarrer.
- **Linux, recommandé :** placer `Galaris-<version>-x86_64.AppImage` dans un dossier personnel
  accessible en écriture, autoriser son exécution dans les propriétés du fichier et l’ouvrir.
  Selon la distribution, le support FUSE des AppImages peut être nécessaire.
- **Debian/Ubuntu :** `Galaris-<version>-amd64.deb` est une alternative intégrée au système.

Au premier lancement, saisir l’adresse **HTTPS** de Galaris fournie par votre administrateur,
par exemple `https://galaris.example.org`, puis **Se connecter**. Utiliser l’adresse de base,
sans chemin ni paramètres. Les certificats HTTPS doivent être reconnus par le système.
S’authentifier ensuite dans l’interface Galaris habituelle.

Le client retrouve le serveur au prochain lancement et conserve sa propre session, séparée de
celle du navigateur. Les règles de durée et de révocation des sessions restent celles de Galaris.
Chaque adresse de serveur possède ses propres cookies et données locales. Pour changer de
serveur ou réessayer après une erreur réseau, utiliser **Galaris → Changer de serveur…**.
Fermer cette fenêtre de configuration ramène à la fenêtre Galaris déjà ouverte.

## Mises à jour

L’interface et les fonctionnalités web arrivent du serveur, comme pour la PWA. Une mise à jour
du serveur ne nécessite pas de réinstaller le client. Un rechargement peut être nécessaire.

Le client **Windows** et l’**AppImage Linux** recherchent séparément leurs mises à jour dans
les publications officielles au démarrage, puis toutes les six heures. Le téléchargement se
fait en arrière-plan. Une fois prêt, choisir **Redémarrer pour mettre à jour**, après avoir
enregistré le travail en cours, ou **Plus tard**. Aucune installation n’est déclenchée par la
simple fermeture du client. **Galaris → Rechercher les mises à jour** permet de vérifier ou
de réessayer manuellement. Un téléchargement échoué n’empêche pas d’utiliser Galaris.
L’AppImage doit rester accessible en écriture à son utilisateur.

Si un éditeur signale des modifications non enregistrées, la fermeture, le changement de
serveur ou le redémarrage est annulé. Revenir à la fenêtre ouverte, enregistrer, puis réessayer.

Le paquet **Debian** ne se remplace pas automatiquement : télécharger le nouveau `.deb`
officiel et l’installer par-dessus l’ancien. Choisir l’AppImage pour les mises à jour intégrées.
Les versions de développement ne recherchent pas de mises à jour.

## Permissions et limites

Le client demande une autorisation avant l’usage du micro, de la caméra, des notifications ou
de la lecture du presse-papiers par le serveur sélectionné. Les permissions du système
d’exploitation restent applicables. Les liens externes ouverts dans une nouvelle fenêtre
utilisent le navigateur habituel ; les aperçus de ressources restent isolés dans le client.
Les parcours de connexion OAuth conservent leur navigation HTTPS dans la même fenêtre.

Fermer la fenêtre principale quitte le client : cette version ne fonctionne pas dans la zone
de notification et ne garantit pas la réception de notifications quand elle est fermée.
Les appels et les notifications nécessitent une qualification sur votre système ; les tests
automatisés ne vérifient ni les périphériques physiques ni la livraison Web Push.

Les conversations, tâches et documents restent sur le serveur. Une désinstallation n’est pas
une déconnexion garantie : sur un appareil partagé ou cédé, se déconnecter dans Galaris avant
de désinstaller. Le changement de serveur conserve sa session locale pour un retour ultérieur.

En cas d’échec, vérifier l’adresse, le réseau et la validité du certificat. Ne pas désactiver
les protections HTTPS. Ne jamais transmettre de mot de passe ni de cookie au support.
