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
5. Vérifier les attributions de compétences : `galaris-knowledge` est activé globalement par
   défaut, mais les réglages de compétence et de catégorie peuvent le désactiver pour un agent.
   Sa projection effective exige également l'autorisation `documentation_catalog`.

La connexion Galaris Admin reste inactive par défaut. L'activation seule conserve la cascade
habituelle d'autorisations des fonctions : désactiver explicitement les inspections pour un
agent chargé uniquement d'aider les utilisateurs.

Le skill apporte les concepts fondamentaux, la méthode de recherche et les limites de
l'assistance. Il est disponible aux exécutions suivantes selon le mécanisme normal des skills,
pour le harnais interne et les harnais externes compatibles. Une conversation ou exécution déjà
engagée peut conserver les instructions déjà chargées ; les appels restent contrôlés côté serveur.

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
