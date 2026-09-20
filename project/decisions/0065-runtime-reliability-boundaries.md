# ADR 0065 — Propriété des tentatives et résultats terminaux

- Statut : Accepted
- Date : 2026-09-05

## Contexte

Un heartbeat valide ne suffit pas à empêcher un ancien worker d'écrire après la reprise
de sa tentative. Les Process pouvaient également conserver leur statut terminal tout
en remplaçant leur résultat lors d'un rafraîchissement ou callback tardif. Enfin, une
notification auxiliaire pouvait faire échouer une admission Messenger déjà réalisée.

## Décision

- Toute construction, finalisation ou résolution d'échec d'un round reçoit le jeton
  de lease du worker. La garde d'effet capture ce même jeton immuable. Les écritures
  vérifient sous verrou le propriétaire, le statut actif et l'expiration. Après un
  transport sortant, la finalisation recharge et vérifie à nouveau cette propriété.
- Les Process valident leur transition avant toute mutation du résultat. Un statut
  terminal refuse aussi les nouvelles données portant le même statut. Les événements
  tardifs restent journalisés. Le verrou de relecture rafraîchit l'identité ORM après
  une attente réseau afin de prendre en compte un callback concurrent.
- Un signal Messenger distingue les récepteurs requis pour l'admission et les
  notifications facultatives. Les erreurs des premiers restent retryables ; celles
  de la projection Chat ou Web Push sont journalisées sans invalider l'admission.
- Le streaming actif suit l'ADR 0062 : un seul accumulateur et un snapshot de reprise,
  communs aux conversations texte et vocales.
- Les jobs périodiques possèdent une durée maximale, par défaut 900 secondes. Les
  deux batches réseau Process adaptent cette limite au nombre maximal d'appels et à
  leur timeout propre. Une interruption libère la session et permet un prochain
  passage ; chaque domaine conserve la responsabilité de la reprise de ses effets.
- Les métriques de durée et d'issue des jobs, ainsi que les métriques Process, sont
  exportées par l'instrumentation Logfire existante. Les snapshots locaux Process
  restent disponibles pour les écrans opérationnels.
- Le frontend distingue refus d'authentification, panne du refresh et erreur de la
  requête rejouée. Un changement d'identité ou de rôle renouvelle le WebSocket ; un
  renouvellement du token conservant la même identité n'interrompt pas la connexion.

## Conséquences

Aucune nouvelle infrastructure, dépendance ou table. Les contrats de fin et de reprise
sont testés au niveau des opérations, avec des connexions PostgreSQL distinctes pour
les reprises de workers, et avec les parcours navigateur existants pour le Chat.

Une interruption après un effet externe peut toujours avoir une issue ambiguë : le
jeton protège les écritures Galaris, il n'annule pas une requête déjà reçue par un
transport externe. Les états de livraison inconnue et la réconciliation existante
restent nécessaires.

Les déplacements massifs de services, la séparation complète de l'inférence et du
transport HTTP, le registre unifié de providers de fichiers et le découpage des
grandes pages restent des chantiers distincts. Ils doivent supprimer une responsabilité
ou une dépendance concrète et conserver les contrats existants ; le nombre de lignes
seul ne justifie pas leur introduction.
