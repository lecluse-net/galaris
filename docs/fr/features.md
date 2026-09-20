<p align="right"><strong>Français</strong> · <a href="../en/features.md">English</a></p>

# Tour des fonctionnalités de Galaris

Galaris est un centre de contrôle auto-hébergé pour agents IA. Il réunit dans une même plateforme
les modèles, les runtimes agentiques, les outils, les conversations, les tâches durables, la
mémoire et les processus métier. L’objectif n’est pas seulement d’obtenir une réponse : il est de
transformer une demande en résultat traçable, récupérable et gouverné.

Cette synthèse reprend la revue du **12 septembre 2026**, avec une mise à jour du contrat
d’inférence le 14 septembre. Le [catalogue français détaillé](../catalogue-fonctionnel-fr.md)
conserve l’inventaire des modules et fonctions MCP. Certaines capacités demandent un modèle,
un bridge ou une connexion explicitement configurés ; les fonctions expérimentales ou futures
restent décrites séparément dans l’[index des plans](../../project/plans/README.md).

## Du message au résultat

Galaris sépare trois rythmes de travail qui peuvent se relayer sans perdre leur contexte :

| Rythme | Usage | Contrôle apporté par Galaris |
|---|---|---|
| **Conversation** | question, échange court, orientation | agrégation des messages, historique durable, anti-boucle, appels LLM et effets inspectables |
| **Task** | action, recherche, production d’un livrable | routage, effort, outils, plan éventuel, délégation, reprise, résultat et coûts persistés |
| **Goal** | objectif de fond mené sur plusieurs cycles | propriétaire, référent, planning, verdicts, preuves, suivi riche, pause et déclenchement manuel |

Une conversation peut lancer une Task ou un Processus de fond puis répondre immédiatement avec sa
référence. Une Task complexe peut devenir un plan de vraies sous-tâches et solliciter d’autres
agents. Un Goal crée des cycles successifs jusqu’à réussite ou arrêt explicite.

## Agents, modèles et runtimes

Chaque agent possède une identité stable, un rôle, des instructions, un niveau d’accès, un modèle,
des skills et des connexions d’outils. Galaris conserve cette identité pendant
les délégations et refuse qu’un appel modifie silencieusement l’agent qui exécute le travail.

Deux runtimes partagent la même façade métier :

- le driver **interne Pydantic AI**, avec Dispatcher, Planner, streaming,
  checkpoints d’outils et annulation sûre ;
- le driver **Hermès**, utilisé comme runtime autonome dans un conteneur isolé par agent, avec
  modèles Hermès ou modèles servis par Galaris et projection de la mémoire commune.

Les fournisseurs LLM sont des bridges remplaçables. OpenAI, Anthropic, Google, Mistral,
OpenRouter, Ollama et de nombreux fournisseurs compatibles peuvent cohabiter. Des modèles distincts
peuvent être affectés à l’exécution standard ou high, aux conversations rapides, au Planner, au
Dispatcher, au Briefing, aux Goals, au Lab, à Dream, aux embeddings, aux médias et aux images.

Les appels texte utilisent les profils SDK et les contraintes de l’endpoint pour le raisonnement,
les plafonds et le sampling. Les extensions inconnues sont transmises ; seul un rejet explicite
avant génération permet de retirer un réglage optionnel. Messages, outils, budgets et formats de
sortie sont préservés. La [matrice des paramètres](dev/provider-parameters.md) est vérifiée avec
des transports simulés, sans appel fournisseur payant.

## Orchestration durable et collaboration

Une Task enregistre son objectif, l’agent affecté, le routage, l’effort, les tentatives, les appels
LLM et outils, les processus liés, les sous-tâches et le résultat terminal. L’ordonnanceur utilise
des leases persistées : un incident de processus ne fait pas disparaître le travail et une
exécution bloquée peut être libérée explicitement.

Le détail des Tasks et leur panneau Chat restaurent l’activité à l’ouverture et à la reconnexion :
pause demandée ou effective, attentes, dernière tentative, prochain essai et progression bornée.
Les nouvelles Tasks conservent la demande initiale, la provenance, les ressources et les reçus.
`task_get` expose aussi les états actifs et terminaux ; un événement tardif ne remplace pas un résultat terminal.

