# 0139 — Capacité de sortie publiée par le fournisseur

Statut : Accepted

## Problème et garantie

Une requête sans `max_tokens` peut hériter d'une valeur fournisseur trop basse pour
produire une réponse après le raisonnement. L'exécution doit demander la capacité de
sortie publiée pour le modèle servi, sans inventer un plafond global « illimité ».

## Consommateurs et garanties à préserver

- Le proxy Chat et Responses est partagé par le harnais interne, les conversations,
  les inférences durables et les harnais externes. La résolution intervient après
  le choix du modèle et l'autorisation, avant le transport.
- Les budgets explicites restent prioritaires, notamment les appels structurés courts
  du dispatcher. La compaction et les endpoints sans contrôle de sortie restent inchangés.
- Le contenu, les outils, le modèle, le raisonnement, la comptabilité et les reçus ne
  changent pas. Une sortie `length` reste incomplète ; aucun outil n'est rejoué.
- Les modèles déjà configurés bénéficient de la découverte à l'exécution, sans migration
  ni réenregistrement. Une métadonnée inconnue ne devient pas un nombre arbitraire.

## Décision

Le DTO de découverte distingue fenêtre de contexte et capacité de sortie. Les métadonnées
du fournisseur sont prioritaires ; le catalogue models.dev fournit les valeurs manquantes.
Les réponses de découverte sont mises en cache de manière bornée, par connexion et modèle,
avec une durée de vie courte. Un changement de connexion ne réutilise pas l'ancien résultat.
Une indisponibilité de découverte laisse fonctionner l'inférence avec les paramètres existants.

En l'absence de limite explicite, le proxy demande la capacité publiée, bornée par la place
estimée restante dans le contexte. L'estimation n'est pas un tokenizer exact ; le fournisseur
reste autoritaire. Les chaînes Responses dont l'historique distant n'est pas disponible et
les contenus multimodaux ne permettent pas une mesure exacte locale.

La limite physique du fournisseur existe toujours. Cette décision supprime la dépendance
à son petit budget implicite quand ses capacités sont connues ; elle ne garantit pas qu'un
appel puisse générer sans fin et ne modifie pas les transitions d'échec ou de reprise.

## Vérification

Un parcours synthétique traverse Agent, le proxy, le transport simulé et la persistance
des appels : le fournisseur termine en `length` avec son défaut et réussit avec sa capacité
publiée. Les tests couvrent ensuite Chat/Responses, budgets explicites, contexte long,
catalogue absent, cache, changement de connexion et préservation des sorties incomplètes.
