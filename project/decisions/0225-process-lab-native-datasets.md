# 0225 — Datasets natifs pour les campagnes Process du Lab

Statut : accepté, 2026-10-23.

Les entrées synthétiques des campagnes Process appartiennent à `app.dataset`.
Le Lab utilise sa façade publique, ses révisions, ses droits et ses clés de
création idempotentes. Il ne crée plus de Document pour conserver du JSON.
Le contrat expose `dataset_id` et une URI `data://` ; l'interface transmet cette
identité lors du lancement des runs réels. Les cas admis restent figés dans la
campagne, indépendamment des modifications ultérieures du Dataset.

La transition du schéma est additive : `lab_process_campaigns.dataset_id`
référence `datasets.id`. L'ancienne FK `dataset_document_id` reste nullable
pour préserver les campagnes existantes. Une contrainte impose exactement une
des deux références. Les anciennes campagnes conservent leur URI `document://`.
Toute nouvelle campagne utilise exclusivement la FK native.
Le nom d'entrée historique reste accepté par l'API et MCP pour les identités
Dataset déjà transférées ; il ne crée aucun nouvel accès aux Documents.
La convergence déclarative DbAdmin ajoute la colonne et la contrainte sans
effacer les campagnes, leurs cas ou les anciennes références.

Les tests Process vérifient l'absence de création documentaire, le rejeu de
création, les conflits d'une même clé, les refus d'accès, les vrais runs et les
preuves conservées. Les projections API conservent leur couverture des anciennes
références. Le parcours navigateur vérifie la création du Dataset, le lancement,
la fin de campagne et sa réouverture.
