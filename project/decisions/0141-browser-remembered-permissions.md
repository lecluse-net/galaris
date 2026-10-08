# 0141 — Permissions réseau du navigateur et décisions humaines mémorisées

Statut : accepté. Date : 2026-09-27.

## Garantie et consommateurs

Le navigateur applique la même politique réseau pour tous ses appelants, y compris les
redirections et requêtes déclenchées par une page. Les agents peuvent prévisualiser leurs
applications locales lorsque leur connexion le permet et qu’un humain l’a autorisé.
Les permissions conservées sont communes au mécanisme d’interactions, indépendantes du
transport de messagerie. Les consommateurs sont le Tool Browser, les aperçus humains,
le sidecar Chromium, les interactions Messenger et l’écran de gestion des décisions.
Les exports PDF inertes gardent leur interdiction de scripts et de réseau.

## Décision

1. La connexion interdit le réseau local par défaut. Elle porte un filtre de destinations
   négatif ou positif et les méthodes nécessitant un accord. Ces interdictions sont évaluées
   avant toute permission. Les GET publics passent avec les paramètres par défaut.
2. La clé est calculée par le backend : `browser:v1:<action>:<origine-normalisée>`. Elle ne
   dépend ni de la formulation de la question, ni d’une Task, ni du modèle. Origine signifie
   protocole, hôte exact et port ; chemins et paramètres sont exclus. Accès local et méthode
   HTTP sont deux permissions distinctes. Les sous-domaines ne s’autorisent pas mutuellement.
3. `app.messenger.request_permission` conserve une décision active par agent et clé, garantie
   par un index unique partiel PostgreSQL. Question originale, responsable humain, réponse
   et date sont conservés. Un bail borne les notifications concurrentes. Les questions
   utilisent les interactions existantes, avec texte ou boutons, et se renouvellent après
   expiration sans perdre leur identité de permission. Les réponses restent valables jusqu’à
   suppression ; un changement de responsable invalide la décision à sa prochaine lecture.
4. La gestion nécessite les privilèges de connexion et reste limitée aux agents gérés.
   Supprimer un choix l’historise et entraîne une nouvelle demande à la prochaine tentative.
   Une réponse tardive à la question supprimée ne restaure pas cette permission.
5. Chaque BrowserContext possède un proxy local lié à son propriétaire. Celui-ci fait
   vérifier chaque requête par un callback backend authentifié avec le secret du sidecar,
   puis utilise l’IP vérifiée. Les adresses DNS privées/réservées et IPv4 encapsulées en IPv6
   sont reconnues ; une liste positive doit admettre toutes les adresses retournées.
6. Le proxy termine TLS dans son processus pour inspecter la méthode HTTPS, puis valide
   normalement certificat et nom de l’amont. Le certificat local reste éphémère. Un tunnel
   CONNECT n’est jamais relayé en TCP brut. Service workers, QUIC et WebRTC sans proxy sont
   désactivés. Les WebSocket ouverts sont réévalués périodiquement sur leur destination
   effective ; un changement DNS ne peut pas requalifier un socket déjà ouvert.

Le callback ne reçoit ni corps, ni chemins, ni paramètres de requête. Une erreur de politique
ou l’indisponibilité du backend bloque l’accès. Les requêtes HTTP déjà transmises ne sont
pas annulées rétroactivement ; les WebSocket sont revérifiés chaque seconde sans chevauchement
et ferment au refus ou au délai maximal de contrôle de 15 secondes. Les actions bloquées
reviennent avec `network_issues`, sans rejouer automatiquement une écriture après approbation.
Le routage conversationnel et les transports existants restent responsables de la réponse
humaine ; le navigateur ne possède aucune implémentation propre des boutons ou messages.

## Extension du 2026-10-01 — Accords durables à portée explicite

Les demandes réseau non locales proposent un troisième choix, « Toujours autoriser tous les sites ».
Il conserve une décision humaine sous `browser:v1:all-sites` pour cet agent,
en réutilisant la table de décisions et son historique. Cette portée couvre les méthodes
configurées et WebSocket sur tous les domaines, protocoles et ports. Les filtres, le refus
du réseau local et les refus explicites par méthode restent prioritaires. Le choix initial
est historisé : révoquer l’accord global ne laisse pas une autorisation implicite pour sa
méthode d’origine. Un changement de responsable invalide également cet accord.
Les anciens accords sous `browser:v1:site:<origine-normalisée>` restent limités à leur site.
Une ancienne question est expirée et remplacée avant de demander un accord élargi ; sa réponse
ne peut pas autoriser tous les sites sans que cette portée ait été présentée.

Les fonctions MCP configurables proposent « Toujours autoriser cette fonction ». L’accord
écrit la politique `enabled` existante de cette fonction sur cette connexion ; les autres
fonctions et agents gardent leurs règles. L’action initiale conserve sa reprise et sa
consommation unique. Les autorisations sans connexion configurable restent ponctuelles.
Révoquer cet accord consiste à remettre la fonction sur « Sur demande ».

Les titres, boutons et explications suivent la langue normalisée du responsable humain,
puis la langue de l’installation. Les catalogues d’autorisation couvrent anglais, français
et chinois. Une autorisation ponctuelle ne porte plus un libellé promettant une mémorisation.

## Extension du 2026-10-08 — Mode d’accès public configurable

La connexion Browser expose `public_access_mode` dans les paramètres globaux et locaux.
`allow`, choix initial des nouvelles installations, autorise les méthodes HTTP et WebSocket
sur des adresses publiques sans demande par site. Cette configuration ne crée aucune décision
humaine implicite : revenir à `ask` rétablit les demandes, sous réserve des accords mémorisés
indépendamment. Les filtres, connexions désactivées et refus explicites restent prioritaires.
Le réseau local reste interdit par défaut. Son activation conserve les autorisations locales
séparées ; le mode public ne les accorde pas. Les politiques des fonctions MCP restent distinctes.
La convergence du schéma de paramètres ajoute le choix sans changer les valeurs administrées
ni les décisions existantes. Le jeu initial du Tool neuf initialise le paramètre global à `allow`.
La convergence d’un Tool existant conserve sa valeur ; si la clé était absente, elle ajoute `ask`.
Le repli du schéma et du contrôle réseau reste `ask`, également après effacement d’une valeur.
Une mise à jour ne bascule donc aucune instance en mode public. `ask` reste disponible pour
rétablir les demandes par site sur une nouvelle installation. Aucun changement de table ou de
données de permission n’est requis. Les sessions humaines sans connexion agent gardent leurs
restrictions indépendantes.

## Validation et mise en service

Les parcours PostgreSQL vérifient réutilisation, refus, portée, suppression, expiration,
concurrence et RBAC. Chromium vérifie HTTP, HTTPS, redirections, WebSocket et indisponibilité.
Le composant Vue/Quasar vérifie consultation, filtres, suppression et reprise après erreur.
DbAdmin converge le schéma et les paramètres de connexion. L’image `browser-executor` doit
être reconstruite ; les anciens accès locaux exigent ensuite configuration et accord explicites.
