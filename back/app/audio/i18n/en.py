"""English audio-processing messages."""

default: dict[str, object] = {
    "audio": {
        "transcribed": "Transcript written (${size} characters): ${location}",
        "long_processing": (
            "⏳ Long recording detected (${duration}). I am processing it as ${chunks} segments "
            "of about ${minutes} minutes, then I will produce an overall synthesis. This may "
            "take a little while."
        ),
        "long_transcribed": (
            "Long transcription completed: ${chunks} segments, ${size} characters. Verbatim: "
            "${transcript}. Hierarchical synthesis: ${summary}. Read only the synthesis when "
            "answering; do not load the complete verbatim into context."
        ),
        "youtube_transcribed": (
            "YouTube captions retrieved (${caption_language}, ${size} characters): ${location}. "
            "Read this transcript to answer the request."
        ),
        "youtube_long_processing": (
            "⏳ Long YouTube video detected (${duration}). I retrieved its captions and am "
            "processing them as ${chunks} segments of about ${minutes} minutes before producing "
            "an overall synthesis."
        ),
        "youtube_long_transcribed": (
            "YouTube captions retrieved: ${chunks} segments, ${size} characters, language "
            "${caption_language}. Timestamped transcript: ${transcript}. Hierarchical synthesis: "
            "${summary}. Read only the synthesis when answering; do not load the complete "
            "transcript into context."
        ),
        "youtube_invalid_url": (
            "Invalid YouTube URL. Use an HTTPS watch, youtu.be, shorts, live, or embed video URL."
        ),
        "youtube_captions_unavailable": (
            "No manual or automatically generated captions are available for this YouTube video."
        ),
        "youtube_video_unavailable": (
            "This YouTube video is unavailable, private, restricted, or requires additional "
            "authorization."
        ),
        "youtube_access_blocked": (
            "YouTube is currently blocking caption access from this server. Try again later or "
            "check the network address used by Galaris."
        ),
        "youtube_fetch_failed": "YouTube captions could not be retrieved at this time.",
        "transcription_failed": "Audio transcription failed: ${error}",
    },
}
