<p align="right"><strong>Français</strong> · <a href="../../en/dev/sharing.md">English</a></p>

# Partage des ressources

`app.share` possède les configurations `share_configs`, les attributions
`share_grants` et les contrats publics de partage. Documents, Dataset et Process
autorisent l'objet métier avant d'appeler sa façade. Le propriétaire, la lecture
seule, les restrictions de source et les privilèges administratifs restent dans
leur domaine. Le droit d'écriture ne donne pas le droit de repartager.

Chaque objet logique possède un `share_id` exclusif. Les références uniques et
typées interdisent qu'une configuration soit réutilisée par un autre objet. Un
Document et sa synthèse Memory portent la même identité logique, garantie par
une clé étrangère composite ; leur configuration doit donc rester identique.
Les mémoires ordinaires restent privées et les pièces jointes continuent de
suivre l'accès à leur parent.

Le domaine Agent fournit l'annuaire et les appartenances aux groupes. Les listes
filtrent les droits en SQL avant comptage et pagination. Aucun cache de décision
ne remplace la vérification des appartenances et révocations courantes.

Le frontend `app/share` possède aussi le formulaire `SharingPanel`, son sélecteur
de destinataires et les types de présentation, déplacés depuis `core.util`.
Il expose `ResourceSharingPanel`, `SharingState` et `SharingUpdate`.
Le contrôleur reçoit des fonctions de lecture et d'écriture du
domaine ; il ne connaît aucun endpoint documentaire. Le composant Memory restant
est un adaptateur de compatibilité vers ses propres services.

## Mise à jour des installations existantes

L'action DbAdmin obligatoire `app.share.resource_acls` copie les droits existants
et remplit les références, y compris celles des ressources supprimées logiquement.
Elle conserve utilisateurs, agents, groupes, accès général et accès historique aux
groupes du propriétaire. Elle vérifie chaque copie avant de rattacher la ressource.
Un rejeu préserve les modifications ultérieures, notamment les révocations.

Les anciennes tables de grants et colonnes d'accès sont conservées comme sources
de migration, sans écriture métier. Leur retrait appartient à une livraison
ultérieure, après vérification de la migration. En développement, appliquer avec
`make sync-db` ; en production, le chemin reste `make update`.

Voir la [décision 0200](../../../project/decisions/0200-exclusive-resource-sharing.md).

## Vérifications de migration et de concurrence

Les tests DbAdmin reconstruisent un ancien schéma peuplé de 484 objets logiques
et 1 089 grants synthétiques, avec trois catégories de destinataires, des accès
généraux et de groupes ainsi que des suppressions logiques. Ils vérifient chaque
droit et l'intégrité des sources, puis le rejeu. Une interruption après le DDL
confirme le rollback du transfert et sa reprise depuis le journal durable.

Les tests de concurrence utilisent des connexions PostgreSQL distinctes et
attendent un véritable blocage de verrou : un seul remplacement gagne, une
version périmée ne rétablit pas un accès révoqué et les autres objets restent
modifiables. Les parcours E2E Documents et Processus utilisent un propriétaire et
un destinataire sans privilège administrateur. Ils couvrent lecture, écriture,
refus de repartager, rechargement, réouverture et révocation.

Ces données sont entièrement synthétiques ; elles ne constituent pas une copie
de production ni une mesure de durée pour une installation réelle.

## Héritage documentaire dans les classements personnels

Memory conserve les ACL propres dans `document_sharing_intents`. Les configurations et
attributions communes restent la projection effective consommée par les contrôles SQL,
les agents, les listes et les exports. Les droits existants deviennent les droits propres
au premier rapprochement ; un résultat hérité n'est jamais repris comme source au rejeu.

Les liens de `document_tags`, `document_tag_assignments` et `document_nesting` ajoutent les
ACL de tous les ancêtres. Seul le classement du propriétaire humain, ou du responsable de
l'agent propriétaire, peut transmettre des droits à un document dont il peut gérer le
partage. Un document reçu en lecture ou modification ne devient pas repartageable en le
classant. Les arbres restent privés, même lorsque les droits de leurs répertoires sont publics.
Les Dataset et Process conservent leurs propres politiques et ne participent pas à ce calcul.

La fermeture additive part des seuls droits propres et retient le maximum lecture/écriture.
Elle termine aussi sur un ancien graphe cyclique. Modifier les droits ou le classement
reconstruit la projection dans la transaction métier, sous un verrou consultatif commun.
Les suppressions et transferts recalculent les contributions devenues inapplicables.
Le reconciler requis `app.memory.sharing_inheritance`, après la structure documentaire,
répare globalement cette projection à chaque synchronisation DbAdmin et `make update`.
Un rejeu sans écart ne modifie ni droits ni versions. Le formulaire F4 réutilise le composant
commun ; enregistrer des droits effectifs inchangés ne les transforme pas en droits propres.

Voir la [décision 0218](../../../project/decisions/0218-personal-tree-sharing-inheritance.md).
