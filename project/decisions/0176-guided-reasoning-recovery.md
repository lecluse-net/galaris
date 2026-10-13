# 0176 — Récupération guidée du raisonnement répétitif

Statut : accepté. Date : 2026-10-12.

## Problème

Le garde commun coupe un stream dégénéré hors du harnais : le modèle ne reçoit aucun
retour pour corriger sa démarche. Rejouer son historique peut réintroduire le raisonnement
répété. Une reprise de plan ne recalculait le curseur que lorsqu'un marqueur de clôture
après échec existait ; les plans anciens ou collections déjà finalisés retombaient donc
sur les résultats en échec sans exécuter de nouveau travail.

Une hésitation sur « déjà produit » et « complètement terminé » est observable dans un
inventaire ; son rôle dans la dégénérescence du modèle reste une hypothèse. Aucun modèle
ni fournisseur n'est remplacé automatiquement.

## Décision

Le harnais interne observe les messages avant leur sortie vers la façade. Il ferme la
génération répétitive et offre au modèle deux changements d'approche au maximum, avec
avertissement explicite, outils et droits inchangés, budget cumulé et journal d'effets
conservé. Le contexte de reprise exclut le raisonnement et les références de réponse
provider qui pourraient le restaurer implicitement ; il conserve les résultats d'outils.
Le checkpoint nettoyé est persisté avant la reprise. Une relance manuelle après l'ancienne
erreur de dégénérescence demande aussi ce nettoyage. La boucle persistante ne devient
jamais une réussite déclarée : elle termine avec un diagnostic d'inachèvement.

La façade garde sa protection commune pour les autres drivers. Les états Task, leases,
frontières d'autorisation et résultat terminal unique ne changent pas. Chaque plan relancé
recalcule son curseur depuis les enfants inachevés, sans dépendre du marqueur de clôture.
Les éléments réussis restent acquis ; les clôtures après échec suivent leur contrat existant.

L'inventaire distingue sortie existante et travail terminé : correction, contrôle qualité,
partage ou régularisation du suivi demandés gardent l'élément dans le périmètre. Le comptage
vient des éléments vérifiés, jamais d'une estimation historique.

## Vérification

Les tests synthétiques couvrent changement d'approche, boucle persistante bornée, fermeture
du stream, conservation d'un effet terminé, nettoyage d'un checkpoint ancien, budget partagé
et reprise d'un plan imbriqué dont le curseur dépassait la dernière étape. Les tests de garde
et du scheduler existants ne suffisaient pas : ils validaient l'arrêt terminal, sans exercer
la réception d'un avertissement par le modèle ni cette reprise de plan finalisé.

La qualification déterministe ne garantit ni le succès métier de chaque Task ni l'absence
de boucle chez un modèle réel. La production ne change qu'après déploiement demandé.

## Complément — alerte de silence sans interruption

Une longue réflexion peut rester utile. Sa durée et son volume ne constituent pas une preuve
de boucle et ne déclenchent aucun nouveau mécanisme d'interruption. Le garde de répétition
exacte et sa récupération guidée existants restent distincts.

Le résumé d'activité partagé entre les détails de Task et le panneau de discussion signale
deux minutes sans mouvement reçu, uniquement pendant une exécution active. Réflexion, texte,
arguments générés et résultats d'outils actualisent cette observation. L'alerte disparaît au
prochain mouvement ; elle ne change aucun état, budget, appel ou effet. Pauses, attentes et
indisponibilité de la consultation sont distinguées d'un silence d'exécution.

Le timestamp durable d'activité runtime appartient à la tentative et au run courant. Il
préserve les arguments en cours comme activité sans les inventer comme outils exécutés.
Les événements WebSocket acceptés complètent la lecture HTTP sans laisser une réponse tardive
ou une ancienne tentative effacer une activité plus récente. Le navigateur affiche cette
alerte dans les suivis ouverts ; elle n'est pas une notification externe persistante.

La vérification combine PostgreSQL réel pour les timestamps et leur isolation, les tests
d'activité existants et le composant Vue/Quasar réel avec une horloge de navigateur contrôlée.

## Complément — interruption manuelle de l’appel avec reprise

L’alerte propose une commande explicite aux utilisateurs disposant de `TASK_EDIT` dans
le périmètre de l’agent. Seul le harnais interne expose actuellement cette capacité,
déclarée par le descripteur du driver et figée dans l’identité du run. L’orchestration
Task ne sélectionne aucun harnais par son nom. La commande désigne
le run exact et porte une identité idempotente et une version attendue ; elle est enregistrée
sur la tentative puis remise par le propriétaire du lease au runtime actif.

Le runtime accepte l’interruption pendant la génération du modèle, ferme son stream et
reprend la même Task avec une consigne de changement d’approche. Le journal d’effets et
le budget initial sont conservés ; le raisonnement et les arguments non exécutés sont
retirés du contexte. Un outil actif ou un effet incertain empêchent l’interruption.
L’annulation de Task conserve sa priorité et les anciens runs ne sont jamais interrompus.

Le bouton affiche la demande puis son acceptation ou son refus. Une requête en cours ne
bloque que sa propre consultation ; changement de Task, de run ou de tentative invalide
son retour, même après réouverture. La réponse ancienne ne termine pas le chargement
d’une demande plus récente. Le clic reste dans le suivi de la discussion sans ouvrir les
détails de Task par propagation au conteneur.

La première validation du bouton n’exerçait pas entièrement les réponses différées ni
l’API sous les protections actuelles de l’inscription. Les scénarios existants couvrent
maintenant ces changements de contexte ; les comptes du test HTTP sont créés directement
dans sa base éphémère. Un parcours assemblé traverse le scheduler et le harnais réels,
avec seulement le fournisseur du modèle remplacé par un stream synthétique contrôlé.

Ce parcours a révélé une commande acquittée mais perdue à la fermeture de la session
HTTP : un simple flush ne constitue pas la persistance de cette commande. L’admission
committe désormais avant l’accusé. Le test HTTP exige la commande relue par une autre
connexion, et le parcours assemblé exige sa réception effective par le scheduler.
