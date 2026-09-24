# 0128 — Requêtes HTTP de l'interface sans délai maximal

Statut : accepté — 24 septembre 2026.

## Problème

Une analyse du Lab peut dépasser le délai de 60 secondes du client HTTP tout en
aboutissant côté serveur. L'interface présente alors un échec de transport pour une
opération réussie. Les documents, transferts et harnais appliquaient aussi des délais
locaux différents, incompatibles avec des traitements longs sur un poste lent.

## Décision

Le client HTTP de l'interface attend la réponse sans échéance temporelle propre. Les
services frontend ne réintroduisent pas de délai arbitraire. Aucun nouveau paramètre
n'est ajouté. Cette règle inclut le renouvellement de session et les transferts.

Les annulations explicites par `AbortSignal`, les erreurs réseau, les refus d'accès et
l'invalidation des réponses d'une ancienne session conservent leur comportement. Une
attente sans réponse peut donc durer jusqu'à une annulation ou une rupture du transport.
Les limites métier, fournisseur et proxy restent des responsabilités distinctes ; cette
décision ne garantit pas une durée d'exécution illimitée de bout en bout.

## Preuves

`front/core/apiWaiting.test.mjs` utilise le transport Fetch réel d'Axios, un fournisseur
Fetch simulé et une horloge contrôlée. Il reproduit le défaut avant correction, puis
vérifie l'acceptation des réponses après plus d'une heure pour le Lab, les documents,
les harnais, le renouvellement de session et un transfert multipart. Il conserve les
garanties d'annulation et de rejet d'une réponse issue d'une ancienne session. Les tests
existants de `front/core/api.test.mjs` couvrent les erreurs et la reprise d'authentification.
