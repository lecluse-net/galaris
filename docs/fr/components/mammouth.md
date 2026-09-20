<p align="right"><strong>Français</strong> · <a href="../../en/components/mammouth.md">English</a></p>

# Mammouth AI

Le fournisseur `mammouth` relie Galaris à l'API publique de Mammouth AI. Le bridge
`back/bridge/mammouth` réutilise les façades LLM, Image et Multimédia ; il ne crée
pas de second système d'agents ni de gestion des fichiers.

## Configuration

1. Ajouter **Mammouth AI** dans les fournisseurs LLM.
2. Renseigner une clé depuis les [paramètres API Mammouth](https://mammouth.ai/app/account/settings/api).
   L'URL par défaut est `https://api.mammouth.ai/v1`.
3. Tester la connexion puis importer les modèles par capacité. Ce test vérifie la clé
   par une lecture authentifiée, sans génération ; il ne garantit pas un solde suffisant.
4. Affecter les modèles aux usages du profil LLM. Pour `audio_read` et `video_read`,
   utiliser la section **Multimédia**, puis activer la connexion Multimedia de l'agent.

Les connexions Multimedia sont créées automatiquement et désactivées par défaut.
Leurs fonctions ne sont exposées que si le profil possède une ressource compatible
et que le fournisseur et la connexion sont actifs. Voir [Multimédia](multimedia.md).
Les crédits API sont distincts des quotas de l'application Mammouth ; le fournisseur
ne déclare donc pas ses appels gratuits ou couverts sans limite par un abonnement.

## Couverture de l'API

Analyse effectuée le 6 septembre 2026 à partir du [guide API](https://info.mammouth.ai/docs/api-quick-start/),
du [schéma OpenAPI publié](https://api.mammouth.ai/openapi.json) et du catalogue public
accessible sans clé. Ce dernier contenait 93 modèles lors de la vérification ; aucune
liste de ces 93 identifiants n'est figée dans Galaris.

| Capacité | Façade Galaris | Contrat Mammouth |
|---|---|---|
| Texte, code, streaming, appels d'outils, sorties structurées | LLM / agents | Chat Completions et Responses ; options selon le modèle |
| Raisonnement, contexte et tarifs | Catalogue / profils LLM | Métadonnées par modèle ; aucune capacité supposée sur les valeurs absentes |
| Vision | Lecture d'image existante | Modèles déclarant `supports_vision` |
| Génération d'images, avec références si le modèle les accepte | Image | Chat Completions ; sortie `message.images[].image_url.url` en base64 |
| Embeddings | Façade embeddings | `/v1/embeddings` ; catalogue dédié par capacité |
| Analyse de sons et musique | Multimedia `audio_read` | Entrée `input_audio`, WAV ou MP3 ; `supports_audio_input` doit être vrai |
| Analyse vidéo | Multimedia `video_read` | Entrée `video_url` ; `supports_video_input` doit être vrai |
| Sélection automatique du modèle | Preset `mammouth-recommended` | L'alias est transmis tel quel ; Mammouth choisit le modèle sous-jacent |

Les dimensions d'image sont exprimées comme une préférence dans le prompt. Le bridge
ne promet pas une taille exacte et n'envoie pas de paramètres Images API non publiés.
Responses utilise l'historique explicite avec `store=false`, sans réinjecter les
identifiants de raisonnement d'un modèle dans un autre ; la compaction passe par le
contrat Responses existant. Les opérations distantes de stockage, consultation ou
annulation des réponses ne remplacent pas les tâches persistées par Galaris.

## Catalogue et facturation

`/public/models` fournit les identifiants appelables et les prix publics ;
`/public/model/info` complète les modalités et capacités. La jointure porte sur
`id` / `model_name`, jamais sur les hashes de déploiement ni les routes internes.
Les deux réponses sont bornées ; les erreurs ne sont pas remplacées par un catalogue
inventé. Une lecture protégée de `/v1/models/{model_id}` valide la clé séparément.

Les prix par token sont convertis en prix par million pour Galaris ; les prix absents
restent inconnus et un zéro explicite est conservé. Les tarifs publics sont des plafonds,
pas une mesure exacte du débit facturé. Les appels LLM et Image utilisent la comptabilité
existante ; l'analyse multimédia ne déclare aucun coût exact absent de sa réponse contractuelle.

## Fonctions propres à l'application Mammouth

L'[application Mammouth](https://info.mammouth.ai/docs/introduction-to-mammouth/) propose
aussi musique Lyria, vidéos, dictée, conversation vocale, synthèse vocale, assistants
personnalisés, comparaison de réponses et connecteurs MCP. Le schéma public inspecté
ne fournit pas les contrats nécessaires pour leurs services dédiés de génération
musicale, de bruitages, de vidéo, de transcription, de synthèse ou de voix temps réel.
Ils ne sont donc pas annoncés dans le fournisseur Galaris. Un indicateur générique
`supports_audio_output` ne suffit pas à inventer un service de voix ou de musique.

La recherche web déclarée par certains modèles reste une propriété de ces modèles ;
elle ne donne pas accès au mode agentique ni aux connecteurs de l'application Mammouth.
Leurs MCP sont des connexions entrantes de leur application, pas un serveur public à
ajouter automatiquement dans Galaris. Mammouth Code est également un produit distinct.
Le suivi de crédit `/key/info` n'est pas intégré : l'exemple du guide vise une adresse
locale et cet endpoint n'apparaît pas dans le schéma public inspecté.

## Validation

Les tests couvrent l'import dynamique, les aliases, les unités de prix, les clés refusées,
les formats image/audio/vidéo, les sorties invalides, les limites de réponse et l'exclusion
des fonctions non exposées. Le catalogue réel a été consulté sans authentification.
Les inférences payantes nécessitent une clé et des crédits ; les tests de contrat utilisent
un transport HTTP simulé et ne constituent pas une validation de tous les modèles en production.
