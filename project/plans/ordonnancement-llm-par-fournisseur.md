# Appels LLM — file et priorités par fournisseur

- Statut : `design`
- Revue des sources : 2026-10-08.
- Dépendances : [inférences durables](llm-calls-durables.md) et
  [ADR 0097](../decisions/0097-durable-inference-lifecycle.md).

## Garantie recherchée

Une connexion `LLMProvider` possède une limite partagée par tous ses modèles/usagers.
Quand elle est saturée, attendre avant tout départ physique, puis admettre selon priorité
effective et FIFO à rang égal. Connexions différentes indépendantes.
L'audio interactif prend le prochain créneau ; il ne préempte pas un appel engagé.

Le cycle durable possède déjà un état `queued`. Il ne fournit pas l'admission par capacité
fournisseur proposée ici ; distinguer cette file des traces d'appels physiques.

## Configuration candidate

`max_parallel_calls` : entier strict ≥ 0 ; zéro sans plafond Galaris, un en série, N au
plus N appels actifs sur la connexion. Refuser négatifs, fractions, booléens et null.
Défaut backend : 1 pour type Ollama, 0 ailleurs, y compris OpenAI compatible personnalisé.
Ne pas inférer le matériel depuis l'URL ; catalogue et connexion personnalisée utilisent
le même résolveur.

Création avec champ omis : défaut du type. Modification/reconfiguration avec champ omis :
valeur conservée, même après changement de type. Initialisation des connexions existantes
par action DbAdmin idempotente, sans écraser une valeur administrée.

`call_priorities` : surcharges JSON typées par code enregistré, défaut vide.
Registre backend exhaustif projeté dans l'administration : code stable, libellé FR/EN,
description, opération, origine et rang par défaut. Codes inconnus/rangs invalides refusés.
Modification réussie reclasse les attentes avec séquence initiale conservée ; appels
actifs inchangés ; omission conserve, remise aux défauts explicite.

| Rang initial | Origine |
|---|---|
| 1, réservé | Audio interactif : STT, modèle et TTS nécessaires à l'échange en direct. |
| 2 | Conversation texte et traitements nécessaires à sa réponse. |
| 3 | Task, planification, récupération et suivi d'objectifs actifs. |
| 4 | API externe sans autre origine vérifiée. |
| 5 | Dream/fond et Lab non interactif. |

Les rangs hors audio sont configurables par type détaillé, pas seulement par cinq catégories.
Audio reste au-dessus de tout autre rang, sans vieillissement qui le dépasse.
FIFO à rang égal ; famine possible du fond explicitement assumée.
Mode 0 garde les rangs sans attente artificielle.

## Prérequis : provenance et inventaire complet

Séparer opération technique/purpose, demandeur immédiat, origine métier et identité autorisée.
Auditer chaque racine et frontière, puis prouver demandeur → appel → propriétaire →
type → priorité à l'admission et dans les traces.

L'inventaire couvre dialogue texte/voix/objectifs, Task/planner/Goal, décisions spécialisées
et repli, Dream/Memory/Topics, Lab, API Chat/Responses/compact, embeddings,
transcription, TTS, vision et génération/analyse média.
Partir de `model_usages`, `purposes.py`, des gateways et façades directes ;
un enum ou une chaîne trouvée n'atteste pas à elle seule un appel effectif.

Créer le descripteur public typé et le porter dans contrats durables, outils,
sous-appels, reprise et fallback. `ContextVar` seul ne traverse pas ces frontières.
Les endpoints d'embeddings et traces TTS doivent conserver identité de connexion/origine
lorsqu'elle manque. Un prompt ou `infer_call_purpose` historique n'est pas une preuve.

Audio de document ou PJ d'un message texte n'est pas une conversation vocale directe.
Une Task issue d'un dialogue devient catégorie Task ; Dream utilisant une Task/un outil
reste fond. Les analyses mutualisées entre demandeurs exigent une règle explicite.
Un client API ne peut falsifier audio ; origine interne inconnue diagnostiquée et
traitée conservativement comme fond pendant transition, jamais présentée comme bien identifiée.
Aucune propagation de priorité ne donne de droits supplémentaires.

## Coordinateur et nettoyage

