<p align="right"><strong>Français</strong> · <a href="../../en/components/multimedia.md">English</a></p>

# Multimédia

Le Service Multimedia analyse les sons, la musique et les vidéos et génère des bruitages,
des morceaux ou des vidéos. La transcription vocale, les conversations Voice, les images
et le texte restent configurés séparément.

## Configuration

1. Ajouter la connexion fournisseur et sa clé dans les préférences LLM.
2. Depuis son catalogue, ajouter une ressource pour chaque capacité souhaitée.
3. Dans le profil LLM de l'agent, sélectionner ces ressources dans **Multimédia**.
   Un agent sans profil personnalisé suit le profil courant ; un champ vide dans un profil
   personnalisé ne reprend pas la valeur du profil courant.
4. Vérifier la connexion **Multimedia** de l’agent. Elle est créée automatiquement et active
   par défaut et conserve les désactivations enregistrées. Ses fonctions sont réservées aux tâches.
   Sans ressource compatible, la fonction reste absente
   du catalogue MCP.

Le catalogue MCP et chaque appel revérifient connexion, capacité, fournisseur et ressource
sélectionnée. La génération durable appartient à `app.multimedia`, avec son worker et ses
checkpoints ; elle ne crée pas de run Process.

| Fonction | Usage du profil | Fournisseurs intégrés |
|---|---|---|
| `audio_read` | Analyse des sons et musiques | OpenRouter et Mammouth AI, modèles avec entrée audio et sortie texte |
| `video_read` | Analyse vidéo | OpenRouter et Mammouth AI, modèles avec entrée vidéo et sortie texte |
| `sound_generate` | Génération de sons | ElevenLabs, service `sound:V5` de SunoAPI.org |
| `music_generate` | Génération musicale | Eleven Music, Lyria sur OpenRouter, SunoAPI.org |
| `video_generate` | Génération vidéo | OpenRouter, Seedance via BytePlus LAS |

SunoAPI.org est un fournisseur tiers. Sa clé est distincte d'un abonnement Suno et de l'accès
Suno Platform. Cette intégration utilise `https://api.sunoapi.org/api/v1`. Le callback exige
une URL publique HTTPS de Galaris (`APP_HOST`). Son payload
ne modifie pas les runs : Galaris récupère l'état auprès du fournisseur avec sa clé.

