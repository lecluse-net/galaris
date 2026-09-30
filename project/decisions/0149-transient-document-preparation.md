# ADR 0149 — Préparation documentaire commune et transitoire

- Statut : Accepted
- Date : 2026-09-30

## Décision

La conversion indépendante des fournisseurs appartient à `core.document`. Un worker
séparé produit un manifeste avec empreinte de la source, texte, rendu et numéro de
chaque page. LibreOffice convertit les fichiers Office, Pandoc les formats textuels
compatibles, PDFium extrait et rend les PDF, Tesseract apporte un OCR indicatif.
La source reste inchangée. Les fichiers temporaires sont supprimés après usage.

La passerelle Chat de `app.llm` compose la lecture native et la préparation à partir
des capacités du modèle. Un PDF compatible est envoyé avec sa couverture rendue ;
les autres formats sont préparés. Un refus documentaire ou un résultat structuré
explicitement incomplet peut déclencher le repli. Les erreurs d'authentification,
les erreurs étrangères aux documents et les effets d'outils ne sont pas rejoués.
Un flux déjà ouvert ne peut pas être relu automatiquement.

Les erreurs fournisseur transitoires 502, 503 et 504 peuvent être reprises deux fois
pour une requête terminée sans flux ni outil ; chaque tentative reste comptabilisée
et consomme le budget d'appels. Les pages pauvres en texte peuvent ajouter quatre
quadrants agrandis à la vue entière, sous la même limite de huit images par lot.
La consolidation distingue l'absence d'une réponse dans un lot d'une incertitude
réelle non résolue à l'échelle du document.

Les grandes entrées préparées sont réparties en lots bornés, puis consolidées avec
leurs citations. Chaque appel conserve le circuit d'autorisation et de comptabilité
existant. Les en-têtes exposent mode, pages source, lots et appels. La couverture
source ne constitue pas une preuve de fidélité sémantique. Le budget d'appels épuisé
et les conversions impossibles restent des échecs explicites.

Le harnais interne et l'ingestion Messenger réutilisent le préparateur. Leur contexte
direct reste borné et signale les omissions. Cela n'implémente pas une analyse durable
des grandes pièces jointes dans tous les parcours ; le SDK Responses et les flux
agentiques nécessitent encore leur propre admission/reprise documentaire.

## Limites et suite

Ce premier lot n'ajoute ni table ni nouveau module métier activé. Il ne promet ni
lecture de tous les formats, ni OCR parfait, ni interprétation parfaite de 500 pages.
Le worker limite la taille source, les pages, le texte, la mémoire et le temps ; la
passerelle limite les fichiers incorporés et les appels. Le rendu des fichiers Office
peut modifier la pagination. Les données XLSX brutes et formules complètent le rendu,
sans garantir les formats numériques ou la fraîcheur des valeurs calculées.

Les checkpoints Process, la couverture persistante, l'isolation réseau des convertisseurs,
les contrôles de fidélité, les autres SDK et la qualification complète restent dans
le [plan documentaire](../plans/analyse-documentaire-unifiee.md).
Les benchmarks du corpus privé restent dans les artefacts locaux ; les fixtures
versionnées sont synthétiques.
