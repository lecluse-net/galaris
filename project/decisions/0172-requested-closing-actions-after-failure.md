# 0172 — Clôtures demandées après un échec

Statut : accepté. Date : 2026-10-11.

## Problème

Le Planner ferme toutes les étapes dépendantes après un échec terminal. Cela supprimait aussi
un bilan durable explicitement demandé pour décrire les échecs. Une recherche documentaire
par nom utilisait en outre le rappel hybride et injectait des passages de corps dans une
opération d'inventaire. La boucle du modèle observée est un fait ; son déclenchement par ce
contexte volumineux reste une hypothèse, pas une causalité démontrée.

## Décision

`PlanStep.run_after_failure`, faux par défaut, désigne uniquement une feuille de clôture
indépendante explicitement demandée, placée après les travaux dépendants. Le schéma et les
prompts la distinguent d'une synthèse textuelle automatique ou d'une tentative de récupération.
Une telle feuille utilise les mêmes outils autorisés, ACL et portée d'exécution que les autres.
Le flag ne lui accorde aucun droit ni aucun retry de travaux métier.

Après une erreur ou un blocage non récupéré, le parent ferme les étapes dépendantes et conserve
`plan.failure_task_id` avant d'activer les clôtures dans l'ordre. Les diagnostics des feuilles
en erreur sont injectés dans leur contexte. L'état reste `PLAN` pendant la clôture, puis `ERROR`,
même si le bilan réussit. La synthèse peut intégrer ce bilan sans transformer l'échec en succès.
Une erreur de clôture reste terminale ; les autres clôtures demandées peuvent encore s'exécuter.

Une reprise explicitement demandée reprend au premier travail inachevé et réarme les clôtures.
`RETRY_CLOSING_ACTION` est la seule nouvelle transition, de `SUCCESS` vers `DISPATCH` pour une
clôture réussie réarmée par la commande manuelle du parent. Son checkpoint de run est retiré
pour lire l'état courant ; les autres succès et preuves durables ne sont pas effacés. Les
anciennes tâches sans flag conservent leur arrêt après échec. Aucun plan déjà terminal n'est
réouvert automatiquement.

Sur `document://`, la recherche `name` respecte enfin son contrat : titres et noms de fichiers,
filtrage ACL/validité et pagination SQL, sans rappel sémantique, extrait de corps, passages ou
métadonnées documentaires arbitraires. La recherche de contenu et le rappel `memory://` restent
inchangés. Le garde de raisonnement répétitif reste actif.

## Vérification

Des reproductions entièrement synthétiques échouent avant correction sur la recherche par nom
et la clôture après erreur. Les scénarios couvrent rapport réussi ou échoué, blocage, saut des
dépendances, conservation de l'échec, persistance/rechargement PostgreSQL, réveils répétés,
reprise manuelle, conservation des succès et actualisation du bilan. Les droits et la pagination
documentaires restent vérifiés. Cette qualification déterministe ne garantit pas qu'un modèle
réel ne bouclera jamais ; la production change uniquement après un déploiement demandé.
