# 0138 — Caches API bornés par leur domaine d’invalidation

Statut : accepté. Date : 2026-09-26.

## Garantie

Réduire les lectures SQL répétées sans conserver une autorisation révoquée entre deux
requêtes HTTP. Les changements de compte ou de rôle, refus, écritures et fins de transaction
ne doivent jamais réutiliser le résultat d’un autre contexte.

## Décision

Le middleware d’authentification réutilise dans la requête le compte intégralement validé,
pour les JWT comme pour les UserToken. Aucun compte ni famille de session n’est conservé
entre requêtes ; les contrôles de révocation restent systématiques.

`core.authorize.request_privilege_cache` ouvre un contexte exclusivement HTTP. Les codes
de privilèges sont des ensembles immuables, chargés par une seule requête SQL et indexés par
session SQLAlchemy, utilisateur et rôle. Les privilèges spéciaux déjà satisfaits n’exigent
aucune lecture des rôles. Les refus sont également mémorisés.

Les événements SQLAlchemy invalident la session concernée après flush, avant une écriture
via Session.execute et à chaque fin de transaction ou savepoint. Les changements ORM en
attente empêchent une lecture du cache de contourner l’autoflush. La sortie du contexte,
y compris sur exception, vide et désactive le cache pour les tâches ayant hérité du contexte.
Les WebSockets et racines autonomes ne l’activent pas.

Extension du 27 septembre : `RequestAuthorizationCache` fournit des espaces de clés typés
qui partagent exactement cette durée de vie et ces invalidations. Le périmètre de gestion
Agent y conserve un `frozenset` d’identifiants par session, utilisateur et rôle ; le droit
de gestion globale reste vérifié avant cette lecture. Une mutation en attente, un flush,
une écriture SQL ou une fin de transaction invalide ensemble privilèges et périmètre.
Les consommateurs HTTP de Documents, Goals et des autres domaines utilisent cette même
frontière ; aucun cache supplémentaire n’est activé pour les notifications ou les workers.

Le compte JWT et l’existence d’une famille de session active sont lus dans une seule
requête corrélée. Le contrôle reste effectué à chaque appel. Les JWT sans famille conservent
leur contrat historique ; les UserToken gardent leur validation indépendante. Le catalogue
des propriétaires de documents réutilise uniquement le compte déjà validé dans la requête.

Les lectures documentaires courantes et les contrôles de type ne chargent pas les révisions.
Une ancienne version lit la révision demandée et, pour une version historique sans marqueur,
au plus son hash précédent. La pagination conserve le classement des versions historiques.
Les appels internes qui utilisent l’historique pour reconnaître une reprise d’ajout de texte
conservent leur chargement complet. Les ACL humaines lecture/écriture utilisent deux EXISTS
dans un même SELECT, sans cache supplémentaire des ACL ou du contenu.

L’autorisation des commandes et cycles Goal ne construit plus une vue complète de l’objectif.
Le propriétaire et le référent Agent restent vérifiés. Les cycles demeurent consultables
si un document Goal manque ; la lecture détaillée continue de signaler cette erreur.
La relecture après les observateurs d’écriture est conservée : ces observateurs peuvent
modifier les données, et la réponse doit refléter leurs effets.

Params conserve son cache existant par processus, couvrant toutes les valeurs, secrets
déchiffrés et réglages typés. Un verrou sérialise chargements et écritures : le premier
chargement concurrent est partagé, un rechargement tardif ne remplace pas une écriture plus
récente, et un rechargement échoué préserve les valeurs précédentes. La publication suit le
commit sans lecture SQL intermédiaire. Les listeners sont appelés hors verrou pour pouvoir
consulter ou modifier des paramètres. Les rechargements relisent aussi les objets déjà présents
dans la session SQLAlchemy.

## Limites

Le cache des droits est une vue limitée à la requête ; une révocation concurrente est
garantie à la requête suivante. Il n’introduit ni cache global avec TTL, ni invalidation
distribuée. Les écritures SQL directes sur une connexion brute, contournant la Session, ne
sont pas un chemin de mutation autorisé pour une requête métier.

Le cache Params reste local au processus, comme avant cette décision. Des écritures depuis
un autre processus ou directement en base nécessitent un rechargement explicite du processus
lecteur ou son redémarrage ; ce changement ne prétend pas fournir une cohérence entre workers.
Les hooks DbAdmin chargent les Params dans leur propre processus d’exécution.

## Vérification

- Parcours HTTP connexion, renouvellement, lectures répétées puis déconnexion et refus des
  anciens jetons ; comptes désactivés, versions changées et UserToken désactivés après lecture.
- Contrôles RBAC répétés, changements de rôle/utilisateur, mutations ORM et SQL, suppressions
  logiques, commit, rollback, savepoint et révocation par une session indépendante.
- Chargements Params concurrents, rechargement tardif/échoué, commit échoué et listener réentrant.
- Les comptes, rôles, paramètres et identifiants des tests sont entièrement synthétiques.
- `tests/test_api_read_cost.py` traverse HTTP, mesure les SELECT et les lignes de révision,
  ouvre/réouvre des documents à 1 puis 1 000 versions et vérifie contenu, historique,
  changement de gestionnaire et retrait du rôle. Il n’est pas un benchmark de charge.
- `app/agent/tests/test_management_scope.py` couvre changements de rôle/utilisateur,
  réaffectation ORM et SQL, commit, rollback, savepoint et tâche détachée.
