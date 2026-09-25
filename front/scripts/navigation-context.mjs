/** Export the shipped navigation, without starting Vue or querying an installation. */
import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import ts from 'typescript'

// These imports only appear inside availability/badge predicates. Never execute them.
const runtimeImports = new Set([
  'app/chat/availability.ts', 'app/chat/stores/inbox.ts',
  'app/connection/availability.ts', 'app/console/stores/consoleStore.ts',
  'app/browser/stores/browserSettingsStore.ts',
])

export function dataLoader(front) {
  const cache = new Map()
  function load(relative) {
    if (cache.has(relative)) return cache.get(relative)
    if (runtimeImports.has(relative)) {
      return new Proxy({}, { get: (_, name) => function unavailable() {
        throw new Error(`Runtime predicate must not run: ${relative}:${String(name)}`)
      } })
    }
    const allowed = /(?:^|\/)(navigation|presentation|access|i18n)\.ts$/.test(relative)
      || ['modules.ts', 'app/index/navigationSections.ts', 'core/navigation/tree.ts',
        'core/authorize/definitions.ts', 'core/i18n/merge.ts',
        'core/i18n/locales/fr.ts', 'core/i18n/locales/en.ts'].includes(relative)
    if (!allowed || relative.includes('..')) throw new Error(`Unreviewed navigation import: ${relative}`)
    const source = fs.readFileSync(path.join(front, relative), 'utf8')
    const output = ts.transpileModule(source, {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
      fileName: relative,
    }).outputText
    const loaded = { exports: {} }
    const require = specifier => {
      if (specifier === '@/core/authorize') {
        return { privileges: load('core/authorize/definitions.ts') }
      }
      const resolved = specifier.startsWith('@/') ? specifier.slice(2)
        : specifier.startsWith('.') ? path.posix.join(path.posix.dirname(relative), specifier) : null
      if (!resolved) throw new Error(`Unsupported navigation import: ${specifier}`)
      return load(resolved.endsWith('.ts') ? resolved : `${resolved}.ts`)
    }
    // Only reviewed repository data modules run here, as in check-i18n.mjs.
    new Function('module', 'exports', 'require', output)(loaded, loaded.exports, require)
    cache.set(relative, loaded.exports)
    return loaded.exports
  }
  return load
}

function catalogsIn(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const file = path.join(directory, entry.name)
    return entry.isDirectory() ? catalogsIn(file) : entry.name === 'i18n.ts' ? [file] : []
  })
}

export function navigationContext(root) {
  const front = path.join(root, 'front')
  const load = dataLoader(front)
  const { modules } = load('modules.ts')
  const { mergeNavigationTrees } = load('core/navigation/tree.ts')
  const { deepMergeMessages } = load('core/i18n/merge.ts')
  const messages = Object.fromEntries(['fr', 'en'].map(lang => [lang, load(`core/i18n/locales/${lang}.ts`).default]))
  // Match the global i18n loader, including catalogs from inactive modules.
  for (const file of ['app', 'core', 'bridge'].flatMap(layer => catalogsIn(path.join(front, layer))).sort()) {
    const catalog = load(path.relative(front, file))
    for (const lang of ['fr', 'en']) if (catalog.default?.[lang]) deepMergeMessages(messages[lang], catalog.default[lang])
  }
  const translate = key => Object.fromEntries(['fr', 'en'].map(lang => {
    if (!key) return [lang, '']
    const value = key.split('.').reduce((parent, part) => parent?.[part], messages[lang])
    if (typeof value !== 'string') throw new Error(`Missing ${lang} navigation label: ${key}`)
    return [lang, value]
  }))
  const tree = {}
  const sources = new Map()
  function recordSources(nodes, source, prefix = '') {
    for (const [key, node] of Object.entries(nodes)) {
      const id = prefix ? `${prefix}.${key}` : key
      sources.set(id, [...(sources.get(id) ?? []), source])
      if (node.children) recordSources(node.children, source, id)
    }
  }
  for (const module of modules) {
    const file = `${module}/navigation.ts`
    if (!fs.existsSync(path.join(front, file))) continue
    const contribution = load(file).default
    recordSources(contribution, `front/${file}`)
    mergeNavigationTrees(tree, contribution)
  }
  const sections = load('app/index/navigationSections.ts').navigationSections
  const roots = [...sections, ...Object.keys(tree).filter(key => !sections.some(s => s.rootKey === key))
    .map(rootKey => ({ rootKey }))]
  const entries = []
  function walk(nodes, prefix, trails, privilegeGroups, conditions) {
    for (const [key, node] of Object.entries(nodes).sort(([, a], [, b]) => (a.order ?? 99) - (b.order ?? 99))) {
      const id = prefix ? `${prefix}.${key}` : key
      const labels = translate(node.label)
      const breadcrumbs = Object.fromEntries(['fr', 'en'].map(lang => [lang, [...trails[lang], ...(labels[lang] ? [labels[lang]] : [])]]))
      const groups = node.privileges?.length ? [...privilegeGroups, node.privileges] : privilegeGroups
      const visibility = node.visible === false ? 'hidden' : typeof node.visible === 'function' ? 'dynamic' : 'always'
      const inheritedConditions = visibility !== 'always' ? [...conditions, { node: id, visibility }] : conditions
      if (node.to || node.href) entries.push({
        id, labels, breadcrumbs, route: node.to ?? null, href: node.href ?? null,
        description: translate(node.description), privilege_groups: groups,
        conditions: inheritedConditions, sources: sources.get(id),
      })
      if (node.children) walk(node.children, id, breadcrumbs, groups, inheritedConditions)
    }
  }
  for (const section of roots) {
    if (!tree[section.rootKey]) continue
    const labels = translate(section.label)
    const trails = Object.fromEntries(['fr', 'en'].map(lang => [lang, labels[lang] ? [labels[lang]] : []]))
    const rootNode = tree[section.rootKey]
    // Include any root-level constraints in every descendant's access requirements.
    walk({ [section.rootKey]: rootNode }, '', trails, [], [])
  }
  return { schema_version: 1, generated_by: 'front/scripts/navigation-context.mjs', entries }
}

