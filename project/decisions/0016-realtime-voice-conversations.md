# 0016 — Conversations vocales temps réel comme capacité fournisseur

- Statut : Accepted
- Date : 2026-07-30

> Le stockage de la sélection vocale décrit ici est remplacé par la
> [décision 0039](0039-exclusive-llm-profiles-and-agent-voice.md).

## Contexte

Le moteur vocal historique segmente la parole puis enchaîne trois services indépendants :
STT, exécution d’un tour agentique textuel et TTS. Cette composition reste utile pour choisir
librement les fournisseurs, mais elle perd la prosodie de l’entrée et ajoute une latence
incompressible.

Certains fournisseurs exposent désormais une session audio stateful qui reçoit et produit du
PCM tout en appelant des fonctions. Cette session doit accéder à la mémoire gouvernée et créer
des Tasks sans contourner les frontières `app.agent`, `app.memory` et `app.task`.

## Décision

Un agent possède une seule sélection vocale visible. Le sélecteur « Synthèse vocale » regroupe :

- les ressources TTS configurées, qui activent le pipeline STT → agent → TTS ;
- les voix natives proposées par les modèles `realtime_conversation`, qui activent le STS.

Le choix est persisté dans l’unique colonne `Agent.voice` : `tts:<resource-id>` pour le pipeline,
ou `realtime:<resource-id>:<provider-voice-code-encodé>` pour le temps réel. La voix native n'est
pas enregistrée comme un faux LLM. Le catalogue de voix reste possédé par le bridge fournisseur.

`app.llm.provider_facade` définit le contrat générique de session temps réel. Un bridge
fournisseur possède le WebSocket, les événements et les formats propres au protocole.
L’implémentation initiale vit dans `bridge.openai`.

Une sélection TTS utilise le STT commun, le runtime agentique ordinaire puis la ressource de
synthèse choisie. Une sélection STS ouvre la session du modèle associé et lui passe directement
l'identifiant de voix native. Les deux architectures restent donc disponibles sans exposer
plusieurs champs de voix sur l'agent.

## Intégration Galaris

`app.agent` prépare l’identité, le prompt commun et tous les providers de contexte enregistrés.
La mémoire core est donc injectée comme pour un run ordinaire. La session expose en plus trois
fonctions locales bornées :

- `memory_search`, via la façade publique et les ACL de `app.memory` ;
- `task_submit`, via `AgentTaskPort.create` puis `schedule` ;
- `task_status`, limité aux Tasks de l’agent courant.

Le fournisseur reçoit uniquement la définition de ces fonctions et leurs résultats JSON. Il
n’accède ni à PostgreSQL, ni aux credentials, ni au scheduler.

Une prise de parole ordinaire reste un `ConversationRound`, pas une Task. En audio natif,
aucun transcript utilisateur n'est inventé : aucune transcription n’est ajoutée au chemin critique.
Une demande de travail asynchrone devient en revanche une vraie Task durable avant que le modèle
puisse confirmer sa création.

## Conséquences

- Le pipeline STT → agent → TTS reste disponible lorsqu’une ressource TTS est sélectionnée.
- Les voix OpenAI sont découvertes sous la forme `voice:<nom>` et proposées directement dans
  le groupe STS du sélecteur d'agent.
- Les anciennes projections vocales ne sont plus lues ni conservées.
- Le transport d’appel reste en PCM mono 48 kHz ; le bridge OpenAI utilise du PCM mono 24 kHz
  et `app.voice` effectue la conversion.
- Le barge-in WebSocket interrompt la lecture locale et tronque l’item fournisseur à la durée
  effectivement jouée estimée.
- Un nouveau fournisseur temps réel implémente le contrat de façade ; aucune branche portant
  son nom ne doit être ajoutée au domaine agent ou au transport d’appel.
