# 0086 — Preuves exécutables de non-régression et CI du dépôt distant

Statut : accepté. Date : 11 septembre 2026.

## Décision

Les garanties critiques sont protégées par des scénarios métier, des contrôles négatifs
et des preuves conservées dans les rapports de CI. Une mutation est détectée seulement
si une baseline réussit puis si son affaiblissement provoque un échec d'assertion métier.
Une erreur de collecte ou de dépendance ne compte pas. Les expériences utilisent des
copies temporaires et la base éphémère du runner backend.

La couverture agrégée conserve son seuil historique ; des planchers séparés de lignes et
branches par domaine empêchent un domaine facile de masquer un domaine critique. Leur
révision est explicite. Les branches critiques modifiées sont examinées par rapport au
commit de base de la demande de fusion. Le registre `project/regressions.json` lie les
incidents ou lacunes de tests disposant d'une mutation permanente à leurs preuves exécutées.

Le dépôt distant étant hébergé sur GitLab, une configuration native reprend les contrôles
existants. Les workflows GitHub restent disponibles pour un miroir. L'activation des
protections de fusion et l'affectation du runner demeurent des opérations distantes ; la
présence de fichiers YAML ne prouve pas qu'elles ont eu lieu.

Les qualifications de modèles et de bridges sont distinctes des tests déterministes.
Les campagnes Lab comparent le même corpus et le même juge, avec budget explicite et seuils
par catégorie. Une note de modèle ne prouve pas une action externe. Le premier parcours
Matrix réel exige deux comptes de test distincts et vérifie la réception exacte du texte
et du fichier. Ces parcours ne s'exécutent pas dans la CI générale et ne choisissent pas
implicitement des comptes, une destination ni un budget utilisateur.

## Conséquences

Les suites continuent de tester les vrais services et écritures ; les frontières externes
restent remplaçables. Les injections SIGKILL ne visent que les sous-processus et bases
éphémères créés par les tests. Les effets d'un fournisseur simulé ne certifient pas les
capacités du fournisseur réel.

Les rapports conservent échecs, ignores, durées, branches et mutations. Les répétitions
servent à diagnostiquer l'instabilité ; elles n'effacent aucun échec. Aucun objectif de
nombre de tests ni promesse d'absence absolue de régression n'est introduit.
