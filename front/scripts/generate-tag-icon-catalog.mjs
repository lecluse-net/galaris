// Run in the frontend container with an extracted emojibase-data@17.0.0 directory.
import { readFile, mkdir, copyFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const [translations] = process.argv.slice(2)
if (!translations) throw new Error('Expected an emojibase-data directory')
const root = path.resolve(import.meta.dirname, '..')
const generated = path.join(root, 'app/memory/emoji')
const extras = path.join(path.dirname(fileURLToPath(import.meta.resolve('@quasar/extras/package.json'))), 'exports')
await mkdir(generated, { recursive: true })
const normalize = code => code.toUpperCase().split('-').filter(part => part !== 'FE0F').join('-')
const message = value => value.replace(/[@{}|]/g, character => `{'${character}'}`)
const locales = ['en', 'fr', 'zh']
const localized = {}
for (const locale of locales) {
  const data = JSON.parse(await readFile(path.join(translations, locale, 'data.json'), 'utf8'))
  localized[locale] = new Map(data.flatMap(item => [item, ...(item.skins ?? []).map(skin => ({ ...item, ...skin }))])
    .filter(item => item.group !== undefined).map(item => [normalize(item.hexcode), item]))
}
const icons = []
const messages = Object.fromEntries(locales.map(locale => [locale, { documentTagEmoji: {} }]))
for (const [code, english] of [...localized.en.entries()].sort((a, b) => a[1].order - b[1].order)) {
  icons.push({ code, value: `emoji:${code}`, family: 'emoji', emoji: english.emoji, group: english.group, tone: Array.isArray(english.tone) ? english.tone[0] : (english.tone ?? 0) })
  for (const locale of locales) {
    const item = localized[locale].get(code)
    if (!item) throw new Error(`Missing ${locale} translation: ${code}`)
    messages[locale].documentTagEmoji[code] = {
      name: message(item.label.charAt(0).toLocaleUpperCase(locale) + item.label.slice(1)),
      keywords: message([item.label, ...(item.tags ?? []), english.label, ...(english.tags ?? [])].join(' ')),
    }
  }
}
const words = {
  account: 'compte personne utilisateur', user: 'utilisateur personne', users: 'utilisateurs personnes groupe',
  group: 'groupe equipe', people: 'personnes equipe', database: 'base donnees', server: 'serveur', network: 'reseau',
  web: 'internet site toile', cloud: 'nuage stockage', computer: 'ordinateur informatique', laptop: 'ordinateur portable',
  desktop: 'ordinateur bureau', code: 'code programmation', git: 'version code programmation', branch: 'branche',
  function: 'fonction', terminal: 'terminal console commande', api: 'interface programmation', security: 'securite',
  shield: 'bouclier protection securite', lock: 'cadenas verrou securite', key: 'cle', password: 'mot passe',
  add: 'ajouter nouveau', plus: 'ajouter plus nouveau', remove: 'retirer supprimer', minus: 'moins retirer',
  delete: 'supprimer effacer', trash: 'corbeille supprimer', edit: 'modifier edition', pencil: 'crayon modifier',
  pen: 'stylo ecrire modifier', check: 'valider verifier termine', close: 'fermer annuler', cancel: 'annuler',
  undo: 'annuler retour', redo: 'retablir', refresh: 'actualiser rafraichir', sync: 'synchroniser',
  save: 'enregistrer sauvegarder', download: 'telecharger', upload: 'televerser importer', search: 'rechercher recherche',
  filter: 'filtre filtrer', sort: 'trier tri', link: 'lien relier', share: 'partager partage', send: 'envoyer envoi',
  copy: 'copier copie', paste: 'coller', cut: 'couper', print: 'imprimer impression', printer: 'imprimante',
  play: 'lire lecture demarrer', pause: 'pause', stop: 'arreter stop', start: 'demarrer', run: 'executer courir',
  file: 'fichier document', folder: 'dossier repertoire', document: 'document fichier', note: 'note',
  book: 'livre lecture', library: 'bibliotheque', archive: 'archive rangement', box: 'boite colis',
  briefcase: 'travail metier mallette', office: 'bureau travail', factory: 'usine industrie', industry: 'industrie usine',
  building: 'batiment immeuble', hospital: 'hopital sante', medical: 'medical sante', doctor: 'medecin docteur sante',
  nurse: 'infirmier sante', school: 'ecole enseignement', graduation: 'diplome etudes', teacher: 'professeur enseignant',
  hammer: 'marteau travaux', wrench: 'cle outil reparation', tools: 'outils bricolage', gear: 'engrenage parametres',
  cog: 'engrenage parametres', settings: 'parametres reglages', calendar: 'calendrier date rendezvous',
  clock: 'horloge heure temps', timer: 'minuteur temps', alarm: 'alarme rappel', bell: 'cloche notification',
  mail: 'courriel email courrier', email: 'courriel courrier', envelope: 'enveloppe courrier', chat: 'discussion conversation',
  message: 'message messagerie', comment: 'commentaire discussion', phone: 'telephone appel', call: 'appel telephone',
  video: 'video film', camera: 'camera appareil photo', image: 'image photo', music: 'musique', microphone: 'micro voix',
  chart: 'graphique statistiques', graph: 'graphique', table: 'table tableau', finance: 'finance argent',
  money: 'argent monnaie', cash: 'argent caisse', currency: 'devise monnaie', invoice: 'facture', receipt: 'recu facture',
  cart: 'panier courses', basket: 'panier', shopping: 'achat courses', store: 'magasin boutique',
  home: 'maison accueil', house: 'maison', car: 'voiture automobile', truck: 'camion', train: 'train transport',
  airplane: 'avion voyage', plane: 'avion', boat: 'bateau', bicycle: 'velo', bike: 'velo', map: 'carte plan',
  earth: 'terre monde', globe: 'globe monde', compass: 'boussole', location: 'lieu localisation',
  heart: 'coeur amour', star: 'etoile favori', flag: 'drapeau', tag: 'etiquette tag', lightbulb: 'ampoule idee',
  tree: 'arbre nature', flower: 'fleur nature', leaf: 'feuille nature', weather: 'meteo', sun: 'soleil', moon: 'lune',
  water: 'eau', fire: 'feu', food: 'nourriture repas', coffee: 'cafe', apple: 'pomme', dog: 'chien', cat: 'chat animal',
  robot: 'robot intelligence artificielle', brain: 'cerveau intelligence', puzzle: 'puzzle assemblage',
  workflow: 'flux processus automatisation', sitemap: 'arborescence organigramme', dashboard: 'tableau bord',
}
const fontValues = new Set()
function addFont(family, style, slug) {
  const value = `font:${style}:${slug}`
  if (fontValues.has(value)) return
  fontValues.add(value)
  const code = `${style}-${slug}`
  const name = slug.replaceAll('-', ' ')
  const label = name.charAt(0).toUpperCase() + name.slice(1)
  icons.push({ code, value, family, emoji: '', group: -1, tone: 0 })
  for (const locale of locales) {
    messages[locale].documentTagEmoji[code] = {
      name: message(`${label}${style === 'far' ? ' (outline)' : style === 'fab' ? ' (brand)' : ''}`),
      keywords: message(`${name} ${locale === 'fr' ? slug.split('-').map(word => words[word] ?? '').join(' ') : ''}`),
    }
  }
}
const mdiCss = await readFile(path.join(extras, 'mdi-v7/mdi-v7.css'), 'utf8')
for (const slug of new Set([...mdiCss.matchAll(/\.mdi-([a-z0-9-]+)::before/g)].map(match => match[1]))) addFont('mdi', 'mdi', slug)
const awesome = JSON.parse(await readFile(path.join(extras, 'fontawesome-v7/icons.json'), 'utf8'))
const awesomeCss = await readFile(path.join(extras, 'fontawesome-v7/fontawesome-v7.css'), 'utf8')
const awesomeSlugs = new Set([...awesomeCss.matchAll(/\.fa-([a-z0-9-]+)(?=\s*[:,{])/g)].map(match => match[1]))
for (const key of awesome) {
  const style = key.slice(0, 3)
  const slug = key.slice(3).replace(/([a-z0-9])([A-Z])/g, '$1-$2').toLowerCase()
  if (awesomeSlugs.has(slug)) addFont('awesome', style, slug)
}
for (const family of ['emoji', 'mdi', 'awesome']) {
  const entries = icons.filter(icon => icon.family === family)
  if (family !== 'emoji') {
    const glyphs = entries.map(icon => icon.value.slice(5).split(':'))
    await writeFile(path.join(generated, `${family}.ts`), '// Generated by scripts/generate-tag-icon-catalog.mjs. Do not edit.\n'
      + "import { createFontCatalog } from '../tagEmojiCatalog.ts'\n"
      + `export default createFontCatalog('${family}', ${JSON.stringify(glyphs)}, ${JSON.stringify(words)})\n`)
    continue
  }
  const names = Object.fromEntries(locales.map(locale => [locale, { documentTagEmoji: Object.fromEntries(entries.map(icon => [icon.code, messages[locale].documentTagEmoji[icon.code]])) }]))
  for (const locale of locales) {
    await writeFile(path.join(generated, `messages.${locale}.ts`), '// Generated by scripts/generate-tag-icon-catalog.mjs. Do not edit.\n'
      + "import type { TagEmojiMessages } from '../tagEmojiCatalog'\n"
      + `const messages: TagEmojiMessages = ${JSON.stringify(names[locale])}\nexport default messages\n`)
  }
  await writeFile(path.join(generated, family === 'emoji' ? 'catalog.ts' : `${family}.ts`), '// Generated by scripts/generate-tag-icon-catalog.mjs. Do not edit.\n'
    + "import type { TagEmojiCatalog } from '../tagEmojiCatalog'\n"
    + `const catalog: TagEmojiCatalog = ${JSON.stringify({ icons: entries, messages: {} })}\nexport default catalog\n`)
}
await copyFile(path.join(translations, 'LICENSE'), path.join(generated, 'LICENSE.emojibase'))
const palette = await readFile(path.join(root, 'core/util/solaire.ts'), 'utf8')
const folders = [...palette.matchAll(/^\s+(\w+): \{ accent:/gm)].flatMap(match => [`folder:${match[1]}`, `folder-open:${match[1]}`])
await writeFile(path.join(root, '../back/app/memory/icon_catalog.json'), JSON.stringify([...icons.map(icon => icon.value), ...folders]) + '\n')
console.log(Object.fromEntries(['emoji', 'mdi', 'awesome'].map(family => [family, icons.filter(icon => icon.family === family).length])))
