# 0121 — Aides contextuelles acquittées par compte

Statut : Accepted

## Décision

Les aides expliquent les notions propres à Galaris et à l’IA, avec un paragraphe
concret sur le rôle de la fonctionnalité et son usage. Leur intégration est explicite :
aucune insertion automatique par route ou module. Les écrans courants (utilisateurs,
rôles, profil, contacts, journaux, etc.) et le menu Préférences restent sans aide.
L’accueil du Lab fait exception : une aide unique au-dessus du menu explique la
philosophie de l’évaluation, sans être répétée dans ses sous-pages.

`core.user` conserve les acquittements dans `user_help_dismissals`, avec une clé stable
par aide, l’utilisateur et la date « vu ». L’unicité utilisateur/clé et un insert
idempotent préservent les autres acquittements, même entre plusieurs appareils.
Les endpoints authentifiés `/auth/me/help-dismissals` déduisent toujours le compte
de la session. Il n’existe pas d’opération de remise à zéro.

La croix et « J’ai compris » enregistrent le même acquittement. La simple consultation
n’enregistre rien. Le frontend ne masque le bloc qu’après confirmation du serveur,
propose de réessayer en cas d’échec et ignore les réponses d’un ancien compte.
Il attend les préférences avant d’afficher le contenu d’une aide.

`ContextHelp`, exporté par `core/util`, porte cette interaction. Le bootstrap lui
fournit le store de `core/user` par un contrat injecté, sans dépendance de l’interface
générique vers le module utilisateur. `PageHeader` propose une intégration optionnelle ;
chaque domaine fournit son texte traduit et sa clé.
Un changement de formulation ou de langue conserve la clé et ne réaffiche pas l’aide.

## Garanties et consommateurs

Les consommateurs sont les écrans agents, outils et connexions, compétences, tâches,
objectifs, dossiers thématiques, mémoire, documents, modèles, Dream, processus,
navigateur, accueil du Lab et Chat. Les textes expliquent notamment les échanges entre
agents, MCP, le format standard Agent Skills et le parcours fournisseurs → modèles
disponibles → profils de modèles utilisés.

Le test `frenchTerminology.test.mjs` continue d’imposer « compétences » dans
l’interface française. Une exception ciblée sur `contextHelpPages.skills` permet à
l’introduction pédagogique de nommer le terme technique « skills », le format Agent
Skills et son fichier `SKILL.md`. Les contrôles et les autres descriptions conservent
la terminologie française ; la parité des langues reste couverte par le contrôle i18n.

Les tests HTTP avec PostgreSQL éphémère couvrent l’authentification, l’idempotence,
l’isolation entre comptes et la restauration après reconnexion. Les composants réels
en navigateur couvrent les deux actions, réouverture, erreur et nouvelle tentative,
réponses tardives, changement de compte, français, mobile et thèmes clair/sombre.