Le Dispatcher choisit entre exécution directe et planification. Le Planner crée des étapes bornées
avec livrables et critères de succès, puis synthétise le résultat. Le Briefing reste disponible
comme mécanisme d’évaluation, mais son activation en production est suspendue. Les agents peuvent
déléguer une sous-tâche ou attendre la réponse d’un collègue sans créer une boucle infinie.

Le harnais interne checkpoint chaque effet MCP avant et après l’appel. Après une annulation ou une
reprise, un résultat déjà obtenu peut être réutilisé au lieu de répéter aveuglément un effet externe.

## Conversations texte et voix

Le journal Messenger est le point d’entrée canonique de tous les canaux. Le Messenger interne,
Nextcloud Talk, Matrix, OneBot, Telegram et WhatsApp Business peuvent être actifs simultanément.
Une réponse repart par la connexion et la conversation d’origine ; un nouveau message vers un
autre canal exige une cible explicite. Le canal interne fournit des rooms privées ou de groupe,
des fichiers, des notes vocales, une activité expurgée et des appels WebRTC ; ses rounds sont
strictement isolés des Tasks.

Les conversations texte courtes disposent de leur propre control plane : messages reçus,
agrégations, rounds, tentatives, livraisons, appels LLM et erreurs sont visibles en temps réel. Le
contrôleur répond directement ou crée une Task/Processus durable pour un travail asynchrone. Les
réponses entre agents sont filtrées afin d’éviter les échanges automatiques sans fin.

Pour la voix en direct, Galaris sait utiliser :

- un pipeline **STT → agent → TTS**, qui permet de composer librement les fournisseurs ;
- une session **speech-to-speech** native, qui conserve la prosodie et réduit la latence lorsque
  le fournisseur et la voix sélectionnés le permettent.

Les appels Matrix et Nextcloud Talk sont suivis avec leurs tours, interruptions, transcriptions
éventuelles, réponses et incidents. Les notes vocales reçues par les autres messageries suivent le
parcours média canonique.

## Mémoire gouvernée et dossiers thématiques

Galaris distingue la session récente de la mémoire durable. La session est reconstruite depuis le
journal canonique et transmise de la même manière aux différents drivers. La mémoire durable est
privée par défaut et associe à chaque élément :

- un propriétaire, un type et un rôle mémoire ;
- des révisions, une provenance et des relations ;
- des accès directs en lecture ou édition ;
- des traces d’usage et un oubli définitif explicite.

Le rappel combine recherche plein texte et similarité vectorielle lorsque le modèle d’embedding est
configuré. Les ACL et bornes sont appliquées avant le classement ; en cas d’indisponibilité de
l’index sémantique, le repli lexical est annoncé au lieu d’être masqué.

Les **documents de travail** utilisent du HTML sémantique versionné et un éditeur riche pour les notes,
brouillons et livrables qui évoluent sur plusieurs Tasks. Les **dossiers thématiques** relient
les souvenirs, tâches et conversations autour d’un même sujet global, indépendamment du canal ou
du salon qui les a produits. Le graphe de mémoire permet d’explorer ces relations et leur période.

La recherche utilise le titre, les mots-clés et le contenu courant ; les aperçus sont des extraits.
Les résumés séparés et motifs libres de modification ont disparu, tandis que révisions, dates,
auteurs, Tasks et sources restent traçables. La déduplication respecte les dates de validité.

Le formulaire mémoire permet consultation, création, édition, saisie des mots-clés et sauvegarde
sans fermeture. L’historique préserve le brouillon, reste accessible aux lecteurs et peut être
rechargé après erreur. Les résultats distinguent documents et souvenirs, avec des relations traduites.

Agents, Goals, cycles, contacts de messagerie et résultats de processus peuvent être projetés de
façon idempotente dans cette mémoire sans remplacer leur source métier.

## Dream : entretien et apprentissage

Dream exploite uniquement la capacité de fond disponible et exécute un mécanisme à la fois. Il peut
classer les sujets, extraire et consolider les souvenirs, relier les dossiers thématiques, projeter
les processus et oublier les éléments devenus inactifs. Sa page de suivi expose en direct le
mécanisme courant, le sujet, la phase, les tentatives et les éventuelles erreurs.