Coordinateur asynchrone dans `app.llm`, par clé de connexion, compteur et file rang/FIFO.
Admission/libération atomiques sous verrou bref ; aucun réseau, transaction SQL,
thread bloqué ou copie de prompt/média pendant attente.
Évincer demandes annulées et états inactifs sans croissance résiduelle.

Résoudre droits/modèle/origine → attendre → revalider commande/contexte/provider →
marquer départ physique → envoyer → conserver le créneau jusqu'à fermeture du transport →
libérer dans un nettoyage résistant à annulation/double appel.
Un stream garde le créneau après headers/premier token.
Le créneau est libéré avant outils, pause humaine et tour suivant ; aucun verrou imbriqué
SDK/proxy/harnais ni interblocage sur sous-appel du même provider.
Retry physique revient dans la file après nettoyage, sans nouvelle politique de rejeu.

Changement à chaud : hausse admet les attentes ; baisse laisse terminer les actifs ;
0 libère les attentes mais suit les actifs ; retour à une limite compte ces actifs ;
désactivation/suppression bloque les départs et respecte la politique des appels engagés.
Publication après persistance, sans rétablir une ancienne configuration ORM.

Premier parcours : Chat/Responses, dialogue/API, stream/non-stream ; puis décisions,
embeddings, STT/TTS et média utilisant LLMProvider. Génération asynchrone comptée pendant
l'exécution distante connue, pas seulement la soumission.
Découverte catalogue/quota/OAuth hors file. SDK hors gateway non couverts : publier leur
couverture. Un backend unique suffit au candidat en mémoire ; multi-réplica demande
coordination partagée avant la même promesse.

Qualifier STT/modèle/TTS sur un provider à 1 : transport vocal ouvert mais inactif
sans réservation permanente. Si duplex impose des calculs simultanés, mode segmenté,
connexions distinctes ou incompatibilité explicite, sans contourner la limite.

## Activité, échéances et reprise

Tracer attente, départ fournisseur, origine/type/rang ; compatibilité additive des anciens
champs/durées, sans inventer de dates historiques. Attente sans tokens/coût ; appels
physiques et budgets comptés au départ. Activité/arrêt/historique/rétention/websocket
distinguent attentes et actifs.

Deadline physique au départ ; échéances du consommateur toujours applicables en file.
Expiration retire la demande avant fallback/arrêt : aucun départ tardif.
Watchdog Task et leases reconnaissent une attente vivante sans masquer un vrai blocage,
via le port agent/task. Tester attente supérieure au watchdog.

À l'arrêt : fermer admissions, nettoyer attentes/transports.
Au redémarrage : réconcilier traces orphelines et reprendre selon le cycle durable,
sans facturation automatique de toute attente. Requête jamais envoyée et effet distant
incertain restent distincts.

Administration existante des providers : limite, aide 0/1, tous les types/rangs et audio
réservé, reset explicite ; activité avec attente/durée/arrêt sans position exacte trompeuse.
Préserver secrets omis, brouillons, sauvegardes concurrentes, réponses tardives, FR/EN,
clavier et réouverture mobile/desktop.

## Lots et réception

| Lot | Preuve |
|---|---|
| Provenance/configuration | Inventaire complet, contrats, registre, DbAdmin et refus RBAC ; preuve de demandeur par chemin. |
| Chat/Responses | 36 demandes à limites 1/2/0, compteur partagé entre modèles, isolation A/B, ordre prioritaire et FIFO, stream et annulation. |
| Décisions/embeddings/médias | Compteur unique sur appels mixtes, origine propagée, aucun verrou réentrant ; chaîne vocale et fallback sans interblocage. |
| Administration/reprise | Limites 1→2→1→0→1, reconfiguration concurrente, arrêt en file sans coût/départ, watchdog, crash et retour au repos. |
| Qualification | Mesures attente/durée/première sortie, saturation/échecs/ressources ; recette Ollama/OpenRouter distincte des frontières simulées. |

Renforcer suites provider/catalogue, traces, inférences/protocoles/décisions,
embeddings/transcription et parcours autosave/activité.
Barrières/événements déterministes pour concurrence, timeout et course annulation/admission.
Une baisse de concurrence ne prouve pas un gain de débit.
Publier ADR, guides FR/EN et limites ; retirer les lots démontrés.
