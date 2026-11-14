# Mémoire — qualification du 24 octobre 2026

Les données de mesure sont entièrement synthétiques. Les contrats et corrections
qualifiés sont décrits dans la [décision 0229](../decisions/0229-memory-evidence-and-context-budgets.md).
Ce compte rendu conserve la mesure historique ; les qualifications suivantes sont dans
les audits du [29 octobre](2026-10-29-memory-and-dataset-retrieval.md),
de [continuité conversationnelle](2026-10-29-memory-conversation-continuity.md) et
du [30 octobre](2026-10-30-memory-context-recall.md).

## Réception quantitative

Comparaison appariée avec ordre alterné et état réinitialisé : 1 320 questions synthétiques
FR/EN, 10 mondes, 2 800 souvenirs chargés dans une base éphémère, quatre domaines et
quatre workers. Les 33 familles de questions sont conservées. Tous les mondes saturent
volontairement le calendrier : les taux ci-dessous ne décrivent pas sa fréquence réelle.
Budget identique : huit souvenirs et 12 000 caractères. La référence fige aussi le rendu
du contexte ; le corpus a été régénéré dans son format courant `/2`.

| Mesure | Référence avant changement | Candidat |
|---|---:|---:|
| Faits nécessaires retrouvés (facettes, 1 160 questions répondables) | 82,30 % | 82,30 % |
| Faits nécessaires effectivement injectés | 0 % | 42,87 % |
| Questions avec tous les faits injectés | 0 % | 31,64 % |
| Requêtes améliorées / régressées en rappel injecté | — | 639 / 0 |
| Références interdites injectées / erreurs fournisseur du benchmark | 0 / 0 | 0 / 0 |
| Requêtes SQL moyennes | 31,45 | 33,42 |
| Latence p95 locale, quatre workers | 1 179 ms | 1 271 ms (+7,8 %) |

Le gain mesuré concerne l'injection, pas une amélioration du classement. Le contexte moyen
passe de 2 478 à 3 218 caractères ; les limites restent respectées. La mesure ne qualifie
ni un index unique de 56 000 souvenirs ni les embeddings réels. Une première campagne plus
large interrompue reste un diagnostic et n'entre pas dans ces chiffres.

Un contrôle aval distinct utilise dix questions synthétiques FR/EN, quatre faits, deux
questions sans réponse et dix rendez-vous distincts, avec huit places/6 000 caractères.
Le même modèle configuré `deepseek-deepseek-v4.1-flash` reçoit les prompts réellement assemblés,
sans réponses attendues ni labels, en ordre alterné. Les huit faits sont retrouvés dans les
deux bras ; leur injection passe de 0/8 à 8/8. Les réponses correctes passent de 2/10 à 9/10,
avec 2/2 abstentions correctes dans les deux bras. Le coût estimé des dix réponses est
respectivement de 0,003018 $ et 0,003060 $. Une seule répétition : ce contrôle factuel n'est
pas une qualification d'une Task autonome ou de tous les harnais.

Les appels au fournisseur vectoriel configuré ont échoué ; aucune mesure hybride réelle
n'est revendiquée. Les identifiants restent dans le runtime de développement ; seuls les
textes synthétiques et réponses sont transmis. Les sources, rapports appariés, erreurs et
évaluations aval sont conservés sous `artifacts/memory-benchmark/relevance-20261024/`.
