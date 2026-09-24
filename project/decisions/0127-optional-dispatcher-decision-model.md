# ADR 0127 — Modèle de décision facultatif pour le dispatcher Task

- Statut : Accepted
- Date : 2026-09-24
- Complète [0095](0095-pydantic-ai-request-ownership.md) et [0097](0097-durable-inference-lifecycle.md).
- Extension : l'[ADR 0129](0129-shared-decision-model-workflows.md) généralise aux topics et à
  la mémoire, étend le Lab et supprime les délais pilotes décrits ci-dessous.

## Contrat

Le profil possède une sélection nullable `decision_llm_id`, réservée aux modèles déclarant
la capacité `decision`. Vide, elle laisse le dispatcher Task utiliser son modèle `TEXT_LOW`
et son protocole structuré existants. Les profils antérieurs et la porte conversationnelle
conservent leur comportement. Un seul couple route/effort autorisé court-circuite toute inférence.

La sélection spécialisée passe par `app.llm.facade.run_decision` et une requête durable
`galaris.decision-inference-request/v1`. Le dispatcher fournit les couples route/effort déjà
filtrés et les langues supportées. Les clés et valeurs sont validées avant application ;
distributions et confiance restent celles du fournisseur, sans score fabriqué pour le texte.

Le bridge OpenRouter appelle `/api/alpha/decisions` avec une requête HTTP native. Pydantic AI
reste responsable du chemin texte. La découverte reconnaît `architecture.output_modalities`
contenant `decisions`, sans déduire la capacité d'un nom de modèle. Aucun SDK supplémentaire,
service Docker ou matériel local n'est nécessaire. L'API TypeSafe directe et les adaptateurs
locaux restent différés.

## Repli et cycle durable

`decision_fallback_policy` vaut `text_on_failure` par défaut, ou `disabled`. En cas d'échec
récupérable, le service peut appeler une seule fois le modèle `TEXT_LOW` du même profil, avec
une sortie structurée de choix fermés et sans retry de validation. La requête partage un délai
total de 30 secondes, dont au plus 10 pour l'appel spécialisé, et un budget d'appels. Ces bornes
sont des limites initiales, pas une mesure de latence ni une promesse de performance.

Les erreurs HTTP 401, 403 et 402, annulations, arrêts, pauses, échéances totales et pertes de
lease ne déclenchent pas de repli texte. Un échec terminal du chemin spécialisé reste un échec,
y compris dans le Lab. Aucun modèle tiers n'est recherché implicitement. L'incertitude seule ne
déclenche pas de repli : aucun seuil de confiance universel n'est activé.

L'admission fige les questions, paramètres, sélection de modèles, politique et empreintes sans
secret des connexions. Une reprise refuse une connexion ou un modèle modifié. Les droits sont
vérifiés lors de l'appel. Un appel natif et son éventuel repli sont deux `LLMCall` d'une même
tentative, avec coûts et jetons conservés, et un seul résultat terminal métier. La version
effective retournée par OpenRouter apparaît dans la trace. Le transport HTTP ne fait pas de retry.

## Configuration et Lab

La page des usages expose « Décision », le modèle texte de secours et la politique de repli.
Les sélecteurs texte et leurs validations API refusent un modèle limité aux décisions. La purge
des modèles inclut la nouvelle FK. DbAdmin fait converger le schéma sans affecter de fournisseur
aux profils existants.

Le Lab existant propose les candidats `chat` et `decision` uniquement pour le dispatcher.
Son candidat initial vient de la sélection décision du profil courant, ou de `TEXT_LOW` si elle
est vide ; le juge reste texte. Le candidat explicite et son empreinte sont figés dans le run.
Les campagnes de candidat désactivent le repli texte et conservent la provenance, les probabilités
et la version effective dans le résultat. L'observation du repli du système complet passe par les
traces des tâches ; aucun nouveau moteur de benchmark n'est ajouté.

## Validation et limites

Les tests utilisent des données synthétiques, PostgreSQL éphémère et le vrai cycle durable,
avec remplacement du seul transport fournisseur. Ils couvrent les deux branches du dispatcher,
les choix du harnais, la configuration, la conservation des coûts, le candidat Lab, les refus,
les limites, l'annulation et la reprise après changement de modèle.

Les gains de qualité et de latence sur Jev réel restent à mesurer dans le Lab. Les tests HTTP
simulés ne qualifient ni le compte OpenRouter ni la disponibilité distante. La réutilisation de
connexions HTTP et l'optimisation des attentes du worker seront évaluées à partir de ces mesures.
