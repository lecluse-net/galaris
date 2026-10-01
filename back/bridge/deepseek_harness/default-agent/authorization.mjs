// One-action permissions are owned by Galaris, including PTC inner dispatches.
export const name = 'galaris-authorizations';
export const inject = ['tools'];
const safeReads = new Set(['read_file', 'list_directory', 'grep', 'glob', 'search_files']);

async function control(suffix, body, signal) {
  const root = process.env.GALARIS_AUTHORIZATION_PROXY;
  const context = process.env.GALARIS_RUN_CONTEXT;
  if (!root || !context) throw new Error('A server-issued Galaris runtime context is required');
  const response = await fetch(root + suffix, {
    method: 'POST', signal,
    headers: {'Content-Type': 'application/json', 'Authorization': `Bearer ${process.env.GALARIS_MCP_TOKEN}`,
      'X-Galaris-Run-Context': context},
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error('The Galaris one-action control failed closed');
  return response.json();
}

export function apply(ctx) {
  const claimed = new Set();
  ctx.on('tools/pre-execute', async (exec, next) => {
    if (exec.name.startsWith('mcp__galaris__')) return next();
    try {
      if (safeReads.has(exec.name)) {
        await control('/context', {}, exec.signal);
        return next();
      }
      const decision = await control('', {callback: exec.callId, name: exec.name, arguments: exec.arguments}, exec.signal);
      if (!decision.allowed) return {kind: 'deny', reason: 'Galaris refused this exact action'};
      claimed.add(exec.callId);
      return next();
    } catch {
      return {kind: 'deny', reason: 'No current Galaris one-action authorization'};
    }
  });
  ctx.on('tools/execute', async (exec, next) => {
    if (!claimed.has(exec.callId)) return next();
    let outcome = 'outcome_unknown';
    let receipt = {};
    try {
      const result = await next();
      receipt = {isError: result.isError, content: result.content};
      outcome = result.isError ? 'outcome_unknown' : 'completed';
      return result;
    } finally {
      claimed.delete(exec.callId);
      try { await control('/receipt', {callback: exec.callId, outcome, receipt}); } catch { /* Unknown remains unknown. */ }
    }
  });
}
