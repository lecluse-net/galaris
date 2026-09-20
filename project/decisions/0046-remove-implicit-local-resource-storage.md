# ADR 0046 — Suppression du stockage local implicite des ressources

- Statut : Accepted
- Date : 2026-08-23
- Remplace : la partie « stockage local du runtime » de l'ADR 0033

## Contexte

Le schéma `workspace://` donnait au modèle l'impression qu'un stockage local générique existait
pour chaque runtime. En pratique, certains drivers ne l'implémentaient pas, les chemins relatifs
étaient convertis sans propriétaire explicite et les pièces jointes Messenger pouvaient perdre le
schéma du Tool qui permettait réellement de les relire. Ajouter des instructions aux prompts ne
rendait pas cette ressource plus accessible.

## Décision

`workspace://` est retiré de la façade `app.file_share`. Son nom reste réservé afin qu'aucun Tool
externe ne puisse le réutiliser. Le parseur refuse ce schéma ainsi que tout chemin relatif : chaque
référence échangée doit nommer explicitement son provider.

`console://` est l'unique système de fichiers local visible, uniquement lorsqu'une console est
attachée au run. Sans console, `file_schemes` n'annonce aucun stockage local, `file_list` sans URI
échoue et les outils producteurs exigent une destination writable explicite. L'agent travaille
alors directement avec les URI du Messenger courant ou des Tools compatibles file-share.

Une pièce jointe entrante conserve toujours la forme
`<tool.code>://<room-locator-provider>/<attachment-uuid-local>`. Lorsqu'un modèle ou une
bibliothèque exige les octets, le serveur matérialise un fichier temporaire borné, le nettoie après
l'appel et ne l'expose ni comme URI, ni dans le Working Set. `file_copy` reste une création
persistante explicite chez un provider choisi.

Les sorties d'outils et les effets de Task ne créent plus le type `workspace_file`. Une ressource
fichier est un artefact identifié par son URI provider exacte. Les anciennes références
persistées peuvent rester dans l'historique, mais elles ne sont plus résolues, projetées comme
livrables ni réinjectées comme ressources actives.

Le transport local privé et le protocole optionnel qui l’exposait aux drivers sont supprimés.
Les contrats génériques de transports utilisent désormais le vocabulaire des fichiers/providers,
la capacité d’exposition s’appelle `file_tools`, et les capacités de gestion des Harness nomment
leurs fichiers internes `runtime_files`. Les répertoires de calcul propres aux SDK restent des
détails de runtime et ne deviennent jamais des providers `file_share`.

## Conséquences

- Les petits modèles ne peuvent plus sélectionner un stockage fictif ou omettre le provider.
- Une pièce jointe est immédiatement réutilisable avec `file_read`, un outil spécialisé ou
  `file_copy`, sans téléchargement local préalable.
- Image et audio peuvent omettre leur destination seulement avec une console active.
- Les matérialisations temporaires sont une implémentation serveur éphémère, pas un espace de
  travail agentique.
- Une URI historique `workspace://` échoue explicitement et ne peut pas être recréée par une
  connexion externe.
