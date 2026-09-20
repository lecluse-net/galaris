# 0055 — Navigateur agentique ouvert aux réseaux de développement

- Statut : Accepted
- Date : 2026-08-28

## Contexte

Le navigateur agentique refusait les noms locaux et toutes les adresses privées, réservées ou de
loopback après résolution DNS. Cette politique limitait les risques SSRF, mais empêchait aussi un
agent d’observer les applications et outils qu’il construit sur un service Docker, une machine du
LAN ou l’hôte de développement.

L’activation du Tool `browser` constitue déjà une autorisation explicite par agent. Ses sessions
restent isolées par couple agent/Task, éphémères et bornées, et le sidecar n’expose aucun port sur
l’hôte.

## Décision

Une connexion `browser` active peut ouvrir toute destination HTTP(S) joignable depuis les réseaux
du sidecar. Le proxy conserve la résolution DNS et le routage de toutes les requêtes Chromium,
redirections et sous-ressources, mais ne classe plus les noms ni les adresses selon leur portée.
Les services de `executor_net`, les adresses LAN, les adresses réservées et le loopback du sidecar
sont donc acceptés. `host.docker.internal` est ajouté explicitement au sidecar pour joindre les
services exposés par l’hôte.

Les schémas autres que HTTP(S) et les URL contenant des identifiants restent refusés. Les limites
de temps, sessions, contenu, captures et mémoire, l’authentification backend–sidecar et
l’isolation des `BrowserContext` ne changent pas.

## Conséquences

- Les agents peuvent générer des aperçus de services en construction sans publication Internet.
- `localhost` désigne le sidecar; un autre conteneur doit être appelé par son nom DNS Docker et
  l’hôte par `host.docker.internal`.
- Un agent autorisé au Tool peut atteindre les services HTTP(S) visibles depuis `executor_net`,
  `browser_egress` ou l’hôte. L’administrateur doit donc traiter l’activation de la connexion
  `browser` comme un droit réseau puissant et peut toujours désactiver ses fonctions.
- La décision 0017 reste applicable pour l’isolation, la gouvernance et les limites, mais sa
  politique de rejet des réseaux privés ou réservés est remplacée par la présente décision.
