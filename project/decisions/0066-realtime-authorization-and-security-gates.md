# 0066 — Autorisation temps réel et contrôles de sécurité

Statut : accepté — 2026-09-05

## Contexte

Un privilège de lecture autorise un domaine, pas toutes ses ressources. Les notifications
globales pouvaient dépasser le périmètre HTTP du gestionnaire. Une connexion Socket.IO
conservait aussi son identité après expiration ou révocation de son justificatif.

## Décision

- Chaque domaine enregistre sa politique de ressources auprès de `core.websocket`.
  Elle complète le contrôle RBAC et utilise le périmètre de gestion du destinataire,
  avec son rôle actif. Le contexte de l'émetteur est préservé. Un sujet global sans
  politique est refusé, sauf `goal_settings`, déjà global dans son contrat HTTP.
- L'autorisation d'une room est revérifiée lors de son affichage et avant chaque
  émission ; l'existence d'une Task ne suffit plus. Les suppressions transportent
  uniquement l'identifiant et la provenance nécessaires au filtrage après suppression.
- Les JWT de connexion/refresh portent la famille de session et la version
  d'authentification du User. HTTP et Socket.IO valident ces mêmes informations.
  Changer le mot de passe ou désactiver le compte invalide les versions antérieures.
  Déconnecter une session révoque sa famille sans affecter les autres sessions.
- Un composant supervisé contrôle les connexions inactives toutes les 30 secondes.
  Chaque émission et accès à une room valide également le justificatif. Le client
  réutilise le mécanisme HTTP de refresh avant de se reconnecter.
- Les uploads Chat et aperçus HTML partagent le quota cumulatif existant, y compris
  les fichiers partiels. Un verrou de fichier protège le compte et l'écriture entre
  processus ; aucun verrou n'est tenu en attendant des octets réseau. Une annulation
  attend l'écriture déjà engagée avant de supprimer le temporaire.
- Les tests HTTP démarrent sur un clone vierge de la base modèle éphémère. La même
  fixture fournit les vraies transactions nécessaires aux essais de concurrence.
- La CI contrôle les dépendances verrouillées, secrets, SAST, images et restauration,
  chaque semaine et à chaque PR. Les exceptions de dépendances sont précises et datées.
  Les rapports d'images conservent les alertes sans correctif ; le contrôle bloquant
  impose les correctifs disponibles de sévérité HIGH/CRITICAL.

## Conséquences

Une colonne User est ajoutée, sans nouveau service ni nouvelle infrastructure.
Les JWT antérieurs sans version restent compatibles avec la version initiale zéro,
jusqu'à leur expiration normale ou à l'invalidation du compte. Les familles ne
peuvent pas être attribuées rétroactivement aux anciens JWT ; le lien de révocation
par déconnexion s'applique aux JWT nouvellement émis.

Les contrôles supplémentaires ajoutent des lectures DB par destinataire. Ne pas mettre
en cache une décision d'autorisation pendant toute la connexion. Une optimisation
future devra conserver la révocation et l'isolation testées.

Les statuts `Quality required` et `Security required` doivent être rendus obligatoires
dans les règles GitHub : leur définition dans YAML ne configure pas la protection
de branche. Un contrôle vert ne garantit pas l'absence de vulnérabilité inconnue ou
de vulnérabilité système sans correctif. Les politiques réseau des agents et du
navigateur restent un chantier séparé.
