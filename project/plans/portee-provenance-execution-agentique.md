# Exécution agentique — portée et provenance

- Statut : `partial` — socle d'activité livré, contrôle générique de portée à concevoir.
- Revue des sources : 2026-10-08.

## Écart à combler

Objectif, Working Set, reçus, activité partagée et checkpoints existent :
[0087](../decisions/0087-task-activity-snapshots.md),
[0143](../decisions/0143-retire-execution-briefing.md) et
[flux d'exécution](../../docs/fr/architecture/flows/agent-execution.md).
Ils ne constituent pas encore le contrat générique de portée proposé ici.
Les autorisations ponctuelles [0153](../decisions/0153-common-action-authorizations.md)
restent distinctes de la justification d'une cible par l'intention utilisateur.

Garantie recherchée : planner, exécuteur et livraison poursuivent les mêmes exigences
sourcées ; profil, mémoire ou ressource découverte ne peuvent introduire silencieusement
une cible ou un effet sans rapport avec l'objectif. La lecture et la production ordinaires
restent autonomes ; clarification seulement pour des effets matériellement différents.

## Contrats candidats

| Contrat versionné | Contenu minimal |
|---|---|
| `ExecutionScopeV1` | Exigences identifiées et provenance ; grants de cibles/capacités/contraintes ; propriétaire et cible de livraison ; hypothèses. |
| `EffectDescriptorV1` | Capacité extensible, mutation, réversibilité, visibilité, arguments portant la cible, idempotence et nature du reçu. |
| Plan validé | Exigences servies, cible ou règle de découverte, provenance, effet attendu, outils utiles, preuves de complétion et inconnues. |
| Décision de préflight | `allow`, `allow_and_record`, `clarify` ou `deny`, avec identité/révision et raison bornée. |

Noms et représentation sont candidats, pas des API actuelles.
Une première persistance de scope dans `Task.data` est possible si aucun besoin SQL dédié
n'est démontré. Les fichiers utilisent des URI canoniques ; autres ressources par référence
publique stable, jamais par libellé interprété.

Priorité cible : demande utilisateur → scope issu de l'admission → grants/Working Set →
reçus vérifiés → politique du domaine propriétaire → contexte pertinent → plan → mémoire/profil.
Une source basse suggère une recherche ; elle n'accorde pas un droit ni ne contredit une source haute.

## Lots restants

| Lot | Livrable et réception |
|---|---|
| Contrats et persistance | Parsing/version inconnue, provenance, héritage parent/enfant et amendement testés via le port Task ; aucune dépendance `app.agent → app.task`. |
| Admission et livraison | Objectif autonome, exigences non affaiblies, cibles exactes et continuité pertinente ; propriétaire unique de livraison, sans copie de tout l'historique. |
| Planner | Sortie structurée et validateur déterministe : exigences couvertes, cibles sourcées, outils effectifs, livraison unique. Rejet sémantique distinct d'un retry de schéma ; clarification sur la même Task si nécessaire. |
| Descripteurs et préflight | Métadonnées optionnelles du catalogue filtré, échantillon lecture/création/mutation/transport/suppression/Process, décision avant effet et validation finale par le domaine propriétaire. |
| Activité et reprise | Scope/préflight projetés dans `TaskActivitySnapshot` existant ; reconnexion, droits, pause, leases et checkpoints préservés, sans seconde timeline. |

Le catalogue appartient à `app.tools`, le scope et sa validation à `app.agent`,
la persistance à `app.task`, l'admission à `app.conversation`.
Les domaines et bridges conservent paramètres, ACL, secrets, idempotence et reçus.

## Compatibilité et autonomie

Un outil sans descripteur reste visible et utilisable selon le RBAC actuel ; son effet
est inconnu, pas implicitement autorisé sur toute cible. Nouvelle cible externe ou effet
irréversible demande justification sourcée ou clarification lorsqu'ils sont décelables.
Ne pas créer de taxonomie centrale par produit ou parser les commandes comme seule barrière.

Une ressource découverte peut enrichir le Working Set pour une exigence déjà autorisée ;
une extension vers un autre acteur, collection ou effet demande une justification.
Une production sans destination imposée suit les contrats existants de document/provider
et du runtime, sans inventer un espace local ni demander un choix technique inutile.

La politique du canal peut livrer dans le contexte courant ; le planner n'ajoute pas un
second transport. Un succès conserve source, destination, fonction et reçu.
Une reprise consulte ce reçu avant de rejouer. Le plan ne confère pas de grant.

## Réception et décisions ouvertes

Exercer profil riche avec objectif sans cible, cible explicite, libellé ambigu, découverte
vérifiée, mémoire contradictoire, outil inconnu, exigence omise et effet hors scope.
Préserver stream à terminal unique, droits et outils légitimes.

Persister décision/révision avant l'effet, revérifier avant publication, puis injecter
pannes ORM avant/après effet, perte de lease, rollback secondaire, redelivery et crash
entre reçu, Working Set et terminal. Un effet confirmé ne se répète pas ; l'incertitude
reste une attente ou une issue explicite. La preuve du harnais interne ne qualifie pas
automatiquement Process ou les autres runtimes.

Arrêter les choix de stockage, héritage/amendement, compatibilité des outils non enrichis
et articulation avec les autorisations existantes dans une ADR avant implémentation.
Réutiliser tests et Lab ; publier les contrats dans les flux d'exécution/process/ressources,
puis retirer les lots réalisés.
