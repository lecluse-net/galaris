# ADR 0041 — Signalements déterministes de maintenance mémoire

- Statut : Accepted
- Date : 2026-08-20

## Contexte

La fusion des souvenirs redondants, le traitement des corrections et l'ancienneté ne doivent pas
être confondus avec des Tasks ni avec les opérations Dream qui appellent un LLM. Une activation
automatique immédiate serait difficile à qualifier en production, tandis qu'une suppression liée
à l'inactivité rend les faux positifs irréversibles. La recherche RAG doit rester fondée sur le
modèle simple des `MemoryItem` actuels.

## Décision

`app.memory` possède une entité durable `MemoryFinding`, révisionnée par les deux souvenirs
examinés. Elle représente un doublon, une contradiction ou un vieillissement et conserve le score,
le seuil et l'action proposée. Chaque politique possède un mode global `off`, `manual` ou
`automatic`. Les doublons réutilisent l'unique
`MEMORY_DUPLICATE_SIMILARITY_THRESHOLD` de l'acquisition et du rappel; seules les contradictions
et l'ancienneté conservent leur seuil propre à leur nature.

`app.memory` possède les politiques et les opérations de détection/résolution. Le mécanisme
`memory.maintain_findings` du scheduler Dream les exécute séquentiellement pendant l'inactivité :
Memory pilote, Dream exécute. Ses reçus durables assurent reprise et idempotence, mais le mécanisme
est exclu des jauges Dream réservées aux traitements substantiels. Aucun LLM génératif n'est
appelé : les doublons lisent l'index d'embeddings courant, les contradictions ajoutent une règle
textuelle conservatrice et explicable, et l'âge compare les dates de modification significative.
Le mode automatique appelle le même service applicatif que le bouton manuel.

Une fusion choisit explicitement le souvenir canonique, transfère provenances, droits et liens,
puis retire l'autre souvenir du rappel. Elle ne synthétise aucun nouveau texte. Une révision
modifiée après détection rend le signalement obsolète. Un refus ne vaut que pour la paire de
révisions examinée.

Une modification de seuil réconcilie immédiatement les signalements en attente avec la nouvelle
politique : ceux qui ne franchissent plus le seuil deviennent obsolètes, sans modifier les
souvenirs concernés. Le jeton de politique du mécanisme Dream rend aussi les souvenirs éligibles à
un nouveau balayage pour découvrir les nouveaux candidats ou reclasser une paire lorsque le seuil
baisse. Un signalement rendu obsolète uniquement par le seuil peut redevenir en attente si la même
paire de révisions satisfait à nouveau la politique.

Le vieillissement renseigne `old_at` et `old_reason`; il ne supprime pas le souvenir et ne change
pas sa participation au RAG. `last_accessed_at` n'intervient pas dans ce calcul : une consultation
RAG ne rajeunit pas un fait. Une modification significative ou une nouvelle provenance efface le
marquage. L'ancien mécanisme Dream `memory.forget_stale` n'est plus enregistré.

## Conséquences

- Le mode manuel, livré par défaut, permet de comparer et qualifier les détections avant
  d'autoriser l'automatisation.
- L'interface Memory affiche les signalements par souvenir et ouvre une comparaison côte à côte.
- Les signalements existants restent auditables lorsque leur politique est désactivée ; seuls les
  nouveaux scans sont arrêtés.
- Le schéma de rappel reste inchangé : le statut d'âge est informatif et aucun graphe correctif
  supplémentaire n'est injecté dans le RAG.

## Preuves dans le code

`back/app/memory/maintenance.py`, `back/app/dream/mechanisms/memory_maintenance.py`,
`models.py`, `router.py`,
`front/app/memory/components/MemoryFindingDialog.vue` et
`back/app/memory/tests/test_maintenance.py`.
