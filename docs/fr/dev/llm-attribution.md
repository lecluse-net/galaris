<p align="right"><strong>Français</strong> · <a href="../../en/dev/llm-attribution.md">English</a></p>

# Attribution des appels LLM par utilisateur

`llm_calls.user_id` désigne le compte Galaris auquel imputer un appel physique. C’est une
clé étrangère facultative vers `users.id`. La suppression physique du compte remet la colonne
à `NULL`. `requester_user_id` garde sa sémantique de demandeur pour les contrats d’exécution
existants. L’attribution budgétaire ne confère aucun droit sur l’appel ni sur sa source.

Le gateway fixe l’attribution avant le départ de l’appel, dans la transaction qui enregistre la
trace. Le tableau se lit de haut en bas. Une preuve trouvée sur une ligne prioritaire l’emporte
sur celle d’un opérateur ou d’un agent qui intervient plus tard. Certaines sources, comme un
round partagé, déterminent explicitement une attribution vide.

| Provenance ou lien disponible | Compte imputé et traitement des cas incomplets |
|---|---|
| Campagne Lab, candidats et juges | Le compte qui a créé le run Lab. Si un agent a lancé l’évaluation depuis une tâche, la tâche d’origine est prise en compte. Le jeu d’évaluation peut utiliser des données d’autres utilisateurs sans leur imputer l’expérience. |
| Processus et sous-processus, notamment `process.exec` et les tâches d’activité | Le demandeur du run racine prime, suivi du demandeur du run courant. Si les deux sont absents, la tâche, le round ou le message peuvent fournir une attribution. Une exécution automatique sans provenance humaine établie reste vide. |
| Tâche, délégation, réflexion Dream sur une tâche et suivi de Goal | Le demandeur de la tâche racine prime. Le parcours remonte `parent_id`, puis `source_task_id` quand le parent est absent. Sans demandeur racine, il utilise le premier demandeur connu en partant de la tâche de l’appel. Le demandeur du Goal de la tâche sert ensuite de repli. |
| Conversation Deep | Le demandeur inscrit sur la session Deep. |
| Chat, messagerie, réponse vocale et préparation conversationnelle, y compris le dispatcher | Le demandeur du round associé, directement ou via la tâche. Un round peut avoir plusieurs entrées. Galaris laisse son demandeur vide quand ces entrées n’ont pas la même identité. La présence du round suffit alors à conserver l’imputation vide. |
| Transcription vocale par lot avant le round | Le demandeur de la session vocale transmise à la transcription. Une session sans compte humain unique reste sans attribution. |
| Classification Dream et découverte de contacts, ou transcription d’une pièce jointe de messagerie | La source durable l’emporte. Un message entrant fournit son `requester_user_id`, figé à l’admission à partir d’un compte lié. Un message sans compte lié reste sans attribution. Un en-tête mail `From` ne suffit pas. |
| Entretien autonome Dream ou contacts | Quand le reçu ou le travail de découverte renvoie à une tâche, un processus, un round ou un message, les règles précédentes s’appliquent. Un entretien de mémoire, un rapprochement de contacts ou un résumé automatique de ressource sans demandeur identifiable reste vide. |
| API LLM directe, dictée personnelle, opérations ponctuelles Lab, analyse de documents, image, résumés audio et multimédia | En l’absence d’une source prioritaire, le compte authentifié prime, suivi du demandeur enregistré par l’inférence, de celui porté par l’appel, puis de l’identité conservée par la génération multimédia. |
| Travail système, lien supprimé ou provenance devenue insuffisante | `NULL` en l’absence de preuve exploitable. Le responsable actuel de l’agent et le propriétaire de la ressource ne servent jamais de repli. |

L’implémentation partage la même projection entre l’admission et l’[action DbAdmin](dbadmin.md).
L’ajout de la colonne déclenche une reprise par lots, après le transfert éventuel des anciens
coûts. Elle traite aussi les traces archivées et préserve les attributions existantes.
L’historique utilise les liens encore disponibles. Une ancienne transcription vocale ou
Messenger sans lien enregistré peut ainsi rester vide. Le champ `correlation_ref` fourni
par un client d’inférence autonome ne constitue pas une preuve d’identité.

Pour un budget, agréger par `user_id` et par période de `started_at`. Compter chaque
`llm_calls.id` une fois, y compris les appels archivés et les tentatives ayant consommé
du budget avant un échec. `cost` mesure le montant facturé. `inference_cost` conserve la
valeur d’inférence, y compris sous abonnement. Les rapports doivent garder visibles les coûts
inconnus et la part sans attribution. Les appels fournisseur effectués en dehors de
`llm_calls` restent hors de ce périmètre.
