<p align="right"><strong>Français</strong> · <a href="../../en/dev/palette-solaire.md">English</a></p>

# Palette Solaire — référence de l’application

Référence validée le 10 septembre 2026. Cette palette définit les couleurs à utiliser dans
toute l’interface Galaris : navigation, icônes, boutons, blocs, badges, états, dialogues et
graphiques, dans les modules `core`, `app` et `bridge`.

La palette contient exactement **11 couleurs et 33 nuances**. Les valeurs ci-dessous sont
celles du dernier aperçu approuvé, complétées par le gris neutre ; elles remplacent les
propositions précédentes.
La [décision 0081](../../../project/decisions/0081-solaire-color-reference.md) acte leur adoption.

## Valeurs exactes

| Clé stable | Couleur | Accent vif | Fond clair | Fond sombre |
|---|---|---|---|---|
| `yellow` | Jaune soleil | `#FFE610` | `#FFF4DE` | `#383517` |
| `orange` | Orange solaire | `#FF9A00` | `#FFF7EB` | `#382A15` |
| `salmon` | Saumon | `#FA8072` | `#FFF5F4` | `#382725` |
| `red` | Rouge solaire | `#F43636` | `#FEEFEF` | `#371C1C` |
| `fuchsia` | Fuchsia | `#D936B5` | `#FCEFF9` | `#331C2E` |
| `violet` | Orchidée | `#AD3CE6` | `#F8EFFD` | `#2D1D35` |
| `iris` | Violet iris | `#854CF0` | `#F5F1FE` | `#271F36` |
| `blue` | Bleu lumineux | `#087FF5` | `#EBF5FE` | `#162637` |
| `cyan` | Cyan | `#00B8D4` | `#EBF9FC` | `#152E32` |
| `green` | Vert feuille | `#11A653` | `#ECF8F1` | `#172C20` |
| `gray` | Gris neutre | `#808080` | `#F5F5F5` | `#272727` |

Les clés sont des identifiants Solaire, pas les noms des couleurs natives de Quasar.
En particulier, `violet` désigne Orchidée et `iris` désigne Violet iris.

## Règles d’usage

- Employer les accents vifs pour les repères colorés et les fonds correspondants pour les
  surfaces teintées. Un bloc conserve sa famille de couleur lors du passage d’un thème à l’autre.
- Utiliser les valeurs exactes via une définition partagée lors de leur intégration au code.
  Ne pas disperser les hexadécimaux dans les composants, recalculer des variantes par module,
  ni remplacer une valeur par une couleur Quasar simplement ressemblante.
- Garder les surfaces générales et les textes neutres. L’aperçu approuvé utilise `#FFFFFF`
  et `#101010` pour les surfaces générales claires et sombres, avec respectivement `#292C30`
  et `#EEEEF0` pour les textes. Ces neutres ne sont pas des accents supplémentaires.
- Choisir un texte neutre lisible sur chaque fond ; un accent vif ne garantit pas à lui seul
  la lisibilité d’un petit texte. Accompagner les états d’un libellé ou d’une icône.
- Conserver une signification cohérente des couleurs entre les écrans. La palette ne requiert
  pas d’utiliser les onze couleurs simultanément dans chaque composant.
- Toute évolution des couleurs doit mettre à jour la référence commune et sa traduction.
  Les anciens fichiers d’exploration sous `work/` ne font pas autorité.

**Couleurs écartées :** Ambre, Mandarine, Corail, Framboise, Rose vif, Azur, Jade et Émeraude.
Ne pas les réintroduire comme accents supplémentaires.

## Origine des fonds validés

Les valeurs ont été obtenues par interpolation des canaux sRGB, arrondis à l’entier le plus
proche, puis validées visuellement :

- fond clair : 8 % de l’accent et 92 % de blanc `#FFFFFF` ;
- exception jaune clair : 14 % de `#FFB010` et 86 % de blanc, soit `#FFF4DE` ;
- fond sombre : 14 % de l’accent et 86 % de `#181818`.

L’exception du jaune s’applique uniquement à son fond clair. Son accent vif reste `#FFE610`.
Les hexadécimaux du tableau sont la référence à consommer, sans interpolation supplémentaire.

## Adoption

### Source unique et variables CSS

Les 33 valeurs sont définies une seule fois dans `front/core/util/solaire.ts`.
`solaireTheme.ts` en dérive automatiquement une feuille globale :
`--solaire-blue-accent`, `--solaire-blue-light`, `--solaire-blue-dark`, et les mêmes
variables pour les dix autres couleurs. Il n’y a pas de copie de la palette en SCSS.

Dans les styles, utiliser `var(--solaire-blue-accent)`. Pour une couleur choisie
dynamiquement, importer `solaireCss` depuis `@/core/util` :
`solaireCss[color].accent`, `.light` et `.dark` sont des références à ces variables.
Le tableau `solaire` contenant les valeurs littérales reste réservé aux exports.
Modifier une nuance dans la source actualise ses consommateurs au rechargement Vite
en développement et à la prochaine construction en production. Les trois nuances
d’une couleur restent explicites, conformément aux valeurs approuvées ci-dessus.

Préférences, Laboratoire, les dossiers et la coloration du code
consomment ces variables. Les dossiers sont rendus en SVG intégré : aucune
régénération d’image n’est nécessaire pour leur affichage. Les documents autonomes
pour l’impression et l’export embarquent la feuille issue de la même source.
Les tests `front/browser-tests/solaire.spec.mjs` vérifient qu’une modification globale
se propage aux consommateurs existants dans les deux thèmes.

La page « Modèles utilisés » applique les fonds Solaire clairs ou sombres aux en-têtes
des familles d’usages. Ses tableaux et contrôles conservent les couleurs du thème de l’interface.

Cette référence fixe la cible de tous les changements visuels. Son adoption documentaire ne
signifie pas que tous les styles historiques ont déjà été remplacés dans le runtime.
L’harmonisation du code doit reprendre ces valeurs et vérifier le rendu dans les deux thèmes.
