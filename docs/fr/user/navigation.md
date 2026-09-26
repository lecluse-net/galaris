<p align="right"><strong>Français</strong> · <a href="../../en/user/navigation.md">English</a></p>

# Se repérer dans Galaris : menus, écrans et parcours

Ce guide aide à trouver une fonction dans l’application. La
[carte des menus générée depuis le frontend](../architecture/generated/navigation.md)
donne les libellés exacts, routes, descriptions et conditions d’accès de la version livrée.
Les chemins ci-dessous sont relatifs à votre instance Galaris.

## Ouvrir les menus

Une fois connecté, utilisez la barre latérale à gauche. Si elle ne montre que des icônes,
dépliez-la avec le bouton menu. Sur un écran de moins de 1024 pixels CSS de large,
le bouton menu de la barre supérieure ouvre le tiroir de navigation. Les sections restent
les mêmes ; leur visibilité dépend du rôle actif et des fonctions disponibles.
Le logo de la barre latérale mène à l’accueil `/`.

Le menu du compte s’ouvre en cliquant sur votre nom ou avatar, en haut à droite.
Il regroupe le profil, les tokens API personnels, la langue, le thème, les affectations
permettant de changer de rôle et la déconnexion. Le rôle affiché sous le nom permet de
vérifier le contexte courant. Les préférences personnelles de langue et de thème sont
distinctes des **Préférences** d’administration de l’instance.

## Les cinq sections principales

| Section | Ce qu’on y trouve |
|---|---|
| **Configurer** | Fournisseurs & modèles, Agents, Outils & connexions, Compétences |
| **Agir** | Discussion, Objectifs, Processus |
| **Connaissances** | Documents, Mémoire, Contacts, Sujets |
| **Superviser** | Tableau de bord, Activité, Dream, Journal des mails, Journal des échecs |
| **Administrer** | Préférences, Laboratoire, Console, Utilisateurs, Équipes, Rôles & autorisations |

Dans la documentation technique, « Chat » correspond au menu **Discussion**, « Skills »
à **Compétences**, « Tasks » à l’onglet **Tâches** d’**Activité**, « Topics » à **Sujets**
et « Lab IA » au **Laboratoire**. Ces termes désignent les mêmes domaines ; ils ne sont
pas autant de menus supplémentaires.

## Fournisseurs, modèles et agents

**Configurer → Fournisseurs & modèles** (`/llm`) propose :

| Onglet | Usage | Lien direct |
|---|---|---|
| Fournisseurs | Configurer les services de modèles et consulter leur catalogue | `/llm?tab=providers` |
| Modèles disponibles | Gérer les modèles exposés à Galaris | `/llm?tab=models` |
| Modèles utilisés | Choisir les modèles employés par les usages et profils | `/llm?tab=usage` |

Dans **Fournisseurs → Ressources disponibles**, la liste **Type de ressources** conserve
les icônes et filtre le catalogue du fournisseur. **Documents / PDF** présente les modèles
de chat déclarant les fichiers en entrée et le texte en sortie. Ajoutez un modèle, puis
affectez-le à **Modèle d’analyse de document** dans **Modèles utilisés**. Si les métadonnées
du fournisseur sont incomplètes, un modèle compatible peut manquer à cette liste.

L’onglet **Modèles utilisés** demande `PARAMS_ACCESS` ou `PARAMS_EDIT`, en plus des
droits nécessaires pour atteindre l’écran. Il est sélectionné par défaut pour les comptes
autorisés ; sinon l’écran ouvre **Fournisseurs**.

### Créer un agent

**Configurer → Agents** (`/agent`) contient les onglets **Agents**, **Équipes** et
**Civilités**, selon les droits. Pour créer un agent, ouvrez l’onglet **Agents**, puis
**Nouvel Agent**. Pour modifier un agent existant, ouvrez sa fiche depuis la liste.
Les onglets de cette fiche ne sont pas les onglets de la page : ils regroupent notamment
le général, les modèles et le MCP selon les droits. Le choix du moteur des Tasks appartient
à la fiche de l’agent ; l’administration des harnais se trouve dans
**Administrer → Préférences → Harnais** (`/params/harnesses`). Les entrées de harnais
dépendent du catalogue serveur : utilisez le lien affiché, sans inventer leur identifiant.

## Outils, connexions et compétences

**Configurer → Outils & connexions** (`/tools`) sépare trois besoins :

| Onglet | Usage | Lien direct |
|---|---|---|
| Outils | Consulter les Tools et leurs fonctions | `/tools?tab=tools` |
| Connexions | Configurer les connexions associées aux agents | `/tools?tab=connections` |
| Autorisations | Administrer les règles d’accès aux outils et fonctions | `/tools?tab=authorizations` |

Pour donner la connaissance du produit à un agent, partez de **Connexions**, trouvez sa
connexion **Galaris Admin**, puis suivez le [guide de connaissance produit](../admin/product-knowledge.md).
Une compétence fournit des instructions ; l’accès effectif aux fonctions dépend aussi
des Tools et connexions autorisés.

