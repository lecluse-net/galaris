<p align="right"><strong>Français</strong> · <a href="../../en/user/code-editor.md">English</a></p>

# Suivre et modifier un dépôt Git dans une discussion

Lorsqu’un agent présente son dépôt avec `repository_show`, le panneau de travail affiche
un éditeur code-server, fondé sur VS Code OSS. Le panneau accueille alternativement un
Document ou un dépôt ; la discussion reste utilisable. La rubrique **Code source** permet
de rouvrir les dépôts déjà présentés, même après une reconnexion. Elle se trouve juste
sous **Documents** dans la barre de droite.

Ouvrez cette rubrique pour rechercher aussi les dépôts présents dans le home SSH de l’agent,
sans lui demander de les présenter. Les chemins sont affichés depuis ce home, par exemple
`work/galaris`, sans préfixe `console://`. Cliquez sur un chemin pour associer le dépôt à
la discussion et l’ouvrir dans VS Code. **Actualiser les dépôts** relance la découverte.
La recherche exige une Console active appartenant à votre compte ; les dépôts déjà autorisés
restent accessibles si la recherche échoue ou si vous n’êtes pas propriétaire de la Console.

La découverte reconnaît les dossiers `.git` et les fichiers `.git` des worktrees. Elle ignore
les dossiers cachés, `node_modules`, `__pycache__` et les liens symboliques. Le parcours est
limité à huit niveaux de sous-dossiers, 10 000 entrées, 100 dépôts et 20 secondes ; un message
signale les résultats partiels ou les dossiers inaccessibles. Le checkout et les droits sont
revérifiés au clic. Une Console externe doit disposer du runtime de l’éditeur pour l’ouvrir.

Un clic sur une carte de dossier `console://…/` ouvre aussi l’éditeur du dépôt de l’agent,
si vous avez accès à l’éditeur et au dépôt.
Le dossier doit appartenir à un checkout Git. Si l’éditeur est indisponible ou le dossier
incompatible, une erreur s’affiche dans la discussion ; aucun aperçu vide ne s’ouvre.
Les dossiers des autres providers restent des références sans aperçu plein écran.

L’éditeur reste sur la même adresse que Galaris ; aucun autre site ni connexion séparée
n’est nécessaire.

Le thème et les préférences se règlent directement dans VS Code et suivent son profil
natif. Leur synchronisation avec Galaris est reportée à une évolution ultérieure.
Changer le thème de Galaris conserve la fenêtre et les brouillons de l’éditeur.

L’éditeur ouvre les fichiers du checkout utilisé par la Console SSH de l’agent, y compris
les changements non commités. Il ne clone pas le dépôt. Une référence
`galaris://code/<uuid>` ouvre son état courant, pas une copie historique du code.

Avec un droit d’écriture, vous pouvez enregistrer les fichiers, consulter les changements et
utiliser les commandes Git habituelles : branches, préparation, commit, fetch, pull, push
et rebase. Le terminal intégré fournit Git dans un environnement isolé. Il reprend la
configuration Git et les clés SSH de forge de l’agent accessibles dans son home ; les
commits utilisent cette identité. Ce terminal ne reproduit pas tous les services et
outils de la Console SSH. Un dossier non approuvé conserve le mode de confiance natif
de VS Code ; accordez votre confiance dans l’éditeur pour activer ses fonctions exécutables.

L’explorateur de fichiers, les diffs et les opérations Git se gèrent directement dans
VS Code. Le panneau Galaris conserve le titre, la disposition et **Masquer l’éditeur**.
Ouvrir ou rouvrir un dépôt ne change pas la vue native de l’éditeur. Une présentation
explicite de l’agent peut désigner un fichier ou un diff. Lors d’une demande Git, VS Code
peut proposer d’approuver le dossier ; Galaris n’accorde pas cette confiance à votre place.

