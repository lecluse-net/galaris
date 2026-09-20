# 0107 — Classement automatique des documents des objectifs

Statut : accepté — 17 septembre 2026.

Les documents liés à un Goal sont classés automatiquement dans une arborescence personnelle
`Objectifs / <libellé du Goal>`. Les dossiers appartiennent exclusivement à un utilisateur.
Le classement ne modifie ni le contenu, ni les révisions, ni les droits des documents.

## Sources et autorité

Les deux références documentaires du Goal et les provenances `MemorySource.task_id` vers ses
Tasks déterminent les documents concernés. Les Tasks déléguées héritent déjà du Goal.
Un titre, un chemin documentaire historique ou une simple mention ne constitue pas ce lien.
Les droits sont ceux de la bibliothèque : accès humain direct, équipes, partage public et agents
administrés. Ils sont recalculés à l'exécution pour chaque utilisateur actif, indépendamment du
rôle du demandeur du job.

`DocumentTag.user_id` reste l'unique propriétaire du dossier. `goal_id` identifie son association
au Goal ; `system_role=goals_root` identifie la racine personnelle. Des index uniques partiels
garantissent une racine et un sous-dossier actif par couple utilisateur/Goal. Les noms ne sont
jamais des identifiants : deux Goals homonymes restent distincts. Une racine personnelle ordinaire
portant exactement le nom localisé attendu peut être réutilisée.

Le nom généré suit le Goal tant que l'utilisateur ne l'a pas personnalisé. Les noms de dossier
respectent leur contrat existant de 100 caractères. Les déplacements et noms personnels sont
conservés. Les documents possédant déjà au moins un dossier actif chez l'utilisateur sont exclus,
même lorsque leur dossier correspond à un autre Goal. Le classement d'un autre utilisateur
n'intervient jamais dans ce choix.

## Exécution durable

Le type `goal_folder_reconcile` utilise `MemoryAutomationJob` et le worker Memory existants.
Les filtres `user_id` et `goal_id` sont facultatifs et cumulatifs ; aucun filtre signifie tous.
Une demande globale parcourt les utilisateurs actifs ; chaque utilisateur parcourt seulement les
Goals dont il peut lire des documents ; chaque couple classe les documents encore sans dossier.
Les pages sont bornées à 50. Chaque page persiste sa continuation dans la même transaction que
ses écritures ; le rejeu d'une continuation possède une clé unique.

Les demandes identiques encore en attente sont regroupées sous verrou. Une demande pendant une
exécution en cours crée un passage ultérieur : elle ne peut pas être absorbée par un parcours
ayant déjà dépassé le document changé. Le worker conserve ses reprises et son budget d'erreurs.

Les écritures et la vérification du classement prennent le verrou d'arborescence de l'utilisateur,
également utilisé par les opérations manuelles. Les projections structurelles sont mises à jour
dans cette transaction ; les vues sont invalidées après validation si le classement a changé.
Aucun dossier n'est créé sans document à ranger. Une suppression ne produit aucune interdiction
de recréation et ne déclenche pas elle-même un job : un prochain événement ou rattrapage peut recréer
le dossier. Aucune opération n'est déclenchée par la simple ouverture de Documents.

## Déclencheurs et administration

- Observer Goal après création/modification ; observer Memory après création, source ou partage.
- Observer User après création/réactivation/changement de langue ; changements d'affectations
  de rôles et de privilèges ; observateurs des équipes et des profils Agent.
- Les observers publient des demandes courtes après le commit métier, selon le mécanisme existant.
  Leur échec est journalisé sans annuler une mutation déjà validée. Le rattrapage global reste
  nécessaire pour réparer un événement manqué.
- Le reconciler DbAdmin `app.memory.goal_folders` enfile un rattrapage global si des Goals existent,
  sans effectuer le classement pendant la synchronisation.
- `POST /api/memory/goal-folders/reconcile`, réservé à `MEMORY_ADMIN`, accepte `{}`, `user_id`,
  `goal_id` ou les deux et répond `202` avec le `job_id` de la demande persistée. La réussite du
  job de répartition n'indique pas que tous ses jobs enfants sont déjà terminés.
- La façade `app.memory.facade.enqueue_goal_folder_reconciliation` offre le même contrat interne ;
  son appelant valide la transaction.

Garanties : `back/app/memory/tests/test_goal_folders.py` couvre classement personnel, accès tardifs,
droits révoqués avant exécution, renommage, suppression/recréation, homonymes, pages, demandes
concurrentes, rollback et reprise, provenance des livrables, déclencheurs et autorisation HTTP.
