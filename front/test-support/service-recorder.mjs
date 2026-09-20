import { loadTypescript } from './load-typescript.mjs'

/** Replace only HTTP: every public service method executes its actual implementation. */
export function serviceRecorder(url, exportName, dependencies = {}) {
  const requests = []
  const response = { id: 'server-result' }
  const api = Object.fromEntries(['get', 'post', 'put', 'patch', 'delete'].map(method => [method, async (...args) => {
    requests.push({ method, args })
    return { data: response }
  }]))
  const module = loadTypescript(url, { '@/core/api': { __esModule: true, api, default: api }, ...dependencies })
  return { service: module[exportName], requests, response }
}