Avec un droit de lecture seul, les fichiers du dépôt et les métadonnées Git sont montés en lecture
seule. Le terminal et les extensions ne peuvent pas écrire dans le dépôt ; cette session
ne reçoit ni clés de forge ni accès réseau. L’agent conserve ses propres accès d’écriture.

Vous et l’agent travaillez sur les mêmes fichiers et le même index Git. Les changements
externes et les conflits de sauvegarde suivent le comportement de VS Code. Il n’y a pas
de curseurs partagés ni de synchronisation des buffers non enregistrés. Avant une branche,
un rebase ou un commit, examinez les changements courants et coordonnez-vous dans la discussion.

**Masquer l’éditeur**, ouvrir un Document ou changer de discussion conserve l’iframe et
ses onglets dans la session du navigateur. Le navigateur peut demander confirmation avant de quitter tant qu’un éditeur
modifiable est ouvert. Galaris ne promet pas une sauvegarde automatique de ses buffers.

Une perte de connexion ou de droits affiche une erreur et conserve la fenêtre. Le serveur
interrompt les accès retirés ; les sauvegardes peuvent alors échouer. Les profils conservés
permettent la récupération native après réouverture autorisée, dans les limites de VS Code.
Après expiration, **Réessayer** renouvelle l'accès au même profil ; les droits et le dépôt
sont revérifiés. Si le processus IDE a été arrêté, une fenêtre de récupération s'ouvre dans
le panneau. **Voir la fenêtre précédente** conserve l'accès aux brouillons de l'ancienne
fenêtre : copiez les modifications nécessaires vers l'éditeur repris, puis enregistrez-les.
Une nouvelle panne demande confirmation avant de recharger la seule fenêtre de récupération ;
enregistrez ou copiez d'abord son contenu. La fenêtre d'origine reste conservée. La durée maximale d’une
session est de 24 heures avant reprise explicite et son bail inactif de 10 minutes.
Le runtime accepte huit IDE actifs et conserve jusqu'à 64 profils. Les profils arrêtés
ne consomment pas le quota des IDE actifs. La maintenance administrateur permet d'archiver
les profils devenus inutiles, puis de les restaurer si nécessaire.

L'édition source fonctionne dans Chromium, Firefox et WebKit. Pour l'aperçu Markdown natif,
utilisez Chromium ou WebKit : son fonctionnement sous Firefox est une limite acceptée
de cette première livraison.

Le panneau ne propose pas de partage ou de suppression de session. Le propriétaire de
la Console et l’agent reçoivent l’accès au dépôt lors de son enregistrement ; les droits
déjà enregistrés restent contrôlés. Les humains ont également besoin du privilège d’accès
aux dépôts Git. Recevoir un lien, participer à la discussion ou gérer l’agent n’accorde pas
automatiquement l’accès au dépôt.

Un dépôt affiché et chargé est joint comme contexte au message envoyé : URI et branche/HEAD
observés côté serveur. Le fichier et la sélection ne sont pas transmis, faute de pont fiable
pour ces informations. Afficher un diff ne vaut pas approbation de commit ou de push.

La disponibilité dépend de la [configuration administrateur](../admin/code-editor.md),
y compris pour une Console externe.
Si l’ouverture indique que l’éditeur n’est pas configuré pour cette Console externe,
un gestionnaire de la connexion peut cliquer directement sur **Déployer l’éditeur de code**
dans la connexion Console de l’agent et enregistrer cette connexion. Le déploiement vérifie SSH
automatiquement. La discussion reste utilisable ; vous pourrez
rouvrir le dépôt après cette configuration.

Si `repository_show` signale un refus de permission, vérifiez aussi que la connexion
Console de l’agent est active. Tester ou déployer l’éditeur conserve son état enregistré.

Après le déploiement initial, les éditeurs gérés des connexions SSH actives sont vérifiés et
mis à niveau si nécessaire lors de chaque mise à jour de Galaris. Aucun bouton de mise à jour
n’est nécessaire. Enregistrez les fichiers et terminez les sessions avant une mise à niveau :
une session ouverte, même masquée, empêche le remplacement de l’éditeur.
