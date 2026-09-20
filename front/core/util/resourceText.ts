const languagesByExtension: Record<string, string> = {
  js: 'javascript', mjs: 'javascript', cjs: 'javascript', jsx: 'javascript',
  ts: 'typescript', mts: 'typescript', cts: 'typescript', tsx: 'typescript',
  py: 'python', pyi: 'python', sql: 'sql', json: 'json', jsonl: 'json', ipynb: 'json',
  yaml: 'yaml', yml: 'yaml', xml: 'xml', xsd: 'xml', xsl: 'xml', svg: 'xml',
  css: 'css', scss: 'scss', less: 'less', vue: 'html', svelte: 'html',
  sh: 'bash', bash: 'bash', zsh: 'bash', ps1: 'powershell',
  c: 'c', h: 'c', cpp: 'cpp', cc: 'cpp', cxx: 'cpp', hpp: 'cpp',
  cs: 'csharp', java: 'java', kt: 'kotlin', kts: 'kotlin',
  go: 'go', rs: 'rust', rb: 'ruby', php: 'php', swift: 'swift',
  ini: 'ini', toml: 'ini', conf: 'ini', diff: 'diff', patch: 'diff',
  txt: 'text', log: 'text', csv: 'text', tsv: 'text', rst: 'text', env: 'bash',
}

const languagesByMime: Record<string, string> = {
  'application/json': 'json', 'application/ld+json': 'json', 'application/x-ndjson': 'json',
  'application/javascript': 'javascript', 'text/javascript': 'javascript',
  'application/typescript': 'typescript', 'text/typescript': 'typescript',
  'text/x-python': 'python', 'application/x-python': 'python',
  'application/xml': 'xml', 'text/xml': 'xml',
  'application/yaml': 'yaml', 'application/x-yaml': 'yaml', 'text/yaml': 'yaml', 'text/x-yaml': 'yaml',
  'application/sql': 'sql', 'text/x-sql': 'sql', 'text/css': 'css',
  'application/x-sh': 'bash', 'text/x-shellscript': 'bash',
  'text/x-c': 'c', 'text/x-c++': 'cpp', 'text/x-java-source': 'java',
  'application/x-httpd-php': 'php',
}

/** Only classify known text formats; unknown binary files keep their download action. */
export function resourceTextLanguage(mediaType: string, name: string): string | null {
  const mime = mediaType.split(';', 1)[0]?.trim().toLowerCase() ?? ''
  const filename = name.trim().toLowerCase().split(/[\\/]/).at(-1) ?? ''
  if (filename === 'dockerfile' || filename.startsWith('dockerfile.')) return 'dockerfile'
  if (filename === 'makefile' || filename === 'gnumakefile') return 'makefile'
  const extension = filename.split('.').at(-1) ?? ''
  return languagesByExtension[extension] ?? languagesByMime[mime]
    ?? (mime.endsWith('+json') ? 'json' : mime.endsWith('+xml') ? 'xml' : mime.startsWith('text/') ? 'text' : null)
}
