# Qualification conversationnelle élargie — 24 octobre 2026

Cette recette complète le [parcours Goal natif](2026-10-24-goal-native-journey.md).
Elle distingue garanties des services, parcours navigateur avec fournisseur simulé et
comportement d'un modèle réel. Elle ne clôt pas le plan conversationnel.

## Attribution : défaut reproduit et corrigé

Trois projections n'avaient pas de scénario réunissant l'agent courant, un collègue IA
et un humain homonyme. Le harness interne et Hermes assimilaient les messages du collègue
aux réponses de l'agent courant. Le client OpenAI des harnais réseau omettait les snapshots
canoniques portant `text`, sans `role`/`content`. Le rendu commun supprimait aussi l'auteur
sans date. Ces défauts avaient échappé aux fixtures à un seul agent et aux attentes portant
sur l'habillage du message sans identité courante explicite.

La reproduction échoue initialement sur **7/7 cas** : trois projections avec et sans date,
puis conservation d'un auteur sans date. Les mêmes cas passent après correction.
L'extension couvre FR/EN, homonymes, identité authentifiée primant sur un rôle fourni,
pair sans identité courante connue, dates invalides, citations et fichiers joints.

Seule l'identité de l'agent courant produit un tour assistant. Un pair reste une entrée
externe attribuée à une IA. Nom et identifiant restent visibles sans date ; une identité
inconnue n'est pas inventée. Les historiques SDK en `role`/`content` restent compatibles,
sans convertir leurs enregistrements d'outils en messages utilisateur. Le filtrage des
cartouches accidentellement repris en streaming conserve les citations en blocs de code.

Le contrôle initial des contrats sélectionnés passe **923 tests**. Après correction,
le groupe des consommateurs passe **775 tests** et signale quatre attentes de l'ancienne
forme du cartouche. Ces attentes sont remplacées par la conservation du nom, de
l'identifiant et du contenu. Le contrôle ciblé final passe **144 tests**, comprenant ces
quatre variantes, les trois projections, les médias et les historiques SDK.
Ces groupes se recouvrent : leurs nombres ne sont pas additionnés.
La revue finale reproduit aussi une collision entre identifiants longs tronqués. Les
libellés abrégés ou échappés conservent désormais une empreinte distinctive ; les trois
cas de collision sont couverts, sans changer l'identité originale utilisée pour les rôles.
La compatibilité vérifie également qu'un corps d'ancien message reste présent lorsque
des fichiers sont joints ; le texte de repli ne doit pas être remplacé par leurs seules URI.

Ces mesures portent sur les données présentées au modèle, pas sur son taux de compréhension
sémantique ni sur une absence universelle d'erreur d'attribution.

## Harnais et frontières externes

Les **quatre exécutables épinglés** Codex, Claude Agent, Hermes et DeepSeek Harness passent
leurs sondes réelles avec modèle de boucle locale et réseau extérieur désactivé. Les preuves
conservent les empreintes des images et sources. Cela qualifie les SDK et les scénarios
de contrôle de la sonde, sans qualifier un compte payant ou un fournisseur réel.
Les bridges de messagerie sont testés aux frontières synthétiques ; ces tests ne prouvent
pas un échange sur des comptes Matrix, Talk, OneBot, Telegram ou WhatsApp réels.

## Application assemblée et limites

La première campagne sélectionne 27 scénarios par navigateur : **72/81 passent**.
Les échecs révèlent des défauts de montage : privilèges Document absents de la fixture,
destinataire au-delà de la première page, ancienne commande de carte documentaire,
permissions de presse-papiers propres à Chromium et modèle de reprise consommé par une
classification annexe. Les corrections conservent le workflow applicatif réel et bornent
le modèle synthétique de reprise à l'exécution agentique.

Les campagnes de confirmation et leurs limites sont conservées dans les preuves locales.
La campagne Chat/partage/références passe **19/19 dans Chromium**, **18/19 dans Firefox**
et **17/19 dans WebKit**. Les deux échecs de référence restants conduisent à reproduire
un défaut applicatif : le menu Coller insère l'URI brute sans résoudre son titre, alors que
le collage clavier utilise le traitement natif des références. Le menu utilise désormais
ce même traitement, en conservant le contrôle de contexte après lecture du presse-papiers.
Le parcours référence → titre → carte → réouverture → modale → affichage mobile passe
ensuite **3/3**, sur les trois navigateurs. Firefox/WebKit remplacent uniquement la frontière
du presse-papiers système ; Chromium utilise son presse-papiers réel.

