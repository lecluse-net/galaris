# 0108 — Index documentaire complet et admission du rappel mémoire

Statut : accepté — 17 septembre 2026. Implémentation et tests du périmètre validés ;
voir le [rapport](../audits/2026-09-17-memory-document-retrieval.md).

Les documents participent à la recherche canonique Memory. Une recherche `memory://`
retourne les natures autorisées ; `document://` restreint les résultats aux documents.
La nature réelle détermine l’URI et les capacités, indépendamment de la collection interrogée.
Le modèle d’embeddings est exclusivement celui configuré dans le profil courant.

## Index reconstruisible

Les writers enregistrent une intention de projection dans la transaction du contenu,
y compris pour une description de pièce jointe. L’intention ne requiert ni fournisseur
disponible ni modèle sélectionné. Le worker résout la configuration à l’exécution et
traite la version courante ; les intentions dépassées deviennent sans effet lorsqu’une
génération complète existe déjà. La réconciliation périodique répare les absences et
la réconciliation DbAdmin prend en charge les données préexistantes.

`MemoryEmbeddingManifest` décrit la génération publiée : empreinte source, espace vectoriel,
version du pipeline, dimensions, nombre de fragments, couverture et date. Les fragments
et le manifeste sont publiés dans la même transaction, après verrouillage de l’item et
comparaison de son empreinte et du modèle courant. Le fournisseur est appelé en dehors
de cette transaction. Un fragment manquant, une mauvaise dimension ou un vecteur nul
invalide la génération pour le rappel canonique.

L’empreinte inclut le digest du contenu HTML : une restructuration qui conserve les mêmes
mots peut déplacer les blocs et exige de nouveaux ancrages. Les blocs, listes, tableaux
et code sont conservés autant que leur taille le permet ; les blocs trop longs sont
découpés avec recouvrement. Les positions sont des offsets de blocs, à base zéro et fin
exclusive, associés à la révision restituée. Le plafond technique est de 4 096 passages ;
son dépassement est une erreur explicite, jamais une publication silencieusement tronquée.

Une indisponibilité réseau, un quota ou une panne serveur entraîne un backoff commun
et n’épuise pas le budget d’essais du document. Les contenus et réponses invalides restent
soumis au budget d’essais. Un rebuild forcé peut reprendre une erreur permanente.
Le changement de modèle interdit de servir l’ancien espace ; le repli lexical est signalé.

## Admission des résultats

Les candidats sémantiques transportent des métadonnées détachées de l’identity map.
Les deux lectures comparent révision, version optimiste et empreinte ; elles ne peuvent
associer un ancien passage à un objet modifié entre les lectures. Le lexical utilise
le texte de recherche de la même révision SQL et produit un extrait centré sur la requête.

Toutes les sorties du rappel canonique, y compris les replis, passent une admission SQL
commune : existence, période de validité, droits actuels, scope, révision, version optimiste,
empreinte et chemins exposés. Les références de provenance sont relues à cette occasion.
Le point d’admission est le snapshot de cette instruction en `READ COMMITTED`. Les commits
de révocation visibles à ce point excluent le résultat ; ceux postérieurs s’appliquent à
l’admission suivante. Les sessions à snapshot figé échouent fermées. Cette convention ne
promet pas de retirer des octets déjà admis ou transmis et ne garde aucun verrou réseau.
Un retrait est déclaré dans `admission_omitted_count` et la réponse devient partielle.

Le brief réadmet ensemble les pages ordinaires et d’expérience avant d’allouer son budget.
Les providers de contexte peuvent déclarer `refreshes_frozen_kinds`. Memory déclare la
nature `memory` : une reprise recherche de nouveau les mémoires avec les droits actuels.
L’assembleur remplace ces entrées et régénère le rendu de la capsule. Un échec du provider
retire ses anciennes entrées ; les autres natures conservent leur mécanisme de continuité.

## Pertinence et preuve

