# Consolidation paramétrique — conception LoRA

- Statut : `design`
- Revue des sources : 2026-10-08.
- Intention conservée : adaptateur personnel pour savoir-faire stable, Memory comme
  autorité révisable et oubliable.

## Hypothèse et prérequis

Mesurer si un adaptateur réduit le contexte stable et le préremplissage sans dégrader
réussite, capacités générales, outils, factualité ni recours aux sources courantes.
Mesurer d'abord rappel, tokens injectés, préremplissage avec/sans cache, recherches
explicites, corrections/reprises et part de procédures répétées.
Un classement insuffisant ou un provider lent n'est pas une preuve de besoin LoRA.

La cible souveraine reste au minimum de la classe DeepSeek V4 Flash, avec calcul
dédié futur. Cette intention ne choisit pas de modèle dans le runtime.
L'absence de matériel ne justifie ni substitution silencieuse par un petit modèle
ni fournisseur permanent imposé. Les anciennes estimations de poids/mémoire/GPU
doivent être requalifiées avant toute dépense ; elles ne sont pas des spécifications actuelles.

Préparation sans GPU → qualification ponctuelle isolée → station d'inférence souveraine →
pool multi-agent → training séparé → infrastructure exploitable.
Memory, Dream et Lab restent utiles en modes `off`/`observe`, même sur un horizon long.

## Autorité et données

Base partagée, adaptateur par agent et révision de base, Memory et contexte courant.
Lignée distincte pour bases standard/high incompatibles ; aucun ancien adaptateur repris
silencieusement après changement de base. Repli explicite base + Memory en cas
d'absence, indisponibilité, incompatibilité ou invalidation.

| Contenu | Destination candidate |
|---|---|
| Préférences de travail stables, procédures corroborées, corrections récurrentes non sensibles, anti-patterns vérifiés | LoRA possible avec Memory et autorisation d'entraînement explicite. |
| Faits changeants, événement isolé, document mutable, données personnelles/sociales, accès temporaire ou partagé | Memory/source métier ; exclus par défaut du training. |
| État Task/Goal/Process | Source transactionnelle. |
| Secrets, credentials, prompt privé, raisonnement interne, contradiction non résolue ou item expiré/oublié | Interdit au corpus. |

Lecture, usage dans le prompt et entraînement sont trois autorisations distinctes.
Un grant/publication ne rend pas entraînable une donnée. Propriété directe,
provenance/révision, éligibilité et confirmation indépendante revérifiées avant snapshot.
Plusieurs reformulations de la même preuve ne sont pas des corroborations.

Dream produit un signal d'éligibilité, pas un entraînement ni une promotion.
Le domaine candidat `app.model_adaptation` possède corpus/candidats/décisions ;
Memory garde droits/oubli, Lab les mesures, app.agent la résolution figée,
app.llm l'inférence, connexion/bridge le trainer.
Le nom et la nécessité du domaine restent à arrêter en ADR.

## Corpus et exécution

Snapshot immuable : propriétaire, base/licence/precision/tokenizer/chat template,
items/révisions/digests/preuves, politique et générateur, exclusions, replay,
partitions et empreinte finale. Conserver la filiation des exemples générés.
Reconstruction SFT LoRA depuis la base gelée et corpus cumulatif admissible ;
pas de chaîne indéfinie d'adaptateurs. DPO différé faute de paires fiables.

Cycle : signal de valeur → snapshot → entraînement isolé → candidat vérifié →
campagne Lab → rejet/indéterminé ou canari → promotion atomique → surveillance.
Modes candidats : `off`, `observe`, `candidate` (activation explicite), puis `gated`.
Première livraison en `off` ; automatisation de promotion après prérequis Lab qualifiés.

Déclenchement par nouvelles preuves/procédures, coût répété ou demande administrative,
pas seulement une durée. Refroidissement, budgets GPU/coût, coalescence et un run par agent/base.
L'entraînement distant ne garde pas HTTP ouvert ni de toolchain ML sur l'hôte applicatif.

Vérifier si le contrat Process permet un job système sans fausse définition métier ni tool
de training pour l'agent ; sinon concevoir un port adapté avant intégration.
Idempotence par base/agent/dataset/recette, callbacks authentifiés, terminaux immuables,
annulation demandée distincte de confirmée, quotas et temporaires bornés.
Trainer isolé sans credentials généraux ; registre d'artefacts dédié, digest vérifié,
jamais de chemin arbitraire fourni par le trainer ou l'utilisateur.

## Faisabilité et serving

Qualifier séparément trainer, PEFT sur la base exacte, artefact autonome non fusionné,
chargement dynamique multi-LoRA, puis deux agents/deux adaptateurs sous concurrence.
Mesurer routage MoE, mémoire de training, tool calling, raisonnement, éviction,
rechargement et repli. Un support d'inférence ou d'entraînement général ne démontre
pas cette chaîne. En cas d'échec, conserver `observe` et Memory ; fusion d'un checkpoint
par agent seulement comme exception explicitement administrée.

