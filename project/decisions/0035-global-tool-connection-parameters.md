# ADR 0035 — Paramètres globaux hérités par les connexions de Tool

- Statut : Accepted
- Date : 2026-08-14

## Contexte

Les connexions d'un même Tool répètent souvent des valeurs administrées à l'échelle de
l'installation : serveur et port SSH, endpoints IMAP/SMTP, limites ou options de transport. Les
dupliquer pour chaque agent complique l'administration, alors que certaines connexions doivent
malgré tout pouvoir cibler une infrastructure différente.

## Décision

Chaque paramètre déclaré dans `Tool.connection_schema` possède une valeur globale nullable,
stockée séparément dans `Tool.global_params`. Une valeur locale non vide surcharge la valeur
globale. En son absence, la valeur globale est utilisée. Lorsque la valeur globale est marquée
`forced`, elle est imposée et toute valeur locale est ignorée.

```text
global forcé → global
sinon local non vide → local
sinon global non vide → global
sinon → absent
```

Les valeurs de type `password` sont chiffrées au repos et leur API publique expose uniquement leur
présence. Les valeurs globales ne font pas partie du schéma déclaratif : la synchronisation d'un
Tool intégré peut donc mettre son contrat à jour sans effacer la configuration administrateur.
Les valeurs par défaut d'un nouveau schéma initialisent ses valeurs globales ; une valeur globale
peut ensuite être explicitement supprimée.

Le formulaire de connexion demande les paramètres sans valeur globale et présente les autres
comme hérités. Une valeur héritée non imposée peut être personnalisée pour créer une exception ;
supprimer cette surcharge rétablit l'héritage.

Chaque définition de paramètre peut porter un ordre explicite, utilisé de façon identique dans le
formulaire de connexion et dans l'administration des valeurs globales. Les anciens schémas sans
ordre explicite utilisent le nom du paramètre comme tri de repli déterministe.

## Conséquences

- La règle est commune aux Tools natifs, externes, Mail et Console SSH.
- Les consommateurs résolvent les paramètres par la façade `app.connection`, jamais en lisant
  seulement les lignes EAV locales.
- Une valeur globale imposée peut rendre une ancienne surcharge locale inactive sans la révéler.
- Les secrets globaux et locaux conservent les mêmes garanties write-only et de chiffrement.

## Preuves dans le code

`back/app/tools/models.py`, `back/app/tools/tool_service.py`,
`back/app/connection/connection_service.py`, `front/app/tools/`, `front/app/connection/` et leurs
tests associés.
