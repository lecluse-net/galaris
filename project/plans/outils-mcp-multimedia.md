# Plan — Qualification et extensions multimédias

> **Statut :** `partial` — socle livré ; qualification réelle des comptes et extensions restantes.
>
> **Revue du code :** 11 septembre 2026. Aucun appel fournisseur payant n'est effectué par
> ce ménage documentaire.

**Qualification locale du 11 septembre 2026 :** les 26 tests du module passent, dont le transfert
de 100 Mo traversant file-share, Messenger et le bridge WhatsApp. La fixture utilise désormais
un destinataire Galaris vérifié et autorisé par le contrat de contact courant. Le transport
fournisseur reste simulé. Un inventaire en lecture seule trouve une ressource musicale
OpenRouter active ; le fournisseur/capacité à essayer et le plafond de dépense restent à
confirmer avant un appel réel. Voir le
[rapport de qualification](../audits/2026-09-11-memory-multimedia-qualification.md).

## 1. Contrats de départ

Le module et ses cinq outils sont réalisés. Leur contrat appartient à la
[décision 0072](../decisions/0072-specialist-multimedia-tools.md), au
[guide de configuration](../../docs/fr/components/multimedia.md) et aux tests du domaine.
Les tests de transport ne prouvent ni l'accès commercial ni la livraison sur chaque compte.
Voix, transcription, texte et image gardent leurs parcours distincts.

## 2. Qualification des comptes et de la livraison

Pour chaque combinaison fournisseur/capacité retenue :

1. Revalider la documentation accessible au compte, les ressources disponibles, les formats,
   les limites, les coûts et les conditions d'utilisation ; ne pas reprendre un tarif historique.
2. Exécuter un essai réel borné en coût avec les credentials de l'installation, sans les placer
   dans le dépôt, les fixtures ou le rapport.
3. Vérifier l'identité du modèle ou du service figée à l'admission, le suivi du Process et la
   récupération après interruption ; ne pas resoumettre aveuglément une opération ambiguë.
4. Lire le fichier résultant par son URI canonique, vérifier type et contenu, puis qualifier
   séparément sa livraison Messenger lorsque ce parcours fait partie de la recette.
5. Publier un résultat daté avec version de code, ressource, format, coût connu ou inconnu,
   limites rencontrées et preuve du résultat.

| Adaptateur présent | Qualification à apporter |
|---|---|
| OpenRouter | Compréhension audio/vidéo, génération Lyria et vidéo selon les ressources du compte |
| ElevenLabs | Effets sonores et Eleven Music |
| BytePlus | Génération vidéo Seedance via le produit accessible au compte |
| SunoAPI.org | Musique et service de bruitages, avec son statut explicite d'intermédiaire |

Réception : aucune capacité n'est annoncée comme qualifiée sur la seule base d'un mock.
Une indisponibilité commerciale reste explicitement distincte d'un défaut du code.
L'absence d'une qualification n'empêche pas de conserver les autres capacités validées.

## 3. Accès officiel Suno

L'adaptateur SunoAPI.org ne constitue pas une intégration de Suno Platform. Avant de concevoir
celle-ci, obtenir le contrat technique et l'éligibilité du compte : authentification,
ressources, soumission, suivi, callbacks, quotas, coûts et idempotence.

Aucun endpoint officiel n'est déduit du nom d'un produit ou d'un exemple tiers. Si l'accès
reste indisponible, le documenter ; ne pas remplacer silencieusement l'intermédiaire existant.

## 4. Extensions à concevoir séparément

| Intention | Condition préalable et preuve attendue |
|---|---|
| Références audio/vidéo, persona, remix, prolongement et reprise | Contrat provider accessible ; ressource stable, provenance et contraintes explicites |
| Plans de composition détaillés ElevenLabs | Paramètres réellement pris en charge ; durée, sections et paroles contrôlables |
| Annulation distante | Confirmation fournisseur vérifiable ; ne pas confondre arrêt local et annulation facturable |
| Analyse musicale mesurée avec Essentia | Distinguer mesures calculées et commentaires du modèle |
| Analyse spécialisée avec Music Flamingo | Vérifier licence, déploiement et qualité avant sélection |
| Génération locale avec ACE-Step | Service conteneurisé propre, ressources nécessaires et campagne comparative |
| Séparation de pistes et montage audiovisuel | Contrats distincts, fichiers et coûts bornés, reprise démontrée |

Chaque extension doit préciser son périmètre avant implémentation. Une persona, un moteur,
une voix et un préréglage restent des identités distinctes ; le catalogue ne crée pas de
pseudo-ressource artificielle uniquement pour satisfaire un exemple.

Les références d'entrée et de sortie restent des URI canoniques. Une extension ne doit ni
exposer un chemin serveur, ni activer automatiquement les connexions, ni modifier le modèle
ou la destination d'une génération en cours.

## 5. Validation et clôture

Pour une évolution retenue, renforcer les tests du contrat concerné : autorisation après
reconfiguration, répétition d'une invocation, timeout ambigu, callback dupliqué, fichier
incorrect, conservation du nom et du type, publication sans double effet et coût traçable.
Les tests automatisés demeurent indépendants des credentials commerciaux.

Les changements de schéma utilisent DbAdmin. Les contrôles Make, la recette fournisseur et
la validation de livraison doivent être rapportés séparément ; les résultats historiques du
6 septembre ne qualifient pas automatiquement une version ou un compte ultérieurs.

Clôturer ce plan lorsque la qualification des capacités retenues est publiée et que les
extensions restantes sont livrées, abandonnées explicitement ou suivies ailleurs. Les limites
durables restent dans l'ADR et le guide de configuration.

## 6. Références à revalider avant reprise

Références conservées de l'analyse du 6 septembre 2026 ; elles ne constituent pas une
vérification actuelle de l'accès ou des conditions commerciales :

- OpenRouter : [audio](https://openrouter.ai/docs/guides/overview/multimodal/audio),
  [vidéo](https://openrouter.ai/docs/guides/overview/multimodal/videos),
  [génération vidéo](https://openrouter.ai/docs/guides/overview/multimodal/video-generation).
- [BytePlus — API vidéo](https://docs.byteplus.com/en/docs/Byteplus_LAS/video_gen_enhanced).
- ElevenLabs : [composition](https://elevenlabs.io/docs/api-reference/music/compose),
  [effets sonores](https://elevenlabs.io/docs/api-reference/text-to-sound-effects/convert).
- [Suno Platform](https://platform.suno.com/).
- [Essentia](https://essentia.upf.edu/streaming_extractor_music.html),
  [Music Flamingo](https://huggingface.co/nvidia/music-flamingo-hf),
  [ACE-Step](https://github.com/ace-step/ACE-Step-1.5).
