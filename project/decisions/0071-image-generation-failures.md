# 0071 — Dimensions natives best effort et échecs de génération d’image

Statut : accepté — 2026-09-05

## Décision

Cette décision remplace l’exigence de dimensions exactes de
[0070](0070-native-image-dimensions.md), en conservant la génération native sans transformation.
`width` et `height` sont des préférences strictement positives, sans plafond sur la demande.
La génération est toujours best effort : une approximation native n’est pas une erreur et
ne demande pas de confirmation. Une demande de 100000 × 100000 choisit le maximum adapté
du modèle ; elle ne tente jamais d’allouer une image de cette taille dans Galaris.

Le sélecteur conserve une taille exacte disponible. Sinon, il préfère une taille couvrant
les deux côtés et minimise le plus grand agrandissement relatif, puis le nombre de pixels.
Si aucune taille ne couvre la demande, il minimise le plus grand écart relatif absolu,
puis l’écart total ; une égalité favorise la plus grande surface. Le choix parcourt uniquement
les candidats autorisés, jamais un espace proportionnel aux dimensions demandées.
Les candidats restent bornés à 8192 pixels par côté et 33 554 432 pixels au total.

Les bridges auteurs des modèles enregistrent leurs règles via
`app.llm.provider_facade.register_image_size_resolver`. OpenRouter consomme ce port pour
choisir les dimensions avant l’appel facturé et transmettre le couple ratio/résolution natif
de Gemini, ou la taille explicite d’OpenAI. Les règles ne sont pas copiées dans le routeur et
aucun import entre bridges n’est nécessaire. Les modèles dont les contraintes sont inconnues
utilisent leur taille par défaut. Gemini 3.1 Flash Image choisit ainsi 1200 × 896 pour une
préférence de 640 × 480, et 4096 × 4096 pour 100000 × 100000.
Un fournisseur sans adaptateur de dimensions utilise le chemin de génération existant avec
ses valeurs par défaut ; une préférence de taille ne désactive pas ce chemin.

La façade conserve les octets originaux même si la taille reçue diffère de la sélection.
La trace indique la préférence, la sélection et les dimensions obtenues. Le résultat MCP
annonce les dimensions réelles, jamais celles demandées si elles n’ont pas été produites.

`image_generate` expose ses véritables échecs comme des erreurs MCP ; les ajustements de taille
n’en font pas partie. Les exceptions ne divulguent pas les réponses brutes du
fournisseur. Un échec ne produit ni URI de succès ni effet de ressource enregistré.

La description de l’outil, son erreur et le skill commun demandent d’expliquer la limitation
au lieu de livrer silencieusement un SVG, du code graphique, une capture ou une image transformée.
L’ajustement des dimensions natives est automatique. Un changement de type de livrable
requiert l’accord explicite de l’utilisateur.
Ces instructions gouvernent le comportement du modèle ; elles ne constituent pas une
interdiction générale de créer des SVG avec les outils de fichiers.

## Validation

- Succès de 640 × 480 et de 100000 × 100000 avec sélection native, sans transformation.
- Sélection directe et via OpenRouter ; exact, supérieur, inférieur, portrait et paysage.
- Transmission des résolutions natives 512/1K/2K/4K et des références via OpenRouter.
- Erreur MCP observable par un client, sans écriture ni projection d’artefact, pour les
  contextes interne et Hermès ; conservation du diagnostic utile et masquage des secrets.

## Références

- [OpenRouter : dimensions normalisées](https://openrouter.ai/docs/guides/overview/multimodal/image-generation)
- [Gemini : résolutions natives](https://ai.google.dev/gemini-api/docs/generate-content/image-generation)
