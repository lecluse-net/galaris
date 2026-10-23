# 0223 — Souvenirs personnels et documents indépendants

Statut : accepté, 2026-10-23.

## Décision

`app.memory` possède les souvenirs privés d'un agent. Un souvenir personnel n'a
ni configuration de partage, ni grants, ni propriétaire humain. Les humains qui
administrent l'agent conservent leur accès de gestion ; leurs autres agents
n'héritent pas de cet accès. Le contrat de mémoire personnelle ne choisit aucun
moteur tiers et n'impose pas son index aux autres domaines.

`app.document` possède les documents éditoriaux, métadonnées, contenus, révisions,
résumés partagés et leur historique, droits, classement personnel, URL et pièces
jointes. Un document et ses versions existent sans ligne `memory_items` ou
`memory_revisions`. Dataset et Process conservent respectivement leur JSON et
leur BPMN ; leurs seuls anciens alias documentaires restent des adaptateurs.

Les résumés documentaires partagés existants restent attachés à leur document,
avec les mêmes droits et la même provenance. Ils ne sont ni dupliqués entre
agents ni réattribués arbitrairement comme souvenirs privés. Un agent peut
acquérir un souvenir privé indépendant concernant un document autorisé.

Le graphe natif peut projeter les documents, dossiers et pièces jointes. Ces
références sont reconstructibles, et leurs lectures revérifient les droits du
domaine source. Leur suppression n'efface pas le document. Document annonce
ses changements par un port ; il n'importe pas l'implémentation Memory. Un index
optionnel peut conserver la recherche classée et ses passages, avec une seconde
vérification des droits et de la révision côté Document. La recherche documentaire
directe reste disponible sans cet adaptateur.

## Compatibilité et migration

L'API documentaire est sous `/documents`. La bibliothèque conserve son chemin
public `/documents`, ses URI `document://` et une redirection du précédent chemin
de page `/memory/documents`. Les anciennes routes API documentaires ne sont plus
une surface de Memory. Le Tool `document` possède `document_sharing` et
`document_share` ; les opérations de partage ne sont plus exposées par Memory.
Les politiques de fonctions et les capacités documentaires des rôles existants
sont transférées sans élargissement implicite des droits.

DbAdmin archive les sources avant l'expansion, vérifie leur intégrité, transfère
les identités, pointeurs, révisions, résumés, provenances, URL et politiques, puis
autorise la contraction. Les anciens souvenirs effectivement partagés deviennent
des documents en conservant leurs destinataires ; les souvenirs privés gardent
leur propriétaire. Une modification après l'archive ou un transfert incomplet
bloque le retrait des sources. Les actions historiques indispensables gardent
une identité reprenable. Les archives sont conservées ; leur purge n'appartient
pas à ce chantier.

Pendant l'expansion, les anciennes colonnes de politique `memory_items.share_id` et
`share_kind` restent présentes jusqu'à la contraction. Une action `BEFORE_EXPAND`
vérifie d'abord l'archive, puis les rend temporairement nullables pour que les reconcilers
puissent créer des souvenirs privés dépourvus de partage. Elle ne modifie ni les valeurs
historiques ni les droits documentaires, et reprend aussi une installation dont le
transfert a déjà été validé mais dont la création de contacts a bloqué la contraction.
Le test d'upgrade reproduit les contraintes `NOT NULL` du schéma historique et exécute
le vrai reconciler de contacts avant la contraction, y compris après un échec antérieur.

## Vérification

### Revue des dépendances extraites

L'extraction conserve les dépendances documentaires existantes : Agent pour les
propriétaires, Conversation et Goal pour leurs adaptateurs, Process pour ses
références, Share pour les ACL, Task pour les auteurs et Tools pour MCP. Aucun
import privé supplémentaire n'est nécessaire ; l'import privé de Goal autrefois
porté par Memory est remplacé par sa surface publique. Le nombre d'importations
privées backend passe de 272 à 271, et celui du frontend reste à 122.

Les consommateurs qui utilisent à la fois souvenirs et documents gardent deux
dépendances explicites. Memory perd sa dépendance à Share et dépend de Document
uniquement pour les références natives facultatives. Document ne dépend pas de
Memory. Le frontend extrait sept dépendances de la bibliothèque et ajoute
Memory → Document pour ses aperçus. Les ensembles cycliques existants incluent
alors Document en plus de Memory ; aucun nouvel ensemble cyclique n'apparaît.
La revue explicite du 23 octobre 2026 retient dans les baselines ces huit
dépendances frontend et l'ajout de Document aux deux ensembles cycliques existants,
sans nouvel import privé, conformément à `AGENTS.md`. La suppression complète des cycles
historiques dépasse l'extraction ; les masquer dans le vérificateur est exclu.

Les suites `app/document/tests/test_boundary.py`, `test_independence_upgrade.py`
et `test_migration_preservation.py` vérifient l'indépendance, les refus inter-agent,
la préservation sur PostgreSQL/Atlas, les interruptions et le rejeu. Les anciens
parcours documentaires sont transférés avec leurs garanties vers Document ; les
parcours de rappel et de graphe restent dans Memory. La livraison exige aussi
les contrôles d'architecture, de typage, de documentation et le parcours assemblé.
