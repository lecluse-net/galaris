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