**Configurer → Compétences** (`/skill`) contient **Compétences** (`?tab=skills`),
**Auto-apprentissage** (`?tab=learned`) si l’apprentissage est activé, et
**Autorisations** (`?tab=authorizations`) avec le privilège `SKILL_ASSIGN`.
Cette dernière page gère l’affectation des skills ; elle ne remplace pas les autorisations
des Tools ni les rôles du compte humain.

Les compétences fournies **Galaris**, **Galaris Lab** et **Connaissance de Galaris** sont
regroupées par défaut dans la catégorie **Galaris**. La synchronisation classe aussi les
compétences existantes sans catégorie, en conservant vos classements personnalisés.

## Discuter, suivre une tâche et retrouver son résultat

Pour échanger avec un agent, ouvrez **Agir → Discussion** (`/chat`). Pour un objectif
durable, ouvrez **Agir → Objectifs** (`/goal`). Pour lancer un workflow prédéfini,
ouvrez **Agir → Processus** (`/process`). Le [guide utilisateur](README.md) explique
quand choisir une conversation, une Task ou un Goal.

Le suivi se fait dans **Superviser → Activité** (`/task`) :

| Onglet | Contenu | Lien direct |
|---|---|---|
| Conversations textuelles | Historique des échanges courts et des rounds | `/task?tab=conversations` |
| Appels téléphoniques | Historique vocal | `/task?tab=voice` |
| Tâches | Travaux durables, état et détails d’exécution | `/task?tab=tasks` |
| Activité LLM | Appels aux modèles | `/task?tab=llm` |
| Processus | Suivi des exécutions de workflows, avec `PROCESS_READ` | `/task?tab=processes` |

Ne cherchez pas un menu latéral « Conversations » ou « Tâches » séparé : ce sont des onglets
d’**Activité**. **Discussion** sert à échanger ; **Activité** sert à suivre les exécutions.
L’accès à cet écran ne donne pas accès à toutes les conversations ni à tous les agents.

## Documents et connaissances

**Connaissances → Documents** (`/memory/documents`) sert à retrouver les contenus rédigés
et les Datasets. **Connaissances → Mémoire** (`/memory`) propose **Recherche**, **Liste**
et **Graphe** : ouvrez la page puis choisissez l’onglet, sans supposer un paramètre d’URL.
Les contacts sont dans `/memory/contacts` ; les regroupements thématiques dans
**Connaissances → Sujets** (`/topic`). Le partage d’un lien ne donne pas accès au contenu.

## Préférences, supervision et compte

**Administrer → Préférences** (`/params`) présente une grille de rubriques et des sous-menus :
Système, Langue, Messagerie, Mémoire, Dream, Voix, Audio, Processus, Tâches et exécution,
Harnais, Recherche, Navigateur, Janus, Instructions et Journaux. La
[carte générée](../architecture/generated/navigation.md) donne la route de chaque rubrique.

Quelques distinctions utiles :

- **Superviser → Dream** (`/dream`) montre l’activité ; **Préférences → Dream**
  (`/params/dream`) règle son fonctionnement.
- **Superviser → Journal des échecs** (`/incident`) sert au diagnostic ;
  **Préférences → Journaux** (`/params/logs`) configure la conservation et les purges.
- **Administrer → Laboratoire** (`/lab`) regroupe l’analyse de tâches et les évaluations
  par mécanisme, filtrées selon les droits. Voir le [guide du Lab](lab-ai.md).
- Le menu du compte ouvre le profil (`/authorize/profile`) et **Mes Tokens API**
  (`/user/tokens`). Il sert aussi à changer la langue, le thème et le rôle actif.
- **Administrer → Rôles & autorisations** (`/authorize`) gère les autorisations des
  utilisateurs ; les droits de dialogue avec les agents passent aussi par les
  [équipes](teams.md), accessibles dans `/team`.

## Un menu ou un bouton manque

Vérifiez d’abord le rôle actif dans le menu du compte. La carte générée indique les
privilèges de visibilité : dans une même liste, un seul suffit ; les contraintes du
parent s’appliquent aussi aux sous-menus. Les actions de création, modification, partage
et suppression peuvent demander des droits supplémentaires, contrôlés par l’API.

Certaines entrées ont aussi une condition de disponibilité : **Discussion** peut être
désactivée globalement ; le **Journal des mails** demande un service mail disponible ;
la **Console** dépend de l’exécuteur intégré ; **Préférences → Navigateur** dépend de la
disponibilité du navigateur. Les sous-menus de harnais proviennent du catalogue serveur.
Une section sans entrée visible disparaît. Un lien direct ne contourne aucun droit.

Un agent qui vous guide doit donner le chemin **section → écran → onglet → action**,
avec les libellés de votre langue, et signaler les prérequis utiles. S’il ne connaît pas
votre rôle ou votre configuration, il doit demander le libellé ou message affiché,
plutôt que conclure qu’une fonction n’existe pas. La carte documentaire décrit les
possibilités du logiciel ; elle ne constitue pas une observation de votre session.
