# 0217 — Journal Mail relié aux autorisations communes

Statut : accepté — 22 octobre 2026.

## Problème

Le journal Mail précédait les autorisations communes des Tools. Il savait décider les
anciennes validations `pending_approval`, mais une demande commune laissait son mail
préparé en `claimed`, sans décision disponible dans le journal. Les tests protégeaient
séparément les deux circuits sans vérifier leur convergence sur la même demande.

## Décision

`mail_outbound_deliveries.authorization_id` référence l'autorisation commune préparée.
`app.tools` expose une lecture publique bornée des métadonnées de revue et la sélection
des demandes en attente. Les lectures ordinaires du journal ne déchiffrent pas les arguments.
Mail conserve la propriété du MIME, de l'idempotence et des états de transport.

Les boutons du journal appellent `answer_action`, comme la conversation, après contrôle du
responsable figé, de l'agent, de la connexion et des droits existants. La décision ne lance
pas SMTP : le mécanisme commun réveille l'appelant et celui-ci reprend l'opération préparée.
Le journal distingue l'accord enregistré de l'envoi effectif. Les décisions identiques sont
idempotentes ; une décision opposée ou expirée ne peut pas remplacer la première.

Une action DbAdmin après expansion rattache les mails déjà préparés à l'autorisation la
plus récente compatible, par pages bornées. Seul le propriétaire Tools déchiffre les données
nécessaires à ce rattrapage et expose les identifiants de ressources. Aucun contenu MIME,
état de transport ou accord humain n'est modifié et aucun effet externe n'est exécuté.
Les anciens mails sans autorisation commune conservent leur circuit de compatibilité.

## Vérification

Les tests PostgreSQL reproduisent l'absence initiale du mail dans la liste en attente,
puis vérifient les décisions depuis chaque entrée, leurs répétitions concurrentes,
les droits, la migration idempotente et l'envoi unique du MIME préparé après reprise.
Les parcours assemblés exercent accord et refus dans Chat et dans le journal, ainsi que
les validations historiques. Les transports externes et le runtime sont synthétiques :
ces contrôles ne constituent pas un envoi réel ni une validation d'un harnais externe.
