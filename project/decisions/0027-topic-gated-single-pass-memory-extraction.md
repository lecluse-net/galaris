# 0027 — Extraction mémoire en une passe, conditionnée par le Topic

- Statut : Accepted
- Date : 2026-08-07

## Contexte

L'extraction automatique depuis les Tasks et les tours Voice exécutait historiquement une première
inférence de souvenirs, puis une seconde inférence dite de consolidation pour décider de créer,
fusionner, mettre à jour, contredire ou ignorer. Cette chaîne était coûteuse, difficile à régler et
impossible à évaluer comme une décision end-to-end unique. Les rounds conversationnels textuels
n'étaient pas couverts et les conversations ne transmettaient pas un historique homogène.

L'ADR 0026 autorisait par ailleurs l'extraction avant le classement thématique. Le besoin produit
est désormais plus strict : le Topic doit être connu avant toute détection automatique de souvenir.

## Décision

Les mécanismes automatiques d'extraction `memory.extract_task` et
`memory.extract_conversation_round` ne réclament une source que
si son `topic_id` est non nul. Ils ne créent aucun reçu, ne rappellent aucune mémoire et n'appellent
aucun modèle tant que cette précondition n'est pas satisfaite. Une source classée ultérieurement
devient éligible à un passage Dream suivant.

Les trois adaptateurs construisent un même contrat d'entrée. Les rounds texte et les tours Voice
incluent au plus cinq messages antérieurs, séparés du tour courant. Après un rappel serveur borné,
une seule inférence structurée choisit zéro ou plusieurs opérations :

- `CREATE` crée un souvenir durable absent des candidats ;
- `LINK` ajoute la nouvelle source à la provenance d'un souvenir candidat sans réécrire son
  contenu ;
- une liste vide constitue la décision `IGNORE`.

Le serveur refuse les cibles absentes de la liste rappelée et les créations sans utilité future
élevée ni motif de rétention fermé. Les projections Topic et Contact ne sont jamais des cibles de
`LINK`. Les candidats, la vérification de chaque fait proposé, le rappel diversifié, les
signalements et leur fusion automatique partagent l'unique
`MEMORY_DUPLICATE_SIMILARITY_THRESHOLD`. Sous ce seuil l'acquisition crée; au seuil ou au-dessus
elle conserve le souvenir existant et ajoute la nouvelle provenance, même si le modèle avait
proposé `CREATE`. Le prompt est un Param administrable sous
`ai.memory-extraction-system-prompt`.

Le composant d'inférence `memory_consolidation` et son benchmark public sont supprimés. Cette
suppression ne définit pas un futur mécanisme d'évolution de souvenirs déjà constitués : fusion,
scission, généralisation et résolution historique des contradictions restent un problème distinct.
L’apprentissage à partir des résultats de Task conserve son propre contrat. L'ADR 0047 remplace
son ancien stockage en expériences Memory par des skills auto-apprises dédiées.

Le Lab `memory_extraction` exécute le même moteur sans effet. Son prompt appartient au dataset et
est figé dans chaque run. Chaque cas possède sa propre liste de dix souvenirs existants au maximum,
issue d'un rappel borné lors de l'import de la Task ou du round source puis identifiée par des IDs
locaux. Un run ne lit jamais la mémoire de production et aucun prompt d'extraction ne reçoit plus
de dix candidats.

## Conséquences

- La partie de l'ADR 0026 qui rendait Topic et extraction indépendants est remplacée par cette
  décision ; le scellement obligatoire par contact reste inchangé.
- Le Topic sert de barrière d'éligibilité, pas d'instruction autorisant un rattachement par simple
  proximité thématique.
- Il n'existe plus de création implicite lorsqu'une seconde décision est absente ou invalide.
- Les anciens checkpoints du même mécanisme restent lisibles et ne peuvent produire que des
  créations répondant aux garde-fous actuels.
- Les taux `CREATE`, `LINK` et `IGNORE`, les faux liens, Recall@5 et MRR deviennent observables par
  benchmark.
