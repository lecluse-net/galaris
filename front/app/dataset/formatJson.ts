/** Indent JSON without re-encoding numbers, strings, or object keys. */
export function formatJson(source: string): string {
  try { JSON.parse(source) } catch { return source }
  const tokens = source.match(/"(?:\\.|[^"\\])*"|[{}[\],:]|[^\s{}[\],:]+/g) ?? []
  const output: string[] = []
  let depth = 0
  const newline = () => output.push('\n', '  '.repeat(depth))
  for (const [index, token] of tokens.entries()) {
    if (token === '{' || token === '[') {
      output.push(token)
      depth++
      if (tokens[index + 1] !== '}' && tokens[index + 1] !== ']') newline()
    } else if (token === '}' || token === ']') {
      depth--
      if (tokens[index - 1] !== '{' && tokens[index - 1] !== '[') newline()
      output.push(token)
    } else if (token === ',') {
      output.push(token)
      newline()
    } else {
      output.push(token === ':' ? ': ' : token)
    }
  }
  return output.join('')
}
