# ADR 0242 — Autorisation de réponse aux contacts externes

- Statut : Accepted
- Date : 2026-10-25

## Contexte

Un message externe était journalisé puis ignoré lorsque son auteur n'avait pas d'identité
Galaris autorisée. Il était absent du suivi textuel, rendant réception et refus indiscernables.
Exiger un compte Galaris pour tout interlocuteur empêchait l'accueil de nouveaux contacts.

## Décision

Une réception humaine sur une connexion externe active de type Conversation, sans droit de
contact reconnu, crée un round textuel `PAUSED`, marqué `contact_authorization_pending`.
Les messages restent dans le journal Messenger. Le suivi montre leur réception et les
informations d'identité réellement fournies par le bridge. Aucun appel IA ni réponse ne
précède l'accord.

L'accord utilise `PermissionDecision` et les interactions canoniques existantes. Sa clé lie
connexion et identité Messenger ; son destinataire est le manager courant de l'agent. La même
demande est notifiée au manager et consultable dans `/connection/permissions`. Les réceptions
supplémentaires de cette personne dans la même room rejoignent le round en attente. Le refus
clôt ce round sans réponse ; l'accord le rend exécutable. Réceptions et décisions rejouées
restent idempotentes.

Le consentement permet les échanges avec cette personne sur cette connexion, sans compte
Galaris ni usurpation de l'identité du manager. Il ne modifie pas les ACL documentaires et
reste révocable dans Permissions. Un changement de manager exige un nouvel accord. Connexion,
personne et accord sont revérifiés avant l'exécution, les effets et l'envoi. Une pause manuelle
reste distincte et ne reprend jamais du seul fait du consentement.

Cette décision remplace l'obligation de rattachement de l'ADR 0083 pour les contacts humains
externes de Conversation. Elle ne change ni le Chat interne, ni les contacts entre agents,
ni le consentement Mail, ni les règles des abonnements LLM personnels.

## Preuves

`app/conversation/tests/test_contact_authorization.py` exerce réception Telegram, suivi,
notification native, Permissions, accord/refus, isolation, révocation et changement de manager.
Les suites Conversation et permissions réseau conservent les garanties de reprise et de contrôle.
`front/browser-tests/conversation-control.spec.mjs` couvre l'identité du contact et l'accès
aux permissions sur mobile et ordinateur.
