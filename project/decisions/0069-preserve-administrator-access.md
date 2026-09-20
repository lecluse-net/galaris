# 0069 — Conserver un administrateur actif

Statut : Accepted

Date : 2026-09-05

## Décision

L'API refuse avec un conflit explicite la désactivation, la suppression ou le retrait
d'affectation du dernier utilisateur actif portant le rôle intégré `admin`.
Un verrou transactionnel commun sérialise les mutations concurrentes de comptes et
d'affectations. Un administrateur inactif ou une affectation supprimée ne compte pas.

Le rôle intégré ne peut pas être supprimé, renommé par son code ou privé de ses droits.
Son libellé reste modifiable. Les autres rôles restent administrables normalement.
Le bootstrap public reste fermé après la première inscription ; la protection ne
réouvre jamais l'inscription publique. Les inscriptions suivantes exigent l'activation
explicite de `ALLOW_USER_REGISTRATION` dans Préférences → Système (désactivé par défaut).
Elles créent des comptes actifs sans affectation de rôle ; seul le premier compte reçoit
le rôle `admin`. La présence d'un compte inactif suffit également à fermer le bootstrap.
La page et son lien consultent le statut public sans cache ; l'API revalide la politique
sous le verrou de création, qui empêche deux inscriptions de devenir le premier compte.

La suppression d'un utilisateur possédant encore des ressources renvoie également
un conflit explicite. Les clés étrangères restent restrictives, y compris pour les
agents archivés : les données ne sont ni supprimées en cascade ni réaffectées implicitement.
