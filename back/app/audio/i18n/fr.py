"""Messages français du traitement audio."""

default: dict[str, object] = {
    "audio": {
        "transcribed": "Transcription écrite (${size} caractères) : ${location}",
        "long_processing": (
            "⏳ Enregistrement long détecté (${duration}). Je le traite en ${chunks} segments "
            "d’environ ${minutes} minutes, puis j’en produirai une synthèse globale. Cela peut "
            "prendre un peu de temps."
        ),
        "long_transcribed": (
            "Transcription longue terminée : ${chunks} segments, ${size} caractères. Verbatim : "
            "${transcript}. Synthèse hiérarchique : ${summary}. Lisez uniquement la synthèse pour "
            "répondre ; ne chargez pas le verbatim complet dans le contexte."
        ),
        "youtube_transcribed": (
            "Sous-titres YouTube récupérés (${caption_language}, ${size} caractères) : "
            "${location}. "
            "Lisez ce transcript pour répondre à la demande."
        ),
        "youtube_long_processing": (
            "⏳ Vidéo YouTube longue détectée (${duration}). J’ai récupéré ses sous-titres et "
            "je les traite en ${chunks} segments d’environ ${minutes} minutes avant de produire "
            "une synthèse globale."
        ),
        "youtube_long_transcribed": (
            "Sous-titres YouTube récupérés : ${chunks} segments, ${size} caractères, langue "
            "${caption_language}. Transcript horodaté : ${transcript}. Synthèse hiérarchique : "
            "${summary}. Lisez uniquement la synthèse pour répondre ; ne chargez pas le "
            "transcript complet dans le contexte."
        ),
        "youtube_invalid_url": (
            "URL YouTube invalide. Utilisez une URL HTTPS de vidéo watch, youtu.be, shorts, "
            "live ou embed."
        ),
        "youtube_captions_unavailable": (
            "Aucun sous-titre manuel ou automatique n’est disponible pour cette vidéo YouTube."
        ),
        "youtube_video_unavailable": (
            "Cette vidéo YouTube est indisponible, privée, restreinte ou nécessite une "
            "autorisation supplémentaire."
        ),
        "youtube_access_blocked": (
            "YouTube bloque actuellement l’accès aux sous-titres depuis ce serveur. Réessayez "
            "plus tard ou vérifiez l’adresse réseau utilisée par Galaris."
        ),
        "youtube_fetch_failed": (
            "Impossible de récupérer les sous-titres YouTube pour le moment."
        ),
        "transcription_failed": "Échec de la transcription audio : ${error}",
    },
}