La recette complémentaire de portée et Process passe **15/15** : cinq scénarios dans chacun
des trois navigateurs. Elle vérifie cinq Tools administratifs et les appels MCP réellement
limités au scope choisi, un IF humain après computation Dataset, les valeurs fausses et
nullables, la réponse Chat avec fichier conservant son URI, et une activité humaine en
attente reprise après un seul résultat. Les services, droits et effets persistés sont réels ;
ce n'est pas une mesure de choix spontané du modèle.

Les composants d'édition passent **87/88** scénarios ; les références passent **17/19**.
Les deux attentes de copie Task portaient sur un ancien bouton ; la copie par menu
contextuel dans la modale conserve désormais leur garantie. Le collage par menu est
couvert par les variantes URL existantes, sans dupliquer le corpus des références.
Les deux variantes Task repassent ensuite **2/2** ; les 17 autres cas étaient déjà réussis.
Une reconnexion WebKit échoue avant soumission dans une campagne ; le même parcours
d'admission passe ensuite trois répétitions isolées. Sa cause n'est pas établie : les
réussites ne suppriment pas l'incident et ne prouvent pas sa correction.
L'autre incident concerne l'ouverture des propriétés d'une image au clavier après upload :
trois répétitions isolées passent ensuite, sans correction produit attribuée à cet incident.

La préparation initiale du pilote d'équipe ouvre le Chat dans Chromium avec trois agents,
quatre documents synthétiques et **zéro appel physique au modèle**. Les deux premiers essais
sont exclus parce que des sources changent pendant la préparation. Une troisième
préparation sur sources stables réussit, sans erreur navigateur ni modification de sources
pendant cet essai. Ce préparatif ne constitue pas une mission générative d'équipe.

## Premier message : défaut applicatif reproduit et corrigé

La première mission réelle révèle quatre lectures HTTP 422 avant le reçu d'envoi : les
panneaux Documents, Tasks et Process, ainsi que les aperçus de références, transmettent
l'identifiant temporaire du message comme UUID persistant. Le scénario avec premier message
et réponse d'admission retenue reproduit les **quatre lectures invalides avant correction**.
Les deux points de projection ignorent désormais les messages temporaires pour ces lectures.
Le même scénario vérifie **zéro lecture invalide**, puis les quatre lectures avec l'identifiant
canonique, un seul message et le compositeur vidé après réception.

Le contrôle des composants passe initialement 30 cas et révèle une fixture utilisant encore
les privilèges Memory pour Documents. Après alignement sur le contrat Document, le nouveau
scénario et cette interaction passent **2/2**. Le parcours assemblé d'admission, exécution
durable, livraison unique et réouverture passe **3/3**, sur Chromium, Firefox et WebKit,
avec une référence documentaire dès le premier message.

La collecte s'arrêtait aussi sur l'erreur navigateur, même après admission de la mission.
Le pilote observe désormais le travail accepté sans le soumettre à nouveau et conserve
l'erreur primaire si une collecte secondaire échoue. Les tests de l'orchestration réelle
du script remplacent uniquement ses commandes externes. Les contrôles de préparation
vérifient également le profil et les appartenances d'équipe avant tout appel payant.
Le groupe pilote/profils/politique de dialogue passe **53 tests**.

## Mission réelle avec trois agents : exécution aboutie, contenu partiellement accepté

La campagne utilise DeepSeek V4.1 Flash via OpenRouter, en environnement isolé, sur des
copies figées du code. Elle conserve les tentatives incorrectes au lieu de les transformer
en réussites après correction des fixtures.

| Étape | Observation | Appels physiques | Coût enregistré (USD) |
|---|---|---:|---:|
| Première soumission | Mission admise, erreur navigateur, collecte interrompue | Inconnu | Inconnu |
| Profil initial | Modèle texte affecté à tort au service natif Decisions ; exécution refusée | 2 | 0,003749 |
| Profil corrigé | Collègues hors équipe : refus de portée, aucune contribution obtenue | 12 | 0,019554 |
| Équipe dédiée, budget initial insuffisant | Un collègue termine ; échéance atteinte malgré une hausse tardive de l'admission | 9 | 0,015194 |
| Équipe et budgets préparés dès le départ | Deux contributions terminées, synthèse livrée ; défauts éditoriaux observés | 17 | 0,044835 |

Les deux corrections de fixture utilisent les services publics : profil texte sans binding
Decisions et équipe dédiée aux trois agents, avec droits documentaires accordés séparément.
Le refus de portée reste un contrôle négatif ; aucune permission applicative n'est élargie.
La limite initiale de 100 000 tokens laisse moins que la réserve nécessaire à une nouvelle
phase. L'augmentation tardive ne démontre pas une reprise réussie. Le dernier essai prépare
300 000 tokens et 480 secondes d'admission dès le départ. Ces limites ne sont pas un plafond
physique de consommation fournisseur ; aucune comparaison de performance entre ces essais
de configurations différentes n'est revendiquée.

