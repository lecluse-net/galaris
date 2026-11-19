import { readFileSync, readdirSync } from 'node:fs'
import { dirname, matchesGlob, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const extensions = ['.ts', '.tsx', '.mts', '.js', '.jsx', '.mjs', '.vue']
const sourceFile = /\.(?:ts|tsx|mts|js|jsx|mjs|vue)$/
const excludedFile = /\.(?:d\.ts|(?:test|spec)\.[^.]+)$/

function frontendFiles(front) {
  const roots = readdirSync(front, { withFileTypes: true })
  const layers = roots.filter(entry => entry.isDirectory() && ['app', 'bridge', 'core'].includes(entry.name))
  const entries = [...roots, ...layers.flatMap(layer =>
    readdirSync(resolve(front, layer.name), { recursive: true, withFileTypes: true }))]
  return entries
    .filter(entry => entry.isFile() && sourceFile.test(entry.name) && !excludedFile.test(entry.name))
    .map(entry => resolve(entry.parentPath, entry.name))
    .sort()
}

function internalPath(front, importer, specifier) {
  if (specifier.startsWith('@/')) return resolve(front, specifier.slice(2))
  if (specifier.startsWith('/')) return resolve(front, specifier.slice(1))
  if (specifier.startsWith('.')) return resolve(dirname(importer), specifier)
}

function valueImport(node) {
  if (ts.isImportDeclaration(node)) {
    const clause = node.importClause
    if (!clause) return true
    if (clause.isTypeOnly) return false
    if (clause.name) return true
    const bindings = clause.namedBindings
    return !bindings || !ts.isNamedImports(bindings) || !onlyTypes(bindings.elements)
  }
  const { exportClause } = node
  return !node.isTypeOnly && (!exportClause || !ts.isNamedExports(exportClause) || !onlyTypes(exportClause.elements))
}

function onlyTypes(elements) {
  return elements.length > 0 && elements.every(element => element.isTypeOnly)
}

function option(options, key) {
  if (!options || !ts.isObjectLiteralExpression(options)) return undefined
  return options.properties.find(property => ts.isPropertyAssignment(property)
    && (ts.isIdentifier(property.name) || ts.isStringLiteral(property.name))
    && property.name.text === key)?.initializer
}

function eagerGlobPatterns(node) {
  if (!ts.isCallExpression(node) || !ts.isPropertyAccessExpression(node.expression)) return []
  const { expression, name } = node.expression
  if (name.text !== 'glob' || !ts.isMetaProperty(expression) || expression.keywordToken !== ts.SyntaxKind.ImportKeyword) return []
  const [selector, options] = node.arguments
  if (option(options, 'eager')?.kind !== ts.SyntaxKind.TrueKeyword) return []
  const query = option(options, 'query') ?? option(options, 'as')
  if (query && ts.isStringLiteralLike(query) && /(?:^|[?&])(?:raw|url|worker|sharedworker)(?:[=&]|$)/.test(query.text)) return []
  const patterns = selector && ts.isArrayLiteralExpression(selector) ? selector.elements : [selector]
  return patterns.flatMap(pattern => pattern && ts.isStringLiteralLike(pattern) ? [pattern.text] : [])
}

function eagerDependencies(front, file, files) {
  const content = readFileSync(file, 'utf8')
  const scripts = file.endsWith('.vue')
    ? [...content.replace(/<!--[\s\S]*?-->/g, '').matchAll(/^\s*<script\b[^>]*>([\s\S]*?)<\/script>/gm)].map(match => match[1])
    : [content]
  const dependencies = new Set()
  for (const script of scripts) {
    const source = ts.createSourceFile(file.endsWith('.vue') ? 'component.ts' : file, script, ts.ScriptTarget.Latest, true)
    function visit(node) {
      if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && valueImport(node)) {
        const specifier = node.moduleSpecifier
        if (specifier && ts.isStringLiteralLike(specifier)) {
          const path = internalPath(front, file, specifier.text)
          if (path) {
            const target = [path, ...extensions.map(ext => path + ext), ...extensions.map(ext => resolve(path, 'index' + ext))]
              .find(candidate => files.has(candidate))
            if (target) dependencies.add(target)
          }
        }
      }
      const patterns = eagerGlobPatterns(node)
      if (patterns.length) {
        const include = [], exclude = []
        for (const pattern of patterns) {
          const negative = pattern.startsWith('!')
          const path = internalPath(front, file, negative ? pattern.slice(1) : pattern)
          if (path) (negative ? exclude : include).push(path)
        }
        for (const candidate of files) {
          if (include.some(pattern => matchesGlob(candidate, pattern))
            && !exclude.some(pattern => matchesGlob(candidate, pattern))) dependencies.add(candidate)
        }
      }
      ts.forEachChild(node, visit)
    }
    visit(source)
  }
  return [...dependencies].sort()
}

/** Return concrete closed paths through value imports, re-exports and eager Vite globs. */
export function frontendEagerCycles(front) {
  const files = new Set(frontendFiles(front))
  const visited = new Set()
  const active = new Map()
  const stack = []
  const cycles = []

  function visit(file) {
    if (active.has(file)) {
      cycles.push([...stack.slice(active.get(file)), file].map(path => 'front/' + relative(front, path)))
      return
    }
    if (visited.has(file)) return
    visited.add(file)
    active.set(file, stack.length)
    stack.push(file)
    for (const dependency of eagerDependencies(front, file, files)) visit(dependency)
    stack.pop()
    active.delete(file)
  }

  for (const file of files) visit(file)
  return cycles
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const cycles = frontendEagerCycles(resolve(import.meta.dirname, '..'))
  if (cycles.length) {
    for (const cycle of cycles) console.error('Eager frontend import cycle: ' + cycle.join(' -> '))
    process.exitCode = 1
  } else console.log('No eager frontend import cycles')
}