Pour le [MCP officiel de Suno](https://help.suno.com/en/articles/14551425), la fiche **Suno** du
catalogue utilise le connecteur MCP HTTP. Après avoir enregistré le Service, connecter le
compte Suno avec [OAuth depuis la Connexion](../admin/service-administration.md).
Les créations utilisent les crédits du compte et apparaissent dans sa bibliothèque Suno.
La récupération d'un fichier via ce connecteur et sa livraison par Galaris restent à qualifier.

## Utilisation par les agents

Les lectures prennent `uri` et une question `prompt`. Les fichiers restent dans leur Service
d'origine ; l'analyse dispose d'un temporaire borné à 32 Mio et 20 minutes, validé par FFprobe,
sans copie durable.

`video_read` accepte aussi `subtitles_uri` et `language`. Il utilise d'abord le fichier
SRT/WebVTT fourni, puis une piste textuelle intégrée, puis le modèle de transcription du
profil de l'agent. Le résultat sépare l'analyse visuelle et `transcript`, avec provenance,
horodatages et avertissements de couverture ; un extrait borné est aussi transmis au modèle
vidéo. Sans son ou sans transcription disponible, l'analyse visuelle reste possible avec
un avertissement. Les sous-titres incrustés ne sont pas extraits par OCR. Une URL de page
YouTube passe par `audio_transcribe`, qui convient aussi aux enregistrements plus longs ou
à une transcription complète enregistrée. Voir le [parcours multimédia](../user/README.md).

Les générations prennent un `prompt` et une `destination` désignant une collection de fichiers
accessible en écriture, terminée par `/`, par exemple une collection renvoyée par `file_list`.
La racine `document://` ne convient pas ; une collection de pièces jointes de document convient.
Une console n'est utilisable que si sa connexion est active.

Le résultat initial fournit un `generation_id` et un `run_id`. Utiliser `multimedia_get_run` jusqu'au résultat terminal.
Les fichiers finaux figurent dans `output.files[].uri`, et sont ajoutés aux ressources de la tâche.
La génération devient réussie après écriture dans la destination. Maximum : quatre fichiers de 100 Mio.

`invocation_key` identifie une seule demande : la réutiliser pour retenter cette demande,
utiliser une nouvelle clé pour produire une autre variation. Sans clé, chaque invocation est distincte.
Une soumission dont la réponse est perdue reste `unknown`. Pour une génération dont le
fournisseur a confirmé l'identifiant, une panne temporaire du suivi ou du téléchargement
produit un état `waiting` et Galaris reprend le suivi sans nouvelle soumission.
Une écriture distante interrompue retourne `delivery_unknown` dès que son issue est incertaine.
Vérifier la destination avant toute relance de la livraison.
Les reçus privés en base conservent les octets jusqu'à leur livraison canonique puis les effacent.
Une annulation confirmée par BytePlus ou OpenRouter est affichée comme `cancelled`, avec un coût
inconnu si le fournisseur ne le communique pas. La demande d'annulation distante reste indisponible.

Les options dépendent du fournisseur : ElevenLabs produit les effets jusqu'à 30 secondes et
la musique à partir de 3 secondes ; SunoAPI accepte les paroles en mode personnalisé avec
style et titre ; Lyria reçoit des indications musicales et de paroles ; Seedance valide les
durées, ratios et résolutions pris en charge. Les options non prises en charge sont refusées.
Les coûts non fournis par l'API sont marqués inconnus dans le résultat.

Avec BytePlus Seedance, `video_generate` accepte `first_frame_uri` et, avec cette première
image, `last_frame_uri`. Indiquer des URI canoniques de fichiers JPEG ou PNG fixes, de 5 Mo
au plus par image, avec des côtés de 300 à 6 000 pixels et un ratio largeur/hauteur de 0,4 à 2,5.
Galaris revérifie les droits et le contenu avant la soumission. Le résultat conserve les rôles
et empreintes SHA-256 dans `reference_frames`.

Avec Eleven Music, `music_generate` accepte un objet `composition`. Chaque élément de `sections`
indique `name`, `duration_ms` (3 000 à 120 000), et éventuellement `lyrics` (une chaîne par ligne),
`styles` et `avoid_styles`. Le plan peut aussi définir les deux listes de styles au niveau global.
Le `prompt` donne la direction générale en 200 caractères maximum. Le total est limité à 600 secondes.
Fournir les styles, durées et paroles dans le plan et omettre les options musicales de premier niveau.

## Installation et validation

L'image backend inclut FFmpeg/FFprobe : reconstruire l'image si l'installation précède cette
fonctionnalité. En développement, `make sync-db` ajoute le schéma et les connexions ; en
production, le chemin habituel est `make update`.

Les tests avec transports simulés couvrent le déroulement, les erreurs de suivi, les reprises et
les plans de composition. Les droits commerciaux et les crédits d'un compte se qualifient avec
un essai réel. Les personas, remixes et autres références multimodales restent des extensions.

Sources des contrats : [OpenRouter audio](https://openrouter.ai/docs/guides/overview/multimodal/audio),
[OpenRouter vidéo](https://openrouter.ai/docs/guides/overview/multimodal/video-generation),
[SunoAPI.org](https://docs.sunoapi.org/suno-api/generate-music),
[Eleven Music](https://elevenlabs.io/docs/api-reference/music/compose),
[BytePlus LAS](https://docs.byteplus.com/en/docs/byteplus_las/video_gen_enhanced).
