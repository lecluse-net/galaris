# ADR 0048 — Prompts administrables avec suivi de défaut

- Statut : Accepted
- Date : 2026-08-24

## Contexte

Les prompts administrables étaient des Params texte ordinaires. Une valeur `NULL` permettait déjà
de résoudre le défaut livré par Galaris, mais l’API matérialisait seulement la valeur effective :
l’interface ne distinguait pas clairement un défaut suivi d’une personnalisation. Une instance
ayant adapté un prompt ne pouvait pas non plus savoir qu’une nouvelle version du défaut avait été
livrée, la comparer, puis choisir explicitement entre les deux comportements.

Une synchronisation interactive de type `dpkg` n’est pas adaptée à l’entrypoint de production :
DbAdmin doit rester idempotent, non interactif et terminer avant la readiness.

## Décision

`core.params` possède un type déclaré `prompt`. Pour ces lignes, `value IS NULL` signifie « suivre
le défaut fourni par Galaris » et une valeur non nulle est exclusivement une personnalisation. Le
service résout l’unique source anglaise sous `core.params` et calcule en parallèle son empreinte
SHA-256. Les instructions destinées au modèle n’appartiennent pas à i18n et ne sont jamais
traduites ; seuls le libellé, la description et l’éditeur du Param sont localisés. La colonne
`default_digest` mémorise le défaut face auquel
l’administrateur a choisi sa version.

Après le merge du dataset Params, DbAdmin applique la politique suivante :

- un prompt suivant le défaut avance automatiquement vers l’empreinte livrée ;
- une personnalisation existante sans empreinte reçoit une baseline initiale sans être modifiée ;
- une personnalisation avec une empreinte ancienne est conservée avec son conflit visible.

L’API Params expose pour chaque prompt le défaut anglais canonique, l’état personnalisé et la
présence d’une nouvelle version. Elle accepte deux résolutions explicites : `keep_custom`, qui
conserve la valeur et acquitte la nouvelle empreinte, et `use_default`, qui remet la valeur à
`NULL`. Sauver un texte égal au défaut courant revient également à suivre ce défaut.

Le frontend déclare un type de champ `prompt` rendu partout par `PromptSettingEditor`. Ce composant
offre un éditeur Markdown, un statut, une restauration du défaut, un diff ligne à ligne et le choix
garder/adopter lorsqu’une nouvelle version est détectée. Les dialogues restent fermables par leur
arrière-plan.

## Conséquences

- Les instances non personnalisées adoptent automatiquement chaque amélioration livrée.
- Une mise à jour ne remplace jamais silencieusement un prompt personnalisé.
- Le conflit est résolu dans l’IHM, sans bloquer le démarrage ni demander une entrée terminal.
- Toute nouvelle préférence de prompt doit utiliser le kind backend `prompt` et l’input frontend
  `prompt`, au lieu de réimplémenter ces états ou d’utiliser un simple textarea.
- Le premier déploiement de ce contrat prend les personnalisations existantes comme baseline : il
  ne peut pas reconstruire un ancien défaut dont aucune empreinte n’avait été persistée.

## Preuves dans le code

`back/core/params/models.py`, `params_service.py`, `dbadmin.py`, le contrat `/api/params`,
`front/core/params/components/PromptSettingEditor.vue`, `settingsCatalog.ts` et les tests de
`core.params`.
