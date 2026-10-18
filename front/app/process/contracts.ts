import type { ResourceDetailTarget } from '@/core/util'

export function processResourceTarget(uri: string, title = '', agentId: number | null = null): ResourceDetailTarget | null {
  const run = /^galaris:\/\/processes\/runs\/([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$/.exec(uri)
  if (run) return { kind: 'process_run', id: run[1]!, title, agentId }
  const process = /^galaris:\/\/process(?:es)?\/([A-Za-z_][A-Za-z0-9_.-]{0,254})$/.exec(uri)
  return process ? { kind: 'process', id: process[1]!, title, agentId } : null
}

export function processReferenceHtml(uri: string, title: string, diagram: boolean): string {
  if (!processResourceTarget(uri)) throw new Error('Invalid Process reference')
  const link = document.createElement('a')
  link.setAttribute('href', uri); link.textContent = title
  const html = '<p>' + link.outerHTML + '</p>'
  return diagram ? '<blockquote class="galaris-link-card galaris-process-diagram">' + html + '</blockquote>' : html
}
