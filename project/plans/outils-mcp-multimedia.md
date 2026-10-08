# Multimédia — qualifications et extensions

- Statut : `partial`
- Revue des sources : 2026-10-08.

Les cinq outils et leur module sont réalisés :
[ADR 0072](../decisions/0072-specialist-multimedia-tools.md),
[configuration](../../docs/fr/components/multimedia.md) et
[qualification historique](../audits/2026-09-11-memory-multimedia-qualification.md).
Texte, image, voix et transcription gardent leurs parcours distincts.

## Recette des capacités retenues

Pour OpenRouter (compréhension audio/vidéo, Lyria/vidéo), ElevenLabs (effets/music),
BytePlus (Seedance) et SunoAPI.org (musique/bruitages intermédiaires), revalider
les ressources/formats/limites/coûts/conditions réellement accessibles au compte.
Les tests de transport ne démontrent pas l'éligibilité commerciale.

Essai réel à coût borné : identité figée, suivi durable et interruption,
lecture du fichier par URI/type/contenu, puis livraison Messenger et droits
du destinataire si le parcours la demande. Publier date/version/configuration,
coût connu/inconnu, limite et preuve, sans credentials.
Issue ambiguë sans resoumission aveugle ; indisponibilité commerciale distincte d'un bug.
Les recettes ordinaires ont vocation à rejoindre le guide, pas à devenir des lots permanents.

## Extensions conservées

| Intention | Prérequis et réception |
|---|---|
| Suno Platform officiel | Contrat technique et éligibilité du compte ; authentification/soumission/suivi/callbacks/quotas/coûts/idempotence. L'intermédiaire existant n'est pas cette intégration. |
| Références/persona/remix/prolongement/reprise | Support provider vérifié, source stable et provenance/contraintes explicites. |
| Composition avancée ElevenLabs | Paramètres réels de durée/sections/paroles qualifiés. |
| Annulation distante | Confirmation vérifiable, distincte de l'arrêt local et du coût facturable. |
| Analyse Essentia | Mesures calculées distinctes des commentaires de modèle. |
| Music Flamingo / ACE-Step local | Licence, service conteneurisé, ressources et campagne comparative avant sélection. |
| Séparation de pistes / montage | Contrats propres, fichiers/coûts bornés et reprise démontrée. |

Persona, moteur, voix et preset restent distincts, sans pseudo-ressource artificielle.
Chaque extension précise son manque et son contrat avant implémentation ;
aucun endpoint officiel inféré ni connexion/modèle/destination changé implicitement.

## Réception et clôture

Réutiliser les tests pour droits après reconfiguration, invocation répétée, timeout ambigu,
callback dupliqué, fichier incorrect, nom/type, publication unique et coût.
URI canoniques, états terminaux et quotas conservés.
Publier limites durables dans ADR/guide puis retirer les lots réalisés ou transférés.

## Pistes historiques à revalider

- [OpenRouter audio](https://openrouter.ai/docs/guides/overview/multimodal/audio),
  [vidéo](https://openrouter.ai/docs/guides/overview/multimodal/videos),
  [génération vidéo](https://openrouter.ai/docs/guides/overview/multimodal/video-generation).
- [BytePlus vidéo](https://docs.byteplus.com/en/docs/Byteplus_LAS/video_gen_enhanced).
- [ElevenLabs composition](https://elevenlabs.io/docs/api-reference/music/compose),
  [effets](https://elevenlabs.io/docs/api-reference/text-to-sound-effects/convert).
- [Suno Platform](https://platform.suno.com/), [Essentia](https://essentia.upf.edu/streaming_extractor_music.html),
  [Music Flamingo](https://huggingface.co/nvidia/music-flamingo-hf), [ACE-Step](https://github.com/ace-step/ACE-Step-1.5).
