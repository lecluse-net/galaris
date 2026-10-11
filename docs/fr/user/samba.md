<p align="right"><strong>Français</strong> · <a href="../../en/user/samba.md">English</a></p>

# Accéder à un partage Samba ou Windows

Le bridge **Samba / SMB 2–3** donne accès aux fichiers d'un partage depuis les fonctions
de **Partage de fichiers**. Le serveur doit être joignable depuis le backend Galaris,
habituellement sur le port TCP 445. Aucun montage de disque dans Galaris n'est nécessaire.

1. Dans **Outils**, créez un Tool avec un code tel que `team-share`, activez sa capacité
   de partage de fichiers et sélectionnez **Samba / SMB 2–3**.
2. Dans l’onglet **Partage de fichiers**, renseignez **Adresse du partage (base_url)**.
   `smb://files.example.test` donne accès aux partages du serveur : l’agent liste
   `team-share://`, puis parcourt `team-share://<partage>/...` avec les fonctions
   génériques de partage de fichiers. Pour limiter la racine, utilisez
   `smb://files.example.test/shared` ou `smb://files.example.test:445/shared/team`.
   Le partage et le sous-dossier configurés doivent déjà exister.
   Cette URL ne contient aucun identifiant ni mot de passe.
   Le **Nom technique** reste un identifiant tel que `team-share` : il ne contient
   pas l’URL SMB, ni `://`, ni underscore.
3. Déclarez les paramètres de connexion `login` (texte) et `password` (mot de passe),
   puis associez-les aux paramètres correspondants du bridge.
   Le login peut être `user` ou `DOMAIN\user`.
4. Pour exiger le chiffrement SMB 3, déclarez un paramètre texte `encrypt`, associez-le
   au bridge et donnez-lui la valeur `true` dans la connexion. Sans ce paramètre,
   le bridge exige la signature SMB et accepte SMB 2 ou SMB 3.
5. Créez et activez une connexion pour l'agent concerné, puis renseignez ses identifiants.
   Les droits du compte distant s'appliquent à chaque opération.

## Parcourir les fichiers avec l'agent

Demandez à l'agent de lister `team-share://`, puis de suivre les URI retournées.
Avec une racine serveur, cette première liste contient les partages accessibles.
L'agent ouvre par exemple `team-share://shared/`, puis les dossiers et fichiers
de ce partage. Il utilise uniquement les fonctions génériques `file_list`,
`file_info`, `file_read` et les mutations autorisées de **Partage de fichiers** ;
le bridge n'ajoute aucune fonction SMB dédiée à son catalogue.

| Adresse configurée par l'administrateur | Racine vue par l'agent | Exemple de fichier |
|---|---|---|
| `smb://files.example.test` | Liste des partages | `team-share://shared/reports/result.txt` |
| `smb://files.example.test/shared` | Contenu de `shared` | `team-share://reports/result.txt` |
| `smb://files.example.test/shared/team` | Contenu de `shared/team` | `team-share://reports/result.txt` |

Le schéma est toujours le code du Tool ; les chemins sont relatifs à la racine
configurée. Réutilisez les URI exactes retournées, notamment pour les espaces,
accents et caractères encodés. Les identifiants sont résolus côté serveur.
Plusieurs Tools peuvent viser des serveurs ou racines différents.

Un Tool qui ne porte que cette capacité de fichiers n'est pas un catalogue de
fonctions réservé aux Tasks : ses ressources passent par les fonctions `file_*`
autorisées dans le contexte courant.

## Droits et limites

L’agent ne reçoit ni l’adresse SMB ni les identifiants : il utilise uniquement les URI
du Tool et les fonctions `file_*`. Avec une racine serveur, la liste utilise SRVSVC
sur SMB authentifié et ne montre que les partages disque accessibles au compte.
Les imprimantes et IPC ne sont pas des dossiers. Les droits du serveur restent appliqués
lors de chaque accès. Un serveur qui ne propose pas SRVSVC exige une racine de partage
explicite dans la configuration. Les partages eux-mêmes ne sont jamais créés ou supprimés.
Un déplacement entre deux partages copie le fichier, puis supprime la source sous
précondition de version ; une suppression refusée indique que seule la copie a réussi.

Le bridge prend en charge la recherche par nom et dans les petits textes UTF-8,
les listes paginées, les lectures bornées, la création, le remplacement, l'ajout,
l'édition, la copie, le déplacement et la suppression de fichiers. L'indexation
peut être exclue, limitée aux URI connues ou récursive via le paramètre standard
de la connexion. Les dossiers ne sont ni déplacés ni supprimés.

Les lectures exposent un `etag` ; les éditions et ajouts vérifient la version sous
verrou SMB. Un conflit exige une nouvelle lecture. Un remplacement écrit dans le
fichier verrouillé : une coupure réseau peut laisser un contenu partiel ; vérifiez
le fichier avant de réessayer. Aucune mutation n'est rejouée automatiquement.

Les partages DFS et les points de reparse SMB sont refusés. Configurez directement
le serveur final et désactivez les liens sortant du partage côté Samba (`wide links = no`).
SMB 1, les accès invités, Kerberos et les liens publics de partage ne sont pas proposés.
Une liste est limitée à 500 résultats par page et à 10 000 entrées par dossier ;
un dossier plus grand exige une racine plus petite.

## Diagnostiquer un accès

- Un refus du **Nom technique** signifie que le code ne respecte pas le format
  indiqué : saisissez `team-share`, puis l'adresse SMB dans `base_url`.
- Une erreur de configuration `base_url` doit être corrigée dans le Tool ;
  l'agent conserve ses URI `team-share://`.
- Un refus d'authentification concerne le login ou le mot de passe de la connexion.
  Un partage absent de la liste peut aussi être interdit à ce compte.
- Si SRVSVC est indisponible, configurez directement un partage existant comme
  racine. Une erreur réseau exige de vérifier la résolution du serveur et TCP 445
  depuis le backend.
- Une interruption du round ou l'expiration de son bail ne prouve pas un refus
  Samba : consultez les appels et résultats `file_*` réellement enregistrés.
  En développement, un rechargement du backend peut interrompre le round.

Le parcours automatisé `make tests-samba` utilise des comptes synthétiques, un
vrai serveur Samba éphémère et PostgreSQL isolé. Il couvre l'énumération des partages,
les réponses SRVSVC fragmentées, la pagination, les droits, les conflits de version
et les transferts entre partages.
