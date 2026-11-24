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

## Partager un MCP local

Ouvrir **Galaris → MCP locaux** dans le menu du client. **Découvrir** lit les
configurations utilisateur de Claude Desktop, Codex, Visual Studio Code et Cursor.
Pour une autre application ou une configuration de projet, utiliser **Importer une
configuration** et choisir un fichier MCP JSON ou TOML. La découverte se limite à
ces fichiers de configuration. Les serveurs découverts restent privés.

Activer l’interrupteur du MCP voulu. Le compte connecté doit pouvoir modifier
les Services. Le serveur sélectionné ajoute alors un **Service MCP HTTP** portant le
nom détecté. Dans **Services & connexions**, créer ou choisir une Connexion pour
l’agent, tester la découverte et régler les permissions des fonctions. Pour les
utiliser dans le Chat, autoriser aussi les outils voulus dans **Outils en conversation**.

Les outils du MCP s’exécutent avec les droits de l’application locale. Le relais
refuse les lectures directes de ressources `file://` sur le poste.

La Connexion de l’agent se crée sans compte ni mot de passe. Si le MCP demande un
jeton, renseigner ses en-têtes HTTP dans le fichier MCP local ou utiliser une variable
d’environnement disponible dans le client. Par exemple, `bearer_token_env_var` donne
le nom de la variable qui fournit le jeton. Le client présente ces identifiants au MCP
sur le poste. Si le MCP HTTP ou SSE refuse l’accès au moment du partage, le client
affiche le refus avant d’enregistrer le Service. Corriger la configuration, puis choisir
**Découvrir** et réessayer. Les commandes `stdio` utilisent leur environnement configuré.

Le client prend en charge les commandes `stdio` et les endpoints Streamable HTTP
ou SSE en boucle locale. Le poste contacte uniquement l’adresse HTTPS de Galaris
pour le relais. Aucun port entrant supplémentaire n’est nécessaire. Si le réseau
filtre le trafic HTTPS, il doit autoriser les requêtes du client vers votre instance.

Le partage est propre au poste et au serveur sélectionné. Fermer le client ou mettre
le poste en veille rend les MCP indisponibles. Une modification de la configuration
détectée par **Découvrir** suspend le partage jusqu’à une nouvelle approbation.
Désactiver le partage conserve le Service et les réglages de Connexion.
Supprimer le Service dans Galaris révoque le relais côté serveur.

## Montrer une partie de son écran à un agent

Dans une discussion lancée depuis le client desktop, l’agent peut demander une
capture avec `chat_screenshot`, un outil du Service **Chat**. La demande s’ouvre
sur le poste et dans la session qui a envoyé le message. L’outil est réservé
aux tours de discussion textuels du Chat interne.

Choisir un écran ou une fenêtre, prendre la capture et vérifier son aperçu. Seul
le bouton **Envoyer la capture** téléverse l’image vers le serveur Galaris.
**Refuser** ou fermer la fenêtre annule l’envoi. Chaque demande nécessite une
nouvelle décision. Galaris enregistre l’image comme fichier privé de l’agent
et renvoie une URI `file://…` que l’agent peut joindre à son message.

## Onglets et orthographe

À gauche des onglets, les flèches **Précédent** et **Suivant** parcourent l’historique
de la page dans l’onglet actif. Elles sont désactivées lorsqu’aucune page n’est disponible
dans ce sens. Le bouton **Recharger** ou **Ctrl+R** recharge la page de l’onglet actif.
Le bouton **☰** ouvre les menus de l’application (changement de serveur,
mises à jour, édition, onglets et affichage) ; la barre de menus classique est masquée.
Les raccourcis **Alt+Gauche** et **Alt+Droite** restent disponibles.
Sur un écran large, cette barre compacte se place à droite du menu latéral, au-dessus
du titre de la page, et suit le repli du menu. Seul l’onglet actif rejoint la page ; les
autres restent espacés de son bord. En fenêtre étroite, ou sur une page externe,
la barre occupe toute la largeur au-dessus du contenu.
Les modales et les aperçus plein écran masquent la barre d’onglets. Elle revient à la
fermeture de la dernière fenêtre superposée.

Le bouton **+**, après le dernier onglet, ou **Ctrl+T** ouvre une nouvelle page Galaris. **Ctrl+W** ferme l’onglet
courant ; **Ctrl+Tab** et **Ctrl+Maj+Tab** changent d’onglet. Les liens internes ouverts
avec Ctrl+clic, le bouton central ou « Ouvrir le lien dans un nouvel onglet » restent dans
la fenêtre. Chaque page conserve sa navigation et ses brouillons pendant les changements
d’onglet. Les onglets partagent la session du serveur ; au redémarrage, seule sa page
d’accueil est rouverte. La fermeture du dernier onglet ferme la fenêtre.
Chaque onglet affiche le titre de sa page courante et suit les changements
de page et de langue. Cette information vient de l’interface servie par Galaris : le
serveur doit aussi être à jour pour remplacer l’ancien titre uniforme « Galaris ».

La vérification orthographique français/anglais est activée dans les champs de texte
qui l’autorisent. Un clic droit sur un mot souligné propose des corrections et **Ajouter
au dictionnaire**. Les champs de texte enrichi hors Documents conservent leur menu
spécifique : utiliser **Maj+clic droit** pour accéder aux suggestions natives.
Les éditeurs de code peuvent désactiver cette vérification. Le premier
chargement des dictionnaires nécessite Internet ; le texte saisi n’est pas envoyé au
service de téléchargement des dictionnaires.

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
