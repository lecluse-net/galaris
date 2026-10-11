# 0169 — Preuves acquises pour la mémoire conversationnelle

- Statut : Accepted
- Date : 2026-10-11

## Contrat

Dream réutilise les transcriptions persistées du journal Messenger et les analyses
documentaires réussies liées à une Task du round, à son agent et à l'URI exacte
d'une pièce jointe du message. Il ne déclenche ni transcription, ni téléchargement,
ni nouvelle analyse. Une pièce jointe sans texte acquis demeure explicitement non analysée.
Le modèle d'extraction reste celui configuré pour Dream dans le profil de l'agent.

Les preuves distinguent écrit, transcription, texte extrait et interprétation.
Chaque opération peut citer les références exactes qui la soutiennent ; les anciennes
réponses sans références conservent l'ensemble des preuves du checkpoint, par prudence.
Les métadonnées conservent message, URI, empreinte du texte, version fournisseur attestée
ou inconnue, localisateur et couverture. Une empreinte des anciens octets ne prouve pas
l'identité des octets actuels lorsque le fournisseur ne donne aucune version.
Résumé et passages d'une analyse ne constituent pas deux corroborations indépendantes.

L'analyse conserve au plus 500 000 caractères de passages déjà préparés dans son
checkpoint. La projection conversationnelle est bornée à 20 pièces jointes par message,
16 analyses réussies, 64 preuves et 8 000 caractères de texte de preuve par message.
Elle sélectionne au plus quatre passages par analyse : frontières et correspondances
lexicales avec le message, puis l'interprétation dans le budget restant. Les troncatures
et limites de couverture restent explicites. Ce choix n'est pas une recherche exhaustive
du texte des pièces jointes et ne qualifie pas les documents longs ou les tableaux.

Une transcription ou analyse documentaire tardive produit un nouveau sujet Dream.
Le reçu et la provenance incluent sa révision ; les effets antérieurs sont conservés et
la même révision reste idempotente. Les références conservent le lien typé vers le round.
Un oubli explicite d'un contenu bloque aussi sa réacquisition depuis une révision tardive
du même round ; un contenu corrigé demeure admissible.

Avant application, Dream reconstruit les preuves et compare leur empreinte à celle
préparée, avec l'agent, le Topic, le contact et la langue. Les nouveaux souvenirs dérivés
portent un validateur fourni par Dream à Memory dès le bootstrap. Lecture directe,
admission du rappel et lecture du graphe revalident les sources : message ou fichier
retiré, transcription corrigée, connexion révoquée ou analyse obsolète rendent cette
preuve indisponible. Une autre provenance indépendante valide conserve le souvenir.
Le marqueur est posé uniquement à la création d'un nouveau fait dérivé. Ajouter une
preuve par LINK ne rend pas un souvenir manuel ou un document existant dépendant de
cette conversation. Les ressources canoniques et historiques conservent leur contrat.
Un nouveau fait marqué sans aucune provenance est refusé à la lecture.
Les validations sont regroupées par page ou lot de candidats, avec hydratation commune
des messages et fichiers ; elles ne constituent pas un cache persistant d'autorisation.
L'admission finale reste fraîche. Le test de recherche sur 6 000 souvenirs est paramétré
pour les provenances historiques et les nouvelles preuves, avec au plus douze requêtes
pour cinquante résultats, tout en conservant l'isolation entre agents.
Les plans synthétiques montrent un coût JIT de plusieurs secondes pour des prédicats
exécutés en millisecondes. Recherche, rappel et graphe désactivent cette compilation
dans leur transaction avec `SET LOCAL`, sans modifier les paramètres de la connexion
pour les transactions suivantes. Le test couvre commit et rollback. Ces mesures sur
6 000 lignes ne qualifient ni la latence en production ni les très grands volumes.

## Vérification et limites

Les scénarios synthétiques de `test_conversation_memory.py` couvrent audio seul,
attribution, reçu tardif, répétition, langue, application après retrait/révocation/correction,
lecture directe, admission et visibilité du graphe, avec une provenance indépendante.
`test_document_analysis.py` réutilise une analyse réelle via ses frontières HTTP simulées,
sans préparation ni appel fournisseur supplémentaire, et vérifie l'isolation agent/Task/URI,
la version obsolète et l'arrivée après un premier reçu vide.
`test_acquisition_automation.py` protège l'oubli entre révisions du même round.

Seules les analyses réussies des Tasks directement liées au round sont reprises.
La propagation des analyses partielles et des Tasks descendantes, l'indexation précise
des passages documentaires et les campagnes de pertinence restent dans le plan mémoire.
