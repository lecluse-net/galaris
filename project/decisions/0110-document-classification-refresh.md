# 0110 — Rafraîchissement ciblé du classement documentaire

Statut : Accepted

Le classement personnel ne modifie pas les droits d'accès aux documents. Il émet désormais
`memory.classification`, autorisé uniquement pour l'utilisateur propriétaire du classement,
avec les dossiers et documents concernés et les indicateurs de modification des dossiers
et de la liste. `memory.invalidate` conserve son rôle d'invalidation des instantanés après
un changement d'accès ; les changements de session continuent à vider les données privées.

La navigation regroupe les notifications et le résultat des mutations locales. Elle recharge
uniquement les branches concernées, conserve leur contenu pendant la requête et invalide les
réponses devenues périmées. Un renommage recharge les métadonnées des dossiers sans recharger
les documents. Une branche déjà chargée se rouvre depuis son cache tant qu'aucune notification
ne l'a invalidée ; une fermeture pendant une lecture impose une nouvelle lecture à la réouverture.
Le déplacement entre dossiers ne recharge pas la liste ; un changement de
classement/non-classement ou d'ordre de la liste la recharge. Les notifications de contenu
rechargent la liste filtrée et les branches contenant les documents concernés.

Les barres de progression du panneau sont supprimées. Les erreurs et leur action de reprise
restent visibles. Les documents déjà affichés et la pagination restent utilisables pendant
une lecture. Les changements de droits continuent à retirer immédiatement les instantanés.

Les tests de classement PostgreSQL couvrent la portée privée des notifications. Le scénario
navigateur reproduit le démontage des lignes sans rapport avant correction, puis vérifie les
requêtes ciblées, les mutations et notifications simultanées, l'utilisation de la liste pendant
une réponse lente, le renommage et l'invalidation d'accès.
