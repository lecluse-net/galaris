<p align="right"><strong>Français</strong> · <a href="../../en/user/datasets.md">English</a></p>

# Jeux de données

## Rechercher et calculer avec un agent

Demandez à l'agent de retrouver un jeu par son contenu ou son sens, puis de filtrer ses lignes,
de trier les résultats ou de calculer un total. Il peut interroger le JSON côté serveur sans
le recopier intégralement dans la conversation. Les résultats indiquent la révision consultée.
Les calculs distinguent valeurs absentes, nulles et types incompatibles ; les unités restent
à préciser. Une modification entre deux pages doit entraîner une nouvelle lecture.

La recherche sémantique dépend du modèle vectoriel configuré et de l'indexation Dream.
L'agent voit si cette couverture est incomplète et peut poursuivre par recherche textuelle.
Le partage du jeu reste nécessaire ; un lien depuis un Document n'accorde aucun droit.

## Description courante

La petite icône **Voir le résumé**, près du titre et du sujet, ouvre la description courante
et ses mots-clés en lecture. Elle recharge les données enregistrées à chaque ouverture,
sans modifier le brouillon de l'éditeur. La fenêtre se ferme avec son bouton, Échap ou un
clic à l'extérieur.

L'onglet **Description et mots-clés** décrit ce que contient le jeu et à quoi il sert.
Enregistrez vos modifications avec le bouton habituel : elles ne créent pas de version JSON.
La description et les mots-clés restent courants, sans historique ; restaurer une ancienne
version JSON les conserve.

Dream peut remplir la description manquante lorsque le JSON normalisé dépasse **1 000 caractères**.
Il ne renouvelle une description automatique qu'au-delà de **25 % de changement cumulé** depuis
sa génération. Ces deux valeurs se règlent dans les paramètres Dream. L'indentation et l'ordre
des clés JSON ne comptent pas comme changement. Une description manuelle est préservée.

## Ouvrir la bibliothèque et l'éditeur

**Connaissances → Jeux de données** contient les ressources JSON indépendantes `data://`.
Elles ont leur propre titre, propriétaire, partage et historique. Elles ne figurent pas
dans la bibliothèque Documents, réservée aux contenus HTML. Les anciens liens documentaires
vers les jeux migrés ouvrent le même éditeur Dataset, avec les droits actuels.

Cliquez sur un jeu pour ouvrir son éditeur dans la page. Sur ordinateur, l'arborescence et
la liste restent à gauche et un séparateur déplaçable règle la largeur des deux volets,
comme dans Documents. Le séparateur se règle aussi au clavier avec les flèches gauche/droite.
Les jeux de l'arborescence affichent uniquement leur icône fixe et leur nom sur une ligne.
Sur mobile, l'éditeur occupe la page. Revenez à la liste par l'historique du navigateur ou
l'entrée **Jeux de données** du menu ; recherche et pagination sont conservées.
Un brouillon non enregistré demande confirmation avant de changer de jeu ou de quitter
l'éditeur. Les cartes Dataset du Chat continuent d'ouvrir une modale, avec le JSON complet,
l'historique et les actions autorisées.

Les boutons **Précédent** et **Suivant** du navigateur retrouvent les jeux visités et la
liste, en conservant ses filtres et sa pagination. Cette navigation demande aussi confirmation
si vous avez un brouillon non enregistré, même avec un JSON invalide. **Annuler** conserve
le jeu courant et votre saisie ; **Abandonner les modifications** poursuit la navigation.

L'arborescence se trouve au-dessus de la liste, avec un séparateur réglable. Ses dossiers sont
indépendants de ceux des Documents et propres à votre compte. Le menu contextuel permet de
créer un sous-dossier ou un dossier voisin, renommer et changer l'icône, trier par nom,
déplier/replier une branche et la supprimer. **Afficher en liste** ouvre le contenu d'un dossier.
Déplacez les dossiers et les jeux par glisser-déposer, ou utilisez **Déplacer vers un dossier**
sur un jeu. Supprimer une branche conserve ses jeux et les remet parmi vos non classés.
La racine contient uniquement les jeux que vous y placez explicitement. Utilisez
**Créer un jeu de données à la racine**, déposez un jeu près des boutons de création, ou
choisissez **Racine** dans **Déplacer vers un dossier**. Le choix est personnel et conservé
après rechargement. Les autres jeux sans dossier restent non classés, hors de l'arborescence.
Pour retirer un jeu de la racine, déposez-le dans la zone de liste ou choisissez **Non classés**
dans **Déplacer vers un dossier**. La création générale conserve aussi les jeux parmi les non classés.

