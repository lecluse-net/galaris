# 0087 — Activité partagée des tâches et provenance consultable

Date : 11 septembre 2026. Statut : accepté pour le lot d’activité demandé.

## Décision

`app.task` projette l’état opérationnel, la dernière tentative et l’activité du run dans
un même contrat `TaskActivitySnapshot`. `POST /tasks/activity` lit jusqu’à 50 tâches par
requête et applique le périmètre de gestion des agents. `task_get` réutilise cette projection
et conserve ses diagnostics détaillés en cas d’échec.

`TaskAttempt.data.live_activity` contient un checkpoint visuel cumulatif : au plus 40 messages,
4 000 caractères par contenu, sans prompts, arguments ou résultats structurés d’outils.
Une session indépendante écrit uniquement cette clé JSONB, au premier événement, au plus
une fois par seconde ensuite, puis au terminal. Les checkpoints de reprise des effets et
les reçus restent propriétaires de leurs domaines. Un arrêt brutal peut perdre la dernière
seconde d’activité visuelle ; cette projection ne décide jamais de rejouer un effet.

Le chat et la fiche tâche partagent les références d’abonnement aux rooms actives. L’ouverture,
la reconnexion, les changements durables et un rafraîchissement de secours toutes les 15 secondes
réhydratent la projection. Les événements reçus pendant la lecture sont rejoués après le snapshot,
par run, tentative et séquence. Une reprise peut conserver le run : sa nouvelle tentative
possède une séquence indépendante et rejette les événements tardifs de la précédente.
Fermer une vue ne coupe pas l’autre ; une tâche terminale quitte sa room.

### Présentation des messages (18 septembre 2026)

Le streaming de texte reste réservé à l'affichage des conversations. Les aperçus et fiches
Task affichent un bloc de texte ou de réflexion lorsque `AIMessage.stream_complete` devient
vrai. Le harnais interne signale cette clôture à `PartEndEvent`, sans répéter le contenu.
Les fragments continuent de traverser les gardes et checkpoints internes ; ils ne sont pas
affichés progressivement dans les Tasks. Les états et opérations d'outils restent visibles
au fil de l'exécution.

Pour les drivers historiques sans ce marqueur, une opération d'outil ou de média ultérieure
permet d'afficher la narration précédente ; le bloc final attend le résultat terminal de
la tâche. La présentation par appels LLM attend `completed_at` pour leur texte/réflexion.
Un résultat Task terminal restitue aussi les blocs interrompus, utiles au diagnostic.

Pour un harnais OpenAI Messages personnalisé, `settings.streams_ai_messages` est un booléen
strict, vrai par défaut, figé dans la cible du run. Les harnais intégrés imposent vrai. Faux
sélectionne exclusivement la présentation existante des appels LLM corrélés au run et à la tâche.
Le chargement est borné aux 500 appels les plus récents d’un lot de 50 tâches, avec une indication
visible lorsque cette limite est atteinte. Les mises à jour et suppressions reconstruisent les
groupes ; les appels auxiliaires restent exclus. Résultat, coût et succès terminaux restent
ceux de la tâche. Aucun événement ne peut être publié après un résultat terminal validé.

La demande initiale des nouvelles tâches est conservée sous `_original_demand` à l’admission,
avant les amendements. Elle ne peut pas être fournie par le client comme preuve de provenance.
Les tâches historiques sans cette clé n’inventent pas de demande initiale. La fiche expose
les liens de provenance et les ressources/reçus existants, sans leurs métadonnées arbitraires.

## Limite de portée

Ce lot rend les états et les preuves existantes observables. Il ne réalise pas le préflight
générique des cibles et effets conçu dans le plan de provenance. Les contrôles RBAC, la politique
de livraison et les protections de reprise existants continuent à faire autorité.
