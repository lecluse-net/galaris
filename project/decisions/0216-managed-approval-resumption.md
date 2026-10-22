# 0216 — Reprise des accords gérés après réclamation de la Task

Statut : accepté — 22 octobre 2026.

## Problème

Un acteur de harnais observait l'accord humain avant que le scheduler ait repris la Task.
Son callback MCP repartait pendant la pause `approval` ; le précontrôle refusait alors
l'effet comme provenant d'une Task inactive. La récupération des exécutions `EXEC`
sans lease considérait également ces attentes durables comme des opérations orphelines.
Les tests des accords couvraient la décision et le claim, sans intercaler la suspension
et la reprise réelle de l'exécuteur Task.

## Décision

`app.tools` conserve un port de disponibilité d'exécution des runtimes. `app.task`
exige une Task en `EXEC`, non suspendue ni annulée, un lease valide et la tentative
`CLAIMED` exacte référencée par le grant. Après décision humaine, cette tentative doit
avoir commencé après la décision : un accord rapide ne libère pas le callback pendant
la finalisation de la première tentative. Les permissions mémorisées ne déclenchent pas
cette attente humaine supplémentaire.

L'accord persiste en `approved`. La lecture opérationnelle du runtime continue de
retourner `pending` tant que le propriétaire n'est pas prêt, comme le fait le claim
d'une opération approuvée mais suspendue. Les anciens runtimes conservent donc leur
callback et leur continuation sans nouvelle image. Les gardes de droits, de contexte,
de grant et de périmètre restent appliquées avant l'effet.

La suspension pour accord ramène `EXEC` à `DISPATCH` avant libération du lease. Le réveil
normalise aussi les anciennes attentes restées en `EXEC`. La récupération des orphelins
ignore les Tasks suspendues ; elle conserve sa politique pour les vraies interruptions.

À la reprise, le driver peut encore lire le snapshot d'attente précédent de l'acteur,
avant son prochain polling d'autorisation. Si toutes les décisions sont utilisables
par le grant et la tentative courants, le client conserve le lease et continue d'observer
le même acteur. Il ne persiste pas une seconde pause dont le réveil a déjà été consommé.
Le contrôle de disponibilité partage la règle de lecture du runtime : un accord rapide
dans l'ancienne tentative, un lease expiré, une pause manuelle ou une décision encore
en attente exigent toujours la suspension normale.

## Vérification

Le scénario PostgreSQL/API est paramétré sur les quatre harnais réseau : décision rapide,
suspension, réveil, nouveau lease sans transfert de grant, lease expiré, pause manuelle,
transfert vers la tentative active et claim unique. Les scénarios SMTP existants conservent
la préparation MIME et l'envoi unique. Le test de récupération protège aussi une attente
sans lease ; celui d'expiration exige une phase effectivement réclamable au réveil.
La matrice intercale aussi le polling du client commun et un callback retardé : le client
doit attendre sa consommation avec le lease actif, puis observer le résultat du même
acteur, pour les accords comme pour les refus. Cette séquence reproduisait la seconde
pause intempestive, que le seul contrôle des droits de reprise ne détectait pas.

La fin normale du tour SDK ne prouve pas l'accomplissement métier. Ce correctif ne déduit
pas un résultat métier depuis le texte final et ne transforme pas un compte rendu d'échec
en preuve d'envoi.
