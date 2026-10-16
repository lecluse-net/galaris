# 0195 — Autorisations bornées des lancements conversationnels de processus

Statut : accepté — 16 octobre 2026.

## Contrat

La surface MCP `conversation_process_start` vérifie les nouveaux lancements avant effet.
Au premier appel, le modèle conversationnel sans outil interprète le message admis
préservé par le serveur, vingt messages canoniques précédents nettoyés, les travaux
actifs, les questions et le catalogue affecté. La proposition de l'exécuteur est une
donnée à vérifier, jamais une autorisation ; son texte généré courant n'est pas transmis.
Une réponse, un suivi, une correction ou une reprise n'autorise pas implicitement un
nouveau run. L'ambiguïté ou des paramètres essentiels inconnus donnent une liste vide.
Les paramètres du lot doivent être collectés avant son premier lancement.

`ConversationRound.process_launch_admission`, nullable pour les anciennes données,
fige au plus vingt invocations avec processus et paramètres JSON exacts, liées par
empreinte au message, à l'agent, à la room et au round. Une écriture conditionnelle
conserve le premier plan ; les appels concurrents ne peuvent pas l'étendre. Aucun
verrou du round n'est retenu pendant l'inférence. Erreur fournisseur ou perte de
fraîcheur n'admettent aucun run. La vérification en lecture seule est limitée à trente
secondes ; son annulation n'accorde aucune permission et ne démarre rien.

Le serveur contrôle ensuite processus, paramètres et multiplicité. Chaque position
fournit une clé d'idempotence stable : les reprises retrouvent la même exécution,
y compris après interruption avant création du lien conversationnel. Les anciens
liens restent rejouables sans inférence. Un nouveau message peut demander un autre
run ; `occurrence=2` désigne la seconde exécution identique seulement si elle figure
dans le plan. Une variation de paramètres ne crée pas une autorisation supplémentaire.

L'interprétation reste probabiliste ; l'application du plan est déterministe.
Ce contrôle avant effet complète les ADR 0101 et 0194 sans jugement après réponse
ni classification générique supplémentaire. Les conversations sans lancement,
Tasks, Goals et réponses aux activités restent inchangés. Le périmètre est la surface
MCP canonique, pas les outils vocaux Realtime distincts ni les invocations du moteur.

## Exploitation et preuves

La synchronisation passe par DbAdmin (`make sync-db` en développement, `make update`
lors d'un déploiement autorisé). Les appels utilisent le purpose
`conversation.process_admission` avec la provenance du round, sans créer de Task.

`test_process_admission.py` utilise PostgreSQL et remplace le fournisseur : refus d'un
lancement après réponse, paramètres modifiés, autre workflow, reprise, interruption,
concurrence, demandes multiples, historique nettoyé et décision tardive.
`test_activity_controls.py` conserve le parcours question → réponse → reprise →
activité suivante. Les tests Chat, Task et voix existants protègent la compatibilité.
Ces tests ne mesurent pas la qualité sémantique d'un fournisseur réel.
