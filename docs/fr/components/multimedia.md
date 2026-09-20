<p align="right"><strong>Français</strong> · <a href="../../en/components/multimedia.md">English</a></p>

# Multimédia

Le Tool Multimedia analyse les sons, la musique et les vidéos et génère des bruitages,
des morceaux ou des vidéos. La transcription vocale, les conversations Voice, les images
et le texte restent configurés séparément.

## Configuration

1. Ajouter la connexion fournisseur et sa clé dans les préférences LLM.
2. Depuis son catalogue, ajouter une ressource pour chaque capacité souhaitée.
3. Dans le profil LLM de l'agent, sélectionner ces ressources dans **Multimédia**.
   Un agent sans profil personnalisé suit le profil courant ; un champ vide dans un profil
   personnalisé ne reprend pas la valeur du profil courant.
4. Activer la connexion **Multimedia** de l'agent. Elle est créée automatiquement et inactive
   par défaut. Les fonctions sans ressource compatible restent absentes du catalogue MCP.

| Fonction | Usage du profil | Fournisseurs intégrés |
|---|---|---|
| `audio_read` | Analyse des sons et musiques | OpenRouter et Mammouth AI, modèles avec entrée audio et sortie texte |
| `video_read` | Analyse vidéo | OpenRouter et Mammouth AI, modèles avec entrée vidéo et sortie texte |
| `sound_generate` | Génération de sons | ElevenLabs, service `sound:V5` de SunoAPI.org |
| `music_generate` | Génération musicale | Eleven Music, Lyria sur OpenRouter, SunoAPI.org |
| `video_generate` | Génération vidéo | OpenRouter, Seedance via BytePlus LAS |

SunoAPI.org est un fournisseur tiers. Sa clé est distincte d'un abonnement Suno et de l'accès
Suno Platform. Cette intégration utilise `https://api.sunoapi.org/api/v1`. Le callback exige
une URL publique HTTPS de Galaris (`PROCESS_GALARIS_BASE_URL`, sinon `APP_HOST`). Son payload
ne modifie pas les runs : Galaris récupère l'état auprès du fournisseur avec sa clé.

## Utilisation par les agents

Les lectures prennent `uri` et une question `prompt`. Les fichiers restent dans leur Tool
d'origine ; l'analyse dispose d'un temporaire borné à 32 Mo et 20 minutes, sans copie durable.

Les générations prennent un `prompt` et une `destination` désignant une collection de fichiers
accessible en écriture, terminée par `/`, par exemple une collection renvoyée par `file_list`.
La racine `document://` ne convient pas ; une collection de pièces jointes de document convient.
Une console n'est utilisable que si sa connexion est active.

Le résultat initial fournit un `run_id`. Utiliser `process_get_run` jusqu'au résultat terminal.
Les fichiers finaux figurent dans `output.files[].uri`, et sont ajoutés aux ressources de la Task.
Le Process devient réussi après écriture dans la destination. Maximum : quatre fichiers de 100 Mo.

`invocation_key` identifie une seule demande : la réutiliser pour retenter cette demande,
utiliser une nouvelle clé pour produire une autre variation. Sans clé, chaque invocation est distincte.
En cas de réponse perdue à la soumission, Galaris ne relance pas automatiquement la génération.
En cas d'interruption ambiguë d'une écriture distante, vérifier la destination avant toute relance.

Les options dépendent du fournisseur : ElevenLabs produit les effets jusqu'à 30 secondes et
la musique à partir de 3 secondes ; SunoAPI accepte les paroles en mode personnalisé avec
style et titre ; Lyria reçoit des indications musicales et de paroles ; Seedance valide les
durées, ratios et résolutions pris en charge. Les options non prises en charge sont refusées.
Les coûts non fournis par l'API sont marqués inconnus dans le résultat.

## Installation et validation

L'image backend inclut FFmpeg/FFprobe : reconstruire l'image si l'installation précède cette
fonctionnalité. En développement, `make sync-db` ajoute le schéma et les connexions ; en
production, le chemin habituel est `make update`.

Les contrats ont des tests avec transports simulés ; ils ne prouvent pas les droits commerciaux
ou crédits d'un compte. Les fonctions avancées (personas, remixes, références audio/images et
plans de composition ElevenLabs) ne sont pas encore exposées.

Sources des contrats : [OpenRouter audio](https://openrouter.ai/docs/guides/overview/multimodal/audio),
[OpenRouter vidéo](https://openrouter.ai/docs/guides/overview/multimodal/video-generation),
[SunoAPI.org](https://docs.sunoapi.org/suno-api/generate-music),
[Eleven Music](https://elevenlabs.io/docs/api-reference/music/compose),
[BytePlus LAS](https://docs.byteplus.com/en/docs/byteplus_las/video_gen_enhanced).
