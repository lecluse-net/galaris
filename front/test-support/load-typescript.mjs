import { readFileSync } from 'node:fs'
import ts from 'typescript'

/** Execute a complete TypeScript module with explicit transport/platform doubles. */
export function loadTypescript(url, dependencies, globals = {}) {
  const output = ts.transpileModule(readFileSync(url, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const exports = {}
  new Function('require', 'exports', ...Object.keys(globals), output)((name) => {
    if (!(name in dependencies)) throw Error(`Missing test dependency: ${name}`)
    return dependencies[name]
  }, exports, ...Object.values(globals))
  return exports
}

export function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
