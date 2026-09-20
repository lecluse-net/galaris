# ADR 0023 — Prompts d’exécuteurs en arbres JSON et jeux de données du Lab

- Statut : Accepted
- Date : 2026-08-02

## Contexte

Les runtimes Task Internal, Hermès, conversation textuelle, voix pipeline et voix realtime
construisaient leurs prompts système avec plusieurs assemblages de chaînes et de sections. Un même
ajout d’instructions pouvait donc changer de position ou ne pas atteindre une surface. Par
ailleurs, le comportement de lancement d’une Task ou d’un Process varie selon le modèle ; le Lab
devait pouvoir isoler le prompt comme variable expérimentale sans modifier la production.

## Décision

Tout prompt système d’exécuteur est un arbre JSON ordonné conforme à
`galaris.system-prompt/v1`. Un renderer pur unique transforme cet arbre en Markdown uniquement à la
frontière du modèle. Le dernier enfant est toujours un nœud `raw_markdown` dont le texte vient du
Param de l’exécuteur : Task, conversation ou voix. Le choix du Param ne dépend jamais du LLM.
La politique qui arbitre les actions des conversations texte et voix est le Param anglais
`ai.conversation-action-policy`. Sa source canonique n’appartient pas à i18n ; elle remplace la
valeur par défaut dans un nœud structuré et ne se confond pas avec le suffixe libre propre à chaque
exécuteur.

Pour une Task, le socle commun rend explicitement le snapshot canonique de l’agent : nom, genre,
poste, personnalité et fiche de poste. Ces données gouvernent aussi le jugement, la rédaction,
la mise en forme et l’auteur des livrables ; une préférence explicite de signature s’applique donc
au contenu pertinent sans devenir une action de transport. Le prompt complet est figé avant la
frontière driver : le harnais interne, Hermès et les harnais réseau reçoivent le même profil, puis
ajoutent leurs seules instructions runtime avant le suffixe configurable.

Le Lab expose trois mécanismes d’exécuteur. Chaque jeu de données d’exécuteur possède son propre
suffixe Markdown. À sa création, celui-ci est initialisé avec le Param système courant ; l’éditeur
peut le personnaliser ou le remettre à la valeur système courante. Une chaîne vide reste une
valeur explicite. Les anciens jeux sans valeur persistée utilisent le Param courant par
compatibilité jusqu’à leur premier enregistrement.

Au lancement, le run fige le suffixe du jeu, sa provenance, son empreinte, la politique
conversationnelle effective et, pour chaque cas, l’arbre et le Markdown exacts. Les workers et
reprises ne relisent ni Params ni jeu de données.
Le bouton de benchmark ne configure rien : il lance directement le jeu avec le LLM sélectionné.

Les benchmarks utilisent les vrais noms et contrats utiles d’outils au travers de fonctions
enregistreuses sans effet. Ils peuvent ainsi mesurer la propension réelle à appeler
`conversation_task_submit` ou `conversation_process_start` sans créer de Task, de Process, de
message ou d’autre effet externe.

## Conséquences

- Internal, Hermès et les harnais réseau partagent le profil et le suffixe Task ; pipeline et
  realtime partagent le suffixe voix.
- Un jeu de données représente un corpus et un prompt cohérents, comparables entre plusieurs modèles.
- Pour comparer plusieurs prompts, on crée ou duplique plusieurs jeux de données.
- Les runs historiques restent auditables même si le Param, le jeu ou le constructeur change.
- Ajouter un nouveau type de nœud impose de versionner le schéma ou de préserver le rendu existant.

## Preuves dans le code

`back/app/agent/prompt_tree.py`, `back/app/agent/executor_prompts.py`,
`back/app/lab/executor_prompt_service.py`, `back/app/lab/mechanism_registry.py`,
`front/core/params/pages/index.vue` et
`front/app/lab/components/MechanismEvaluationTab.vue`.
