# ADR 0130 — Classement du topic en parallèle de l'admission

- Statut : Accepted
- Date : 2026-09-24
- Complète [0129](0129-shared-decision-model-workflows.md).

## Garantie observable

Lorsqu'un profil effectif dispose d'un modèle Décision et de son compagnon texte Dream,
un nouveau message entrant textuel peut recevoir son topic pendant le dispatch. L'admission
et l'exécution ne patientent pas pour ce classement. Un résultat enregistré n'est pas recalculé
par le passage de maintenance Dream. Sans modèle Décision, le classement différé reste actif.

Les consommateurs inventoriés sont l'admission Messenger commune (Chat et bridges), les rounds
conversationnels, leurs Tasks et les Tasks admises directement depuis un message, le contexte
du harnais et les outils mémoire. Il faut préserver la déduplication, les droits de contact,
les topics manuels, la priorité de la room, les reprises et l'absence de session SQL partagée
entre branches asynchrones.

## Mise en œuvre

Messenger émet `message_admitting` après les vérifications de contact/bridge et la projection
du contact. Le récepteur optionnel de `app.dream.live_topics` copie uniquement les identifiants
et démarre une tâche avec un contexte isolé. L'historique importé, écarté en amont par le contrat
d'âge existant, ne déclenche pas ce traitement. Les sorties agent et les tours vocaux journalisés
sans admission textuelle gardent leur parcours actuel.

Les messages sont traités successivement par room dans un worker local ; les rooms peuvent
avancer en parallèle. Une prise en charge SQL ciblée vérifie le profil, les surcharges, le topic
de room, les approbations en cours et le reçu existant. Elle partage le mécanisme
`topic.classify_message`, ses checkpoints et son lease avec Dream. Les réservations d'une même
room sont sérialisées sans conserver un verrou SQL pendant l'inférence. Une room déjà détenue
par un autre classement laisse le message au rattrapage Dream.

Ce worker ne dépend pas de l'inactivité de la conversation et n'est pas préempté par le dispatch.
Il utilise le budget général d'exécution Dream existant, inférieur au lease : aucun nouveau
délai ni réglage n'est introduit. À l'arrêt il annule les appels et rend les reçus récupérables.
Les erreurs deviennent des reprises Dream ; le journal reste la file de récupération après un
arrêt avant réservation. La politique existante de repli vers le texte reste applicable.

Les appels sont corrélés au message et au reçu ; le checkpoint indique
`classification_trigger=message_admission`. La politique existante de création de topics
(`forbid`, `propose`, `auto`) reste appliquée : une proposition n'est pas une création acquise.

## Publication et recherche

L'application relit sous verrou le message et la room. Elle préserve une affectation manuelle
arrivée pendant l'inférence. Seul le dernier input d'un round peut lui transmettre son topic ;
un résultat ancien ne remplace pas le classement d'un input plus récent. Les Tasks directement
issues du message reçoivent aussi la projection si leur topic est vide.

Les admissions relisent la projection canonique avant de créer un round ou une Task. La façade
`current_turn_scope` permet au harnais, aux outils mémoire et à la création de Tasks depuis un
round de lire un classement arrivé après la capture du tour. Les lectures ne patientent jamais
sur le modèle. Si le topic arrive après une recherche déjà exécutée, cette recherche n'est pas
rejouée ; les opérations suivantes peuvent le consommer.

Le rappel automatique humain conserve sa portée contact et les souvenirs globaux autorisés.
Le topic précoce ne devient pas un nouveau filtre d'exclusion et n'accorde aucun droit.

## Héritage des réponses texte et audio

Le sujet d'un round est piloté par son entrée humaine. `inherit_reply_topics` copie
le topic et sa surcharge explicite depuis le dernier input vers toutes les réponses
du round : texte, segments vocaux et réponses vocales successives. Les messages conservent
la même résolution du topic de room que l'entrée, sans transformer ce défaut en surcharge.
Un sujet inconnu reste inconnu ; aucun modèle n'est appelé pour classer une réponse.
L'enregistrement d'une transcription tardive et le classement Dream resynchronisent aussi
les sorties déjà présentes. Les publications vocales et la projection différée se sérialisent
sur le round ; aucune inférence n'est exécutée par cette projection.

Le détecteur séquentiel applique aussi cette règle dans le Lab : un message `sender_is_ai`
retourne directement le topic courant, avec `resolution=inherited` et un coût nul. Un salut
initial sans sujet connu produit `null` dans la liste de topics du Lab. Les titres existants
restent compatibles ; `null` exprime une absence réelle et non un nouveau dossier.

## Validation

Tests synthétiques sur PostgreSQL isolé et transport fournisseur simulé : admission et dispatch
pendant une inférence suspendue, résultat unique, saut par Dream, profil sans spécialisation,
topics manuels/de room, historique importé, refus de contact, message suivant, annulation,
reprise après erreur et propagation avant/après création d'une Task. La qualité et la latence
de Jev réel restent à mesurer dans les conditions d'usage.

Les tests d'héritage couvrent aussi les topics détectés, manuels, inconnus et explicitement
effacés, plusieurs segments audio, une sortie précédant la transcription, le rejeu et un
échange complet dans le Lab dont seuls les inputs humains produisent des appels modèle.
