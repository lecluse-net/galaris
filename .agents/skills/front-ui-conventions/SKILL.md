---
name: front-ui-conventions
description: Conventions frontend Galaris avec Vue, Quasar, Pinia, routage par fichiers, services API, navigation, RBAC et i18n. À utiliser pour toute modification sous front/core ou front/app, avec les skills framework correspondant aux imports.
---

# Écrire l’interface Galaris

## Charger les références spécialisées

Utiliser également :

- `vue-skilld` pour tout fichier `.vue` ou import Vue ;
- `quasar-skilld` pour les composants Quasar ;
- `pinia-skilld` pour un store Pinia ;
- `vue-router-skilld` pour le routage ;
- `vue-i18n-skilld` pour les catalogues ou appels i18n.

## Respecter les responsabilités

- Page : orchestration de l’écran, chargement et composition des composants.
- Composant : interaction ou présentation focalisée avec props et événements typés.
- Service : types du contrat et appels à l’API Galaris.
- Store Pinia : état partagé ou durable côté interface, pas tout état local.
- `presentation.ts` : libellés/icônes de présentation partagés lorsqu’un domaine le prévoit.

Éviter les composants monolithiques. Extraire une unité quand elle possède son propre état,
cycle de vie, contrat de props ou comportement testable.

## Routes basées sur les fichiers

Les pages sous `front/<layer>/<module>/pages/` sont découvertes automatiquement. Le préfixe
du module vient de `front/modules.ts`; `index.vue`, `[id].vue` et `[...all].vue` définissent
ensuite les segments. Ne pas ajouter une seconde configuration manuelle sans nécessité du
routeur central.

## Services et état

Les documents ont un type immuable `html` ou `dataset` dans la même bibliothèque.
Utiliser CKEditor pour HTML et CodeEditor en langage JSON pour Dataset, y compris dans
l'historique. Ne jamais convertir le JSON en HTML. Une autosauvegarde attend un JSON valide
et préserve le brouillon invalide ; le partage, les icônes et le classement restent communs.
Les documents acceptent directement formulaires HTML, CSS et JavaScript. Conserver la barre
d'outils et l'édition habituelles : aucun mode lecture/édition, démarrage ou assistant de
formulaire supplémentaire. Seul Source affiche le code. CKEditor conserve les portions
interactives comme objets opaques internes ; leur rendu isolé n'ajoute aucun habillage.
Les anciens `language-galaris-app` restent compatibles. Les autres lecteurs masquent le code
et restent inertes. Les Datasets déclarés exigent les droits du lecteur et son accord personnel
enregistré côté serveur pour la révision courante. L'icône Permissions gère cet accord hors du
HTML ; préserver le rendu et la saisie lors d'un refus d'accord.
Voir `docs/fr/dev/document-apps.md` pour les règles de CSP, révisions et révocation.

- Typer les requêtes et réponses ; ne pas propager `any` depuis Axios.
- Centraliser l’URL et la sérialisation d’une ressource dans son service.
- Dans Pinia, typer l’état, les retours d’actions et les erreurs attendues.
- Nettoyer listeners websocket, timers et abonnements dans le cycle de vie approprié.
- Ne pas dupliquer dans le store une donnée dérivable par un getter.

## Quasar et expérience utilisateur

- Utiliser les tokens, espacements et composants déjà présents dans les pages voisines.
- Afficher explicitement chargement, état vide et erreur.
- Préserver clavier, focus, libellés accessibles et comportement responsive.
- Confirmer une action destructive et ne mettre à jour l’état optimiste que si son rollback
  est défini.

### Normaliser toutes les modales

- Donner à chaque `q-dialog` une barre de titre bleue avec la classe partagée
  `galaris-dialog-title`, un titre explicite et un bouton de fermeture `close` en haut à
  droite (`flat`, `round`, `dense`, `v-close-popup` et libellé accessible).
- Laisser systématiquement le clic sur l’arrière-plan fermer la modale. Ne jamais utiliser
  `persistent`, `no-backdrop-dismiss` ni une option équivalente.
- Reprendre les dimensions, espacements, séparateurs et actions des modales voisines. Mettre
  les actions Annuler puis Valider dans le pied de modale.
- Préférer un `q-dialog` applicatif explicite au plugin Dialog lorsque le plugin ne permet pas
  d’afficher la barre de titre et le bouton de fermeture normalisés.

## RBAC et traductions

La navigation peut masquer un élément selon les privilèges, mais l’API reste l’autorité.
Toute chaîne visible utilise une clé i18n. Les objets `en` et `fr` d’un module doivent avoir
les mêmes clés, types de valeurs et paramètres nommés. Ne pas concaténer des fragments dont
l’ordre dépend de la langue.

## Validation

Lancer les contrôles ciblés, puis `make typecheck`. Si les pages, modules ou éléments de
navigation changent, régénérer aussi la cartographie avec `make project-context`.
