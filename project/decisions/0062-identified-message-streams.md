# ADR 0062 — Streaming des messages identifiés d'un AIResult

- Statut : Accepted
- Date : 2026-09-05

## Contexte

Le texte, la réflexion, les événements conversationnels et l'audio ne conservaient pas
tous les mêmes unités de streaming. Une projection finale pouvait remplacer une trace
partielle plus riche ; les moteurs vocaux consommaient les deltas pour parler sans les
publier dans Chat. La séquence recommençait aussi à zéro lors d'une nouvelle tentative
du même round sans permettre au client de distinguer les tentatives.

## Décision

La structure reste `AIResult.messages: list[AIMessage]`. Le champ existant `stream_id`
identifie un message sémantique au sein du résultat. Un événement de message transporte
un delta à ajouter à ce message (`stream_mode="delta"`, valeur par défaut), ou un bloc
cumulatif à remplacer (`stream_mode="snapshot"`). Un résultat terminal ou HTTP transporte
des messages cumulatifs, à fusionner par identité sans concaténer une seconde fois leur contenu.
Hermès utilise le mode snapshot pour réconcilier ses événements live avec ses checkpoints
déjà persistés, y compris pour le texte et les réflexions. Le garde-fou de répétition observe
uniquement le suffixe nouveau d'un snapshot identifié.

Le harnais interne attribue une identité à chaque partie texte ou réflexion et aux
résultats d'outils. Les fragments de réflexion sont publiés dès leur réception. La fin
d'une partie ne répète pas son contenu cumulatif. Les indices de parties réutilisés par
un nouvel appel LLM reçoivent de nouvelles identités. Le regroupement temporel du texte
conserve ces identités et ne fusionne pas deux messages distincts.

`ConversationRuntimeStream` possède l'accumulation et la publication ordonnée du résultat
conversationnel. Le scheduler texte et les deux moteurs vocaux utilisent cette même
projection. Le terminal conserve les messages techniques déjà observés lorsqu'un
producteur omet sa trace ; les moteurs vocaux la persistent avec leur round. Les règles
de confidentialité des événements publics restent celles de `public_ai_message` et
`public_ai_result`.

Les événements portent le numéro de tentative du round et leur séquence au sein de cette
tentative. Le client ignore les anciennes tentatives, les doublons et les événements
suivant une fin déjà reçue. Il conserve la réflexion lors d'une nouvelle tentative.

Un snapshot versionné du résultat actif est aussi disponible dans la page d'activité
de la room, sous les mêmes autorisations que son historique. Le client le récupère à
la reconnexion et lorsqu'une séquence de deltas manque. Il remplace les contenus
cumulatifs par identité ; un ancien snapshot ne rouvre pas un résultat terminé.

La publication ne bloque pas la génération : lorsqu'un listener prend du retard,
le runtime conserve un indicateur de modification et publie ensuite le dernier
snapshot cumulatif. Il n'accumule pas une file de fragments. Chaque listener possède
un délai maximal de deux secondes ; une perte de notification se répare par HTTP.
La fin attend la publication en cours avant son événement terminal.

## Conséquences et limites

- La réflexion et la réponse conservent des identités stables du direct au résultat final.
- Les réponses aux tours audio sont visibles dans Chat pendant leur génération.
- Les traces historiques sans `stream_id` restent lisibles avec une fusion de compatibilité.
- Aucun changement de schéma SQL n'est requis ; les résultats restent du JSON existant.
- Le snapshot actif reste local au processus et disparaît à la fin du runtime. Cette
  décision n'ajoute pas de journal de replay des deltas ni de bus inter-processus.
  Après redémarrage serveur, le message durable et la trace finale restent les sources
  de récupération. L'annonce vocale initiale sans round conserve son chemin de journalisation.

## Validation

Tests du harnais sur les parties texte/réflexion et la réutilisation des indices ; tests
du flux conversationnel sur l'entrelacement, la finalisation et les traces partielles ;
tests des deux moteurs vocaux vérifiant la publication avant la fin de génération ;
tests frontend sur la fusion des snapshots, les tentatives et les événements tardifs.
