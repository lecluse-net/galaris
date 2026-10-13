# 0180 — Profil LLM secondaire par agent

Statut : accepté. Date : 2026-10-13.

## Garantie

Un agent peut poursuivre une inférence lorsque son fournisseur principal est surchargé
ou inaccessible, sans rejouer sa boucle d'outils. Les permissions Galaris, budgets,
et annulations ne déclenchent pas ce secours. Un refus exprimé dans une réponse normale
du modèle n'est pas une erreur fournisseur. La classification HTTP inclut tous les
statuts 401, 403, 404, 408, 429, 500, 502, 503, 504 et 529 ; elle ne distingue pas
les différents motifs de quota ou d'accès à l'intérieur d'un même statut.

## Décision

`agents.profile_id` conserve sa signification : `NULL` suit le profil courant.
`agents.fallback_profile_id` référence un profil secondaire facultatif ; `NULL` désactive
le secours. La suppression d'un profil détache ces références par les clés étrangères.
L'API valide les deux sélections et le formulaire les présente dans l'onglet Modèles.

La sélection conserve le même usage et son effort de raisonnement dans le second profil.
Un usage secondaire vide, un modèle identique ou un profil identique ne crée pas d'essai
supplémentaire. Les candidats explicites du Lab restent fixes. Les modèles et la sélection
secondaire sont figés à l'admission des inférences durables et à la construction du modèle
pour le harnais interne.

`app.llm` possède la bascule, bornée à un essai du second modèle pour la requête courante.
Le harnais interne conserve le secondaire pour la suite du run et recommence par le
principal lors d'un nouveau run. Les erreurs d'accès fournisseur, surcharges, erreurs
réseau et HTTP temporaires sont distinguées des refus d'autorisation locaux. Les deux
fournisseurs traversent les contrôles d'accès et la comptabilité habituels.

Le stream interne conserve les événements progressifs. Après une erreur, le second
modèle reçoit le même historique acquis ; seule sa réponse complète entre dans l'historique
du modèle. Les reçus des outils terminés restent acquis. Les appels physiques ont chacun
leur identité, résultat terminal et coût. `LLMCall` conserve le profil secondaire,
le modèle principal remplacé et le motif de la bascule ; la requête d'inférence conserve
aussi sa sélection figée. Une erreur SSE après HTTP 200 reste un échec fournisseur.

Les gateways bruts peuvent basculer avant la publication de la réponse. Un flux brut déjà
publié ne mélange jamais les octets de deux fournisseurs. Les opérations de compaction,
les sélections explicites de l'API par profil, les médias génératifs, les embeddings et
les connexions voix natives conservent leurs contrats propres.

## Vérification

Les reproductions utilisent uniquement des fournisseurs HTTP synthétiques et PostgreSQL
éphémère. Elles couvrent une surcharge au milieu du flux après un outil confirmé, les
erreurs d'accès et de réseau, l'échec du secours, les résultats terminaux des deux appels
et l'édition d'un profil après préparation d'une inférence. Le parcours Vue/Quasar vérifie
la conservation, la sauvegarde, la réouverture et la remise à vide du profil secondaire.
