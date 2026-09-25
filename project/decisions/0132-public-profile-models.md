# 0132 — Modèles publics sélectionnés par profil et usage

Statut : accepté. Date : 2026-09-25.

## Garantie

Un client choisit `profil1/text/high` sans connaître un identifiant numérique ni
le fournisseur affecté. Tous les profils sont disponibles derrière une même URL
de base par protocole, indépendamment du profil courant de l'instance.

## Décision

`LlmProfile.code` est un code ASCII unique et persisté, généré depuis le libellé :
minuscules, translittération des accents et ligatures usuelles, espaces remplacés
par `-`, alphabet `a-z0-9_-`. Une collision reçoit un suffixe `-2`, `-3`, etc.
Un libellé sans caractère exploitable utilise `profil`. Le code ne change pas lors
d'un renommage. Une action DbAdmin remplit les lignes existantes avant `NOT NULL`.
Les clés étrangères et le CRUD administratif conservent leurs identifiants internes.

Les surfaces `/api/profile/openai` et `/api/profile/anthropic` réutilisent les
gateways, leurs droits `LLM_API_ACCESS`, leur journal et leur gestion du streaming.
Le sélecteur exact est `<code>/<usage>/<niveau>`. Les endpoints `/models` listent
tous les profils et filtrent les usages selon le protocole ; ils excluent les
sélections vides, supprimées ou dépendant d'un fournisseur inactif.
`/api/profile/models` donne le catalogue commun, décisions incluses.

La première surface couvre les quatre paliers texte (`text/default` est un alias
de `text/standard`), `embedding/default` et `decision/default`. Les embeddings
utilisent `/api/profile/openai/embeddings` ; les décisions ont le contrat Galaris
à choix fermés sur `/api/profile/decisions`, sans simuler un chat.

Une sélection vide ou incompatible échoue. Aucun modèle n'est emprunté à un autre
profil. La résolution fige le modèle et son effort avant l'admission durable ; le
sélecteur reste dans la corrélation et le modèle physique dans les traces. Une
Task corrélée conserve sa sélection figée : un sélecteur contradictoire est refusé.
Les surcharges explicites de raisonnement suivent le contrat existant du gateway.

Pour un appel utilisateur autonome aux API de profils, le contenu des messages
et résultats d'outils n'est pas une source de métadonnées d'exécution : les
références à des tâches, runs ou modèles restent du contenu. Les métadonnées
explicites du corps et des en-têtes gardent leur validation habituelle. La
corrélation par le prompt reste disponible pour les runtimes gérés et les routes
historiques `/api/llm/*`.

Le libellé du jeton utilisateur authentifié est figé à l'admission dans la
provenance serveur, transmis au worker et copié dans `LLMCall.api_token_label`.
Les appels directs, dont les embeddings, le capturent depuis le même contexte
d'authentification. Le journal HTTP et temps réel expose ce libellé sans secret ;
il survit au renommage ou à la suppression du jeton. `NULL` désigne une provenance
non enregistrée, la chaîne vide un jeton sans nom. Aucun libellé n'est déduit pour
les appels historiques ni accepté depuis les métadonnées fournies par le client.

La décision utilise, si la politique du profil l'autorise, `text/standard` du même
profil comme repli. Le modèle et l'effort de ce repli sont figés avant l'appel.
La réponse distingue `specialized` et `text`, avec la raison du repli.
Les endpoints spécialisés sont des appels utilisateurs autonomes ; les jetons
de runtimes restent sur leurs chemins corrélés. Aucun paramètre fourni par le
client ne remplace l'identité du demandeur.

## Consommateurs et validation

La page des jetons utilisateur accueille une contribution du module LLM pour
générer les configurations des clients externes. Le catalogue public fournit les
codes de profils et les paliers disponibles, avec `LLM_API_ACCESS` ; le générateur
ne lit aucun jeton. La composition suit les contributions existantes des pages
utilisateur, sans import métier direct dans `core/user`. Pour un profil incomplet,
les alias Claude Code sans palier disponible pointent explicitement vers le modèle
de démarrage choisi, ce que l’interface indique avant la copie.

Les routes physiques `/api/llm/*`, le harnais interne et les runtimes gérés gardent
leur contrat. Les fonctions d'embedding internes restent consommées par Memory,
la recherche d'outils et le classement sémantique : leur retour vectoriel, l'ordre,
la validation et les délais restent inchangés. Le nouvel adaptateur conserve en
plus l'usage réellement fourni pour l'API et la comptabilité.

Les tests couvrent les collisions et renommages, le backfill idempotent, les
catalogues multi-profils, l'authentification et les refus RBAC, les appels HTTP
texte avec et sans streaming, les embeddings et les décisions avec repli activé
ou désactivé. Les services du parcours restent réels ; seul le fournisseur HTTP
est remplacé par des réponses synthétiques.
