<p align="right"><strong>Français</strong> · <a href="../../en/admin/product-knowledge.md">English</a></p>

# Donner la connaissance de Galaris à un agent

Tout agent peut expliquer Galaris et guider ses utilisateurs sans changer de mission ni de
personnalité. La capacité repose sur la documentation officielle de la version installée,
une recherche hybride et le skill système **Connaissance de Galaris** (`galaris-knowledge`).

## Activation

1. Dans **Configurer → Outils & connexions → Connexions** (`/tools?tab=connections`),
   activer la connexion **Galaris Admin** de l'agent.
2. Dans les autorisations de cette connexion, conserver `documentation_catalog` et
   `documentation_search` autorisés.
3. Pour un accès documentaire seul, désactiver `conversation_round_get`, `voice_turn_get`,
   `llm_call` et `llm_calls`. Ces fonctions donnent accès à des données d'exécution sensibles ;
   elles ne sont pas nécessaires à la connaissance du produit.
4. Activer le **mode conversation** du Tool pour que ses fonctions soient proposées dans le Chat.
5. Autoriser `galaris-knowledge` pour l'agent dans les attributions de compétences. Son
   défaut global est désactivé ; les réglages de compétence et de catégorie restent applicables.
   Sa projection effective exige également l'autorisation `documentation_catalog`.

La connexion Galaris Admin reste inactive par défaut. L'activation seule conserve la cascade
habituelle d'autorisations des fonctions : désactiver explicitement les inspections pour un
agent chargé uniquement d'aider les utilisateurs.

Le skill apporte les concepts fondamentaux, la méthode de recherche et les limites de
l'assistance. Il est disponible aux exécutions suivantes selon le mécanisme normal des skills,
pour le harnais interne et les harnais externes compatibles. Une conversation ou exécution déjà
engagée peut conserver les instructions déjà chargées ; les appels restent contrôlés côté serveur.

## L'assistant Galaris fourni à l'installation

L'assistant Galaris reçoit déjà l'accès documentaire et cette compétence lors de sa création.
Le harnais interne charge son guide produit dès la première requête du modèle en conversation
texte, en voix par tours et en Task : concepts, recherche des sources, vérification des menus
et distinction entre fonctions livrées et projets. Ce chargement reste soumis aux attributions
et droits effectifs ; il n'active aucune connexion ni fonction. Il repose sur la configuration
de la compétence, sans dépendre du nom, du code ou du marqueur d'installation de l'agent.

### Politique de chargement des compétences

Le fichier facultatif `runtime.yaml` à la racine d'une compétence configure son chargement
dans le harnais interne : `loading: eager` charge les instructions dès la première requête
en Task, conversation texte et voix par tours. Sans fichier, ou avec `loading: deferred`,
le chargement reste à la demande en Task ; ce mécanisme ne l'ajoute pas aux conversations.
Une configuration invalide conserve ce défaut. Le frontmatter de `SKILL.md` reste inchangé.

La compétence système `galaris-knowledge` fournit `loading: eager`. Tout agent auquel elle
est effectivement attribuée avec le droit documentaire bénéficie donc du même chargement.
Le fichier ne donne aucun droit et n'active aucune compétence ; le défaut global de cette
compétence reste désactivé. Les compétences utilisateur peuvent fournir le même fichier
via leur éditeur de ressources. Les harnais externes conservent leur propre mécanisme.

Les outils restent ceux autorisés dans le contexte courant. Si la recherche n'est disponible
qu'en Task, une lecture directe d'une source connue reste possible avec `file_read` et le droit
documentaire ; la recherche peut être confiée à une Task. Le mode voix temps réel conserve son
inventaire limité et son recours aux Tasks. Les compétences sans configuration conservent
leur chargement habituel.
Ces consignes et le RAG ne garantissent pas à eux seuls l'exactitude de chaque réponse : vérifier
les sources citées et les outils employés dans l'activité de la conversation.

## Recherche et lecture

Le [guide de navigation](../user/navigation.md) décrit les parcours et onglets ; la
[carte des menus](../architecture/generated/navigation.md), générée depuis le frontend,
fournit routes, libellés traduits et conditions de visibilité. Ces sources font partie
du corpus recherché et des points d’entrée du catalogue. Le skill les utilise pour
indiquer **section → écran → onglet → action**, sans présumer des droits du compte humain.

`documentation_catalog` indique la version, les langues, les domaines et les points d'entrée.
Cette fonction porte aussi le droit de lire les sources sous `galaris://documentation/`.
`documentation_search` accepte une question et les filtres `language`, `domain`, `kind` et
`path_prefix`. Il renvoie les titres, sections, extraits, statuts et empreintes des sources.

```text
documentation_search(query="Comment partager un document ?", language="fr", domain="user")
file_read(uri=<uri du résultat>, offset=<offset>, max_chars=<max_chars>)
```

