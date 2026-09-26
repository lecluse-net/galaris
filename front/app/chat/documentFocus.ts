import { onMounted, onBeforeUnmount, type Ref } from 'vue'

export interface DocumentTextRange {
  start: number
  end: number
  text: string
  truncated: boolean
}

export interface DocumentFocus {
  revision: number
  surface: 'rendered' | 'source' | 'dataset'
  selection: DocumentTextRange | null
  cursor: { offset: number; before: string; after: string } | null
  viewport: DocumentTextRange | null
}

// Offsets use UTF-16 units in the editor's textContent (or textarea value),
// never positions in the saved HTML. Excerpts let agents locate the same passage.
function sliceText(text: string, start: number, end: number): string {
  // Never create an unpaired surrogate when clipping an emoji at the payload limit.
  if (text.charCodeAt(start) >= 0xdc00 && text.charCodeAt(start) <= 0xdfff) start++
  if (text.charCodeAt(end - 1) >= 0xd800 && text.charCodeAt(end - 1) <= 0xdbff) end--
  return text.slice(start, Math.max(start, end))
}

function excerpt(text: string, start: number, end: number, limit: number): DocumentTextRange {
  return { start, end, text: sliceText(text, start, Math.min(end, start + limit)), truncated: end - start > limit }
}

function clip(element: HTMLElement): { top: number; bottom: number; left: number; right: number } {
  const box = element.getBoundingClientRect()
  const result = { top: Math.max(0, box.top), bottom: Math.min(innerHeight, box.bottom), left: Math.max(0, box.left), right: Math.min(innerWidth, box.right) }
  for (let parent = element.parentElement; parent; parent = parent.parentElement) {
    const style = getComputedStyle(parent), bounds = parent.getBoundingClientRect()
    if (/(auto|scroll|hidden|clip)/.test(style.overflowY)) {
      result.top = Math.max(result.top, bounds.top)
      result.bottom = Math.min(result.bottom, bounds.bottom)
    }
    if (/(auto|scroll|hidden|clip)/.test(style.overflowX)) {
      result.left = Math.max(result.left, bounds.left)
      result.right = Math.min(result.right, bounds.right)
    }
  }
  return result
}

function visibleText(element: HTMLElement, text: string): DocumentTextRange | null {
  if (element instanceof HTMLTextAreaElement) {
    // The syntax highlight mirrors the textarea's metrics and scroll, including
    // wrapped Source lines. Measure it instead of estimating rows from lineHeight.
    const mirror = element.parentElement?.querySelector<HTMLElement>('.galaris-source-highlight, .code-highlight')
    return mirror ? visibleText(mirror, text) : null
  }
  const bounds = clip(element)
  const toolbar = element.closest('.ck-galaris-editor')?.querySelector('.ck-sticky-panel__content')?.getBoundingClientRect()
  if (toolbar && toolbar.top <= bounds.top && toolbar.bottom > bounds.top) bounds.top = toolbar.bottom
  if (bounds.top >= bounds.bottom || bounds.left >= bounds.right) return null
  const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT)
  const range = document.createRange()
  let offset = 0, first: number | null = null, last = 0
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const length = node.textContent?.length ?? 0
    range.selectNodeContents(node)
    const intersects = [...range.getClientRects()].some(rect => rect.height > 0 && rect.bottom > bounds.top && rect.top < bounds.bottom && rect.right > bounds.left && rect.left < bounds.right)
    if (intersects && length) {
      // Binary search the first and last intersecting lines, including long paragraphs.
      const boundary = (below: boolean): number => {
        let lo = 0, hi = length
        while (lo < hi) {
          const mid = Math.floor((lo + hi) / 2)
          range.setStart(node, mid); range.setEnd(node, mid + 1)
          const rect = range.getBoundingClientRect()
          if (below ? rect.top < bounds.bottom : rect.bottom <= bounds.top) lo = mid + 1
          else hi = mid
        }
        return lo
      }
      first ??= offset + boundary(false)
      last = offset + boundary(true)
    }
    offset += length
  }
  return first !== null ? excerpt(text, first, Math.min(last, text.length), 6000) : null
}

/** Remember document selection across composer focus, but never across content replacement. */
export function useDocumentFocus(container: Ref<HTMLElement | null>) {
  let remembered: { element: HTMLElement; text: string; start: number; end: number; cursor: number } | null = null
  function surface(): HTMLElement | null {
    const root = container.value
    return root?.querySelector<HTMLTextAreaElement>('.document-editor-fields .ck-source-editing-area textarea, .document-editor-fields textarea.code-editor')
      ?? root?.querySelector<HTMLElement>('.document-editor-fields .ck-editor__editable') ?? null
  }
  function remember(): void {
    const element = surface()
    if (!element) return
    if (element instanceof HTMLTextAreaElement) {
      if (document.activeElement !== element) return
      remembered = { element, text: element.value, start: element.selectionStart, end: element.selectionEnd,
        cursor: element.selectionDirection === 'backward' ? element.selectionStart : element.selectionEnd }
      return
    }
    const selection = document.getSelection()
    if (!selection?.rangeCount || !selection.anchorNode || !selection.focusNode
      || !element.contains(selection.anchorNode) || !element.contains(selection.focusNode)) return
    const range = selection.getRangeAt(0)
    const offset = (node: Node, position: number): number => {
      const prefix = document.createRange()
      prefix.selectNodeContents(element); prefix.setEnd(node, position)
      return prefix.toString().length
    }
    remembered = { element, text: element.textContent ?? '', start: offset(range.startContainer, range.startOffset),
      end: offset(range.endContainer, range.endOffset), cursor: offset(selection.focusNode, selection.focusOffset) }
  }
  function capture(revision: number): DocumentFocus | null {
    const element = surface()
    if (!element) return null
    const text = element instanceof HTMLTextAreaElement ? element.value : element.textContent ?? ''
    const current = remembered?.element === element && remembered.text === text ? remembered : null
    return {
      revision,
      surface: element instanceof HTMLTextAreaElement ? element.classList.contains('code-editor') ? 'dataset' : 'source' : 'rendered',
      selection: current && current.start !== current.end ? excerpt(text, current.start, current.end, 4000) : null,
      cursor: current ? { offset: current.cursor, before: sliceText(text, Math.max(0, current.cursor - 160), current.cursor), after: sliceText(text, current.cursor, current.cursor + 160) } : null,
      viewport: visibleText(element, text),
    }
  }
  const controller = new AbortController()
  onMounted(() => {
    document.addEventListener('selectionchange', remember, { signal: controller.signal })
    // Input and keyup also cover textarea selections and edits before blur.
    for (const event of ['input', 'keyup', 'pointerup', 'select']) container.value?.addEventListener(event, remember, { signal: controller.signal })
  })
  onBeforeUnmount(() => controller.abort())
  return { capture, reset: () => { remembered = null } }
}
