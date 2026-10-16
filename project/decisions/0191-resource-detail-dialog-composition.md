# 0191 — Composition des modales de détail des ressources

Statut : accepté

## Contexte

Le détail d’un sujet doit ouvrir les tâches, rounds, espaces et ressources liés sans
quitter la page. Les domaines concernés utilisent déjà les composants Topics pour
l’affectation : les importer en retour depuis Topics créerait des cycles supplémentaires.

## Décision

`core.util` expose `ResourceDetailDialog` et un contrat de cible limité au type,
à l’identifiant, au titre et au contexte d’agent éventuel. Il charge à la demande le
point de composition applicatif `front/resourceDetails.vue`, découvert comme fournisseur
sans importer les domaines dans Core.

Les runs internes ouverts depuis le Chat utilisent cette même composition avec la cible
`process_run` et le composant public de suivi natif de Process. Le diagramme figé, les
activités et commandes restent ceux de Process ; le Chat ne duplique pas leur lecture.
Les processus externes conservent leur détail spécifique.

Le fournisseur peut exposer un préchargement de code par type de cible. `core.util`
le relaie avec `preloadResourceDetail`, sans lecture de données ni nouvelle dépendance
entre domaines. Le Chat prépare ainsi le diagramme lorsqu'un run interne est présent.
Les services et vues des autres types sont importés uniquement lorsqu'ils sont utilisés.

Ce fournisseur assemble les services et vues publics des domaines. Il conserve leur
autorisation serveur, leurs actions et leurs composants de détail. Les lectures tardives
sont ignorées après fermeture ou changement de cible ; les traces LLM ne bloquent pas
la lecture du round. La fermeture par l’arrière-plan reste disponible.

## Vérification

`front/browser-tests/topic-detail.spec.mjs` couvre les six types de cibles sur desktop
et mobile, le clavier, la fermeture, le réessai après refus et les réponses tardives.
Le contrôle d’architecture ne doit ajouter aucune dépendance entre les domaines.
