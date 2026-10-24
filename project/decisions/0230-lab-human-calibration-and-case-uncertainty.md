# 0230 — Étalonnage humain et incertitude par cas du Lab

- Statut : accepté et implémenté.
- Date : 2026-10-24.

Le Lab calcule l'étalonnage à partir des revues immuables de l'utilisateur authentifié
et des jugements de la même campagne. Une revue d'agent n'est jamais une référence
humaine. Aucun jugement non révélé n'entre dans le bilan ; un jugement absent, en erreur
ou sans verdict exploitable reste inconnu. La couverture revus/éligibles est explicite.
Le rapport expose faux passages/rejets, biais signé, écart absolu et biais par dimension.
La campagne conserve le snapshot de rubrique et les références de juge ; le rapport
reste reconstructible depuis cette campagne et ces revues, sans modifier leurs notes.

Les observations partageant entrée et référence forment un groupe. Les moyennes donnent
le même poids à chaque groupe, quelle que soit sa répétition. L'écart de qualité entre
runs comparables et les écarts de calibration utilisent un bootstrap percentile par
groupe à 95 %, 2 000 rééchantillonnages, graine 0 et méthode versionnée. Les comparaisons
incompatibles ne produisent pas d'intervalle. Le taux de faux passages parmi les échecs
humains utilise une borne de Hoeffding sur les moyennes par groupe, bornées à [0, 100],
afin qu'aucun faux passage observé ne signifie pas une incertitude nulle.

Moins de deux groupes ne produit aucun intervalle. Moins de 20 groupes déclenche un
avertissement ; ce seuil de restitution ne prouve pas l'indépendance ni la représentativité.
Les calculs s'exécutent hors de la boucle API. Les résultats sont conditionnels au corpus
et au juge ; le protocole ne sépare pas la variabilité du candidat de celle du juge.
La répétabilité du juge, l'arbitrage multi-humain, les campagnes d'étalonnage réellement
annotées et les gardes CI restent des travaux distincts. Aucune certification humaine
n'est déduite de fixtures synthétiques ou de l'implémentation du rapport.

Les tests protègent regroupement des répétitions, poids des cas, inconnus, isolation par
utilisateur/campagne et refus de comparaison non comparable. Le parcours navigateur
préserve la revue avant révélation et affiche l'insuffisance d'échantillon.