L’apprentissage va plus loin qu’un résumé de réponse. Il examine des preuves observables —
tentatives, outils, sous-tâches, verdict Goal, corrections humaines et usages Memory — puis crée ou
renforce une candidate dédiée à l'agent, y compris en parcourant progressivement les Tasks
historiques. Chaque procédure possède un score et un journal de preuves positives ou négatives.
Elle devient une skill injectée en plus des skills affectées seulement lorsque plusieurs Tasks
distinctes confirment la même action — 3 par défaut, seuil réglable — et que sa note atteint le
minimum configuré. Cette fonction est **désactivée par défaut** et sépare les modes d'observation et
d'apprentissage ; son onglet est alors masqué et elle n'écrit aucun nœud dans Memory.

## Outils et connexions

Les fonctions ne sont pas toutes envoyées au modèle à chaque tour. Galaris construit un catalogue,
filtre d’abord selon les droits et connexions actives, puis charge à la demande les capacités
pertinentes. Un administrateur peut désactiver une connexion complète ou seulement certaines de
ses fonctions.

Les surfaces livrées couvrent notamment :

| Domaine | Capacités |
|---|---|
| **Web** | métarecherche SearXNG locale, navigateur Chromium interactif isolé, snapshots accessibles et captures visuelles bornées |
| **Fichiers** | URI canoniques, providers connectés, transferts en flux et pièces jointes entrantes/sortantes |
| **Médias** | transcription audio/vidéo, sous-titres YouTube publics, segmentation longue, verbatim et synthèse hiérarchique |
| **Images** | génération, modification, description et transport par identifiants de fichiers |
| **Console** | sessions SSH contrôlées, exécuteur embarqué et fichiers du home sans exposer les credentials au modèle |
| **MCP** | outils natifs Galaris et serveurs distants, diagnostics de connexion, restrictions par fonction |
| **Processus** | définitions personnelles, administration séparée, runs durables, événements, callbacks, annulation et bridge n8n |
| **Organisation** | gestion spécialisée des agents, Goals, skills, Tasks et inspections LLM selon les droits accordés |

Le navigateur utilise un sidecar Chromium partagé, mais chaque couple agent/Task reçoit un contexte
isolé et éphémère. Il peut ouvrir toute URL HTTP(S) joignable depuis les réseaux du sidecar, y
compris les services Docker, le réseau local et l’hôte via `host.docker.internal`, afin de produire
des aperçus d’outils en cours de construction.

## Fichiers, audio, vidéo et images

Les médias entrants sont bornés et conservent l’URI exacte du Tool qui les a reçus. Un consommateur
peut les matérialiser dans un temporaire serveur nettoyé après l’appel, sans créer de nouvelle
ressource ni modifier l’identité présentée au modèle. Les fichiers volumineux restent référencés
par URI et ne sont pas copiés dans chaque message du modèle.

`audio_transcribe` accepte un fichier audio, un fichier vidéo ou une URL YouTube publique. Pour un
fichier local, Galaris extrait la première piste audio, la normalise, segmente les longues durées,
conserve le verbatim et produit une synthèse hiérarchique. Pour YouTube, il récupère les sous-titres
disponibles sans télécharger la vidéo ni appeler le STT. L’analyse et la génération d’images passent
également par des modèles dédiés et le transport de fichiers commun.

## Processus métier et n8n

Une définition de processus décrit son entrée, son propriétaire et son moteur. Chaque lancement
crée un run persistant avec statut, événements, sortie, erreur et liens vers les Tasks concernées.
Le bridge n8n fournit clés d’idempotence, callbacks authentifiés et états terminaux immuables. Les
processus personnels et leur administration globale utilisent des permissions distinctes.

Un callback terminal conserve résultat, erreur et identité externe même si la réponse initiale
arrive tardivement ou se perd. Les découvertes concurrentes convergent vers un run unique et
refusent les collisions avec un autre workflow.

## Lab IA et observabilité

