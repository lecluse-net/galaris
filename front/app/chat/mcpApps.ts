export type McpTableCell = string | number | boolean | null
export interface McpTable {
  title: string
  columns: string[]
  rows: McpTableCell[][]
}

export interface McpPresentation {
  id: string
  source: string
  tool_name: string
  resource_uri: string | null
  table: McpTable
}

function escapeHtml(value: string): string {
  return value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
}

export function tableHtml(table: McpTable, source: string): string {
  const headers = table.columns.map(column => '<th scope="col">' + escapeHtml(column) + '</th>').join('')
  const rows = table.rows.map(row => '<tr>' + row.map(cell => '<td>' + escapeHtml(String(cell ?? '')) + '</td>').join('') + '</tr>').join('')
  return '<figure class="table"><table><thead><tr>' + headers + '</tr></thead><tbody>' + rows
    + '</tbody></table><figcaption>' + escapeHtml([table.title, source].filter(Boolean).join(' · ')) + '</figcaption></figure>'
}

const restrictions = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; form-action 'none'; base-uri 'none'"

function sandboxHead(policy: string): string {
  return '<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="' + policy
    + '"><meta name="referrer" content="no-referrer">'
}

export function sandboxMcpApp(html: string): string {
  const inner = sandboxHead(restrictions)
    + '<meta name="viewport" content="width=device-width,initial-scale=1">'
    + '<script>for (const name of ["RTCPeerConnection", "webkitRTCPeerConnection", "mozRTCPeerConnection", "RTCIceGatherer", "RTCIceTransport", "RTCDtlsTransport"]) { Object.defineProperty(window, name, {value: undefined}); }'
    + 'for (const url of new Set([URL, window.webkitURL].filter(Boolean))) Object.defineProperty(url, "createObjectURL", {value: undefined});</script>'
    + html.replace(/^\s*<!doctype\s+html[^>]*>/i, '')
  const encoded = JSON.stringify(inner).replaceAll('<', '\\u003c')
  return sandboxHead(restrictions + '; frame-src blob:')
    + '<style>html,body,iframe{margin:0;width:100%;height:100%;border:0}iframe{display:block}</style>'
    + '<iframe title="MCP App" sandbox="allow-scripts allow-forms" referrerpolicy="no-referrer"></iframe><script>'
    + 'const frame = document.querySelector("iframe"); let started = false, closed = false, loaded = false;'
    + 'const close = () => { closed = true; frame.remove(); parent.postMessage({closed:true}, "*"); };'
    + 'addEventListener("securitypolicyviolation", event => { if (event.effectiveDirective === "frame-src") close(); });'
    + 'frame.addEventListener("load", () => { if (!started) return; if (loaded) close(); loaded = true; });'
    + 'addEventListener("message", event => {'
    + 'if (closed) return;'
    + 'if (event.source === parent) {'
    + 'if (!started && event.data === "start") { started = true; frame.src = URL.createObjectURL(new Blob(['
    + encoded + '], {type:"text/html"})); }'
    + 'else if (started) frame.contentWindow.postMessage(event.data, "*");'
    + '} else if (started && event.source === frame.contentWindow) parent.postMessage(event.data, "*");'
    + '});</script>'
}
