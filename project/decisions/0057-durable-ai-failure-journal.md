# 0057 — Journal durable et exploitable des échecs IA

- Statut : Accepted
- Date : 2026-08-28

## Contexte

Les journaux applicatifs et les traces Logfire permettent d’observer une panne au moment où elle
survient, mais ne constituent pas une file de travail durable pour éliminer les classes d’erreurs.
Les échecs de validation d’outil, notamment ceux qui sont absorbés par une nouvelle tentative,
étaient particulièrement difficiles à retrouver. Une erreur terminale telle que
`UnexpectedModelBehavior` ne suffisait pas non plus à reconstruire toutes les tentatives qui
l’avaient précédée.

## Décision

`app.incident` est l’autorité PostgreSQL des échecs d’appels LLM et d’outils. Une occurrence
immuable est enregistrée pour chaque appel en échec, y compris lorsqu’une nouvelle tentative
réussit ensuite. Elle conserve les corrélations de l’exécution, l’identité du composant, la
politique de retry connue, l’erreur et une trace JSON complète de la frontière observée.

La trace est convertie en JSON, les secrets et contenus binaires sont remplacés par des empreintes,
et une limite de 8 Mio protège PostgreSQL contre un payload accidentellement non borné. Toute
occurrence possède une clé d’idempotence stable. Les insertions concurrentes sont sérialisées et
ne doivent jamais faire échouer le travail métier qu’elles observent.

Les occurrences partageant une empreinte versionnée alimentent un motif durable. Son statut suit
`new`, `triaged`, `fix_planned`, `resolved`, `ignored` ou `regression`, et sa fiche porte le
diagnostic, la cause racine, le correctif, son commit et le test de non-régression. Une nouvelle
occurrence d’un motif résolu le rouvre automatiquement en `regression`. Les Préférences exposent la file de
revue avec des privilèges distincts de lecture et d’édition.

Logfire reçoit uniquement les métadonnées et l’identifiant de l’incident. Il reste un outil de
navigation opérationnelle ; PostgreSQL reste l’autorité de conservation et de traitement.

## Emplacement dans l’interface — 7 septembre 2026

Le journal est accessible dans **Préférences → Journal des échecs IA**. Son module frontend
`app/incident` possède la page `/incident`, le service API et les traductions `incidents.*`.
Les droits `INCIDENT_ACCESS` et `INCIDENT_EDIT` restent indépendants des droits de benchmark.
La navigation et les cartes des préférences utilisent les contributions filtrées par privilèges.
La consultation et le traitement des motifs ne proposent aucune conversion vers un jeu de tests.

Revue des dépendances frontend : `app/incident` reprend les quatre surfaces publiques déjà
utilisées par la page — `core/api`, `core/authorize`, `core/navigation` et `core/util`.
Ces quatre relations sont enregistrées dans la baseline du nouveau module, sans import privé
ni dépendance applicative supplémentaire. La dépendance backend `app.lab -> app.incident`
est supprimée ; le budget sortant du LAB revient de 15 à 14.

## Conséquences

- Un retry d’outil échoué reste visible même si le run produit finalement un résultat réussi ;
  l’occurrence reçoit alors un horodatage de récupération.
- Un appel LLM finalisé en échec conserve sa requête, sa réponse partielle, son usage et ses
  corrélations dans la même transaction que son statut terminal.
- Les drivers externes bénéficient d’une capture terminale commune ; le harnais interne ajoute la
  trace brute des événements Pydantic AI avant leur compactage d’affichage.
- Les annulations explicites ne sont pas classées comme des échecs.
- La file de revue ne remplace ni `LLMCall`, ni les événements de Task, ni Logfire : elle les relie
  et fournit le cycle durable de prévention des récidives.

## Stabilisation des observations — 20 septembre 2026

L'identité d'un échec terminal inclut la tentative lorsqu'elle existe : deux tentatives du
même run peuvent échouer pour des causes différentes. Une ancienne clé limitée au run reste
reconnue lorsqu'elle porte la même tentative. Les occurrences historiques ne sont pas réécrites.

La frontière MCP native conserve séparément, après rollback de sa transaction, les types,
messages expurgés et emplacements de code de la chaîne d'exceptions. Ces détails sont réservés
au journal administratif ; le modèle conserve son diagnostic public borné. La référence publique
permet aux observations du harnais et de la façade d'enrichir la même occurrence, sans nouveau
comptage. Les clés historiques des appels d'outils restent reconnues à la reprise. L'enrichissement
ajoute uniquement les champs manquants, conserve les masquages et respecte la rétention des traces.

La catégorie privilégie le code structuré de la frontière. Le fallback historique ignore
l'enveloppe d'erreur et les références aléatoires. Une politique de retry inconnue reste inconnue :
la capture d'un résultat terminal ne décide pas à la place du scheduler.