Les offsets sont des caractères Unicode, à partir de zéro. Les longues lectures fournissent
`next_offset`. `file_list` parcourt les sources avec un curseur ; un changement de corpus rend
ce curseur périmé et demande de recommencer la liste. Les sources conservent leur format natif
Markdown, JSON ou HTML et restent en lecture seule. La recherche spécialisée est fournie par
`documentation_search`, plutôt que par `file_search` sur cette collection.

La documentation couvre `docs/`, les décisions et les plans du projet. Un plan est identifié
comme prospectif et conserve son statut ; son approbation ne prouve pas qu'il soit réalisé.
Les décisions expliquent l'historique, tandis que les guides courants sont prioritaires.

## Mettre à jour la documentation et sa recherche

Après une modification de documentation ou de navigation, dans le dépôt de développement :

```bash
make docs-update
```

Cette commande régénère les cartes du projet et des menus, vérifie leur fraîcheur, la
présence des guides FR/EN et les liens documentaires, puis compare les sources préparées
avec celles réellement visibles dans le backend actif. Elle synchronise l’index textuel
commun et vérifie la recherche et la lecture des guides de navigation dans les deux langues.
Les mises à jour concernent tous les agents déjà autorisés ; aucun droit ni affectation
de skill n’est modifié. Aucun redémarrage n’est nécessaire pour une édition documentaire.

Si les montages ou l’image du backend sont anciens, la commande échoue explicitement :
appliquer alors `make update` en développement. Une différence de corpus ne doit pas être
masquée par une copie ponctuelle de fichiers dans un conteneur.

Pour préparer les sources sans backend démarré, utiliser `make docs-prepare`.
`make docs-check` vérifie les sources sans les régénérer. Ces vérifications détectent une
traduction absente, mais ne rédigent pas les traductions et ne vérifient pas leur exactitude
sémantique : actualiser les guides et parcours concernés en français et en anglais.

Avant publication, lancer `make validate` sur les sources préparées. En production, utiliser
la mise à jour normale de la version validée : `make update`, ou `make update RELEASE_DIR=…`
pour un paquet d’images qualifié. Générer et vérifier les cartes avec `make docs-prepare`
en développement, puis les committer avec les changements de sources. Dans tous les
environnements, dont `dev`, `demo` et `prod`, `make update` embarque cette documentation
préparée, sans régénérer les cartes ni relancer les contrôles documentaires statiques.
Après démarrage, la commande actualise l’index textuel commun
et vérifie le résultat. Aucun `docs-update` préalable n’est nécessaire.
Avec `RELEASE_DIR`, elle actualise cet index depuis la documentation déjà générée et embarquée
dans les images qualifiées, sans modifier ces images. Un échec de l’actualisation ou de son
contrôle empêche d’annoncer la réussite du déploiement.
Ce contrôle ne restaure pas automatiquement une ancienne version déjà remplacée.
Les paquets distribués sont également contrôlés à la construction et dans leurs tests E2E.

Le contrôle imprime l’empreinte du contenu, celle du corpus, la version et le nombre de
passages indexés. Les embeddings continuent à se mettre à jour en arrière-plan si un modèle
vectoriel est configuré ; leur achèvement et la disponibilité du fournisseur ne bloquent
pas la recherche textuelle ni la mise à jour. Les conversations déjà engagées conservent
leurs anciennes réponses : une nouvelle lecture documentaire utilise les sources actuelles.

## Disponibilité de la recherche

La recherche textuelle et les correspondances exactes fonctionnent sans modèle vectoriel.
Avec le modèle vectoriel configuré, l'index s'enrichit progressivement en arrière-plan, puis
la recherche combine résultats textuels et sémantiques. Un modèle absent, une panne ou un index
incomplet sont signalés dans le résultat. Les passages inchangés ne sont pas réencodés.

Sous forte charge, l'indexation traite huit passages au maximum par lot, avec un délai
de 60 secondes pour le fournisseur. Après un échec, ce job attend 1, 2, 4, 8 puis au maximum
10 minutes entre les tentatives, par processus backend. Un succès rétablit sa cadence normale
de 30 secondes. Un avertissement indique le type d'échec et le délai avant reprise.
Les lots validés restent conservés ; les nouveaux passages sont accessibles en recherche
textuelle avant le calcul des embeddings. Les recherches interactives gardent leur délai
court et peuvent s'exécuter en parallèle des autres appels LLM et de l'indexation.

Les fichiers sont embarqués dans les images backend ; les mises à jour de Galaris actualisent
le corpus. En développement, les sources documentaires sont montées en lecture seule et leurs
modifications sont détectées automatiquement. L'empreinte du corpus identifie exactement les
sources, y compris lorsque le libellé de build est inconnu.

La désactivation de la connexion ou de `documentation_catalog` bloque également les lectures
directes d'URI connues, les métadonnées et les copies. Désactiver `documentation_search` bloque
la recherche tout en conservant la lecture si le catalogue reste autorisé.

Cette capacité ne prouve ni les droits de l'utilisateur accompagné, ni l'état réel de ses
connexions ou paramètres. L'agent doit vérifier ces éléments avec les outils effectivement
autorisés, ou demander le détail manquant. L'accès à la documentation n'autorise aucune mutation.
