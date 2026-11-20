import { shallowRef, watch, type Ref } from 'vue'
import { connectorKey, type MindMapConnector, type MindMapNode } from './model'

type ConnectorPath = { key: string; path: string; x: number; y: number; label: string; anchor: 'middle' | 'start' }

export function useMindMapConnectors(stage: Ref<HTMLElement | null>,
  visibleNodes: Readonly<Ref<MindMapNode[]>>, connectors: Readonly<Ref<MindMapConnector[]>>) {
  const paths = shallowRef<ConnectorPath[]>([])

  watch([stage, visibleNodes, connectors], ([tree, nodes, links], _, cleanup) => {
    const visible = new Set(nodes.map(node => node.id))
    const drawable = links.filter(link => visible.has(link.source) && visible.has(link.target))
    if (!tree || !drawable.length) {
      paths.value = []
      return
    }
    const boxes = new Map<string, Element>()
    for (const item of tree.querySelectorAll<HTMLElement>('[data-mindmap-node]')) {
      if (item.closest('[role="tree"]') === tree && item.firstElementChild) {
        boxes.set(item.dataset.mindmapNode!, item.firstElementChild)
      }
    }
    const measure = (): void => {
      const bounds = tree.getBoundingClientRect()
      if (!bounds.width || !tree.offsetWidth) { paths.value = []; return }
      const scale = bounds.width / tree.offsetWidth
      const rects = new Map<string, DOMRect>()
      for (const { source, target } of drawable) {
        for (const id of [source, target]) {
          const box = boxes.get(id)
          if (box && !rects.has(id)) rects.set(id, box.getBoundingClientRect())
        }
      }
      paths.value = drawable.flatMap(link => {
        const source = rects.get(link.source), target = rects.get(link.target)
        if (!source || !target) return []
        const toRight = source.right + 8 * scale < target.left
        const toLeft = target.right + 8 * scale < source.left
        const sideways = toRight || toLeft
        const x1 = ((toLeft ? source.left : source.right) - bounds.left) / scale
        const x2 = ((toRight ? target.left : target.right) - bounds.left) / scale
        const y1 = (source.top + source.height / 2 - bounds.top) / scale
        const y2 = (target.top + target.height / 2 - bounds.top) / scale
        const bend = sideways ? Math.abs(x2 - x1) / 2 : 28
        const first = x1 + (toLeft ? -bend : bend)
        const last = x2 + (sideways ? (toLeft ? bend : -bend) : bend)
        const labelAbove = sideways && Math.abs(x2 - x1) < link.label.length * 7 + 8
        return [{
          key: connectorKey(link), label: link.label,
          path: `M ${x1} ${y1} C ${first} ${y1}, ${last} ${y2}, ${x2} ${y2}`,
          x: (x1 + 3 * first + 3 * last + x2) / 8,
          y: labelAbove ? (Math.min(source.top, target.top) - bounds.top) / scale - 4 : (y1 + y2) / 2 - 5,
          anchor: sideways ? 'middle' : 'start',
        }]
      })
    }
    let frame = 0
    const observer = new ResizeObserver(() => {
      if (!frame) frame = requestAnimationFrame(() => { frame = 0; measure() })
    })
    observer.observe(tree)
    boxes.forEach(box => observer.observe(box))
    measure()
    cleanup(() => { observer.disconnect(); cancelAnimationFrame(frame) })
  }, { flush: 'post', immediate: true })

  return paths
}