Dans ce dernier essai, les **deux collègues produisent chacun leur contribution**, la Task
responsable termine et la livraison finale est observée une seule fois dans le Chat.
L'observation dure **46,98 secondes**, hors préparation de la stack. Les **17 appels** incluent
les classifications et le dispatch. Les trois sources restent à la révision 1, avec leur
contenu inchangé ; le document cible passe de la révision 1 à 3, sans document supplémentaire.
Les captures de soumission et de résultat ne signalent aucune erreur navigateur.

La relecture par l'assistant constate les quatre critères factuels initiaux satisfaits :
date et capacité sourcées, montants et transport non engagé préservés, inscriptions ouvertes,
références exactes sans nouvelle réservation prétendue. Ce constat n'est pas une acceptation
humaine. Le document contient encore **deux défauts de qualité** : un titre de section dupliqué
et une contradiction non établie entre l'interdiction d'envoi externe et l'existence d'un devis
de transport. Un devis ne prouve ni un prestataire externe ni un envoi. La réponse finale
reprend cette inférence. L'ambiguïté distincte du cadrage « sans réservation » face à une
réservation déjà confirmée est une limite de fixture, pas une erreur du modèle démontrée.

La grille initiale, centrée sur la conservation des faits, n'aurait pas détecté ces deux
défauts. Deux critères d'acceptation sont ajoutés pour les prochaines campagnes : contradiction
fondée sur des affirmations incompatibles de même objet/périmètre, et intégration sans
répétition éditoriale inutile. Ils ne sont pas injectés dans la mission. Les preuves et la grille
originales restent inchangées ; une relecture locale séparée consigne les deux échecs ajoutés
après observation. Aucun gain sémantique, taux général de réussite ou correction de ces défauts
n'est revendiqué sur cet essai unique. Les consignes générales ne sont pas modifiées à partir
de cette seule observation.

Lint backend/frontend, typage strict et catalogues de traduction passent. La préparation
documentaire et les contrats d'architecture passent ; `git diff --check` est propre.

Les preuves détaillées restent sous `artifacts/conversation-wide/`, `artifacts/e2e/`,
`artifacts/agent-team/` et `artifacts/harness-runtimes/`. Ce rapport conserve uniquement
des agrégats et conclusions techniques. Le coût cumulé enregistré atteint **3,24761 USD**,
dont **0,08333 USD** pour les quatre observations Quartz réconciliées. Une réserve de
**0,25 USD** reste affectée à la première soumission non réconciliée : total prudent
**3,49761 USD**, sous le plafond autorisé de 4 USD. Ce total n'est pas une facture complète.
Comptes de messagerie externes réels, parcours vocal complet, changements de consigne pendant
un travail d'équipe réel, répétitions comparables et qualité sémantique restent à qualifier.
Aucun déploiement ni validation complète réservée à l'utilisateur n'est effectué.

## Correction des deux défauts éditoriaux après la recette

La trace relie la fausse contradiction à la reprise d'une hypothèse du collègue sans contrôle
de sa compatibilité avec les sources. Le doublon provient d'un `file_edit` couvrant les blocs
7 à 11 mais réintroduisant un titre situé dans le bloc précédent, conservé par l'édition.
Le stockage exécute correctement la plage demandée ; aucun dédoublonnage silencieux du contenu
n'est ajouté.

Les consignes communes demandent désormais de vérifier les contributions avant adoption et
de réserver les contradictions aux affirmations incompatibles sur le même objet, la même
période et le même périmètre. Une inconnue ne devient pas un conflit établi. La politique
d'édition et le contrat MCP précisent la correspondance entre bornes numérotées, premier/dernier
bloc remplacé et titre conservé hors plage. Le passage assemblé se vérifie avant soumission,
sans imposer un nouvel appel ou une relecture systématique après écriture. Le skill système
et le contrat éditorial FR/EN portent les mêmes règles.

Un contrôle structurel est ajouté au pilote : il signale les titres identiques consécutifs
sans modifier le document ni accorder une acceptation de contenu. Il détecte **un doublon
dans la preuve initiale et zéro dans la preuve corrigée**. Quatre variantes couvrent également
les titres avec balisage, les répétitions légitimes séparées par du texte et les niveaux
différents. Les quatre cas échouent d'abord en l'absence du contrôle ; le groupe ciblé complet
passe ensuite **70 tests**, avec les consommateurs du prompt, les droits et révisions
documentaires et le contrat MCP.