Version immuable : agent, base, recette/rang, digests corpus/artefact, rapport, état
candidate/canary/active/rejected/superseded/invalidated et dates.
Résoudre base + adaptateur une fois avant le driver ; les runs déjà construits gardent
leur version, tracée aussi dans LLMCall. Qualifier harnais interne et Hermès.
Voix temps réel et modèles propriétaires non adaptables hors premier périmètre.

Serving : registre allow-listé, préchauffage, chargement atomique, cache GPU/CPU borné,
éviction LRU, refus d'incompatibilité, repli et métriques. API d'administration séparée.
Aucun modèle ne peut promouvoir, charger ou supprimer son adaptateur via tool.

## Évaluation, invalidation et réception

Réutiliser le [Lab](lab-evaluation-mecanismes-ia.md) et
l'[apprentissage Dream](../decisions/0019-evidence-based-dream-experience.md).
Comparer baseline active, candidat avec Memory identique, puis candidat avec contexte
stable réduit. Figer modèle/adaptateur, driver, prompts/tools, politique Memory,
paramètres, corpus, juge et score. Une base nue ne remplace pas la baseline active.

Séparer training, work, validation, holdout et sentinelles par preuve d'origine.
Mesures déterministes pour ACL/contrats/effets ; juge ouvert étalonné humainement.
Campagne incomplète/non comparable/indéterminée sans promotion.
Gardes : aucune fuite, régurgitation interdite, fait invalidé, défaut de fraîcheur,
effet/stream incorrect ni nouvelle défaillance critique ; stabilité générale et gain
ciblé mesurés. Publier tokens, préremplissage, premier token, débit, HBM, coût/durée
du cycle et qualité par dimension. Moyenne sans compensation d'une garde critique.

Correction/oubli/sensibilité rendent immédiatement inéligibles les versions dépendantes :
nouveaux runs sur base + Memory, reconstruction propre, retrait du serving puis purge
de l'artefact selon politique. Le contre-entraînement ne prouve pas l'oubli.
Arrêter le projet si invalidation trop lente, gain matériel absent, RAG plus fiable,
coût supérieur aux économies, données insuffisantes ou gardes impossibles à étalonner.

| Phase | Preuve de sortie |
|---|---|
| 0 — Mesurer | Rapport de gain potentiel matériel ; aucune infrastructure GPU requise. |
| 1 — Expérimenter | Base souveraine figée, corpus synthétique/non sensible audité, chaîne trainer/artefact/multi-LoRA et campagnes répétées démontrées hors production. |
| 2 — Gouverner | Corpus/candidats/filiation/invalidation et exécution idempotente ; mode observe sans activation. |
| 3 — Servir | Population bornée, canari manuel, résolution/traces, repli et rollback prouvés. |
| 4 — Produire des candidats | Signaux/budgets/reconstruction automatiques ; activation encore opérateur. |
| 5 — Promouvoir sous gardes | Lab étalonné, canari/surveillance/invalidation/rollback automatiques, arrêt global et revue des gains/coûts. |

Arbitrages : révision et modules adaptables/rang, replay et quantité de preuves,
identité de l'adaptateur, seuil de rentabilité, cache/concurrence, délai d'invalidation,
port système Process, campagne composite et maturité du mode gated.
Pas de fine-tuning complet, fusion inter-agent, apprentissage à chaque tour,
model editing comme oubli ni suppression du rappel Memory.

## Références historiques à revalider avant expérimentation

- [LoRA](https://arxiv.org/abs/2106.09685), [QLoRA](https://arxiv.org/abs/2305.14314).
- [Fine-Tuning or Retrieval?](https://aclanthology.org/2024.emnlp-main.15/),
  [hallucinations après fine-tuning](https://aclanthology.org/2024.emnlp-main.444/).
- [Apprentissage continu](https://arxiv.org/abs/2404.16789),
  [oubli par model editing](https://aclanthology.org/2024.findings-acl.902/),
  [données récursivement générées](https://www.nature.com/articles/s41586-024-07566-y).
- [vLLM LoRA](https://docs.vllm.ai/en/stable/features/lora/),
  [base V4 Flash](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash),
  [recette d'inférence](https://recipes.vllm.ai/deepseek-ai/DeepSeek-V4-Flash),
  [NeMo AutoModel](https://github.com/NVIDIA-NeMo/Automodel/blob/main/docs/guides/llm/dsv4-flash.md).
- [DGX Station](https://docs.nvidia.com/dgx/dgx-station-development-guide/overview.html),
  [MI325X](https://www.amd.com/en/products/accelerators/instinct/mi300/mi325x.html).

Ces liens conservent les pistes de recherche ; cette revue du dépôt ne vérifie pas
leur actualité ni la compatibilité technique de bout en bout.
