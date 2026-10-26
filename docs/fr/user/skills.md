<p align="right"><strong>Français</strong> · <a href="../../en/user/skills.md">English</a></p>

# Utiliser et administrer les compétences

Ouvrez **Configurer → Compétences** (`/skill`). Une compétence est un package contenant un
`SKILL.md` et éventuellement des références, scripts ou modèles. Elle apporte une méthode
à l'agent ; les connexions, autorisations d'action et droits sur les ressources restent nécessaires.

## Choisir la bonne collection

| Onglet | Contenu |
|---|---|
| Compétences | Catalogue générique, catégories et packages système protégés |
| Compétences personnelles | Packages privés appartenant chacun à un agent |
| Auto-apprentissage | Procédures apprises par Dream, si l'apprentissage est activé |
| Autorisations | Affectations génériques, avec `SKILL_ASSIGN` |

Les personnels ne sont ni des souvenirs ni des Documents. Un package générique peut être
attribué à plusieurs agents ; un personnel est utilisable uniquement par son propriétaire.
Pouvoir administrer ce propriétaire ne rend pas ses compétences utilisables par vos autres agents.

## Désactiver un générique pour tous

Dans **Compétences**, utilisez **Désactiver pour tous** sur la ligne ou dans son menu
contextuel. Cette action demande `SKILL_EDIT` et la gestion globale des agents ; elle est
aussi disponible pour les packages système. Le package devient invisible dans les compétences
utilisables des agents, même si une catégorie ou un agent l'autorise explicitement.
Ses fichiers et ses affectations sont conservés. **Activer pour tous** rétablit l'application
de ces affectations ; la valeur globale dans **Autorisations** reste une valeur par défaut.

La gestion MCP reste disponible avec les droits habituels : `skills_list(administration=true)`
et `skill_read(..., administration=true)` permettent de consulter le package désactivé.
`skill_set_enabled(skill_id, enabled, expected_revision, administration=true)` permet à un
agent de portée `all` de le désactiver ou de le réactiver pour tous.

## Modifier un package personnel

Dans **Compétences personnelles**, recherchez le package ou filtrez son agent propriétaire.
La liste est paginée, avec 50 éléments par défaut et les choix 10, 20, 50, 100 ou 500.
Ouvrez le package pour consulter ses fichiers, éditer un fichier texte ou son libellé,
l'activer, le désactiver ou le supprimer. La lecture suit vos droits Compétences et votre
périmètre de gestion ; les mutations demandent `SKILL_EDIT`.

Les modifications contrôlent la révision lue. Si un autre acteur a changé le package,
le conflit conserve votre brouillon : rechargez et examinez les changements avant de
réessayer. L'activation concerne seulement le propriétaire. La suppression porte sur
le package et ses fichiers ; les packages système restent protégés.

**Changer de propriétaire** transfère le personnel à un autre agent actif que vous gérez.
Le package conserve son identité, son auteur et ses fichiers ; son activation est retirée
à l'ancien propriétaire et attribuée au seul nouveau. Vérifiez le destinataire et confirmez.
Une collision de code ou un dépassement de quota refuse le transfert sans écrasement.
Les quotas sont de 100 packages personnels et 200 Mio cumulés par propriétaire.

## Passer entre personnel et générique

Ces conversions demandent l'édition des compétences et la gestion globale des agents.

- **Passer en personnel** sur un générique non système demande un agent propriétaire.
  Les anciennes autorisations, l'activation globale et la catégorie du package sont retirées ;
  il devient actif pour ce seul propriétaire. Les autres compétences de la catégorie restent intactes.
- **Convertir en compétence générique** retire la propriété, initialement sans activation
  pour quiconque. Configurez ensuite ses affectations dans **Autorisations**.

Choisissez un autre code en cas de collision. Les conversions préservent l'identité, l'auteur
et les fichiers et disposent d'un reçu de reprise ; réessayer une opération incertaine ne doit
pas créer une seconde conversion. Un transfert entre agents reste distinct d'une publication
dans le catalogue générique.

## Déléguer la gestion à un agent

Dans **Outils & connexions → Connexions**, configurez la connexion **Compétences** (`skills`).
Sa portée locale `tools.management_scope` n'a ni valeur globale ni héritage :

| Portée | Possibilité |
|---|---|
| `usage` | Découvrir et lire les compétences utilisables ; défaut si la portée est absente |
| `personal` | Administrer ses propres packages personnels |
| `team` | Administrer aussi les personnels et affectations génériques des agents partageant une équipe active |
| `all` | Administrer tous les packages utilisateurs et le catalogue générique ; retirer la propriété |

`team` suit l'union des équipes actives, relue à chaque appel. L'administration d'un personnel
étranger reste une vue explicite ; elle ne permet pas son usage. Seul un humain en session web,
avec édition des connexions et gestion globale des agents, peut modifier cette délégation.
Activer une connexion seule ne donne aucune portée globale.

L'agent utilise `skills_list` et `skill_read` pour découvrir et lire le `SKILL.md`.
Les fichiers passent par `file_*` sur `galaris://skill/` ; l'espace personnel est
`galaris://skill/personnal/<agent>/<code>/` (orthographe canonique `personnal`). La création
commence par un `SKILL.md` valide dans l'espace de l'agent authentifié. Les fonctions
`skill_update`, `skill_set_enabled`, `skill_delete`, `skill_set_authorization`,
`skill_set_category_authorization` et `skill_release_ownership` gardent leurs contrôles
de portée, de révision et de permission à chaque appel.

L'ancien Tool `skill_management` est remplacé par `skills` en conservant ses connexions
et leurs réglages. Une connexion désactivée reste désactivée.

## Quand les changements prennent effet

Avant une nouvelle exécution, les harnais managés réconcilient les packages et affectations
autorisés, y compris les personnels du seul propriétaire. Un échec de projection bloque
le départ avec une copie périmée et reste réessayable. Une tâche déjà lancée conserve son
contexte ; une reprise avec checkpoint conserve celui de l'opération qu'elle réconcilie.
Les prochaines lectures et mutations revérifient néanmoins les droits courants.

Voir aussi [les privilèges](../admin/privileges.md), [l'administration des outils](../admin/tool-administration.md)
et [la navigation](navigation.md).
