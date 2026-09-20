# 0101 — Dispatcher sans classification d'action ni jugement après réponse

Statut : accepté — 16 septembre 2026.

## Problème

Le dispatcher conversationnel consultait un modèle pour un message humain alors que sa route
était déjà fixée à `EXEC standard`. Sa classification `requires_action` déclenchait un contrôle
d'admission après réponse et une reprise corrective. Le même champ alimentait des jugements
d'action et d'artefact dans les exécuteurs de Task. Ces contrôles ajoutaient de la latence et
partageaient la responsabilité de l'utilisation des outils entre dispatcher et exécuteur.

## Décision

Le dispatcher reste unique. Son entrée conversationnelle retourne immédiatement `EXEC standard`
pour un auteur humain, avant résolution du modèle et construction du prompt. Cette règle dépend
de l'identité serveur, sur tous les canaux textuels. La classification existante de provenance
reste inchangée : une entrée sans identité IA est traitée comme non-IA. Une provenance à trois
états demanderait un contrat distinct. Les limites et replis du dialogue entre pairs IA restent
inchangés ; la voix conserve son chemin existant.

`requires_action` disparaît des décisions courantes, des prompts, du Lab et des vues frontend.
L'exécuteur choisit ses outils, une admission de Task ou un Process selon sa politique d'action.
Les commandes explicites conservent leur admission déterministe. Le dispatcher de Task conserve
ses choix de route et d'effort ; leur refonte relève d'un autre lot.

Le contrôleur conversationnel orchestre dispatch et exécution, puis restitue le résultat. Il ne
juge ni l'absence d'admission ou d'outil ni la répétition de formulation. Les drivers interne et
Hermès ne rejettent plus un résultat réussi au titre du garde d'action ou d'artefact. Une réponse
réussie sans outil est donc acceptée ; ce succès ne constitue pas une preuve d'effet réel.

Les erreurs d'exécution restent reprises par les schedulers existants, dans leurs budgets et
sous leurs conditions de sécurité. Aucun second mécanisme de retry n'est ajouté au contrôleur.
Un ancien verdict de garde ne permet plus de contourner l'exigence de checkpoint après un effet.
Les autorisations, la fraîcheur du round, l'idempotence, les reçus, la récupération de livraison
et les contrôles de protocole/limites pendant le stream restent applicables.

## Compatibilité et preuves

Les nouvelles inférences utilisent `galaris.dispatcher.active/v2` et
`galaris.dispatcher.conversation/v2`. Les contrats v1 restent enregistrés exclusivement pour
recharger les inférences gelées avec leur schéma original. Une décision historique contenant
`requires_action` se lit dans le contrat courant sans réémettre ce champ. Les traces historiques
ne sont pas réécrites. Les copies/restaurations de cas Lab normalisent leur sortie attendue et
le barème courant passe à `dispatcher-score:v3` sans dimension d'action.

Les tests de classement d'action, de rejet d'artefact et de répétition après réponse abandonnent
ces contraintes. Ils sont remplacés par les garanties d'acceptation sans outil ni relance,
d'admission décidée par l'exécuteur, d'absence d'inférence humaine et de compatibilité des schémas
gelés. Les tests existants de reprise, de livraison idempotente et d'admission durable sont conservés.
La [matrice de preuves](../audits/2026-09-19-fiabilisation-transversale.md) conserve la qualification.
Les mesures de latence restantes sont regroupées dans le
[plan conversationnel](../plans/fiabilisation-conversationnelle.md).
