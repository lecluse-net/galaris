# Qualification du rappel mémoire contextuel — 30 octobre 2026

Audit exclusivement synthétique. Aucun profil, échange ou identifiant de production n'est
inclus. Les résultats concernent le rappel `memory-query-evidence/v14` en développement.

## Défauts reproduits et corrections

- Une demande de coordonnées à la première personne pouvait sélectionner un autre contact.
  La fiche est désormais ancrée sur l'UUID du correspondant connu, avec contrôle de propriétaire.
- Un acquiescement pouvait remplacer le dernier sujet humain d'une relance. Les réponses
  brèves sont ignorées dans cette recherche bornée, sans traverser un changement de sujet.
- Une URI documentaire intégrée dans une phrase pouvait manquer au repli lexical. Les
  références exactes entrent avant la limite des candidats, sous les mêmes contrôles d'accès.
- Un long préambule ou un autre libellé de tâche pouvait faire disparaître cette référence.
  La requête concise conserve les URI complètes dans son budget existant.

Les régressions ajoutées ont d'abord produit sept échecs sur huit scénarios, puis quatre
échecs sur huit tests supplémentaires de bornes et de faux positifs. Une vérification mixte
a également empêché la nouvelle priorité du contact de remplacer une véritable recherche
documentaire. Les URI de sous-ressources ne sont pas promues en URI de leur document parent.

Les demandes simples de coordonnées déjà attribuées et les identités autonomes utilisent un
accès exact sans embeddings ni reranking de tout l'annuaire. Questions plus riches, autres
personnes et contexte sémantique élargi conservent le parcours hybride. Droits, source,
validité, révision, conflits et comptabilisation des usages restent contrôlés.

## Corpus et mesures

Le corpus fixe contient six contacts, trois documents, 24 notes distractrices et un contact
privé appartenant à un autre agent. Ses 51 requêtes combinent noms complets avec ou sans
accents, minuscules, coordonnées à la première personne et références documentaires.
Il est exécuté en repli lexical puis avec des embeddings uniformes : ces vecteurs ne peuvent
pas corriger artificiellement un défaut de résolution d'identité.

| Mesure | Repli lexical | Hybride |
|---|---:|---:|
| Requêtes | 51 | 51 |
| Bonne ressource au premier rang | 51/51 | 51/51 |
| Rang réciproque moyen | 1,0 | 1,0 |
| Fuite inter-agent | 0 | 0 |
| SQL avant l'accès direct, après les corrections fonctionnelles | 1 030 | 1 497 |
| SQL après l'accès direct | 862 | 1 113 |
| Réduction du nombre de requêtes SQL | 16,3 % | 25,7 % |
| Dernière mesure locale de latence p95 | 182,97 ms | 202,04 ms |

Les services, PostgreSQL, projections, indexation, classement, admission et préparation du
contexte sont réels. Seuls les appels fournisseur sont remplacés. Les latences sont indicatives,
prises pendant d'autres contrôles ; elles ne démontrent pas une accélération du temps mural.
La réduction SQL est mesurée sur les mêmes données et les mêmes requêtes. Huit scénarios
séparés vérifient la bonne fiche parmi seize distracteurs dont huit homonymes, en portée
normale et stricte, et l'absence de résolution d'un modèle d'embeddings pour une question simple.

## Étendue des contrôles

La batterie générale Memory, Contacts, Dream, contexte agent, Hermès et ressources fichiers
a exécuté **1 002 tests sans exclusions : 999 réussis, 2 échecs préexistants, 1 ignoré**.
Le test ignoré est la campagne optionnelle avec fournisseurs configurés.

Les deux échecs existaient avant ces changements et avaient déjà été reproduits sur le code
de référence :

- `test_legacy_dataset_type_is_fixed_and_stays_out_of_the_document_library` attend encore
  le libellé historique `html`, alors que le domaine Document retourne `text`.
- `test_populated_upgrade_through_dbadmin_preserves_content_and_resumes_after_ddl` ne parvient
  pas à reconstruire son ancien schéma : des clés étrangères Document dépendent du registre
  de fichiers qu'il essaie de retirer. La migration à qualifier n'est pas atteinte.

Après les derniers ajustements, le lot complet de rappel a passé **205 tests**. Les derniers
cas de références et questions mixtes ont passé **11 tests supplémentaires ciblés**. Ces lots
se chevauchent et ne doivent pas être additionnés. Ils ne constituent pas un nouveau passage
de la batterie générale sur l'ultime état du code.

Le typage strict backend/frontend, la parité des traductions, les 34 tests d'architecture et
le lint des surfaces modifiées passent. Les scénarios existants couvrent aussi les retraits
de droits, suppressions, corrections, révisions tardives, temporalité, budgets, saturation du
calendrier, reprise et isolation des conversations.

## Limites

Le score de 100 % porte sur ce corpus défini, pas sur toute formulation possible. Une identité
homonyme sans contexte suffisant reste ambiguë ; le rappel ne prouve pas une réponse. Cette
campagne ne mesure ni la qualité d'embeddings d'un fournisseur réel, ni les réponses finales
d'un LLM, ni les latences réseau. Aucune promesse de trois millisecondes pour la recherche
mémoire complète n'en découle. Les données historiques n'ont pas été réécrites.
