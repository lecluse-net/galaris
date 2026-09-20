# 0072 — Outils multimédias spécialisés et générations persistantes

Statut : accepté — 2026-09-06

## Décision

`app.multimedia` possède un Tool intégré et cinq opérations : `audio_read`, `video_read`,
`sound_generate`, `music_generate`, `video_generate`. La voix, la transcription, les images
et le texte conservent leurs usages et Tools existants. Les connexions Multimedia sont
créées par les datasets Tools et laissées inactives, y compris pour les nouveaux agents.

Le profil effectif fournit les cinq ressources. Une ressource doit avoir la bonne capacité,
un fournisseur actif, une clé et un adaptateur compatible. Le catalogue MCP est filtré à
chaque interrogation ; l'exécution revérifie les droits et la configuration. Les anciennes
ressources de chat avec entrée audio/vidéo restent compatibles avec la compréhension.

Les bridges implémentent les contrats publics du domaine LLM. OpenRouter couvre la compréhension,
Lyria et les modèles vidéo ; ElevenLabs fournit Eleven Music et les effets sonores ; BytePlus
fournit Seedance ; SunoAPI.org est explicitement un intermédiaire distinct de Suno Platform.
Les ressources peuvent être des modèles ou des services : `sound:V5` distingue le service
de bruitages SunoAPI de son moteur musical `V5`, comme les voix ElevenLabs sont distinctes
de leur moteur de synthèse. Aucun endpoint officiel Suno n'est supposé.

La génération utilise `app.process`, sans workflow n8n. Le Process fige le modèle, le fournisseur,
l'opération et la destination. Une clé d'invocation explicite déduplique les retries ; deux
commandes identiques sans cette clé produisent deux générations. Une réclamation persistante
et atomique précède toute soumission facturable : une réponse perdue ne provoque pas de resoumission.

Le callback SunoAPI accuse réception avec un secret propre au run. Il ne consomme ni le statut
ni les URL reçus : le polling authentifié fait autorité. Les refus explicites et les résultats
inconnus restent distincts. Un fournisseur dont le modèle ou la connexion a changé ne peut pas
être remplacé silencieusement pour un run existant.

Les sorties transitent par des reçus privés PostgreSQL, bornés à quatre fichiers de 100 Mo.
Ces octets ne constituent pas un nouveau stockage adressable par les agents. Ils sont effacés
après création du fichier dans sa destination canonique via `app.file_share`. Le Process devient
`success` après réception des URI finales. Une interruption pendant une création distante laisse
un état `unknown` à vérifier, sans création répétée aveuglément. Les reçus suivent la rétention
du Process par clé étrangère avec suppression en cascade.

Les analyses matérialisent temporairement les URI, avec une limite de 32 Mo et 20 minutes.
FFprobe vérifie le type de piste et la durée ; les données binaires et URL temporaires ne sont
pas ajoutées aux traces LLM. Les coûts absents des réponses sont indiqués comme inconnus dans
les résultats, sans tarif inventé.

## Validation et limites

Les tests couvrent le catalogue MCP dynamique, les refus après reconfiguration, l'activation
préservée, les reprises, la livraison, les identités d'invocation et les contrats fournisseurs
avec transports simulés. L'accès commercial et les générations facturées nécessitent les clés
de l'installation. Les annulations distantes ne sont pas annoncées tant que leur confirmation
n'est pas implémentée. La création de personas, les références multimodales de génération,
les remixes et les plans de composition ElevenLabs restent des extensions distinctes.
