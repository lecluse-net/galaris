"""English Dream strings used in generated memory documents."""

default = {
    "dream": {
        "experience": {
            "title_prefix": "Experience",
            "title_separator": ": ",
            "situation": "Situation",
            "recommendation": "Recommendation",
            "avoid_action": "Action to avoid",
            "applicability": "Applicability",
            "observed_result": "Observed result",
        },
        "topic_approval": {
            "title": "Approval to create a thematic dossier",
            "body": (
                "I propose creating a new thematic dossier: **${title}**.\n\n"
                "${description}\n\nKeywords: ${keywords}"
            ),
            "create_option": "Create this new dossier",
            "reuse_option": "Attach to the “${title}” dossier",
            "reject_option": "Leave this activity unclassified",
            "no_description": "No description was proposed.",
            "no_keywords": "none",
        },
    }
}
