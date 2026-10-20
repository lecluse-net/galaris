import fs from 'node:fs'
import path from 'node:path'
import ts from 'typescript'
import { deepMergeMessages, type LocaleMessages } from './core/i18n/merge.ts'

const importedCatalogs = new Set(['app/lab/processI18n.ts', 'app/process/nativeI18n.ts'])

/** Evaluate only the repository's reviewed catalog data and its two shared catalogs. */
export function readLocaleCatalog(root: string, locale: string, onRead: (file: string) => void = () => {}): LocaleMessages {
  const cache = new Map<string, LocaleMessages>()
  function read(relative: string): LocaleMessages {
    const cached = cache.get(relative)
    if (cached) return cached
    const file = path.join(root, relative)
    onRead(file)
    const source = fs.readFileSync(file, 'utf8')
    const output = ts.transpileModule(source, {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
      fileName: file,
    }).outputText
    const exports: LocaleMessages = {}
    const require = (specifier: string): LocaleMessages => {
      const target = path.posix.join(path.posix.dirname(relative), `${specifier}.ts`)
      if (!specifier.startsWith('./') || !importedCatalogs.has(target)) {
        throw new Error(`Unreviewed catalog import: ${relative}: ${specifier}`)
      }
      return read(target)
    }
    new Function('exports', 'require', output)(exports, require)
    cache.set(relative, exports)
    return exports
  }
  function object(value: unknown, file: string): LocaleMessages {
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`Invalid catalog: ${file}`)
    return value as LocaleMessages
  }
  function catalogs(directory: string): string[] {
    return fs.readdirSync(path.join(root, directory), { withFileTypes: true }).flatMap(entry => {
      const relative = path.posix.join(directory, entry.name)
      return entry.isDirectory() ? catalogs(relative) : entry.name === 'i18n.ts' ? [relative] : []
    })
  }
  const base = `core/i18n/locales/${locale}.ts`
  const messages = deepMergeMessages({}, object(read(base).default, base))
  for (const file of ['app', 'core', 'bridge'].flatMap(catalogs).sort()) {
    const catalog = object(read(file).default, file)
    if (locale === 'zh') deepMergeMessages(messages, object(catalog.en, file))
    deepMergeMessages(messages, object(catalog[locale], file))
  }
  return messages
}
