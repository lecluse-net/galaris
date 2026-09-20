import { marked } from 'marked'
import { sanitizeHtml } from './sanitizeHtml'

/** Convert the Markdown persisted by the API into safe HTML expected by QEditor. */
export function markdownToHtml(markdown: string | null | undefined): string {
  if (!markdown) return ''
  return sanitizeHtml(marked.parse(markdown, { breaks: true }) as string)
}

/** Convert QEditor's HTML back into the Markdown persisted by the API. */
export function htmlToMarkdown(html: string | null | undefined): string {
  if (!html) return ''

  const temporaryElement = document.createElement('div')
  temporaryElement.innerHTML = html

  temporaryElement.querySelectorAll('*').forEach(element => {
    const languageClass = element.tagName.toLowerCase() === 'code'
      ? element.className.match(/(?:^|\s)language-([a-z0-9_+-]+)/i)?.[1]
      : undefined
    element.removeAttribute('style')
    element.removeAttribute('class')
    if (languageClass) element.className = `language-${languageClass}`
    const attributes = element.attributes
    for (let index = attributes.length - 1; index >= 0; index -= 1) {
      const attribute = attributes.item(index)
      if (
        attribute
        && (attribute.name.startsWith('data-') || attribute.name.startsWith('aria-'))
      ) {
        element.removeAttribute(attribute.name)
      }
    }
  })

  const cleanHtml = temporaryElement.innerHTML
    .replace(/<p[^>]*>\s*(<br\s*\/?>\s*)*\s*<\/p>/gim, '')
    .replace(/<span[^>]*>\s*<\/span>/gim, '')
    .replace(/<div[^>]*>\s*<\/div>/gim, '')

  const container = document.createElement('div')
  container.innerHTML = cleanHtml

  function processNode(node: Node): string {
    if (node.nodeType === Node.TEXT_NODE) {
      return (node.textContent || '').replace(/\s+/g, ' ')
    }

    if (node.nodeType !== Node.ELEMENT_NODE) return ''

    const element = node as HTMLElement
    const tag = element.tagName.toLowerCase()
    if (tag === 'script' || tag === 'style' || tag === 'meta') return ''

    const content = Array.from(element.childNodes).map(processNode).join('')

    switch (tag) {
      case 'h1': return `# ${content.trim()}\n\n`
      case 'h2': return `## ${content.trim()}\n\n`
      case 'h3': return `### ${content.trim()}\n\n`
      case 'h4': return `#### ${content.trim()}\n\n`
      case 'h5': return `##### ${content.trim()}\n\n`
      case 'h6': return `###### ${content.trim()}\n\n`
      case 'b':
      case 'strong': {
        const strongContent = content.trim()
        return strongContent ? `**${strongContent}**` : ''
      }
      case 'i':
      case 'em': {
        const emphasizedContent = content.trim()
        return emphasizedContent ? `*${emphasizedContent}*` : ''
      }
      case 'strike':
      case 's':
      case 'del': {
        const strikeContent = content.trim()
        return strikeContent ? `~~${strikeContent}~~` : ''
      }
      case 'u': {
        const underlinedContent = content.trim()
        return underlinedContent
      }
      case 'pre': {
        const codeElement = element.querySelector('code')
        const codeContent = (codeElement?.textContent ?? element.textContent ?? '')
          .replace(/\n$/, '')
        const language = codeElement?.className.match(/(?:^|\s)language-([^\s]+)/)?.[1] ?? ''
        return `\`\`\`${language}\n${codeContent}\n\`\`\`\n\n`
      }
      case 'code': {
        const codeContent = content.trim()
        return codeContent ? `\`${codeContent}\`` : ''
      }
      case 'blockquote': {
        const quoteContent = content.trim()
        return quoteContent
          ? `${quoteContent.split('\n').map(line => `> ${line}`).join('\n')}\n\n`
          : ''
      }
      case 'a': {
        const href = element.getAttribute('href') || ''
        const linkContent = content.trim()
        return linkContent && href ? `[${linkContent}](${href})` : linkContent
      }
      case 'img': {
        const source = element.getAttribute('src') || ''
        const alternative = element.getAttribute('alt') || ''
        return source ? `![${alternative}](${source})` : ''
      }
      case 'hr': return '---\n\n'
      case 'table': {
        const rows = Array.from(element.querySelectorAll('tr'))
          .map(row => Array.from(row.querySelectorAll(':scope > th, :scope > td'))
            .map(cell => (cell.textContent || '').trim().replace(/\|/g, '\\|')))
          .filter(row => row.length > 0)
        if (!rows.length) return ''
        const width = Math.max(...rows.map(row => row.length))
        const normalizedRows = rows.map(row => [
          ...row,
          ...Array.from({ length: width - row.length }, () => ''),
        ])
        const header = normalizedRows[0] ?? []
        const body = normalizedRows.slice(1)
        return [
          `| ${header.join(' | ')} |`,
          `| ${header.map(() => '---').join(' | ')} |`,
          ...body.map(row => `| ${row.join(' | ')} |`),
          '',
          '',
        ].join('\n')
      }
      case 'br': return '\n'
      case 'p': {
        const paragraphContent = content.trim()
        return paragraphContent ? `${paragraphContent}\n\n` : ''
      }
      case 'ul': {
        const items = Array.from(element.children)
          .filter(child => child.tagName.toLowerCase() === 'li')
          .map(child => {
            const itemContent = processNode(child).trim()
            return itemContent ? `* ${itemContent}` : ''
          })
          .filter(Boolean)
        return items.length ? `${items.join('\n')}\n\n` : ''
      }
      case 'ol': {
        const items = Array.from(element.children)
          .filter(child => child.tagName.toLowerCase() === 'li')
          .map((child, index) => {
            const itemContent = processNode(child).trim()
            return itemContent ? `${index + 1}. ${itemContent}` : ''
          })
          .filter(Boolean)
        return items.length ? `${items.join('\n')}\n\n` : ''
      }
      case 'li': return content
      case 'div': {
        const divContent = content.trim()
        if (!divContent) return ''
        return `${divContent}\n\n`
      }
      case 'span':
      case 'font':
        return content
      default:
        return content
    }
  }

  return Array.from(container.childNodes)
    .map(processNode)
    .join('')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
    .replace(/ \n/g, '\n')
    .replace(/\n /g, '\n')
}