Le Lab IA sert à comprendre et comparer les mécanismes réellement utilisés par Galaris. Il peut
importer une Task, un round de conversation ou un tour vocal dans un dataset, figer une référence,
exécuter un modèle candidat et produire un jugement sémantique détaillé. Dispatcher, Briefing,
Planner, exécuteurs et mécanismes Dream/Goal disposent de jeux de données séparés afin de ne pas
mélanger des contrats différents.

Les runs sont persistés par cas, reprenables et analysables. Un score n’est jamais présenté comme
une vérité absolue : dimensions, couverture, erreurs, similarité stricte et calibration du juge
restent visibles.

Dans l’exploitation quotidienne, les écrans de suivi temps réel regroupent Tasks, conversations,
appels vocaux, activité LLM, processus et Dream. Les identifiants de run relient les appels et
effets à leur origine. Les journaux applicatifs et traces Logfire complètent cette vue lorsqu’ils
sont configurés.

Un round qui réussit après reprise est présenté comme réussi ; ses erreurs antérieures restent
dans l’historique. Les diagnostics API exposent détail, route et statut disponibles, et distinguent
les erreurs réseau des délais dépassés.

## Sécurité et maîtrise des données

- déploiement Docker auto-hébergé avec PostgreSQL 17 et pgvector ;
- RBAC par privilèges, rôles et affectations, appliqué dans l’API comme dans la navigation ;
- secrets de connexion chiffrés et jamais relus en clair par l’API ;
- second facteur TOTP facultatif, codes de secours à usage unique et verrouillage progressif des
  connexions échouées ;
- sessions PWA persistantes par refresh token rotatif, cookie protégé et révocation de famille ;
- connexion explicite en attente de l’identité courante ; une erreur garde le formulaire ouvert,
  et une réponse obsolète ne remplace pas le compte actuel ;
- outils et fonctions explicitement autorisés par agent ;
- approbations non transmissibles automatiquement aux agents délégués ;
- workspaces, sessions navigateur et mémoires isolés par propriétaire ;
- annulation, limites, idempotence et états terminaux pour réduire les doubles effets.

Galaris reste une plateforme d’agents probabilistes : les traces et contrôles rendent le travail
auditable, mais une action importante doit toujours être vérifiée au niveau approprié.

## Expérience utilisateur et exploitation

L’interface Vue/Quasar est bilingue français/anglais, compatible clair/sombre et installable en PWA
sur Android et iPhone. Le parcours de bienvenue vérifie le modèle, le premier agent, ses outils et
la messagerie. Les listes et tableaux de bord utilisent les droits courants et les flux actifs sont
mis à jour en temps réel.

Les sélecteurs d’agents et de sujets chargent leurs options à l’ouverture, préservent les valeurs
existantes et permettent une reprise après erreur. Les filtres concernés écartent les réponses
d’un contexte précédent. Les mises à jour PWA renouvellent le cache et rechargent les onglets en
conservant la session ; sauvegarder les formulaires ouverts avant déploiement. Les mises à jour
de production ordinaires réutilisent le cache Docker et préservent HTTPS ; `RELEASE_DIR`
déploie les images qualifiées sans modification. DbAdmin conserve les erreurs bornées avec son verdict.

`make validate` vérifie un instantané isolé incluant les changements non committés, avec empreinte
et rapports dans `artifacts/validation/`, sans commit ni déploiement. `make tests-coverage` mesure
toutes les sources backend, même non importées. Le seuil de **95 %** lignes et branches concerne
le sous-ensemble critique ; des planchers par domaine et contrôles des branches critiques modifiées
le complètent. Les scénarios fonctionnels et mutations couvrent reprises, concurrence, sessions,
documents, Lab, médias, stockage, transferts et DbAdmin. Voir les [garanties fonctionnelles](dev/functional-tests.md)
et le [guide de tests](dev/testing.md).

Pour aller plus loin :

- [guide utilisateur](user/README.md) ;
- [installation et exploitation](admin/installation.md) ;
- [guide administrateur](admin/README.md) ;
- [guide développeur](dev/README.md) ;
- [flux d’architecture](architecture/README.md) et
  [décisions du projet](../../project/decisions/README.md).
