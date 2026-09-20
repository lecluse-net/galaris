# 0074 — Succession compatible des actions DbAdmin

Statut : accepté.

Une correction de code d’une action facultative inachevée ne doit pas empêcher
l’application d’utiliser une expansion possible. L’ancienne règle refusait tout
changement de checksum avant même la vérification de postcondition.

`DbAdminAction.compatible_checksums` déclare les comportements anciens que le
nouveau handler et sa postcondition peuvent reprendre sans perte. Sans cette
garantie, une action indispensable reste bloquante ; une action facultative est
différée avec diagnostic, conservation de l’ancien journal et protection des
sources contre la contraction. Avec la garantie, la postcondition est vérifiée
avant toute exécution, comme pour une reprise de la même action.

Une table technique de révisions conserve la criticité lors de l’admission. Elle
est créée avec les autres tables du journal avant les actions, sans modifier une
table ancienne avant le passage Atlas. Les anciennes entrées sans criticité
utilisent la déclaration encore présente ; une disparition inconnue reste fatale.

La règle nullable → remplissage → NOT NULL reste inchangée. La compatibilité ne
rend pas un changement de type destructif sûr : il exige toujours une preuve de
reprise et la conservation de la représentation source.

Validation : matrices PostgreSQL de checksum, criticité, postcondition et absence
de contribution ; suites existantes d’expansion/contraction.
