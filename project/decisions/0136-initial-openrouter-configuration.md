# 0136 — Configuration OpenRouter proposée à l'installation

Statut : accepté. Date : 2026-09-25.

## Garantie

Une nouvelle installation propose OpenRouter sans secret, neuf modèles et un profil
Défaut prérempli. Les affectations et les efforts de raisonnement reprennent la sélection
de référence retenue pour la distribution. Aucun identifiant de base, compte, secret,
historique ou tarif propre à une installation n'est embarqué.

## Décision

`app.llm.initial_configuration` est une action DbAdmin `AFTER_EXPAND`, applicable uniquement
lorsque les trois tables `llm_providers`, `llms` et `llm_profiles` viennent d'être créées.
Le fournisseur est résolu depuis le catalogue du bridge OpenRouter. Les modèles et le
profil sont créés dans la même transaction, avant les datasets qui établissent le profil
courant. La présence du fournisseur, y compris historisé, prouve la création atomique
et protège les personnalisations après un commit réussi. Après un échec, les datasets
peuvent avoir créé un profil vide ; la reprise le réutilise au lieu d'en créer un second.

Les données appartiennent ensuite à l'administrateur. Un dataset permanent recréerait
les éléments supprimés ou renommés ; cette proposition ne doit donc pas en être un.
Les synchronisations sans création des tables ne la rejouent pas. Le mécanisme de reprise
DbAdmin conserve les actions inachevées et réessaie après rollback. Les bases existantes
restent inchangées. Aucune requête réseau ni récupération de secret n'est nécessaire à
l'initialisation. Les prix restent actualisables par le mécanisme habituel du fournisseur.

Les contraintes métier restent applicables : pour supprimer le dernier profil proposé,
l'utilisateur crée un remplaçant, éventuellement vide. Le fournisseur et les modèles
restent supprimables par leurs services ordinaires.

## Vérification

`app/llm/tests/test_initial_configuration.py` vérifie l'installation réelle sur base
éphémère, la résolution des sélections, l'absence de secrets, la conservation des
personnalisations et suppressions, ainsi que le rollback et la reprise atomique.
