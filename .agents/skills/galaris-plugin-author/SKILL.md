---
name: galaris-plugin-author
description: Concevoir ou créer un plugin Galaris. À utiliser pour choisir une façade publique, créer un bundle signé de fiches de Service ou développer une contribution native telle qu’un codec, un éditeur de document ou un adaptateur.
---

# Créer un plugin Galaris

Lire le [guide auteur](../../../docs/fr/dev/plugin-authoring.md) pour choisir la famille
et son Sample. Besoin et frontière du domaine déterminent la façade. Vérifier dans le
code le mode de chargement disponible avant de choisir la structure du livrable.
Les Samples se trouvent dans `plugins/sample`. Garder les points d’entrée backend et
frontend ainsi que les données dans le même dossier de plugin et la même archive
de version.

- **Archive signée.** Copier REST ou MCP pour une fiche. Utiliser Dessin (ZIP), Fournisseur IA, Conversion ou Données pour le manifeste 2. Garder le code de plugin stable et
  qualifié par l'éditeur. Déclarer chaque contribution et sa version de contrat. Les
  réglages d'un compte et ses secrets passent par les paramètres standard de Connexion.
  Utiliser `plugins.sample.package` pour calculer les empreintes et signer. La clé
  privée reste chez le signataire. Présenter l'archive, son origine et les actions
  administratives séparément.
  Déclarer les dépendances Python exactes et les services externes épinglés par
  empreinte. Une contribution exécutable exige un éditeur explicitement approuvé
  par l’opérateur. Garder le code backend et les modules compilés dans le même ZIP.
- **Contribution native.** Suivre la façade et la composition du Sample correspondant.
  Pour Documents, fournir le même code, fournisseur et numéro de format dans les deux
  points d'entrée. L'éditeur binaire reçoit `DocumentContentSource`, envoie la révision
  lue et garde le brouillon après un échec. Le lecteur historique et la capture sont
  en lecture seule. Documents possède les révisions, les droits et la source originale.
- **Façade à ouvrir.** Décrire le port manquant, son propriétaire et un scénario
  d'intégration avant de proposer une extension du SDK. Éviter d'exposer les services
  ou modèles internes et de simuler une capacité installable.

Conserver une arborescence montrant le lien entre le manifeste, les ressources, les
points d'entrée et les tests. Lancer le skill
[galaris-plugin-qualification](../galaris-plugin-qualification/SKILL.md) pour vérifier le
mode réellement livré, les refus, la compatibilité et le retrait.
