# 0085 — Profils LLM personnels et voix des éditeurs enrichis

Statut : accepté. Date : 11 septembre 2026.

`app.llm` possède les préférences personnelles `user_llm_preferences` : une ligne par
utilisateur, une référence facultative vers un profil LLM et une référence facultative vers
une ressource vocale (`voice_llm_id`), son mode (`voice_mode`, TTS par défaut) et son code natif
facultatif (`voice_code`). Les deux nouvelles colonnes conservent les choix TTS existants.
`core.user` reste indépendant des domaines applicatifs.
Comme pour les agents, une sélection de profil vide suit le profil courant ; un profil
explicitement choisi ne mélange jamais ses modèles avec ceux du profil courant. La voix TTS
est indépendante du profil. Le même choix inclut les voix natives des modèles temps réel ;
la lecture documentaire reste une synthèse TTS. La suppression d’un profil ou d’une ressource
nettoie les références.

Les endpoints `/llm/me/preferences` et `/llm/me/options` sont accessibles aux utilisateurs
authentifiés. Ils n’acceptent aucun identifiant utilisateur fourni par le client et ne donnent
aucun droit de modifier les profils partagés ni les fournisseurs. Le catalogue expose seulement
les identifiants et libellés nécessaires aux sélections.

Le formulaire d’un utilisateur expose l’onglet **Modèles**, et **Mon profil** expose le même
composant en libre-service. Les contributions `userTab.ts` et `profile.ts` permettent cette
composition sans import applicatif dans `core`. Le bouton documentaire et la page autonome
de réglages sont retirés. L’API `/llm/users/{user_id}/preferences` exige `UPDATE_USER` pour
écrire, `READ_USER` ou `UPDATE_USER` pour lire, et vérifie l’existence de la cible. Les endpoints
`me` restent accessibles à chaque utilisateur pour son propre compte.

La dictée exige une session authentifiée, utilise le modèle de transcription du profil de l’utilisateur
connecté et insère le texte au curseur pendant l’enregistrement, via une commande du groupe
Lecture, dans les modes simple et complet. Ce groupe réunit les deux commandes vocales, la
source et le plein écran ; la pleine largeur reste réservée à l’affichage en page. Les
commandes Imprimer, PDF et ZIP sont dans Édition. Toutes les deux secondes,
un instantané audio cumulatif conserve l’en-tête du
conteneur ; les requêtes sont séquentielles et les instantanés intermédiaires sont regroupés
si le fournisseur est occupé. Seul le texte nouvellement reconnu est inséré. L’arrêt termine
la dernière transcription, sans étape de validation. Le navigateur borne la capture à
cinq minutes et 20 Mio ; l’API borne les octets reçus. L’insertion reste une édition HTML
ordinaire, échappée, annulable et soumise au contrôle d’écriture du domaine lors de la sauvegarde.
Elle est masquée en lecture seule.

La lecture exige une session authentifiée, sans privilège documentaire. Ces deux services
personnels n’accordent aucun accès aux données d’un domaine et restent utilisables dans
les champs Agent, Task, Goal et Memory, comme dans les documents.
Le client transmet un instantané HTML de la sélection CKEditor, ou du document entier si la
sélection est réduite au curseur. Cet instantané reste identique pendant toute la lecture,
y compris après une pause ou un changement de sélection. L’API ne charge aucun document par
identifiant. L’extracteur éditorial canonique produit le texte brut, sans scripts ni attributs
de présentation, en conservant les retours à la ligne des blocs et sauts explicites. Pour la
synthèse vocale, les tabulations séparant les cellules deviennent aussi des retours à la ligne.
Des morceaux de 2 000 caractères
au maximum sont synthétisés successivement, sans troncature du texte. Le bouton de lecture
démarre ou met en pause/reprend la restitution sans ouvrir de menu. Sa flèche indépendante
ouvre le menu Pause/Reprendre et Arrêter, sans démarrer la lecture ; la pause conserve la position audio, y compris
quand elle est demandée pendant la synthèse. L’éditeur reçoit les commandes vocales par un
contrat générique de `core.util`, sans dépendance applicative. Arrêter la lecture ou
remplacer le contenu externe ou fermer l’éditeur annule les requêtes et libère l’audio côté navigateur. Une requête déjà
transmise au fournisseur peut néanmoins avoir été exécutée.

Revue de dépendance : `RichTextEditor` utilise le port public `EditorVoiceProvider` de
`core.util`. La contribution `app/llm/editorVoice.ts`, découverte parmi les modules actifs,
instancie une session audio propre à chaque éditeur. Le raccordement particulier
`app/memory → app/llm` et le composant `DocumentVoiceControls` sont supprimés. Le cœur ne fait
aucun import statique applicatif ; aucun nouveau cycle n’est introduit. La contribution
de formulaire ajoute l’import public `app/llm → core/user` pour son contrat de contribution ;
cette dépendance de type reste conforme aux couches et n’introduit pas de cycle.

Validation : `test_personal_speech.py` couvre persistance, isolation, suppression, extraction,
découpage, sélection du fournisseur et refus HTTP ; `document-voice.spec.mjs` couvre les
préférences, la capture réelle sur microphone simulé, l’insertion et les annulations.
