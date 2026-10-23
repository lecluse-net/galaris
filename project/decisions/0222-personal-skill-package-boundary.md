# 0222 — Frontière des packages de skills personnels

- Date : 2026-10-23.
- Statut : accepté et implémenté ; activation en développement vérifiée après accord utilisateur.

## Décision

`app.skill` possède les packages personnels éditables, distincts des skills appris,
de Memory et des Documents. `owner_agent_id` est une FK nullable : `NULL` désigne un
générique. L'auteur agent reste indépendant. La suppression d'un agent conserve sa
propriété ; sa restauration ne réactive pas automatiquement ses packages.

L'identité associe ID stable, code, propriétaire et révision. Un générique et plusieurs
propriétaires peuvent utiliser le même code. Les contraintes PostgreSQL interdisent
système, catégorie et activation globale sur un personnel. Les anciens sélecteurs par
code, la matrice et les datasets génériques excluent les personnels.

Le stockage personnel est sous `.personal/<agent>/<code>/`, exclu du rescan générique.
Son URI est `galaris://skill/personnal/<agent>/<code>/`. La création personnelle déduit
le propriétaire du contexte authentifié, jamais du frontmatter ou d'un argument libre.
Aucune affectation étrangère, copie hors package ou modification du propriétaire n'est
permise. Les budgets sont de 100 packages et 200 Mio cumulés par propriétaire.

Un seul Tool `skills` remplace `skill_management` en conservant sa clé primaire,
ses connexions et leurs réglages. Les connexions historiques actives conservent leur
administration globale ; les connexions désactivées ne sont pas réactivées. Une collision
de Tools ou un ancien générique nommé `personnal` bloque explicitement la migration,
sans effacement des données.

Le paramètre dédié `tools.management_scope` appartient à la connexion Skills et propose
`usage`, `personal`, `team`, `all`. Son absence signifie `usage`. Sa déclaration est
réutilisable par d'autres Tools internes, qui devront appliquer leurs règles métier.
Il n'a ni valeur globale ni héritage. Seul un humain authentifié par session web ayant
édition des connexions et management global peut le modifier. Les écritures par les services
agentiques sont refusées, même avec une connexion d'administration. Chaque appel relit la
valeur locale et la connexion active. L'usage reste indépendant de la délégation de gestion.
La sauvegarde de la connexion et de sa portée est atomique. Une erreur ne réactive pas
une connexion avec son ancienne portée. Réaffecter une connexion portant ce paramètre
demande la même autorité que modifier sa délégation.

`team` couvre le propriétaire et l'union des agents appartenant à au moins une de ses
équipes actives, avec déduplication. Les adhésions sont relues sans cache à chaque appel.
Cette portée administre les personnels correspondants et leurs affectations génériques ;
elle ne donne ni usage des personnels étrangers, ni modification du catalogue générique,
ni retrait de propriété. Ces deux dernières opérations exigent `all`.

`app.skill.interface` porte les règles partagées entre MCP et File Share. Le Tool
Skills expose découverte, lecture du `SKILL.md`, métadonnées, activation, suppression,
autorisations génériques et retrait de propriété. Les fichiers et références restent
sur les fonctions `file_*` du Tool File Sharing. La vue MCP administrative est explicite.
La création via `file_create` dans l'espace personnel du seul agent authentifié fait partie
de la production privée ordinaire d'une Task : l'URI du nouveau package n'a pas à figurer
dans sa demande source. Le descripteur d'effet déclare ce préfixe avec l'identité serveur ;
il n'ouvre ni tout `galaris://`, ni les génériques, ni les espaces étrangers. Les validations,
quotas et autorisations vivantes de Skills restent obligatoires. Le parcours MCP réel avec
Task est couvert dans `app/task/tests/test_execution_scope.py`, en complément des parcours
Skills sans Task qui ne traversaient pas le contrôle de périmètre.
L'administration d'un personnel étranger exige `team` dans son périmètre, ou `all`, et ne le rend jamais utilisable
par l'administrateur.

Le retrait de propriété est une commande globale explicite, avec révision attendue et
UUID d'opération. Il conserve ID et auteur, publie un générique sans activation pour
quiconque et refuse les collisions sans écrasement. Un reçu durable permet le rejeu sans
réinitialiser les droits. Staging, marqueur atomique et réconciliation DbAdmin assurent
la reprise après interruption. Le rescan ignore les publications non confirmées. Les
mutations verrouillent les identités ; les publications génériques partagent un verrou
transactionnel de catalogue entre processus.

Les harnais et les projections incluent les personnels actifs du seul propriétaire.
Des noms runtime déterministes évitent les collisions générique/personnel/appris sans
renommer leurs sources. La réconciliation s'applique avant la prochaine exécution,
sans redémarrer une Task en cours ; un contexte déjà chargé ne peut pas être effacé.
Les lectures et mutations futures revérifient néanmoins les droits courants.

L'onglet **Skills personnels**, indépendant de Dream, expose liste paginée, recherche,
filtre propriétaire et lecture des fichiers dans le périmètre humain courant. Il ne
prend jamais l'identité de l'agent filtré. L'édition humaine des fichiers et les commandes
de suppression/conversion ne disposent pas encore de boutons dans cet onglet ; la
conversion a une route HTTP globale et le parcours agent est exposé par MCP.

La configuration des portées se trouve dans **Tools → Connexions**, dans le formulaire
de la connexion. L'onglet personnel ne contient plus de délégation. La précision utilisateur
retient l'union des équipes de l'agent, sans sélection d'équipes autorisées dans la connexion.

## Vérification

Les tests utilisent PostgreSQL éphémère et des données synthétiques : confidentialité,
homonymes, révocation, budgets, révisions, migration et conservation des connexions,
MCP réel en mémoire, File Share, chargement des harnais, suppression/restauration,
concurrence, pannes de publication/commit/nettoyage et reprise. Les tests navigateur
exercent consultation, périmètre humain et délégation. Ils ne constituent pas un essai
avec des modèles externes réels. Après autorisation utilisateur, `make sync-db` a convergé
en développement sans erreur ; la projection du Tool `skills` expose le paramètre et ses
quatre valeurs. Aucun contrôle visuel supplémentaire sur le navigateur utilisateur n'est revendiqué.
