# 0081 — Solaire comme référence chromatique de toute l’application

Statut : accepté — 10 septembre 2026.

L’utilisateur a validé la palette Solaire après comparaison et ajustement des accents, des fonds
clairs et des fonds sombres. Complétée à sa demande par le gris neutre, la sélection conserve
onze couleurs et exclut Ambre, Mandarine, Corail, Framboise, Rose vif, Azur, Jade et Émeraude.

## Décision

- La [référence Solaire](../../docs/fr/dev/palette-solaire.md) fixe les onze triplets exacts
  accent/fond clair/fond sombre à utiliser dans toute l’interface Galaris.
- Cette référence s’applique aux modules `core`, `app` et `bridge`, y compris aux icônes et
  aux graphiques. Les variantes historiques ne constituent pas une palette alternative.
- Le jaune clair conserve son ajustement propre, distinct du calcul des autres fonds clairs.
- `AGENTS.md` et les guides développeur renvoient à cette référence pour les changements visuels.
- L’intégration au runtime doit centraliser ces valeurs et préserver leur identité entre
  thèmes, avec des textes lisibles et une sémantique cohérente.

## Conséquences

La palette est une décision de design acceptée. Cette décision et sa documentation ne réalisent
pas à elles seules le remplacement de tous les styles historiques. L’harmonisation de ces styles
doit être vérifiée dans les deux thèmes et ne doit pas réintroduire les couleurs écartées.
