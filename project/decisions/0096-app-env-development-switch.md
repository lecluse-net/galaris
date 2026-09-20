# ADR 0096 — APP_ENV conserve son libellé, seul dev active le développement

- Statut : Accepted
- Date : 2026-09-13

## Garantie

`APP_ENV` est une chaîne libre, `prod` par défaut. Seule la valeur exacte `dev`
active le développement. `prod`, `pp`, `test`, `demo`, une valeur inconnue ou vide
appliquent le comportement production. La valeur est conservée pour identifier
l’environnement, notamment dans la télémétrie et pour une future charte graphique.

## Décision

Le backend et le frontend dérivent uniquement `settings.is_dev`. Les validations
de secrets, les hôtes autorisés, les exigences TURN et le mode DbAdmin utilisent
ce booléen. Make sélectionne le Compose de développement uniquement pour `dev`,
accepte tous les autres libellés et transmet la même valeur au backend et au build
frontend. Une surcharge explicite par le shell ou Make prime sur `.env`.

`test` n’est plus un raccourci applicatif désactivant des protections : les quotas
HTTP et l’instrumentation restent actifs, et les secrets sont validés. Les tests
automatisés fournissent leurs propres secrets dans leurs Compose isolés et isolent
explicitement la télémétrie et les quotas dans leurs compositions Python. Le mode
DbAdmin `test` reste accessible par l’option explicite `--mode test`, sans être déduit
de `APP_ENV`. Les scripts de tests conservent leurs garde-fous sur le libellé et la
base dédiée avant toute opération de préparation ou suppression.

## Validation

Les scénarios paramétrés couvrent `dev`, les libellés connus, un libellé arbitraire,
la casse, une valeur vide et l’absence de valeur. Les tests HTTP conservent la preuve
des réponses 429. Les tests WebRTC et DbAdmin vérifient les protections hors `dev` ;
les tests Make exercent le choix des commandes et les surcharges sans démarrer la stack.

Les anciennes attentes autorisant des secrets faibles ou supprimant la télémétrie
pour `APP_ENV=test` sont remplacées par ce contrat. L’isolation de la télémétrie des
tests est vérifiée directement sur leur composition dédiée.
