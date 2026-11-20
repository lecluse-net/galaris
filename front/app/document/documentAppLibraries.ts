import type { AnyNode, ImportDeclaration, ImportExpression, Program, parse } from 'acorn'
import type { DocumentApp } from './documentApps'

const threeReference = /\bTHREE\b/
const executableScriptType = /^(?:|module|(?:application|text)\/(?:x-)?(?:java|ecma)script|text\/(?:javascript1\.[0-5]|jscript|livescript))$/i
const javascriptUrl = /^\s*javascript:/i
const hasImports = /\bimport\b/

type ThreeModule = 'three' | 'OrbitControls' | 'GLTFLoader'
type ResolveModule = (specifier: string) => ThreeModule | undefined
const addons = new Map<string, ThreeModule>([
  ['controls/OrbitControls.js', 'OrbitControls'],
  ['loaders/GLTFLoader.js', 'GLTFLoader'],
])
const cdnPackagePaths = new Map([
  ['cdn.jsdelivr.net', /^\/npm\/three(?:@[^/]+)?(?=\/|$)/],
  ['unpkg.com', /^\/three(?:@[^/]+)?(?=\/|$)/],
  ['cdnjs.cloudflare.com', /^\/ajax\/libs\/three\.js\/[^/]+(?=\/|$)/],
  ['esm.sh', /^\/three(?:@[^/]+)?(?=\/|$)/],
])

