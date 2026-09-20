# 0070 — Dimensions natives des images générées

Statut : accepté — 2026-09-05

## Décision

`image_generate` accepte `width` et `height` en pixels, fournis ensemble. Ces dimensions
pilotent la génération native. Aucun recadrage, redimensionnement ou réencodage ne peut
servir à satisfaire la demande. Une taille non prise en charge échoue explicitement.

`app.image` conserve la matérialisation des références et l'écriture du résultat via
`app.file_share`. Pour une taille explicite, il appelle la façade publique
`app.llm.generate_image_native`, qui sélectionne le modèle configuré, contrôle le fournisseur
et l'autorité d'abonnement, puis journalise l'appel et son usage.

Le port `ImageGenerationProvider` de `app.llm.provider_facade` est enregistré par les bridges.
Chaque bridge possède le protocole, l'authentification HTTP, les restrictions de dimensions
et la lecture de la réponse de son fournisseur :

- OpenAI : `size` dans Images API, JSON pour la génération et multipart pour l'édition ;
- OpenRouter : `size` dans l'API `/images`, références conservées dans `input_references` ;
- Gemini : correspondance exacte avec les dimensions documentées de `imageConfig` ;
- Fireworks : `width`/`height` pour les modèles synchrones dont ce contrat est connu.

Une connexion personnalisée sans profil catalogue utilise le protocole Images compatible
OpenAI. Un fournisseur catalogue sans adaptateur explicite est refusé. Les connexions
historiques sont résolues par les URL du catalogue, sans supposer que tout endpoint compatible
Chat possède le même protocole d'image.

La façade vérifie les dimensions de l'image reçue. Si elles diffèrent, l'appel est marqué
en erreur en conservant l'usage facturé, aucune nouvelle génération n'est déclenchée et la
destination reste intacte. En cas de succès, les octets originaux sont rendus sans modification.
Sans dimensions explicites, le chemin de génération existant conserve les valeurs par défaut.

## Références

- [OpenAI Images](https://developers.openai.com/api/docs/guides/image-generation)
- [OpenRouter Images](https://openrouter.ai/docs/guides/overview/multimodal/image-generation)
- [Gemini : dimensions et résolutions](https://ai.google.dev/gemini-api/docs/generate-content/image-generation)
- [Fireworks : dimensions explicites](https://docs.fireworks.ai/faq-new/models-inference/how-do-i-control-output-image-sizes-when-using-sdxl-controlnet)

Les contraintes des modèles peuvent évoluer ; les adaptations et leurs tests restent dans
les bridges. La limite applicative est de 8192 pixels par côté et 33 554 432 pixels au total.
