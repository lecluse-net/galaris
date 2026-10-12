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
