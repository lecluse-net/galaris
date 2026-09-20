# 0126 — Entrées multimodales natives du chat et des Tasks

Statut : accepté — 2026-09-19

## Garantie observable

Un modèle compatible reçoit directement les pièces jointes utiles du message courant et de
l'historique retenu. Il n'a pas à appeler un spécialiste pour voir une image, entendre un audio
ou lire un PDF déjà présent. Les outils Image, Audio et Multimedia restent disponibles pour
l'analyse dédiée, la persistance des descriptions/transcripts et les replis.

## Consommateurs et décision

- `HarnessConversationController` et l'exécuteur Task fournissent les messages canoniques au
  runtime Pydantic AI commun ; les historiques des tours vocaux bénéficient de la même projection.
- `app.harness.media` matérialise les ressources autorisées via `app.file_share`, une fois par URI
  et dans un budget total d'octets, en privilégiant les messages courants puis l'historique récent.
  Il conserve les références et la provenance chronologique, et nettoie immédiatement les temporaires.
- Les capacités effectives croisent les drapeaux du modèle et la politique de formats du bridge.
  L'interdiction absolue audio/vidéo est retirée, ainsi que les tests qui la figeaient. Les garanties
  de références canoniques, limites, contrôle des droits et nettoyage sont reprises dans les tests
  du nouveau parcours. Les formats non supportés restent explicitement signalés.
- La version SDK installée ne sérialise pas les octets audio/vidéo en Responses. Un modèle avec
  ces entrées effectives utilise Chat Completions dans le harnais, sans changement de modèle et toujours via le
  proxy LLM comptabilisé. Le point d'extension protégé stable du SDK encode les formats déclarés
  par le bridge OpenRouter, notamment `video_url`. Aucune URL publique temporaire n'est nécessaire.
  Les autres consommateurs de la fabrique (services structurés et Lab) gardent leur choix de
  protocole existant : la prise en charge native est activée explicitement par le harnais.
- La transcription automatique tient compte du transport et de la taille, pas seulement du
  drapeau `input_audio`. Le budget préalable réserve une estimation par média et ne compte plus
  le base64 comme des tokens textuels. La consommation fournisseur reste l'autorité.

## Validation et limites

Les tests observent les contenus reçus par Pydantic AI et les payloads envoyés au proxy, les
réouvertures, la déduplication, les droits refusés, les formats modifiés, les tailles et annulations.
Les checkpoints conservent leur historique multimodal existant à la reprise. Les tests de
sérialisation remplacent la frontière fournisseur ; ils n'attestent pas d'un appel commercial réel.

Le contrat concerne les pièces jointes canoniques, pas le téléchargement implicite de toute URI
citée dans du texte. Le transport Hermès reste limité aux formats qu'il sait transmettre. Les
appels vocaux realtime gardent leur propre transport audio. Les vidéos natives des autres
fournisseurs nécessitent un adaptateur déclaré ; la seule capacité du modèle ne suffit pas.

Références : [Pydantic AI](https://ai.pydantic.dev/input/),
[audio OpenRouter](https://openrouter.ai/docs/guides/overview/multimodal/audio),
[vidéo OpenRouter](https://openrouter.ai/docs/guides/overview/multimodal/videos).
