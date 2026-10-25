# Appels LLM — extensions de l'admission par fournisseur

- Statut : `partial`.
- Revue documentaire : 2026-10-25.
- Socle livré : [ADR 0181](../decisions/0181-provider-llm-admission.md).
- Contrat consommé : [inférences durables](../decisions/0097-durable-inference-lifecycle.md),
  complété par les [commandes et échéances](../decisions/0170-execution-scope-and-durable-controls.md).

## Socle actuel

`app.llm.provider_scheduler` partage la limite `max_concurrent_calls` d'une connexion
entre ses modèles et appelants. Le défaut effectif est 10 pour le catalogue et 1 pour
une connexion personnalisée, notamment Ollama ; zéro signifie sans plafond Galaris.
Le champ est administrable et les écritures partielles conservent sa valeur.

Les appels tracés utilisent une admission voix, texte puis fond, avec capacité protégée,
vieillissement et rotation entre contextes. Un stream conserve sa place jusqu'à sa
finalisation ; les outils ne réservent pas un run entier. Les inférences durables
attendent avant claim. Annulation, baisse/hausse à chaud et changement de fournisseur
nettoient leurs réservations. Le délai physique commence au départ ; l'échéance globale
reste celle de l'inférence. Ce coordinateur correspond au backend mono-worker fourni.

Les sources et tests sont dans `back/app/llm/provider_scheduler.py`,
`back/app/llm/tests/test_provider_scheduler.py` et les suites d'inférence durable.
Le [guide administrateur](../../docs/fr/admin/provider-admission.md) décrit le parcours
livré. La présence de tests ne qualifie pas tous les fournisseurs ou la charge réelle.

## Provenance de l'admission tracée

`app.llm.admission` résout un contexte typé (source, classe, propriétaire) commun à
la file durable avant claim et à la création de l'appel physique. Une Task reste du
fond et constitue son propre contexte de rotation, même si elle conserve un round
vocal ou textuel d'origine. Sans Task, le round direct possède l'appel ; sans round,
le run agentique sert de propriétaire lorsqu'il est connu. La transcription vocale
avant création du round utilise le signal interne `voice_dialogue` ; un fichier audio
ne reçoit pas ce signal. Les usages inconnus sans round restent du fond.

Sans Task, round ou run agentique, la rotation utilise successivement la génération
média, le run Process, la source serveur (`LLMExecutionAuthority.source_kind` et
`source_id`), l'agent, puis le demandeur. Les catégories sont séparées dans la clé
de rotation. Une provenance incomplète sans agent ni demandeur reste anonyme ; les
libellés de corrélation libres et les sélecteurs de profil ne deviennent pas des
identités de travail. Les appels natifs conservent le demandeur authentifié ou
restauré dans leur trace, même hors fournisseur à abonnement personnel.

Le scheduler lit la provenance déjà persistée de chaque inférence, sans hériter
de l'autorité du worker qui l'a démarré. Une source Dream `conversation_round`
reste du fond si aucun round direct n'est demandé. Le Lab fournit `lab_run` et
son run ; les sujets Dream fournissent leur type et identité via leur scope serveur.
Le suivi Goal possède déjà sa Task. Ces scopes servent à la rotation et ne remplacent
jamais les contrôles de droits de leurs domaines.

Cette tranche corrige deux écarts de rotation : des Tasks distinctes issues du même
round étaient regroupées sous ce round ; un run sans Task ni round n'avait pas de
propriétaire dans la file durable alors que son appel physique en avait un.
Le scénario d'intégration a également révélé une perte de `agent_run_id` et
`conversation_round_id` entre l'inférence texte directe et son modèle. Leur
propagation est désormais commune aux appels texte et structurés. La reconstruction
de la requête texte pour un appel durable conserve aussi ces deux identités.
Les tests `tests/test_provider_admission_context.py` traversent la file, le gateway,
PostgreSQL et un fournisseur HTTP synthétique. À saturation, deux demandes du même
propriétaire et une d'un autre propriétaire vérifient que ce dernier reçoit la
prochaine place libre, en exécution durable comme en appel direct.
Les tests précédents vérifiaient la rotation du scheduler isolé, sans vérifier la
propagation des propriétaires à travers les adaptateurs réels ; ce scénario ferme
cette lacune. Le chemin structuré propageait déjà les deux identités ; les contrôles
sur les fournisseurs et leurs compteurs ne suffisaient pas à détecter la perte texte.
Le même scénario couvre désormais Process, source serveur, agent, demandeur restauré
et utilisateur authentifié. Les huit variantes Process/source/agent/demandeur
échouaient avant cette extension en admettant une demande supplémentaire du
propriétaire actif avant celle du propriétaire indépendant.

