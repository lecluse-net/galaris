# 0295 — Composition frontend sans cycles et erreurs par opération

Statut : accepté, implémenté. Complète la décision 0294.

## Garanties et responsabilité des écrans

Les URL `/agent`, `/services`, `/tools` (redirection) et `/task` restent identiques.
Les pages qui assemblent plusieurs domaines appartiennent à `app.index`, le shell
applicatif. Les composants, services et stores métier restent dans leurs domaines ;
leurs consommateurs utilisent leurs surfaces publiques. Le graphe frontend ne conserve
aucun cycle entre modules ni import privé inter-domaines. La baseline protège ce résultat.
Le contrôle des imports statiques complète cette vérification au niveau des fichiers Vue
et TypeScript, y compris les réexports et les contributions Vite chargées avec `eager: true`.
`make architecture-check` et le workflow Quality rejettent ces cycles et indiquent leur chemin.

Les résultats et messages IA sont des contrats de `app.agent`, réexportés par Task pour
ses consommateurs historiques. Les appels LLM ouvrent le détail Task par le mécanisme
commun des ressources. La contribution de capture Lab et la sélection des utilisateurs
des paramètres Service sont assemblées à la racine, comme les autres contributions du
frontend ; elles conservent les droits et sources de données des domaines propriétaires.
Un domaine ne devient pas propriétaire d'une autre ressource pour afficher son détail.

## Composants et erreurs asynchrones

La page Agents possède les onglets du catalogue. L’aperçu de ressource et la page composent
le même espace de gestion dans `app/index`, qui réunit les actions Agent, Harnais et LLM.
La carte et le catalogue des intitulés appartiennent à `app/agent`. L’aperçu lit directement
la fiche autorisée de l’agent ciblé.
Le composable `useAgentHarnessRuntime` possède les lectures d’état, le suivi de
disponibilité du gestionnaire, les actions individuelles, la relance groupée et
l’ouverture des journaux. Il arrête le rafraîchissement lorsque le contexte est fermé.
L’espace Agents conserve les sélections, confirmations et sauvegardes du formulaire.

Le composable de sauvegarde documentaire possède le brouillon de reprise, sa base,
les conflits et la file d’écriture. L’éditeur fournit le contexte documentaire et de
session, les droits et les interactions avec le rendu. Le composable vérifie ce contexte
à chaque réponse avant de poursuivre une sauvegarde.

Les menus utilisent les fichiers internes de navigation. Les contributions de harnais
fournissent leurs panneaux par chargement différé.
Le démarrage importe le contrat d’événement Connection sans charger ses sélecteurs.
La conversion Markdown des extraits d’aperçu se charge à la demande.

La modale d'import YAML de Service possède le fichier, son aperçu et le cycle de
confirmation. Une réponse tardive ne modifie pas une modale rouverte. La liste reçoit
les imports réussis pour actualiser son catalogue et, si la modale était encore ouverte,
révéler le Service importé.

Le formulaire Service construit la configuration du diagnostic MCP et la définition
du candidat. La modale possède les paramètres temporaires, les résultats du test et la
référence de candidat. Chaque requête reste liée à son ouverture et à sa session.
Modifier un paramètre temporaire invalide les réponses aux requêtes lancées avec les anciennes valeurs.

La synthèse Goal, les paramètres globaux Service et l'onglet MCP Agent portent des
contrats et cycles de vie autonomes. Les paramètres réutilisent l'éditeur commun ; une
fin de sauvegarde ne remplace ni ne ferme un formulaire rouvert. Changer d'agent efface
les tokens MCP révélés. Un changement de borne de message Chat recharge la liste Task
sans fermer son détail ; changer de conversation, de lecteur ou de droits le ferme.

La sélection automatique du superviseur Goal possède sa propre génération. La fermeture
ou l'annulation d'une recherche ne l'annule pas ; choisir un autre contact, changer
d'agent ou fermer l'objectif l'invalide. Une recherche et une sélection ne partagent
donc pas un indicateur exclusif qui pourrait bloquer silencieusement la création.

`storeRequests` conserve un diagnostic par action. Le dernier lancement de cette action
possède son erreur ; une réussite différente ne l'efface pas. `storeRequestFailure`
permet aux lectures historiquement non rejetantes de signaler leur échec sans changer
leur contrat. Les bannières de catalogue et paramètres proposent leur propre reprise.

Les clés faibles des stores utilisent `toRaw`, y compris pour invalider les lectures
lors d'une mutation ou d'une sélection. Le proxy supplémentaire des actions Pinia en
développement ne doit pas créer une identité distincte. Les tests Node seuls ne
représentaient pas ce chemin ; le scénario de reprise des paramètres dans Vue réel
couvre maintenant la différence, en complément du test central de proxy.

## Styles et vérification

Les règles de modalité et de compacité mobile restent des contrats partagés, explicités
dans une feuille dédiée. Les règles responsive de PageHeader vivent dans le composant.
Les anciennes correspondances de couleurs sans consommateur ont été retirées : les
surfaces utilisent les jetons Solaire. Les `!important` conservés sur les utilitaires
Quasar et les contraintes des modales répondent à leur cascade et aux tailles inline.
La réduction des styles globaux ne justifie pas un changement de présentation métier.

Les parcours de composants couvrent reprise, droits, réponses tardives, fermeture,
réouverture et contenu conservé ; les E2E utilisent une API et PostgreSQL isolés. Une
suite ciblée réussie ne constitue pas une qualification complète de l'application.
