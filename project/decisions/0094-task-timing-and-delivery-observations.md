# 0094 — Mesures des tâches et preuves de livraison

Date : 13 septembre 2026. Statut : accepté pour les corrections demandées.

## Décision

Les dates d’audit basées sur PostgreSQL `now()` désignent le début de transaction. Elles ne
doivent pas servir à calculer une attente du scheduler après une préparation longue effectuée
dans cette transaction. La conversation observe sa préparation et son admission ; toutes les
insertions ORM de tâches observent leur mise en file avant commit. La première prise en charge
est horodatée explicitement dans la tentative. L’intervalle admission–claim borne l’attente,
car il inclut la persistance et les éventuelles pauses.

`Task.lifecycle_timing`, JSONB nullable administré par DbAdmin, conserve les cumuls par état et
phase ainsi que leur début d’observation. Ce champ séparé préserve la sémantique de `Task.data`
et reste absent des commandes clients. Les observations suivent les changements persistés de
phase, bail, pause et backoff ; elles ne pilotent pas les transitions. Les traitements sous bail
incluent les pauses en attente de libération. Un backoff expiré redevient de l’attente en file.

La projection récupère les heures de traitement des tâches historiques depuis les appels LLM
conservés. La préparation antérieure à l’existence d’une tâche est attribuée uniquement si le
round ne possède qu’une tâche distincte. Aucune date de commit historique n’est inventée.

Les détails Task et Conversation projettent aussi la première sortie utile depuis le journal
LLM : texte non vide ou appel d'outil, hors raisonnement et décisions internes. La mesure
part du premier appel ; une Task expose également les délais depuis l'admission et la
première prise en charge lorsque ces dates existent. L'union des intervalles d'appels avant
la sortie évite de compter deux fois les appels simultanés. Les temps entre appels restent
non attribués, sans être présentés comme du temps scheduler ou réseau. Une fin d'appel
manquante rend cette décomposition inconnue. Une absence de journal reste « non mesuré » ;
`first_token_at` et les dates d'audit ne remplacent jamais cette preuve.
Ce sont des observations serveur, pas une mesure de rendu ou un reçu de livraison.
Les lectures utilisent les identifiants autorisés et ne chargent ni prompts ni contenus.

Le transport de fichiers Messenger enregistre un reçu serveur au retour d’un upload réussi
dans le contexte de la tâche. Il porte l’URI, le message, la connexion et la salle observés.
La notification finale reconnaît cette livraison, y compris lorsque l’outil spécialisé n’a
pas produit d’entrée de fichier dans le Working Set. Ce reçu ne bloque pas un nouvel envoi
explicitement demandé. Un reçu ne constitue pas une garantie atomique entre réseau et base.

Le résultat du dispatcher reprend le coût des appels effectivement persistés, même si le
parsing de sortie échoue. Une portée asynchrone collecte les mises à jour par identifiant
d’appel ; elle ne remplace pas `llm_calls` comme comptabilité durable et ne recompte pas les
mises à jour ou les finalisations répétées. Les abonnements conservent un coût facturé nul.

Les quatre façades d’inférence (`run_structured`, `run_prompted`, `run_text` et
`run_text_with_tools`) reprennent également ces coûts pour leurs résultats réussis. Les coûts
de préparation, briefing, planification et autres consommateurs n’utilisent donc plus une
estimation locale lorsque la passerelle possède déjà une valeur persistée. Le repli estimé
reste réservé aux exécutions sans appel de passerelle, notamment les modèles de test.