Une nouvelle mission réelle avec trois agents termine avec **deux contributions et une
livraison unique**, en **20 appels physiques**, pour **0,055589 USD**. Les trois contenus
sources restent inchangés à la révision 1 ; le document existant passe à la révision 2.
Les quatre critères factuels initiaux sont préservés. La relecture de l'assistant ne retrouve
ni le titre dupliqué ni le conflit inventé entre devis de transport et interdiction d'envoi
externe, dans le document comme dans la réponse finale. L'acceptation humaine reste distincte.
La limite d'admission de tokens a dû être augmentée pendant ce run après la fin des deux
contributions : sa durée n'est pas comparable à celle de l'essai initial. Aucun gain de coût,
de nombre d'appels ou taux général de réussite n'est revendiqué sur ces deux missions.

Le contrôle comportemental apparié reprend six familles FR/EN sur le modèle réel, avec
outils simulés : **10/12 avant et 10/12 après**, sans nouvel échec apparié ni effet interdit.
Les deux échecs communs, en FR et EN, concernent la lecture indisponible : recherches de
repli et nouvelles lectures épuisent la limite d'appels de la fixture. Ils restent ouverts ;
ce contrôle n'est pas présenté comme entièrement réussi.

La calibration révèle ensuite une nuance supplémentaire : dans **6/8 propositions longues
exploitables** avec la première correction, le champ des contradictions contient encore une
inférence du collègue pourtant décrite comme non étayée dans le corps de la proposition.
La règle finale précise qu'une absence de preuve ne réfute pas une affirmation : sans fait
source incompatible, l'inférence reste non étayée et ne doit pas figurer parmi les contradictions.

La vérification finale compare les anciennes et nouvelles consignes sur trois situations
courtes, chacune répétée trois fois : devis non engagé sans conflit établi ; coût du transport
absent ; deux capacités existantes différentes pour la même salle et la même date. Le protocole,
le modèle et les paramètres sont identiques entre variantes ; l'ordre alterne entre répétitions.
Les **18 réponses sont exploitables**. La relecture par l'assistant et le contrôle des classes
attendues donnent **8/9 avant → 9/9 après**, sans nouvel échec apparié. Les cas d'inférence non
étayée passent de **5/6 → 6/6** ; les vrais conflits restent identifiés dans **3/3 → 3/3**.
Les coûts inconnus ne sont pas inventés. Ces sondes ne rédigent ni ne modifient de document
et ne prouvent pas une coordination d'équipe. Elles ont servi à la calibration : ce n'est pas
une réserve indépendante ni une mesure générale de compétence. La dernière précision de consigne
n'a pas été rejouée dans une nouvelle mission complète à trois agents.

Les sondes longues antérieures ne sont pas retirées des résultats : **27 appels, 23 propositions
exploitables et quatre sorties tronquées ou sans contenu final exploitable**. Le retrait du mode
JSON forcé ne suffit pas à supprimer cet incident fournisseur. Les collecteurs s'arrêtent sans
réessai automatique ; le contenu de raisonnement n'est pas substitué à une réponse finale.
La campagne de six missions supplémentaires avait été refusée par la revue automatique, faute
de garantie sur sa marge monétaire. Les vérifications de remplacement utilisent des appels
unitaires sans outils, avec bornes d'entrée/sortie explicites et réserve calculée avant lancement.
Ce changement de protocole est conservé comme limite, sans attribuer son effet aux consignes.

Les **70 tests ciblés** passent, puis les **20 tests des consommateurs du prompt** repassent
après la dernière précision ; ces groupes se recouvrent. Lint backend/frontend, Ruff ciblé,
typage des deux fichiers de production modifiés et préparation documentaire passent.
Le typage global signale encore deux erreurs dans `core/authorize/guard_provider.py`, modifié
en parallèle hors de ce lot ; aucun correctif RBAC n'est inclus ici. Le parcours vocal,
les comptes externes et la qualité générale restent ouverts. Aucune validation complète
réservée à l'utilisateur, aucun commit et aucun déploiement ne sont effectués.

Le cumul enregistré final est de **3,39700 USD**, plus **0,25 USD** de réserve pour la première
soumission non réconciliée, soit **3,64700 USD** au total prudent. Les échecs de sondes sont inclus.
Les mesures, reçus, contrôles structurels et relectures séparées restent sous
`artifacts/conversation-quality/` ; les preuves originales ne sont pas réécrites.
