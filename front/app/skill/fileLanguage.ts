export type CodeLanguage = 'json' | 'yaml' | 'xml' | 'markdown' | 'text' | 'javascript' | 'typescript' | 'python' | 'sql' | 'html' | 'css'

export function languageForSkillFile(path: string): CodeLanguage {
  const extension = path.split('.').pop()?.toLowerCase()
  const languages: Record<string, CodeLanguage> = {
    json: 'json', yaml: 'yaml', yml: 'yaml', xml: 'xml', md: 'markdown',
    js: 'javascript', jsx: 'javascript', ts: 'typescript', tsx: 'typescript',
    py: 'python', sql: 'sql', html: 'html', css: 'css',
  }
  return extension ? languages[extension] || 'text' : 'text'
}
