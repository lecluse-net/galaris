<p align="right"><strong>Français</strong> · <a href="../../en/user/datasets.md">English</a></p>

# Jeux de données

## Ouvrir la bibliothèque et l'éditeur

**Connaissances → Jeux de données** contient les ressources JSON indépendantes `data://`.
Elles ont leur propre titre, propriétaire, partage et historique. Elles ne figurent pas
dans la bibliothèque Documents, réservée aux contenus HTML. Les anciens liens documentaires
vers les jeux migrés ouvrent le même éditeur Dataset, avec les droits actuels.

Cliquez sur un jeu pour ouvrir sa modale sur ordinateur comme sur mobile. La croix,
Échap ou le clic sur l'arrière-plan ramène à la liste, en conservant recherche et page.
Un brouillon non enregistré demande confirmation avant fermeture. Les cartes Dataset du
Chat ouvrent cette même modale, avec le JSON complet, l'historique et les actions autorisées.

Le filtre **Agent propriétaire** limite la liste aux jeux d'un agent géré. **Tous les agents**
rétablit tous les jeux accessibles, y compris ceux d'un utilisateur. La recherche et la
pagination s'appliquent au résultat filtré : 50 éléments par défaut, choix 10, 20, 50, 100 ou 500.

## Créer et modifier du JSON

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

**Supprimer** demande confirmation et retire l'accès au jeu. Son historique reste conservé ;
les références existantes peuvent devenir indisponibles. Les anciens jeux créés pour des
processus suivent les mêmes droits. Les processus actuels stockent leurs données et fichiers
dans leurs runs ; ils ne créent pas de Dataset pour conserver cet état. Au lancement d'un
workflow, l'agent recueille les informations manquantes et prépare les variables attendues ;
Process les valide et conserve les URI autorisées des fichiers.
