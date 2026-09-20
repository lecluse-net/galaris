# 0064 — Compose commun et réseaux administrés des harnais

Statut : Accepted

## Décision

`harness.default.compose`, éditable dans Préférences → Harnais, porte la surcharge
`compose.yaml` commune à Hermès, Codex, Claude Agent et DeepSeek Harness.
`services.agent` désigne le service principal et est traduit vers le nom propre au
template du provider. Les valeurs du template sont conservées sauf surcharge explicite ;
les surcharges individuelles Hermès restent prioritaires.

Le dataset des paramètres transfère l'ancienne valeur `hermes.default.compose` lors de
la création du nouveau paramètre. Une valeur commune déjà présente, même remise à vide,
reste intacte. La migration est transactionnelle et idempotente. La surcharge héritée
devient commune : les déploiements qui y avaient placé des réglages propres à Hermès
doivent les déplacer dans la surcharge individuelle avant de recréer d'autres harnais.

Aucun provider n'ajoute un réseau externe après cette fusion. Un nom de réseau ou
une URL de manager ne prouve pas la colocalisation. Faute de preuve de topologie,
aucun défaut réseau n'est déduit. Une future détection positive ne pourra initialiser
qu'un défaut visible et modifiable, jamais une injection cachée. La variable historique
`HARNESS_MANAGER_DOCKER_NETWORK` n'attache plus aucun réseau.

Cette décision remplace la politique d'attachement réseau de 0063, sans changer la
résolution de l'URL API de Galaris. Le transport backend → runtime conserve ses coordonnées
actuelles ; cette modification ne prétend pas apporter un relais réseau multi-hôte.

## Application

Les providers écrivent `compose.yaml`. Le manager accepte encore les anciens noms pour
superviser les instances non resynchronisées. Aucun conteneur existant n'est recréé par
une sauvegarde de ces paramètres. Les réseaux et routes doivent être vérifiés par
l'opérateur avant la prochaine synchronisation/recréation.