### Inventaire des racines physiques tracées

| Racine dans `back/app/llm` | Provenance disponible à l'admission |
|---|---|
| `proxy_service.py` — Chat et Responses/compact | Task, round, run, Process et purpose propagés ; source serveur puis agent/demandeur en repli. Les harnais et inférences texte/structurées convergent ici. |
| `decision_service.py` — décision native | Identités de la requête durable ; le fallback texte revient au proxy. |
| `transcription_service.py` — STT à la demande | Signal voix direct avant round, ou fichier en fond ; agent et demandeur dans la trace. |
| `image_generation_service.py` — image native | Task éventuelle, agent et demandeur ; fond. |
| `media_facade.py` — analyse/génération spécialiste | Task éventuelle, génération média, source serveur et agent ; fond. |
| `profile_inference.py` — embeddings publics | Demandeur authentifié ; rotation par demandeur, sans utiliser le sélecteur de profil comme propriétaire. |

Cet inventaire couvre les racines de `create_running_call`, pas encore une preuve
exhaustive de chaque demandeur en amont. Le contexte typé est interne à l'admission,
sans nouveau champ durable ni paramètre de priorité fourni par le client.
Les embeddings internes via `embedding_service`, la synthèse vocale via `tts_service`,
les transcripteurs persistants et les sessions audio natives ne passent pas tous par
ces racines. Leur intégration à la limite exige un contrat propre ; cette tranche
ne les annonce pas couverts.

## Extensions à concevoir ou qualifier

| Écart | Critère de réception |
|---|---|
| Provenance typée exhaustive | Contexte partagé, racines physiques et repli sur les propriétaires métier/serveur/agent/demandeur réalisés ; restent la preuve de chaque demandeur en amont et l'inventaire des opérations réellement anonymes. |
| Priorités configurables par opération | Registre stable traduit, validation serveur, défauts et remise aux défauts ; ne pas transformer les anciens rangs candidats en configuration déjà disponible. |
| Couverture de tous les transports | Identifier les sessions audio et générations distantes non représentées comme appels physiques tracés ; ne pas les annoncer couvertes par la limite actuelle. |
| Plusieurs backends | Coordination distribuée avant toute garantie de plafond global entre processus indépendants. |
| Diagnostics d'attente | Mesures comparables attente/départ/première sortie, distinction file et appel physique, réconciliation après interruption sans génération automatique. |
| Qualification fournisseur et charge | Exercices Ollama et fournisseurs distants autorisés, appels mixtes, saturation et retour au repos ; comparer débit, latence, mémoire et échecs sous les mêmes conditions. |

## Garanties à préserver

L'admission ne donne aucun droit et ne contourne ni budget, ni annulation, ni refus de
contenu, ni politique de rejeu. Une attente vivante ne doit pas être déclarée bloquée
par le watchdog Task. Un transport actif n'est pas préempté par une priorité plus haute.
Une réponse perdue après effet reste à réconcilier. Une baisse de concurrence n'atteste
pas à elle seule un gain de débit ; une priorité candidate ne remplace pas le contrat livré.

Renforcer les suites existantes avec des événements et barrières déterministes pour les
courses admission/annulation, streams, reprises, changements de configuration et extinction.
Publier les mesures et limites de chaque extension avant d'en annoncer la disponibilité.
