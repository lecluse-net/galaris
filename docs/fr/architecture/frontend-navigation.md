<p align="right"><strong>Français</strong> · <a href="../../en/architecture/frontend-navigation.md">English</a></p>

# Architecture de navigation du frontend

La navigation relie une intention utilisateur à un écran. Le
[guide des menus et parcours](../user/navigation.md) décrit les étapes visibles ; la
[carte générée](generated/navigation.md) et son [contrat JSON](generated/navigation.json)
inventorient les entrées livrées, sans présumer des droits d’une session.

## Composition du shell et des menus

`front/modules.ts` active les modules. Chaque `navigation.ts` contribue un arbre indexé
par clés stables. `core/navigation/tree.ts` fusionne récursivement ces arbres dans l’ordre
d’activation, sans modifier les contributions d’origine. Un module peut ainsi compléter
`admin.params.children` sans remplacer les autres préférences.

`app/index/navigationSections.ts` ordonne les cinq racines de la barre latérale.
`MainLayout.vue` porte le conteneur de pages, la barre mobile et le menu utilisateur ;
`Sidebar.vue` affiche les sections ayant au moins une entrée visible. Les enfants sont
triés par `order`, avec 99 par défaut. Les libellés et descriptions sont résolus par les
catalogues i18n ; les noms internes ne sont pas les libellés affichés.

`core/navigation/composables/useNavigation.ts` filtre chaque nœud : au moins un de ses
privilèges doit être présent, puis sa condition `visible` doit être satisfaite. Masquer
un parent masque aussi ses descendants. Ces filtres ne remplacent pas les autorisations
des pages, des actions et de l’API. L’absence d’un menu ne prouve pas l’absence du module.

## Routes, sous-menus et onglets

`front/vite.config.ts` configure les routes issues des fichiers `pages/`. Les chemins
`to` des menus donnent les destinations de navigation. La colonne `route_hint` de la
cartographie générale reste indicative : ne pas l’utiliser pour inventer un lien utilisateur.

Les préférences et le Laboratoire construisent leurs sous-menus depuis leurs
`presentation.ts` ; le Laboratoire ajoute les droits de `access.ts`. Les harnais peuvent
ajouter des entrées depuis le catalogue serveur. Ces noms et identifiants dépendent de
l’installation, donc ils ne figurent pas comme entrées fixes de la documentation.

Les onglets sont définis par les pages et composants Vue. Un nom d’onglet ne constitue
pas automatiquement un paramètre d’URL. Le guide utilisateur documente les liens
`?tab=` réellement consommés par Outils, Compétences, LLM et Activité, et les interactions
sans lien direct comme les onglets de Mémoire. Le menu du compte est un composant séparé,
avec profil, tokens, préférences personnelles et changement de rôle.

## Génération et entretien du corpus des agents

`front/scripts/navigation-context.mjs` lit les modules actifs, charge leurs déclarations
et réutilise la fusion du runtime. Il charge les catalogues FR/EN et les données de
présentation pour produire `docs/{fr,en}/architecture/generated/navigation.{md,json}`.
Les deux fichiers JSON contiennent les deux langues. Chaque entrée expose :

- son identifiant stable, son fil de navigation traduit, sa route et sa description ;
- ses groupes de privilèges, en OU au sein d’un groupe et en ET entre ancêtres ;
- ses conditions supplémentaires, y compris celles héritées ;
- les fichiers sources qui contribuent au nœud.

Le générateur ne démarre pas Vue et n’interroge aucune instance. Il charge uniquement
les modules de données admis ; les imports des prédicats de disponibilité sont remplacés
par des fonctions qui refusent toute exécution. Un nouvel import non prévu ou une
traduction manquante fait échouer la génération plutôt que produire une carte incomplète.
Ce chargeur traite le code du dépôt comme une source de confiance, pas comme un bac à sable.

`make project-context` régénère carte générale et menus dans des conteneurs.
`make project-context-check` vérifie les deux ; `make architecture-check` inclut ce contrôle.
Les tests du générateur vérifient composition, traductions, héritage des conditions,
exclusion des modules inactifs et propagation des changements de routes.

Lors d’un changement de navigation, régénérer la carte et mettre à jour les parcours
FR/EN concernés. La carte générée couvre les menus déclarés, pas l’ensemble des boutons,
onglets de modales ou données propres à l’installation : ces parcours restent documentés
dans le guide utilisateur après lecture des composants réels.

Le corpus documentaire embarque ces fichiers avec la version du produit. Galaris Admin
les expose à la recherche et à la lecture générique, et `documentation_catalog` annonce
le guide et la carte comme points d’entrée. Le skill `galaris-knowledge` les consulte
pour guider l’utilisateur avec **section → écran → onglet → action**. Aucun compte rendu
de session, contenu utilisateur ni secret n’entre dans cette cartographie.
