---
name: galaris-plugin-qualification
description: Vérifier un plugin Galaris avant de le livrer. À utiliser pour tester une archive signée, un cycle installation/activation/retrait, un adaptateur natif ou la qualification d’un format documentaire.
---

# Qualifier un plugin Galaris

Utiliser le [guide auteur](../../../docs/fr/dev/plugin-authoring.md) pour déterminer
les tests observables de la façade. Préparer des sources et identifiants synthétiques
ainsi qu'un environnement Docker isolé.

- **Archive.** Valider avec le vrai lecteur de bundle. Tester un digest altéré, un
  signataire inconnu, un code/version déjà occupé et une incompatibilité. Une répétition
  de l'import doit garder une seule version. Tester installation inactive, activation,
  accès refusé, retrait et persistance des copies locales. En dev, la dérogation ne
  couvre que la plage de version hôte.
  Pour le manifeste 2, vérifier le refus sans autorisation d’exécution, le refus
  si une dépendance manque et la conservation de la génération précédente après
  un échec de chargement. Tester le vrai module frontend dans Chromium.
- **Document.** Tester des entrées valides et invalides avec la qualification de codec.
  Dans l'application, créer, enregistrer et relire une révision, injecter un conflit ou
  un refus d'écriture puis retrouver le brouillon. Vérifier aperçu inerte, accès selon
  les ACL, révisions historiques et téléchargement de la source après retrait.
- **Adaptateur.** Tester le protocole à sa frontière avec un service synthétique et des
  identités distinctes. Qualifier les délais, erreurs, annulations et la reprise selon
  le contrat de la façade. Exercer uniquement les capacités déclarées.

Associer les résultats à la version et à l'empreinte de l'archive quand elle existe.
Dans le compte rendu, distinguer ce qui a été testé par le codec, l'API et le navigateur.
La déclaration d'une capacité et un TCK incomplet ne constituent pas une certification.
