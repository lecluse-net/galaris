# 0122 — Outils disponibles par défaut aux nouveaux agents

Statut : Accepted

## Décision

Les connexions Browser, Search, Image et Multimedia sont initialisées actives.
Ces Tools et Console sont autorisés en conversation lors de leur première
initialisation. La cascade des fonctions reste permissive en l'absence de refus
explicite. Ces capacités restent optionnelles : les réglages et restrictions
existants sont conservés par DbAdmin.

La console interne exige un compte et des clés SSH. `app.console` observe la
création d'un agent utilisant le harnais interne et réutilise le service de
provisionnement de la route administrative. La connexion devient active après
vérification SSH/SFTP. Un événement rejoué ne remplace aucune connexion existante,
même inactive ou externe ; les mises à jour de profil ne provisionnent rien.
Les autres harnais ne reçoivent pas de console SSH Galaris automatiquement.

Une indisponibilité de l'exécuteur laisse la connexion inactive et est journalisée
par l'observateur sans annuler la création de l'agent. L'administrateur peut
relancer le provisionnement depuis les connexions. Des paramètres globaux seuls
ne constituent pas une configuration antérieure permettant une réactivation
après erreur. Les clés restent chiffrées par le service des connexions.

## Garanties

Les tests des datasets vérifient les connexions actives, l'idempotence et la
conservation des désactivations. Les tests d'intégration du provisionnement
vérifient le harnais interne, les paramètres utilisables, la préservation des clés
et de l'état administrateur lors d'un rejeu, et l'inactivité après échec.
