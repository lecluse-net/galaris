# Plan — Qualification restante d’AgentAdmin

> **Statut :** `partial` — les 34 fonctions et les parcours synthétiques sont implémentés ;
> la recette photographique avec un fournisseur réel reste ouverte.
>
> **Revue :** 30 septembre 2026. Aucun commit, déploiement ou changement en production
> n’est impliqué par cette qualification.

Le contrat implémenté, le catalogue, les droits de délégation et le suivi Process sont décrits
dans [AgentAdmin](../../docs/fr/dev/agent-admin.md) et dans la
[décision 0148](../decisions/0148-agent-admin-delegation.md).
Les garanties persistées sont couvertes par
[`test_agent_admin.py`](../../back/app/agent/tests/test_agent_admin.py), les suites des
connexions, harnais, Tools, images et Process ; le parcours assemblé utilise
[`agent-admin.spec.mjs`](../../e2e/specs/agent-admin.spec.mjs).

## Qualification réelle à terminer

L’essai avec un fournisseur réel a reçu un HTTP 401 lié à l’absence d’authentification.
Aucun portrait n’a été enregistré et aucune resoumission automatique n’a été effectuée.
Le prédicat de disponibilité contrôle désormais aussi les credentials requis par le
profil fournisseur. Cette mesure ne qualifie pas leur validité auprès du fournisseur.

Après configuration humaine des credentials de l’usage image de l’appelant :

1. Utiliser un appelant et une cible entièrement fictifs ; activer explicitement AgentAdmin
   pour l’appelant et vérifier que la génération est disponible.
2. Donner à la cible une civilité et un profil HTML descriptif, distincts du profil de
   l’appelant. Demander un portrait photographique par `agent_avatar_generate`.
3. Suivre le Process jusqu’au reçu `registered=true`. Vérifier que le modèle est celui de
   l’usage image de l’appelant, que le portrait représente les traits décrits de la cible
   et que ses champs HTML restent inchangés.
4. Vérifier le portrait dans l’UI après navigation et réouverture, puis son remplacement
   par une deuxième génération réussie.
5. Ne pas relancer automatiquement un résultat `unknown`. Conserver uniquement les
   conclusions techniques et mesures agrégées, sans profil réel ni capture individuelle.

Le critère de réception restant est un portrait photographique exploitable produit et
persisté par un fournisseur réellement authentifié, visible à la réouverture de l’UI.
Les parcours synthétiques prouvent déjà le suivi, le remplacement, les conflits tardifs,
la révocation et la conservation de l’avatar courant en cas d’échec ; ils ne prouvent pas
la qualité photographique du fournisseur.
