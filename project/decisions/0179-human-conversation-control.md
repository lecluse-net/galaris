# 0179 — Contrôle humain des réponses conversationnelles

Statut : accepté. Date : 2026-10-13.

## Garantie

Un participant autorisé d’une discussion native peut suspendre, arrêter, reprendre,
relancer ou demander immédiatement une réponse, depuis la barre de réflexion. La commande
vise le round et la tentative observés. Elle survit au redémarrage du backend.

## Décision

`app.conversation` possède la commande durable `control_action`. Elle utilise les gardes
de préparation, hooks d’interruption et checkpoints existants. Une inférence s’interrompt
rapidement ; un outil engagé termine avant l’arrêt, conserve son reçu, puis aucun nouvel
effet ni réponse partielle n’est livré. Le lease reste détenu jusqu’à cette sauvegarde.

Pause produit `PAUSED`, hors de la file automatique. Reprendre requiert un checkpoint sûr
et aucune entrée plus récente en attente. Stop produit `CANCELLED`. Relancer crée un round
lié avec les mêmes inputs et le checkpoint sûr réattribué ; le round arrêté reste terminal.
Les effets non idempotents confirmés ne sont pas rejoués et les effets incertains bloquent
la reprise. Les tentatives humaines ne consomment pas le budget d’erreurs techniques.

Répondre maintenant interrompt l’inférence puis reprend sans dispatcher, outils, recherche
d’outils ni capacités de skills. Le modèle répond avec les éléments disponibles. Une
commande ne change pas les autorisations d’outils, les ACL ni les travaux de fond.

L’API Chat requiert `CHAT_SEND` et l’accès à la room native. La projection publie les actions
disponibles et le numéro de tentative. Pause et arrêt restent visibles après réouverture ;
les doubles appels sont idempotents et une tentative périmée est refusée.

## Vérification

Tests DB des transitions, checkpoints et refus ; tests du harnais sans outils ; composants
Vue/Quasar pour clavier, erreurs, droits et réponses tardives ; parcours assemblé avec le
scheduler et le harnais réels, seul le fournisseur de modèle étant synthétique.
