# 0079 — Vérifier les comportements frontend dans leur environnement réel

Statut : accepté — 7 septembre 2026.

L'audit des tests a montré des contrôles de texte source qui refusent un CSS équivalent
ou acceptent une régression de visibilité. L'utilisateur demande la mise en œuvre de
l'audit hors Lab, actuellement réécrit séparément.

## Décision

- Exécuter les modules et stores pour les contrats unitaires, les vrais composants Vue
  avec Quasar dans Chromium pour les interactions et styles, et conserver les parcours
  E2E avec backend réel pour l'intégration complète.
- Réutiliser l'image Playwright existante, avec un serveur Vite de test et des réponses
  HTTP explicites. Toute API non prévue fait échouer le scénario. Le banc de composants
  n'est pas une qualification d'un fournisseur externe.
- Ajouter `make tests-front-components` au contrôle local et un job obligatoire à la CI.
  Les artefacts d'échec et logs restent disponibles après nettoyage du projet isolé.
- Conserver les tests statiques lorsque la structure est le contrat. Retirer les
  assertions de détail visuel ou textuel sans leur attribuer une garantie fictive.
- Conserver le test d'efficacité de la porte TypeScript dans `test:tooling`, hors de
  la collecte unitaire rapide, mais dans la CI et `make quality`.
- Mesurer la couverture critique pendant l'exécution backend complète, une seule fois.
  Le seuil de 70 % reste agrégé sur la sélection de `coverage-critical.ini`.

## Conséquences

Les tests de composants valident le code applicatif avec un serveur simulé ; ils ne
prouvent pas la connectivité réelle de WhatsApp, Telegram, Matrix ou d'un autre fournisseur.
Les évaluations déterministes restent des preuves de contrats et de règles, pas de qualité
générale d'un modèle. Aucun compte externe ni plateforme supplémentaire n'est créé.

La [traçabilité de mise en œuvre](../audits/2026-09-07-test-suite-improvements.md) distingue
remplacements, consolidations et contraintes abandonnées. Les portions de tests relatives
au Lab et au déplacement concomitant du journal d'incidents sont préservées.

## Extension du 10 septembre 2026

L’utilisateur généralise la démarche module par module, Lab compris, en partant du métier.
Le [catalogue fonctionnel](../../docs/fr/dev/functional-tests.md) relie les garanties aux suites.
Les dimensions d’écran deviennent des conditions d’usage ; aucune géométrie ni couleur de
contrôle n’est figée pour conserver une ancienne demande de présentation. Les tests de contenu
imprimable, de sélection d’un style documentaire, d’accès aux actions et de conservation d’un
brouillon gardent leur portée fonctionnelle.

Les tests d’intégration conservent les services et la persistance réels ; les unités restent
adaptées aux règles pures. On renforce les scénarios existants avant d’en ajouter, et on consigne
chaque garantie reprise ou contrainte abandonnée. La nouvelle
[revue de mise en œuvre](../audits/2026-09-10-functional-tests.md) distingue les résultats
exécutés de l’inventaire et ne qualifie pas les comptes externes ni la qualité d’un modèle réel.
