# 0294 — Snapshots frontend par session et surfaces publiques

Statut : accepté, implémenté.

## Garantie

Une lecture ou un enregistrement asynchrone ne doit pas remplacer les données d'un
autre utilisateur, rôle, fichier sélectionné ou formulaire rouvert. Les indicateurs
partagés restent actifs tant qu'une opération correspondante est en cours.

## Décision

Les stores de catalogues utilisent `withSessionScope`, dans la surface légère de
`core.util`. Cette composition Pinia réinitialise les snapshots au changement réel de
session ou de rôle et à la déconnexion, conserve les données pendant un renouvellement
de token, agrège les opérations concurrentes et expose leurs diagnostics par action.
Les rejets des anciennes réponses restent garantis à la frontière HTTP. Les éditeurs
et préférences locales ne sont pas réinitialisés par cette composition.

Les lectures exclusives conservent leur propre génération : fichier Skill, aperçu
Onboarding, listes filtrées, modale Topic et contexte MCP Agent. Leur indicateur décrit
la sélection courante, et non toutes les requêtes devenues obsolètes. Une fin de sauvegarde
ne ferme que l'ouverture qui l'a déclenchée. Le polling attend la fin du chargement avant
de se réarmer ; les Goals réconcilient les vues actives à la reconnexion websocket.

Les références Topic utilisent le cache de session borné existant, avec une fraîcheur
de 60 secondes et invalidation après mutation. Les requêtes de plus de 500 identifiants
sont découpées sans tronquer les résultats ; les consommateurs éliminent les titres
supprimés, interdits ou évincés de leur ensemble d'observation borné.

Les imports inter-domaines passent par des exports intentionnels de racine, `contracts`,
`interface` ou `facade`. Les façades purement calculatoires existantes, notamment les
résultats IA Task, restent indépendantes des transports et des composants. Les écrans
consomment les composants lourds via les exports asynchrones existants.

La purge des journaux utilise des contributions découvertes au bootstrap, détenues par
Task, LLM et Incident. `core.params` n'importe plus leurs services internes. Les nouvelles
dépendances des stores vers `core.util` correspondent à cette primitive commune ; elles
ne justifient aucune nouvelle exception d'import privé ni aucun nouveau cycle.

## Réutilisation et contrôles

Topic partage son formulaire de création et d'édition ; les deux vues d'appel LLM et les
deux vues Memory partagent leurs présentations. L'historique des cycles Goal et la gestion
MCP Agent possèdent des unités autonomes. Les Documents Données utilisent la bibliothèque
Document commune ; l'ancienne arborescence Dataset inutilisée est supprimée.

Les boutons et couleurs utilisent les composants Quasar et les jetons Solaire communs.
Un contrôle ESLint central protège noms accessibles, fermeture des modales, styles des
actions et palette statique. Les contrôles de promesses couvrent les trois couches frontend.
Ces contrôles structurels ne remplacent pas les scénarios d'interaction et le rendu dans
le shell, notamment sur mobile et en mode sombre.

Les cycles de composition métier déjà recensés et les autres grands écrans restent une
dette de conception suivie par la baseline. La présence d'une surface publique ne démontre
ni leur disparition, ni l'absence de toute régression fonctionnelle.
