"""French Dream strings used in generated memory documents."""

default = {
    "dream": {
        "experience": {
            "title_prefix": "Expérience",
            "title_separator": " : ",
            "situation": "Situation",
            "recommendation": "Recommandation",
            "avoid_action": "Action à éviter",
            "applicability": "Applicabilité",
            "observed_result": "Résultat observé",
        },
        "topic_approval": {
            "title": "Autorisation de créer un sujet",
            "body": (
                "Je propose de créer un nouveau sujet : **${title}**.\n\n"
                "${description}\n\nMots-clés : ${keywords}"
            ),
            "create_option": "Créer ce nouveau sujet",
            "reuse_option": "Rattacher au sujet « ${title} »",
            "reject_option": "Ne pas classer cette activité",
            "no_description": "Aucune description proposée.",
            "no_keywords": "aucun",
        },
    }
}