const cell = value => String(value).replaceAll('|', '\\|').replaceAll('\n', ' ')
export function renderNavigation(context, lang) {
  const fr = lang === 'fr'
  const lines = [
    fr ? '<p align="right"><strong>Français</strong> · <a href="../../../en/architecture/generated/navigation.md">English</a></p>'
      : '<p align="right"><a href="../../../fr/architecture/generated/navigation.md">Français</a> · <strong>English</strong></p>',
    '', fr ? '# Carte des menus Galaris' : '# Galaris menu map', '',
    fr ? '> Généré depuis les modules actifs, leurs menus et traductions par `make project-context`. Ne pas modifier à la main.'
      : '> Generated from active modules, menus and translations by `make project-context`. Do not edit manually.', '',
    fr ? 'Cette carte décrit le produit livré, pas les menus visibles pour un compte donné. Chaque groupe de privilèges est un OU ; les groupes des ancêtres et de l’entrée doivent tous être satisfaits. Les conditions dynamiques sont évaluées dans l’application, jamais pendant cette génération.'
      : 'This map describes the shipped product, not the menus visible to a particular account. Privileges within each group use OR; every ancestor and entry group must be satisfied. Dynamic conditions are evaluated in the application, never during generation.', '',
    fr ? 'Le [guide de navigation](../../user/navigation.md) détaille les onglets, le menu du compte, les parcours et les entrées absentes. Les sous-entrées de harnais chargées depuis le catalogue serveur ne sont pas figées ici.'
      : 'The [navigation guide](../../user/navigation.md) explains tabs, the account menu, workflows and missing entries. Harness subentries loaded from the server catalog are not frozen here.', '',
  ]
  for (const entry of context.entries) {
    const rights = entry.privilege_groups.map(group => `(${group.join(' OR ')})`).join(' AND ') || '—'
    lines.push(`## ${entry.breadcrumbs[lang].join(' → ')}`, '',
      `- ${fr ? 'Route' : 'Route'} : \`${entry.route ?? entry.href}\``,
      `- ${fr ? 'Usage' : 'Purpose'} : ${entry.description[lang] || '—'}`,
      `- ${fr ? 'Visibilité du menu (privilèges)' : 'Menu visibility (privileges)'} : ${rights}`,
      `- ${fr ? 'Conditions supplémentaires' : 'Additional conditions'} : ${entry.conditions.map(c => `${c.node}: ${c.visibility}`).join('; ') || '—'}`,
      `- ${fr ? 'Sources' : 'Sources'} : ${entry.sources.map(s => `\`${cell(s)}\``).join(', ')}`, '')
  }
  return lines.join('\n')
}

export function generatedNavigationFiles(root) {
  const context = navigationContext(root)
  const files = new Map()
  for (const lang of ['fr', 'en']) {
    const directory = path.join(root, 'docs', lang, 'architecture/generated')
    files.set(path.join(directory, 'navigation.json'), JSON.stringify(context, null, 2) + '\n')
    files.set(path.join(directory, 'navigation.md'), renderNavigation(context, lang))
  }
  return files
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const index = process.argv.indexOf('--root')
  const root = index >= 0 ? path.resolve(process.argv[index + 1]) : path.resolve(import.meta.dirname, '../..')
  const check = process.argv.includes('--check')
  for (const [file, content] of generatedNavigationFiles(root)) {
    if (check) {
      if (!fs.existsSync(file) || fs.readFileSync(file, 'utf8') !== content) {
        console.error(`Stale navigation documentation: ${file}. Run make project-context.`)
        process.exitCode = 1
      }
    } else {
      fs.mkdirSync(path.dirname(file), { recursive: true })
      fs.writeFileSync(file, content)
      console.log(`generated ${file}`)
    }
  }
}
