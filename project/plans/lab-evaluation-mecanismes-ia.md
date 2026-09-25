# Plan — Étalonnage, comparaison et gardes du Lab IA

> **Statut :** `partial` — socle livré ; qualification empirique et capacités de décision restantes.
>
> **Revue du code :** 11 septembre 2026. Cette revue documentaire ne rejoue pas les campagnes
> et n'atteste pas la qualité des modèles distants.

## 1. Périmètre restant

Rendre les évaluations comparables dans le temps et suffisamment étalonnées pour éclairer,
puis éventuellement bloquer, une promotion de modèle ou de politique. Un score agrégé ne
constitue pas à lui seul une preuve de qualité.

Le contrat courant est maintenu dans l'[architecture du Lab](../../docs/fr/architecture/ai-lab-evaluation.md)
et le [guide opérateur](../../docs/fr/user/lab-ai.md). Les décisions
[0078](../decisions/0078-lab-variable-and-judgment-campaigns.md) et
[0082](../decisions/0082-lab-stability-human-review.md) remplacent les anciennes descriptions
jeu/item, candidat et juge de ce plan.

## 2. Limites des preuves existantes

Les rôles de datasets ne prouvent pas à
eux seuls l'étanchéité d'un holdout ; une revue masquée à l'ouverture ne peut pas effacer une
exposition préalable aux réponses ; une empreinte ne remplace pas la politique de comparabilité.

## 3. Lots ouverts

### E — Étalonnage humain

- Constituer un corpus annoté pour chaque mécanisme utilisé dans une décision de promotion.
- Organiser l'arbitrage des désaccords entre annotateurs et conserver sa justification.
- Compléter les écarts dimensionnels, désaccords de verdict et écarts absolus déjà visibles par
  les mesures de biais, corrélation de rang et faux passages utiles au risque métier.
- Évaluer le juge lui-même ; publier la version, le corpus et la date de son étalonnage.

Réception : une décision de passage erronée du juge est mesurable contre une référence humaine
revue ; ni une panne du juge ni une faible couverture ne deviennent une bonne note.

### F — Incertitude

- Qualifier les agrégats existants sur des campagnes réelles.
- Calculer des intervalles de confiance adaptés au volume et à la dépendance entre cas.
- Séparer expérimentalement variance du candidat et variance du juge.

Réception : les répétitions d'un même épisode ne sont pas présentées comme des observations
indépendantes ; un nombre insuffisant de cas reste signalé.

### G — Comparabilité et tendances

Le comparateur MCP de deux runs (axes modèle, prompt et paramètres), ses blocages explicites
et ses écarts par cas sont décrits par l'[ADR 0134](../decisions/0134-agent-lab-control.md).

- Étendre les politiques de comparaison aux expériences portant sur la rubrique, le corpus
  ou le juge et les qualifier sur des campagnes réelles.
- Compléter les sorties dimensionnelles par des agrégats de régressions/améliorations et
  des tendances dans le temps, avec les règles d'incertitude du lot F.

Réception : une modification du corpus ou du juge ne peut pas être présentée silencieusement
comme un gain du candidat ; les résultats restent rattachés aux snapshots d'origine.

### H — Gardes de non-régression

- Définir une baseline approuvée et sa politique de remplacement.
- Calibrer les seuils globaux et dimensionnels, les seuils de couverture et les taux d'erreur.
- Bloquer une nouvelle défaillance critique indépendamment d'une amélioration moyenne.
- Produire un verdict machine explicable et un export utilisable en CI.

Réception : la décision se reconstruit depuis les résultats persistés, sa politique et sa
baseline ; un rapport narratif ne peut pas lever une garde.

### I — Portabilité et gouvernance

- Exporter/importer les datasets et résultats dans un format versionné.
- Tracer les raisons de modification des références et organiser la revue des données importées.
- Définir la rétention et le protocole de gel/ouverture des holdouts en réutilisant `purpose`.

Réception : un export préserve le corpus, les paramètres, les références et leur provenance,
sans exposer les secrets ni contourner les droits des sources.

### J — Jugement renforcé

- Étudier des juges multiples et un arbitrage explicite des désaccords.
- Mesurer les biais de position, de verbosité et d'auto-préférence avec des cas sentinelles.
- Séparer les modèles de référence, de jugement et d'analyse seulement si l'étalonnage le justifie.

Réception : l'ensemble améliore un risque mesuré par rapport au juge courant et son coût est
connu ; le nombre de juges ne constitue pas une preuve en soi.

## 4. Ordre et clôture

Préparer d'abord les corpus d'étalonnage et la comparabilité, puis qualifier l'incertitude,
avant de rendre les gardes décisionnelles. Portabilité et jugement renforcé restent des lots
distincts, sans nouvelle autorisation d'implémentation portée par ce ménage.

Clôturer ce plan lorsque les lots retenus ont leurs preuves sur des cas réels, les limites sont
publiées dans les documents canoniques et chaque intention restante a été livrée, abandonnée
explicitement ou reprise par un autre plan. Les suites du socle restent celles du
[catalogue fonctionnel](../../docs/fr/dev/functional-tests.md).
