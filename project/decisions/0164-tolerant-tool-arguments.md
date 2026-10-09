# 0164 — Paramètres inconnus tolérés à la frontière MCP

Statut : accepté. Date : 2026-10-08.

## Décision

Un modèle peut inventer un argument, y compris pour une fonction sans paramètre. Le rejet
de cet argument seul crée un appel supplémentaire inutile et n'aide pas le modèle à
identifier le contrat disponible.

La frontière commune des outils natifs et des proxies MCP externes retire les clés de
premier niveau absentes d'un schéma fermé avant validation et autorisation. Les adaptateurs
externes Pydantic AI appliquent la même règle avant de demander l'accord. La signature de
chaque outil et le catalogue restent précis : aucune fonction n'accepte implicitement
des paramètres supplémentaires.

La réponse MCP conserve son contenu et sa sortie structurée. Elle ajoute un bloc texte et
une métadonnée `galaris.tool-arguments/v1` avec les noms ignorés, disponibles et obligatoires.
Les valeurs ignorées ne figurent pas dans cet avertissement. L'adaptation interne Pydantic AI
associe la sortie structurée et l'avertissement dans sa projection modèle pour les réponses
textuelles : le SDK privilégie sinon la sortie structurée et masque les autres blocs texte.
Les réponses multimédias conservent leurs blocs de contenu, avec l'avertissement ajouté.
Le checkpoint conserve la réponse
ainsi transmise au modèle et les arguments originaux pour identifier l'appel lors de la reprise.

## Garanties conservées

- Les paramètres requis, types et valeurs restent validés avant effet. Un rejet natif rappelle
  les noms disponibles et obligatoires sans reprendre les valeurs invalides.
- Les dictionnaires ouverts et leurs schémas `additionalProperties` ne sont pas réduits à
  leurs seules propriétés nommées. Les clés admises par `patternProperties` sont conservées.
- Les schémas composés ou référencés à la racine restent soumis à leur validation existante :
  la normalisation n'infère pas une liste complète de clés à partir d'une branche.
- Les objets métier imbriqués restent intacts : aucun filtre ne supprime du contenu utilisateur.
- L'accord humain porte sur les arguments réellement exécutés. Changer une clé ignorée ne
  change pas l'action approuvée ; changer un paramètre effectif conserve les contrôles existants.
- Révocation, isolation des agents, preuves d'exécution et reprise sans duplication restent
  applicables. Les appels valides sans correction gardent leur résultat habituel.

## Vérification

Les tests synthétiques du loader reproduisent le rejet puis vérifient le succès pour les
runtimes interne et Hermès. Les scénarios existants d'accord, de révocation et de rotation
des credentials sont renforcés avec des arguments inconnus. Les tests de schéma couvrent
les entrées ouvertes, les motifs, les compositions et la validation imbriquée. Un véritable
agent Pydantic AI utilisant un modèle déterministe reçoit l'avertissement ; son checkpoint
le rejoue sans nouvel effet. Aucun changement de production n'est appliqué par cette décision.
