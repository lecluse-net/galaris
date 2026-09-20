# 0102 — Choix du dispatcher déclarés par chaque harnais

Statut : accepté — 16 septembre 2026.

## Décision

Pour une Task, les capacités du harnais sélectionné définissent les choix du dispatcher.
`DriverPipelinePolicy` expose les efforts d'exécution, le planner et les efforts compatibles
avec le briefing. L'exécution standard est obligatoire ; les autres possibilités doivent être
déclarées. Un provider réseau peut préciser la politique du driver de transport commun, via le
port de sélection de harnais existant. Le dispatcher ne connaît pas l'identité des providers.

`EXEC high` exige aussi `uses_llm_calls=true` : l'exécution doit traverser la sélection
de modèle et le journal `LLMCall` de Galaris. Cette déclaration vaut `false` par défaut.
Sans elle, la politique retire l'effort high de l'exécution et du briefing, même si le
provider l'a demandé. La capacité native d'un SDK à choisir son propre modèle ou son
raisonnement ne suffit pas. Le dispatcher et le Lab conservent cette propriété dans
leur politique capturée ; il n'est pas nécessaire d'observer un premier appel en base.

La politique produit une liste de couples route/effort : `EXEC standard`, éventuellement
`EXEC high`, `BRIEFING` avec un effort accepté, et `PLAN high`. Le dispatcher applique ensuite
les contraintes explicites et les choix déjà assignés aux enfants. Il n'existe qu'un calcul des
choix, partagé avec la prévisualisation Lab.

- Aucun couple compatible : erreur explicite, sans modèle.
- Un couple compatible : décision déterministe, sans même résoudre le modèle dispatcher.
- Plusieurs couples compatibles : inférence limitée à la liste fournie dans le prompt.
- Modèle absent ou résultat proposant un couple indisponible : premier couple permis,
  dans l'ordre déclaré (exécution standard, high, briefing, plan), avec motif tracé.

La présence d'une seule route `EXEC` ne suffit pas à éviter le LLM si les deux efforts restent
disponibles. Une contrainte `PLAN standard` est incompatible ; un effort standard imposé exclut
`PLAN`. Le manque de modèle ne contourne aucune contrainte. Les résultats déterministes,
les échecs, la langue et les capacités utilisées suivent la même persistance que les inférences.

`BRIEFING` devient un choix indépendant. Une nouvelle décision `EXEC high` exécute directement ;
une décision `BRIEFING` prépare puis exécute. Les directives explicites conservent ce choix
jusqu'à la Task. Le résultat et le texte du briefing sont transmis à l'exécuteur. Le harnais
interne garde sa désactivation actuelle du briefing ; déclarer le mécanisme dans le contrat
ne le réactive pas. Les anciennes décisions sans liste de choix gardent leur politique de reprise.

Les rounds conversationnels conservent le contrat [0101](0101-dispatch-without-action-judgment.md).

## Capacités vérifiées dans le code

| Harnais | EXEC standard | EXEC high | BRIEFING | PLAN |
|---|---|---|---|---|
| Interne | oui | oui | désactivé | oui |
| Hermès | oui | oui | non | non |
| Codex | oui | oui | non | non |
| Claude Agent géré via la passerelle Galaris | oui | oui | non | non |
| DeepSeek Harness | oui | oui | non | non |
| OpenAI Messages générique, dont Claude Code externe avec API propre | oui | non | non | non |

Les adapters Codex et Claude consomment le modèle et l'effort résolus. DeepSeek reçoit l'effort
de raisonnement ; la passerelle Galaris résout aussi le modèle high par Task pour les runtimes
gérés, notamment Hermès et DeepSeek. Le transport générique ne prouve pas à lui seul que le
serveur distant exploite deux efforts : sa politique reste limitée à standard.
Les providers gérés ci-dessus imposent tous la passerelle Galaris. Ils n'exposent pas
actuellement de mode « abonnement propre » ; une telle sélection devra déclarer
`uses_llm_calls=false` et ne pourra donc proposer `EXEC high`.
Cette vérification porte sur les adapters et leurs tests, pas sur une nouvelle qualification
en production des fournisseurs.

## Compatibilité et validation

Les nouvelles inférences Task utilisent `galaris.dispatcher.active/v3`, avec le contrat
`TaskDispatchDecision`. Les contrats v1/v2 restent inchangés pour recharger les requêtes gelées.
Le contrat conversationnel demeure en v2. Les colonnes SQL existantes ne changent pas.
Le Lab accepte `BRIEFING`, vérifie les couples de la politique et capture la politique réellement
enregistrée, y compris lorsqu'elle vient d'un provider plutôt que du driver commun.

Les tests couvrent les déclarations des providers, les quatre chemins, les contraintes
incompatibles, le modèle absent, les anciens schémas et décisions, ainsi que la persistance sans
aucune ligne d'inférence ou d'appel LLM pour une Task à choix unique. Les résultats exécutés
figurent dans la [matrice de preuves](../audits/2026-09-19-fiabilisation-transversale.md).
Les mesures de latence restantes sont regroupées dans le
[plan conversationnel](../plans/fiabilisation-conversationnelle.md).
