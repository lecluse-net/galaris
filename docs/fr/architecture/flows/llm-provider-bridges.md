<p align="right"><strong>Français</strong> · <a href="../../../en/architecture/flows/llm-provider-bridges.md">English</a></p>

# Bridges de fournisseurs IA

`app.llm` est le langage commun des ressources IA. Il expose des connexions détachées du modèle
ORM et des façades par service. Les produits externes vivent dans `bridge.*`.

```text
API / agents / messagerie / mémoire
                  │
                  ▼
             app.llm
  catalogue + contrats + registres
  protocoles OpenAI compatibles génériques
                  │
        résolution par catalog_code
                  ▼
 bridge.<provider>          bridge.models_dev
 endpoints, auth, payloads  métadonnées publiques
```

## Façades disponibles

| Contrat `app.llm` | Responsabilité du bridge |
|---|---|
| `ResourceDiscovery` | Lister modèles, voix ou autres ressources |
| `ModelManagement` | Installer ou supprimer un modèle géré |
| `ModelMetadata` | Enrichir les métadonnées propres au fournisseur |
| `TranscriptionProvider` | Adapter le STT batch |
| `RealtimeTranscriptionProvider` | Ouvrir une session STT PCM |
| `SpeechProvider` | Produire un MP3 ou un stream PCM |
| `ProviderAuthentication` | Réaliser une authentification externe |
| `ProviderChatTransport` | Adapter requête, réponse et SSE du chat |
| `OpenAIProtocolAdapter` | Normaliser l’URL du protocole commun |
| `RequestParameterPolicy` | Déclarer les paramètres et combinaisons acceptés par modèle et protocole |

Les implémentations reçoivent un `ProviderConnection` immuable. Elles ne reçoivent ni session
SQLAlchemy ni modèle ORM, sauf lorsqu’une intégration d’authentification possède explicitement la
persistance de ses jetons.

Le proxy applique la politique de paramètres après résolution du modèle et de l’effort,
avant l’envoi Chat ou Responses. Voir la [matrice auditée](../../dev/provider-parameters.md)
pour les règles de compatibilité et leur validation.

## Ajouter un fournisseur

1. Créer `back/bridge/<code>/__init__.py`.
2. Déclarer le `ProviderProfile` immuable : identité, URL, acquisition de clé, capacités et champs
   de configuration non secrets.
3. Implémenter une ou plusieurs façades existantes dans le bridge.
4. Enregistrer le profil, les services et la politique de paramètres texte au chargement du package.
5. Ajouter `bridge.<code>` à `back/modules.py`.
6. Si le fournisseur ajoute un type de connexion personnalisée dans l’interface, contribuer un
   fichier `front/bridge/<code>/llmProvider.ts`.
7. Tester le contrat du bridge et exécuter `make typecheck`, `make architecture-check` et les
   tests concernés.

Le protocole OpenAI-compatible générique ne doit pas être copié dans chaque bridge. Un bridge ne
remplace que les différences du produit : authentification, URL, headers, payloads, découverte ou
streaming.
