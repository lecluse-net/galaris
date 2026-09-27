# 0144 — Temporalité partielle des souvenirs

Statut : accepté. Date : 2026-09-27.

## Décision

Un item mémoire possède au plus un ancrage temporel facultatif : année, mois, jour du mois,
jour ISO de semaine (1–7), heure, minute et fuseau IANA. Les composantes absentes sont libres ;
les composantes présentes se combinent par conjonction. Aucun champ seconde. Un objet sans
composante n'est pas un ancrage : l'absence est représentée par `null`.

Le contrat Pydantic est partagé par HTTP, MCP et Dream. L'objet normalisé est conservé dans
une colonne JSONB nullable de MemoryItem et de ses révisions. Cette représentation correspond
à un seul attribut structuré par item, sans collection ni moteur de récurrence supplémentaire.
Les données existantes restent sans temporalité ; aucun backfill inféré depuis le texte.
`valid_from` et `valid_until` conservent leur rôle de validité, distinct de la correspondance.

## Consommateurs et garanties

- Création/édition HTTP, outil `memory_remember`, acquisitions Dream et révisions : préserver
  l'ancrage, sa suppression explicite et les conflits de version ; aucune date ajoutée par défaut.
- Déduplication exacte, acquisition sémantique et fusion de maintenance : ne pas fusionner des
  ancrages différents. Les anciennes clés d'idempotence sans temporalité restent inchangées.
- Préparation commune du contexte et capsules conversationnelles : remonter les correspondances
  sans seuil lexical ou vectoriel, en conservant ACL, portée contact, admission finale, budget
  d'items/caractères, provenance et indication de troncature. L'occurrence fait partie de l'extrait
  pour rester visible après allocation du contexte conversationnel.
- Outils fichier : exposer la temporalité dans les métadonnées. `memory_upcoming` fournit la
  consultation paginée des correspondances supplémentaires sous la même portée d'accès.
- Interface : champs partiels facultatifs, interprétation explicite, fuseau proposé depuis
  l'application, conservation des brouillons et suppression de l'ancrage sans perte du contenu.
- Liste mémoire : union de deux sélections indépendantes, avant comptage et pagination :
  souvenirs sans date répondant aux filtres texte/type/sujet/contact, plus souvenirs datés
  correspondant à la cible, indépendamment de ces filtres. Hors période, un souvenir daté
  ne passe pas par la branche ordinaire. L'IHM ne propose qu'un champ date/heure prérempli avec l'heure
  actuelle du navigateur dès la première recherche, sans activation ni désactivation. Le navigateur convertit la cible locale en instant UTC
  explicite et transmet une anticipation nulle, sans sélecteur de fuseau. Les résultats s'affichent
  en heure locale du navigateur. La réponse expose la fenêtre effective et chaque correspondance.
  Les ACL et la validité restent évaluées au présent.
  La liste garde son tri courant et utilise la même fonction de correspondance que le contexte.

## Consultation unifiée

L'onglet Recherche est supprimé au profit de Liste. Une requête textuelle de Liste appelle le
rappel canonique hybride uniquement sur les souvenirs sans ancrage ; leurs critères exacts
sujet/contact/type sont appliqués avant les limites lexicales, vectorielles et de graphe.
Les souvenirs datés sont ajoutés par une branche indépendante du texte et de ces critères.
Les ACL, la validité et l'isolation du contact conversationnel ne peuvent jamais être contournées.
Le prédicat SQL du
calendrier à un instant est vérifié contre `next_match`, notamment pour les heures répétées.
La sélection pertinente sans date est bornée à 500 items ; les correspondances temporelles ne
partagent pas ce plafond. L'union est comptée, triée et paginée puis réadmise sous les ACL et
versions actuelles. Les correspondances temporelles passent en premier en l'absence de tri explicite.
L'IHM signale une sélection textuelle tronquée ou un repli lexical.
Sans texte, le parcours paginé existant reste exhaustif. Le graphe reste indépendant.

Les consommateurs de `/browse` sans filtre temporel gardent leur comportement existant.
La recherche de cibles dans le dialogue de liaison, les outils et le contexte conservent leurs
points d'entrée de rappel. Les tests du composant Recherche supprimé et de son helper de retrait
sont remplacés par les parcours réels Liste : recherche/type/ouverture, oubli et révocation avec
réponse tardive. Les garanties de contenu et d'accès sont conservées sans figer l'ancien onglet.

Pour le contexte automatique, le rappel ordinaire et celui des expériences excluent les ancrages
avant leurs limites de candidats ; `temporal_hits` sélectionne séparément les correspondances,
sans filtre de texte/type/Topic. Les correspondances sont prioritaires dans le budget commun en
items et en caractères, y compris devant les expériences. La troncature reste explicite et
`memory_upcoming` permet d'explorer les autres correspondances. La recherche explicite et la
lecture par URI restent possibles pour retrouver ou corriger un ancien souvenir daté.

Le skill runtime, la politique de mémoire et le prompt Dream décrivent l'ancrage comme une règle
de rappel, jamais un horodatage d'audit. Seuls rendez-vous, anniversaires, habitudes et autres
rappels voulus à cet instant le justifient. Une date historique peut rester dans le texte sans
ancrage ; aucune temporalité n'est ajoutée automatiquement aux connaissances ordinaires.

Les correspondances sont calculées à la minute dans une fenêtre UTC inclusive, puis interprétées
dans le fuseau de l'item. Les heures locales inexistantes sont ignorées ; les heures répétées
peuvent correspondre deux fois. Une date seule correspond toute la journée. Le 29 février sans
année correspond uniquement aux années bissextiles. La fenêtre est gouvernée par
`MEMORY_TEMPORAL_LOOKAHEAD_HOURS` (24, plage 0–744) ; zéro conserve les correspondances actuelles.

La sélection parcourt uniquement les ancrages accessibles, indexés par un index partiel, en
pages bornées et conserve les résultats les plus proches. Aucun item n'est créé par occurrence.
Le mécanisme ne crée ni tâche ni notification et n'induit aucune expiration.

## Validation

Scénarios unitaires du calendrier, intégration DB acquisition → contexte → correction/historique,
isolation par agent/contact, pagination et budget, extraction Dream et parcours Vue de saisie et
suppression. Les suites mémoire existantes couvrent les garanties inchangées des autres consommateurs.