Le canal global reste indépendant du Topic. Un document contribue une seule candidature,
avec au plus trois passages sélectionnés parmi les candidats lexicaux et vectoriels,
sans votes supplémentaires liés à sa longueur. L'enrichissement lexical ne lit que les
générations complètes du modèle configuré ; ses preuves de révision sont comparées à
celles du résultat avant l'admission commune. Les localisations proviennent des fragments
indexés, pas d'un offset inventé depuis l'extrait.
Les liens structurels traversent les natures intermédiaires autorisées avant d’appliquer
la restriction de nature aux résultats. Les URI et UUID exacts évitent un appel vectoriel.
Les résultats fichiers conservent mode effectif, dégradation, couverture et limite de fenêtre.

Après la campagne réelle et les ablations du 17 septembre, le classement
`memory-query-evidence/v10` donne priorité à la couverture des termes de la question,
pondérée par leur rareté parmi les candidats. Les URI/UUID et titres exacts restent
prioritaires. Les poids configurés répartissent le signal lexical/vectoriel et les bonus
contextuels ; ces derniers sont désormais bornés à un rôle secondaire (0,03 avant
normalisation). Ils ne peuvent admettre un résultat sans preuve directe. La diversité ne
peut inverser les classes de preuve et sa pénalité est plafonnée à 0,05.

Le filtre lexical reconnaît les flexions courantes et une faute sur les mots longs ;
la requête PostgreSQL utilise des préfixes de termes contrôlés. Les compléments nommés
explicites et identifiants littéraux contribuent au classement par les termes correspondants,
sans exclure les autres candidats. Le rappel restitue les meilleurs candidats disponibles
jusqu'à la limite demandée, **sans seuil d'admission lexical ou vectoriel**. Un incident
conversationnel a montré que le seuil v8 pouvait dépasser le meilleur candidat et vider le rappel.
La correction intermédiaire v9 par médiane du corpus est abandonnée : la décision retenue
privilégie le rappel et laisse l'agent évaluer l'utilité des souvenirs proposés. Aucun calcul
de médiane, dictionnaire de remplacement ou appel de modèle supplémentaire n'est ajouté.
Le modèle configuré et les contrôles d'admission SQL restent inchangés.

Les voisins structurels doivent eux aussi porter des termes pertinents. Les candidats
identiques en titre et empreinte sont dédupliqués, sauf identité ou titre explicitement
demandés. Une similarité vectorielle élevée ne supprime plus une information distincte :
le seuil `MEMORY_DUPLICATE_SIMILARITY_THRESHOLD` conserve son rôle dans l'acquisition,
la maintenance et la prévisualisation de fusion, mais ne supprime plus de résultats du rappel.

Le moteur peut retourner moins que la limite demandée si les candidats manquent, sont
redondants ou ne passent plus l'admission SQL. Une recherche URI/UUID reste une résolution
exacte. Sans embeddings utilisables, le repli conserve les correspondances lexicales.
`relevance_status=no_sufficient_evidence` reste le libellé de compatibilité d'une liste vide ;
`matched` signifie que des candidats ont été restitués, pas que la réponse est démontrée.
Un corpus sans réponse peut donc produire des candidats : la présence de hits n'est plus
une mesure d'abstention attendue, et les scores ne sont pas des probabilités de vérité.
Les diagnostics de couverture et de dégradation restent distincts. La campagne et les
limites connues sont consignées dans le [rapport v8](../audits/2026-09-17-memory-ranking-v8.md).

Les compteurs d’accès restent des observations d’exposition. Le banc déterministe ajoute
nDCG et taux de faux positifs sur les questions sans réponse ; plusieurs passages du même
document ne peuvent augmenter artificiellement le recall.

Les scénarios PostgreSQL couvrent les modifications concurrentes, le repli, les capsules,
la publication incomplète, la reconstruction, la fin d’un long document et le changement
de configuration. Les embeddings y sont substitués : ces tests prouvent les contrats,
pas la qualité linguistique du fournisseur sur le corpus de production.