La liste affiche les **Non classés** par défaut. **Filtres** permet de désactiver cette option,
choisir un propriétaire utilisateur ou agent, un mot-clé, des dates de création/modification
et le tri manuel, par titre ou par date, croissant ou décroissant. La recherche porte sur le
titre et le JSON. La pagination propose 50 éléments par défaut, avec les choix 10, 20, 50, 100 ou 500.

## Créer et modifier du JSON

Un agent peut renommer un jeu avec `file_rename`, après lecture de `file_info` et de son
`lock_version`. Seul le titre change : l'URI `data://`, le JSON, son historique, les pièces
jointes et les droits sont conservés. Un renommage concurrent impose de relire les métadonnées.
Le droit d'écriture reste nécessaire ; un jeu en lecture seule ne peut pas être renommé.

L’éditeur propose trois onglets : **Contenu**, **Historique** et **Utilisations**.
Dans **Contenu**, l’éditeur JSON occupe la hauteur disponible jusqu’en bas de la vue.
Changer d’onglet conserve votre brouillon, y compris un JSON invalide.

Créez un jeu depuis cette bibliothèque. Son contenu peut être un objet, un tableau ou une
valeur simple, sans schéma associé. Pour recueillir des ajouts successifs, partez d'un tableau
racine `[]`. Un agent utilise `file_create(path="data://", name="Réponses", content="[]")`
et conserve l'URI retournée. Le JSON complet est obligatoire ; remplacer son schéma par
`document://` ne crée pas une référence valide.

Le JSON est indenté à l'ouverture et dans l'historique sans changer les valeurs exactes ni
enregistrer une modification. Un JSON invalide ou un conflit conserve votre brouillon ;
gardez les changements à reprendre avant de recharger. Les lectures d'un agent donnent les
repères de ligne, la révision et les limites des lignes partielles avant `file_edit`.
La consultation et la restauration d'une ancienne version restent soumises aux droits
et au contrôle de révision ; une restauration ne rétablit pas d'anciens partages.

## Propriétaire et partage

**Propriétaire** et **Partage** sont sur la même ligne. Le propriétaire ou un administrateur
autorisé peut transférer le jeu à un agent qu'il gère ou à lui-même ; un administrateur Dataset
peut aussi choisir un autre utilisateur actif. Le transfert est immédiat, conserve brouillon
et historique, et laisse l'ancien propriétaire en écriture. Les jeux en lecture seule
ne peuvent pas être transférés.

Le partage reprend les règles des Documents : privé, groupes ou public pour les utilisateurs
authentifiés, avec des destinataires agents, utilisateurs ou groupes en lecture ou écriture.
Seul le propriétaire ou un administrateur autorisé peut repartager ; le droit d'écriture
ne suffit pas. Les groupes suivent leurs membres actuels. Une ressource en lecture seule
ne peut pas être repartagée. Documents, Datasets et processus gardent des droits indépendants ;
voir le [mécanisme de partage](../dev/sharing.md).

## Citer et utiliser les données

Dans un document, **Insérer un lien ou un fichier → Ajouter une PJ interne** ouvre le sélecteur
de ressources. Choisissez `data://`, puis les jeux voulus : ils sont cités sans copie JSON ni
pièce jointe supplémentaire. Coller une URI `data://` ou un lien `/dataset/…` de cette
installation permet aussi de choisir **Afficher une carte**. Son titre ouvre la modale
Dataset sans quitter le document. Retirer la citation ne supprime pas les données ; partager
la page ne partage pas les jeux cités.

Les applications HTML/JavaScript peuvent lire et alimenter ces jeux via le pont Dataset,
avec les droits et l'accord personnel du lecteur pour la révision courante de la page.
Partagez séparément page et données. Voir les [applications documentaires](../dev/document-apps.md).
Une référence aux données ne met pas automatiquement à jour un texte déjà rédigé.

## Voir les utilisations et supprimer

**Utilisations** liste les documents qui référencent le jeu, les définitions et exécutions de
processus qui le mentionnent et les agents dont les traces d'outils conservées portent son URI.
Chaque catégorie respecte vos droits sur les sources. Les URI construites dynamiquement et
les historiques purgés peuvent manquer ; une mention ne prouve pas que l'accès a réussi.

**Supprimer** demande confirmation et retire l'accès au jeu. Son historique reste conservé.
La projection mémoire des anciens jeux migrés est effacée avec ses contenus et index.
Les items mémoire liés uniquement à ce jeu ou à ses pièces jointes sont également supprimés.
Les références existantes peuvent devenir indisponibles. Les anciens jeux créés pour des
processus suivent les mêmes droits. Les processus actuels stockent leurs données et fichiers
dans leurs runs ; ils ne créent pas de Dataset pour conserver cet état. Au lancement d'un
workflow, l'agent recueille les informations manquantes et prépare les variables attendues ;
Process les valide et conserve les URI autorisées des fichiers.
