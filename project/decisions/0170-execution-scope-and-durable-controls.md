# 0170 — Portée d'exécution et commandes durables

- Statut : Accepted
- Date : 2026-10-11

## Garanties et vérification

Le remplacement explicite peut arrêter un arbre de Tasks lorsque son périmètre est
figé et ses propriétaires externes coopèrent. Le successeur demeure suspendu jusqu'à
la libération des leases et la preuve d'arrêt de chaque run de l'arbre et de ses Process.
Un effet distant inconnu ne vaut jamais confirmation. Une Goal active ou une attente
non reconnue reste un conflit explicite : arrêter une Task ne vaut pas arrêt de sa Goal.
Les travaux indépendants et les pauses utilisateur restent préservés.
Les tests utilisent PostgreSQL, les façades réelles et des serveurs externes synthétiques.

Une inférence peut être admise en état `prepared`, sans programmation ni appel fournisseur.
Sa requête, ses droits et sa configuration sont figés dès l'admission ; une modification
demande une nouvelle identité. `start` est une commande idempotente. Les commandes
acceptent une révision attendue optionnelle pour préserver les clients historiques.
Le reçu réutilisé doit garder action, inférence et révision attendue ; la relecture
d'un reçu réussi précède le contrôle de la révision courante.

L'échéance globale facultative part de la création de l'inférence et inclut attente,
préparation, pauses et reprises. Elle ne se renouvelle pas à la reprise. Le rejeu explicite
crée une autre inférence et conserve l'original, ses fragments, ses coûts et son identité.
L'expiration arrête le transport local ; elle ne certifie pas l'arrêt physique du fournisseur.
La lecture expose révision et échéance. Les tests couvrent démarrage concurrent, commandes
périmées, pause/reprise, expiration silencieuse, budget épuisé et résultat tardif.

La portée agentique est un contrat versionné persisté dans `Task.data`, possédé par
`app.agent` et transporté par le port Task. Elle conserve la demande source, les exigences,
les cibles justifiées et le propriétaire de livraison. Un enfant hérite de cette portée,
sans pouvoir l'élargir depuis sa propre rédaction. Une ressource découverte peut soutenir
une exigence existante ; elle ne donne aucun droit de publication sur une nouvelle cible.
L'admission conserve la demande entière sous la clé `demand` ; chaque amendement sourcé
ajoute une exigence, sans effacer les précédentes. La couverture du plan est déclarative :
elle ne prouve pas automatiquement la compréhension sémantique de chaque phrase.

Les descripteurs d'effets sont optionnels et appartiennent au catalogue des outils.
Un propriétaire peut déclarer une sélection dans son catalogue affecté. Sans cible explicite
de ce type dans la demande, la sélection reste autonome, enregistrée sous `allow_and_record`
et contrôlée par l'affectation vivante et l'autorisation native. Une cible explicite divergente
reste refusée. Cette politique est déclarée par Process, pas déduite du profil ou du planner.
Les cycles Goal prennent leurs exigences depuis la description ; le suivi ne crée pas de grants.
Le préflight utilise ces descripteurs et les cibles exactes, avant l'effet ; les domaines
conservent leurs ACL et leurs validations finales. L'absence de descripteur est enregistrée
comme inconnue et ne désactive pas les outils historiques. La portée et les décisions
s'intègrent dans l'activité existante, sans seconde timeline ni contenu sensible dans les logs.
Les tests couvrent héritage, version inconnue, cible divergente, outils historiques,
révisions et absence d'effet avant une décision refusée.

Les créations dans une sous-collection métier peuvent déclarer leur parent sourcé dans
le descripteur, par un motif complet avec un groupe `parent`. Pour `file_create`, seule
la collection `galaris://processes/runs/<uuid>/attachments/` hérite ainsi du grant de son
run exact. Une découverte, un autre run ou une cible externe n'accordent aucun droit.
L'opération ne crée pas de grant durable supplémentaire ; Process conserve ses contrôles
d'édition, de fin de run et de publication réservée au moteur pour les sorties typées.
Goals, Tasks et définitions Process gardent leurs outils de création métier ; leurs
snapshots ne deviennent pas des fichiers génériques modifiables.

Le suivi périodique expose seulement le résumé de portée, tandis que le contrat complet
reste dans `Task.data` et l'enveloppe du runtime. Le contrôle des ressources produites
charge les provenances en lot et n'importe pas les historiques des tâches productrices.
Les tests de performance utilisent des demandes longues et plusieurs producteurs synthétiques ;
ils protègent le volume de la projection d'activité et le nombre borné de requêtes, sans figer
une latence dépendante de l'environnement.

Les campagnes sur comptes réels, comparaisons de prompts, latences fournisseur et parcours
illustrés restent des qualifications distinctes ; les tests synthétiques ne les remplacent pas.
