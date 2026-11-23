import { Node } from '@tiptap/core'
import { svgCode, svgImage } from './editorialSvg'

export const EditorialSvg = Node.create({
  name: 'editorialSvg', group: 'block', atom: true, draggable: true, priority: 1150,
  addAttributes: () => ({ source: { default: '' } }),
  parseHTML: () => [{ tag: 'pre', getAttrs: element => {
    const code = element.firstElementChild
    return code?.classList.contains('language-galaris-svg') ? { source: code.textContent ?? '' } : false
  } }],
  renderHTML: ({ node }) => ['pre', {}, ['code', { class: 'language-galaris-svg' }, String(node.attrs.source)]],
  addNodeView: () => ({ node }) => {
    const dom = svgImage(document, String(node.attrs.source)) ?? document.createElement('span')
    dom.contentEditable = 'false'
    return { dom }
  },
})

export const EditorialSvgFigure = Node.create({
  name: 'editorialSvgFigure', group: 'block', content: 'editorialSvg caption?',
  parseHTML: () => [{ tag: 'figure', getAttrs: element => element.querySelector(':scope > ' + svgCode) ? null : false }],
  renderHTML: ({ HTMLAttributes }) => ['figure', HTMLAttributes, 0],
})
