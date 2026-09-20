# Plan — Qualification et compacité du prompt conversationnel

> **Statut :** `partial` — les changements de composition sont présents ; mesures empiriques
> et améliorations de sélection restantes.
>
> **Revue du code :** 11 septembre 2026.

## 1. Périmètre

Mesurer puis améliorer la pertinence du contexte fourni aux conversations texte et voix,
notamment avec les petits modèles. Les prompts des sessions de Task sont hors périmètre :
leurs objectifs, historiques, outils et reprises ont un autre contrat.

Le [guide développeur](../../docs/fr/dev/README.md) et le
[flux d'exécution](../../docs/fr/architecture/flows/agent-execution.md) portent le comportement
courant. Ce plan remplace sa rédaction historique accumulée depuis août : les variantes
abandonnées et les incréments déjà décrits dans le code ne sont plus des lots à implémenter.

## 2. Contrats de départ

Le flux d'exécution et le catalogue fonctionnel portent la composition déjà réalisée.
Les historiques d'implémentation et tableaux d'acquis ne sont plus maintenus ici.

Les budgets existants sont conservés. Les profils `compact`, `standard` et `extended` sont
abandonnés. L'annonce textuelle exhaustive des outils effectivement disponibles reste conservée.
Le choix actuel est l'historique natif unique : l'ancienne proposition d'une seconde chronologie
système n'est plus une cible de ce plan.

Ces contrats et tests ne démontrent pas encore un gain empirique sur tous les modèles.

## 3. Travail restant

### A — Baseline et mesures par section

- Figer un corpus multilingue représentatif de conversations, avec petits modèles et modèles
  de référence, appels d'outils et conversations vocales transcrites.
- Mesurer séparément identité/règles, message courant, historique, Memory, continuité,
  travaux liés et définitions d'outils : volume, troncature, latence, coût et qualité.
- Réutiliser le Lab et ses captures ; ne pas créer un second moteur d'évaluation.
- Décider si la ventilation par nœud est calculée depuis les traces ou persistée avec l'appel.

Réception : les mêmes cas sont rejouables avant/après, avec une variable modifiée à la fois.
Un prompt plus court mais moins fidèle n'est pas considéré comme meilleur.

### B — Qualification des incréments déjà présents

- Vérifier sur des rounds récents que Memory ne réinjecte pas le profil de l'agent et ne perd
  pas une préférence du contact simplement parce qu'elle ressemble à ce profil.
- Mesurer rappel et faux choix des Processes, y compris au-delà de dix affectations et lors
  d'un repli lexical ; préserver leur priorité lorsqu'ils correspondent réellement à la demande.
- Vérifier le choix création/amendement et les demandes de statut après filtrage des travaux.
- Évaluer la recherche et la capture volontaires de souvenirs : rappel utile, sur-capture,
  doublons, corrections et oublis rapides, sans appel systématique à chaque tour.
- Évaluer l'incarnation après un outil ou une donnée contradictoire, sans préfixe de personnage,
  narration à la troisième personne ni refus artificiel dû au petit catalogue conversationnel.

Réception : rapport par famille de cas, erreurs critiques visibles, gain mesuré et possibilité
identifiée de revenir à la configuration précédente.

### C — Continuité documentaire et sélection pertinente

- Mesurer les documents ou ressources utiles qui sortent de la fenêtre de messages récente.
- Comparer récence, proximité sémantique, lien au contact et activité sans créer un second moteur
  de mémoire. Préserver URI, révision et toutes les provenances pertinentes lors de la fusion.
- Déterminer quand une URI suffit et quand injecter un résumé ou un extrait borné.
- Étudier une sélection supplémentaire des travaux liés seulement si les mesures démontrent
  un bruit résiduel ; préserver les travaux actifs et les interactions non résolues.
- Conserver une sélection multilingue, sans classificateur de salutations fondé sur des mots-clés.

Réception : un document pertinent reste retrouvable hors de l'historique récent ; son corps
n'est pas répété dans Memory, la continuité et les travaux. Une donnée récupérée ne devient
jamais une instruction privilégiée et les ACL sont appliquées avant son exposition.

### D — Capacités immédiates et capacités de fond

- Vérifier que les fonctions appelables dans le round correspondent au catalogue effectif.
- Qualifier la présentation des capacités accessibles via une Task, calculée après filtrage des
  droits, sans annoncer les schémas d'outils absents du premier plan.
- Mesurer quel niveau de détail aide les petits modèles à admettre le bon travail.

Réception : une fonction absente du round ne produit pas un faux refus si le travail est possible
en arrière-plan ; une capacité interdite n'est pas promise. Sans outil d'admission disponible,
la réponse décrit cette limite locale sans inventer une incapacité générale.

## 4. Matrice de réception

| Cas | Garantie |
|---|---|
| Question autonome ou salutation | Réponse adaptée, sans action ni contexte injustifié |
| Pronom, correction ou pièce jointe seule | Chronologie native et contenu conservés |
| Ancien document pertinent | Référence exacte retrouvée, provenance conservée |
| Ressource rappelée par plusieurs domaines | Une seule représentation détaillée ; révisions utiles distinctes |
| Faux titres ou instructions dans l'historique | Données non fiables, sans changement de politique |
| Travail conséquent réalisable en arrière-plan | Admission réelle avant toute annonce de lancement |
| Process affecté compatible | Priorité au Process après vérification de son adéquation |
| Correction du même livrable / demande indépendante | Amendement exact / nouvelle Task |
| Statut ou renvoi d'un fichier | Lecture durable / URI existante, sans progression ou livrable inventé |
| Interaction en attente | Résolution seulement à partir d'un choix suffisamment explicite |
| Appels d'outils intra-round | Paires appel/résultat valides |
| Petit modèle, texte et voix | Identité, langue, capacité et contexte maintenus |

Préserver les contrôles de structure du prompt : nœuds non vides, délimiteurs sûrs,
instructions configurables bornées et absence de duplications accidentelles. Le rappel final
court de l'identité est intentionnel et s'évalue comme tel.

## 5. Dépendances et clôture

Utiliser le [plan du Lab](lab-evaluation-mecanismes-ia.md) pour l'étalonnage et les comparaisons.
Les améliorations du rappel durable relèvent du [plan mémoire](amelioration-globale-memoire.md).
La portée des effets, l'objectif transmis et la livraison des Tasks relèvent du
[plan de provenance](portee-provenance-execution-agentique.md).

L'observation historique d'une répétition du rôle dans les prompts de Task appelle un audit
séparé si elle est reprise ; elle n'autorise pas à modifier ces sessions dans ce plan.

Clôturer après publication des mesures et limites, et livraison ou abandon explicite des
améliorations retenues. Un test de composition vert ne remplace pas cette qualification.
