import ts from 'typescript'
import type { Plugin } from 'vite'
import { readLocaleCatalog } from './catalogData.ts'

/** Select a language before bundling, keeping the existing module catalogs editable. */
export function selectCatalogLocale(source: string, fileName: string, locale: string): string {
  const file = ts.createSourceFile(fileName, source, ts.ScriptTarget.Latest, true)
  const statement = file.statements.find(ts.isExportAssignment)
  const catalog = statement?.expression
  if (!statement || !catalog || !ts.isObjectLiteralExpression(catalog)) {
    throw new Error(`${fileName}: locale catalog must default-export an object`)
  }
  const property = catalog.properties.find(item => ts.isPropertyAssignment(item)
    && !ts.isComputedPropertyName(item.name) && item.name.getText(file).replace(/^['"]|['"]$/g, '') === locale)
  if (!property || !ts.isPropertyAssignment(property)) {
    throw new Error(`${fileName}: missing locale ${locale}`)
  }
  // Preserve imports and local constants; the bundler removes unused languages.
  return source.slice(0, statement.getStart(file))
    + `export default ${property.initializer.getText(file)};`
    + source.slice(statement.end)
}

export function localeCatalogs(): Plugin {
  let root = process.cwd()
  let development = false
  const prefix = 'virtual:galaris-locale-'
  return {
    name: 'galaris-locale-catalogs',
    enforce: 'pre',
    configResolved(config) { root = config.root; development = config.command === 'serve' },
    resolveId(id) {
      if (id === `${prefix}fr` || id === `${prefix}zh`) return '\0' + id
    },
    load(id) {
      if (!id.startsWith('\0' + prefix)) return
      const locale = id.slice(('\0' + prefix).length)
      const source = JSON.stringify(readLocaleCatalog(root, locale, file => this.addWatchFile(file)))
      if (development) return `export default ${JSON.stringify(`/@galaris-locales/locale-${locale}.json`)}`
      const asset = this.emitFile({ type: 'asset', name: `locale-${locale}.json`,
        originalFileName: `core/i18n/catalogs/${locale}.json`, source })
      return `export default import.meta.ROLLUP_FILE_URL_${asset}`
    },
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const match = /^\/@galaris-locales\/locale-(fr|zh)\.json$/.exec(request.url ?? '')
        if (!match) return next()
        try {
          const source = JSON.stringify(readLocaleCatalog(root, match[1]!))
          response.setHeader('Content-Type', 'application/json; charset=utf-8')
          response.setHeader('Cache-Control', 'no-store')
          response.end(source)
        } catch (error) { next(error) }
      })
    },
    transform(source, id) {
      const [fileName, query] = id.split('?')
      const locale = new URLSearchParams(query).get('galaris-locale')
      if (!locale || !fileName?.endsWith('/i18n.ts')) return
      if (!['en', 'fr', 'zh'].includes(locale)) throw new Error(`Unsupported catalog locale: ${locale}`)
      return { code: selectCatalogLocale(source, fileName, locale), map: null }
    },
  }
}
