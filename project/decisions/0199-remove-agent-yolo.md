# 0199 — Retrait du mode YOLO des agents

Acceptée le 2026-10-17. Remplace les dispositions YOLO de la décision
[0153](0153-common-action-authorizations.md).

Le mode global d’approbation automatique est supprimé. Les modes par fonction
Actif/Bloqué/Sur demande et les accords mémorisés par type d’action de harnais
couvrent le besoin d’autonomie avec une portée explicite.

Les actions Sur demande restent en attente d’un humain, sauf autorisation mémorisée
correspondante. Les accès réseau Browser suivent leurs réglages et accords dédiés.
Les blocages, droits métier, préconditions et gardes de contexte restent prioritaires.

Le réglage, ses badges, son endpoint et `agents.yolo` disparaissent, ainsi que
`agent_authorization_changes`. DbAdmin applique ces suppressions déclarativement.
Le compteur interne `agents.authorization_version` reste nécessaire : un changement
de responsable invalide les accords mémorisés, même après un retour au responsable initial.

Les anciens accords automatiques non consommés ne donnent plus accès à l’exécution,
y compris au dispatch différé. La réconciliation les invalide ; les actions terminées
conservent leur historique. Aucun accord automatique n’est converti en accord humain
ou en autorisation permanente.

Les tests de confirmation du réglage retiré sont supprimés. Les parcours d’accord,
de refus, de réouverture et de configuration par fonction restent couverts par les
tests existants. Les tests d’audit et de rétention utilisent désormais des accords
humains explicites ; un scénario conserve une ancienne décision synthétique pour
vérifier son invalidation.
