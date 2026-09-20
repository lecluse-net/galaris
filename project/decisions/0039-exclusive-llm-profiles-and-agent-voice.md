# 0039 — Profils LLM exclusifs et voix canonique par agent

> La granularité des colonnes de modèles texte décrite ici est remplacée par la
> [décision 0050](0050-shared-text-model-tiers.md). L’exclusivité du profil effectif et la sélection
> vocale restent en vigueur.

- Statut : Accepted
- Date : 2026-08-20

## Contexte

Les usages LLM ont d’abord été exposés comme des paramètres globaux `ai.model.*`, puis projetés
dans des profils. Cette coexistence rendait la résolution ambiguë : un agent doté d’un profil
personnel pouvait encore emprunter une valeur au profil courant ou à un ancien paramètre. La voix
d’un agent était parallèlement décomposée entre plusieurs colonnes TTS et temps réel.

`app.messenger.Room` et `app.conversation.ConversationRound` portent désormais la portée et la
chronologie conversationnelles. `ConversationFingerprint` n’a plus de responsabilité durable.

## Décision

`LlmProfile` est l’unique source des modèles affectés aux usages. Chaque usage correspond à une
colonne explicite du profil, notamment l’exécution standard et high, la conversation, le
dispatcher, le planner, le briefing, les Goals, Dream, le Lab, les médias, la transcription et
les embeddings. Les constantes de `app.llm.model_usages` identifient directement ces colonnes ;
ce ne sont pas des paramètres applicatifs.

Le seul paramètre global lié aux profils est `Params.LLM_PROFILE_ID`, pointeur vers le profil
courant. Pour un agent :

- `Agent.profile_id IS NULL` signifie « utiliser le profil courant » ;
- un `profile_id` renseigné sélectionne exclusivement ce profil ;
- une colonne vide dans un profil personnel reste vide : elle n’emprunte jamais la valeur du
  profil courant ;
- l’unique repli entre usages est documenté dans le runtime : l’exécuteur `high` peut reprendre
  l’exécuteur standard du même profil effectif.

La voix reste propre à l’agent et vit dans une seule colonne `Agent.voice`. Sa représentation est
canonique : `tts:<resource-id>` pour le pipeline STT/TTS, ou
`realtime:<resource-id>:<provider-voice-code-encodé>` pour une session audio native. Aucun autre
champ de projection vocale n’est conservé.

`ConversationFingerprint` est supprimé. Une Room Messenger et ses rounds sont la source canonique
des échanges ; les appels compatibles OpenAI sans identifiant conversationnel explicite reçoivent
un identifiant indépendant et ne tentent aucune déduction heuristique.

Il n’existe aucun chemin de compatibilité qui relise les anciens paramètres ou les anciennes
colonnes de voix. Atlas retire les colonnes et tables obsolètes depuis les modèles déclaratifs.

## Conséquences

- Le choix « profil courant » est une valeur durable, pas une copie de l’identifiant courant dans
  chaque agent ; un changement du pointeur s’applique donc immédiatement aux agents concernés.
- Tous les chemins spécialisés doivent recevoir l’agent ou son identifiant afin de résoudre le
  même profil effectif que l’exécuteur.
- Supprimer un profil personnel remet ses agents à `profile_id = NULL` ; ils suivent alors le
  profil courant.
- Supprimer une ressource LLM efface les colonnes de profil et la sélection vocale qui la
  référencent, sans toucher au pointeur du profil courant.
- Cette décision remplace les parties de 0010, 0016 et 0022 qui décrivaient des paramètres
  `ai.model.*`, des replis inter-profils ou les anciennes projections de voix.