function threeModule(specifier: string): ThreeModule | undefined {
  if (specifier === 'three') return 'three'
  let path = specifier
  if (/^(?:https:)?\/\//i.test(specifier)) {
    let url: URL
    try { url = new URL(specifier, 'https://invalid.invalid') } catch { return }
    if (url.protocol !== 'https:' || url.username || url.password || url.port) return
    const pattern = cdnPackagePaths.get(url.hostname)
    if (!pattern?.test(url.pathname)) return
    path = url.pathname.replace(pattern, '')
    if (/^(?:\/?|\/(?:build\/)?three(?:\.module)?(?:\.min)?\.js)$/.test(path)) return 'three'
  } else if (path.startsWith('three/')) {
    path = path.slice('three'.length)
  } else {
    return
  }
  const addon = path.replace(/^\/(?:addons|examples\/jsm|examples\/js)\//, '')
  return addons.get(addon)
}

function resolveModules(html: DocumentFragment): ResolveModule {
  const entries = new Map<string, string | null>()
  for (const script of html.querySelectorAll('script[type="importmap" i]:not([src])')) {
    try {
      const map: unknown = JSON.parse(script.textContent ?? '')
      if (!map || typeof map !== 'object' || !('imports' in map) || !map.imports || typeof map.imports !== 'object') continue
      for (const [key, value] of Object.entries(map.imports)) {
        if (key && !entries.has(key) && (value === null || typeof value === 'string')) entries.set(key, value)
      }
    } catch { /* Invalid import maps remain subject to normal browser handling. */ }
  }
  const prefixes = [...entries.keys()].filter(key => key.endsWith('/')).sort((a, b) => b.length - a.length)
  return specifier => {
    const exact = entries.get(specifier)
    if (exact !== undefined) return exact === null ? undefined : threeModule(exact)
    const prefix = prefixes.find(key => specifier.startsWith(key))
    if (!prefix) return threeModule(specifier)
    const mapped = entries.get(prefix)
    return mapped?.endsWith('/') ? threeModule(mapped + specifier.slice(prefix.length)) : undefined
  }
}

function moduleValue(module: ThreeModule): string {
  return `globalThis.__galarisDocumentThree.${module}`
}

function staticBindings(declaration: ImportDeclaration, module: ThreeModule): string {
  const namespace = moduleValue(module)
  return declaration.specifiers.map(binding => {
    if (binding.type === 'ImportNamespaceSpecifier') return `const ${binding.local.name} = ${namespace};`
    const name = binding.type === 'ImportDefaultSpecifier' ? 'default'
      : binding.imported.type === 'Identifier' ? binding.imported.name : binding.imported.value
    const member = JSON.stringify(String(name)).replaceAll('<', '\\u003c')
    return `const ${binding.local.name} = ${namespace}[${member}];`
  }).join('\n')
}

function importNodes(program: Program): (ImportDeclaration | ImportExpression)[] {
  const result: (ImportDeclaration | ImportExpression)[] = []
  const pending: unknown[] = [program]
  while (pending.length) {
    const value = pending.pop()
    if (Array.isArray(value)) {
      for (const item of value) pending.push(item)
    } else if (value && typeof value === 'object' && 'type' in value) {
      const node = value as AnyNode
      if (node.type === 'ImportDeclaration' || node.type === 'ImportExpression') result.push(node)
      for (const child of Object.values(node) as unknown[]) pending.push(child)
    }
  }
  return result
}

function localizeImports(source: string, sourceType: 'script' | 'module', resolve: ResolveModule, parseSource: typeof parse): string {
  let program: Program
  try {
    program = parseSource(source, { ecmaVersion: 'latest', sourceType })
  } catch {
    return source
  }
  const bindings: string[] = [], body: string[] = []
  let offset = 0
  for (const node of importNodes(program).sort((a, b) => a.start - b.start)) {
    const specifier = node.source.type === 'Literal' ? node.source.value
      : node.source.type === 'TemplateLiteral' && node.source.expressions.length === 0 ? node.source.quasis[0]?.value.cooked : undefined
    if (typeof specifier !== 'string') continue
    if (node.type === 'ImportDeclaration' ? node.attributes.length : node.options) continue
    const module = resolve(specifier)
    if (!module) continue
    if (node.type === 'ImportDeclaration') bindings.push(staticBindings(node, module))
    const replacement = node.type === 'ImportDeclaration' ? ';' : `(async () => ${moduleValue(module)})()`
    body.push(source.slice(offset, node.start), replacement)
    offset = node.end
  }
  if (!offset) return source
  body.push(source.slice(offset))
  // Imports bind before the original module body, even when declared later.
  return bindings.join('\n') + '\n' + body.join('')
}

export async function prepareDocumentAppLibraries(app: DocumentApp): Promise<{ app: DocumentApp; threeSource: string }> {
  const html = document.createElement('template')
  html.innerHTML = app.html ?? ''
  const resolve = resolveModules(html.content)
  let needed = Boolean(html.content.querySelector('[data-galaris-library="three"]')) || threeReference.test(app.javascript ?? '')
  let changed = false
  for (const script of html.content.querySelectorAll('script')) {
    const type = script.getAttribute('type')?.trim() ?? ''
    if (!executableScriptType.test(type)) continue
    const src = script.getAttribute('src')
    if (src !== null) {
      if (threeModule(src)) {
        if (script.hasAttribute('onload')) {
          script.removeAttribute('src')
          script.setAttribute('type', 'text/javascript')
          script.textContent = "document.currentScript.dispatchEvent(new Event('load'));"
        } else script.remove()
        changed = needed = true
      }
      continue
    }
    const source = script.textContent ?? ''
    needed ||= threeReference.test(source)
    if (!hasImports.test(source)) continue
    const rewritten = localizeImports(source, type.toLowerCase() === 'module' ? 'module' : 'script', resolve, (await import('acorn')).parse)
    if (rewritten !== source) {
      script.textContent = rewritten
      changed = needed = true
    }
  }
  const javascript = hasImports.test(app.javascript ?? '')
    ? localizeImports(app.javascript ?? '', 'script', resolve, (await import('acorn')).parse) : app.javascript
  needed ||= javascript !== app.javascript || [...html.content.querySelectorAll('*')].some(element =>
    [...element.attributes].some(({ name, value }) =>
      threeReference.test(value) && (name.startsWith('on') || javascriptUrl.test(value.replace(/[\t\r\n]/g, ''))),
    ),
  )
  const threeSource = needed ? (await import('virtual:galaris-document-three')).default : ''
  return { app: { ...app, html: changed ? html.innerHTML : app.html, javascript }, threeSource }
}
