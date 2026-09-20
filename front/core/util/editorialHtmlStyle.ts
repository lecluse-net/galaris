const colors = /^(?:#[0-9a-f]{3}(?:[0-9a-f]{3})?|(?:rgb|hsl)a?\([0-9.,% /]{1,65}\)|black|white|red|green|blue|yellow|orange|purple|gray|grey|silver|maroon|navy|teal|lime|aqua|fuchsia|transparent)$/i
const length = (value: string, maximum = 1600): boolean => {
  const match = /^(\d+(?:\.\d+)?)(px|pt|em|rem|%)?$/.exec(value)
  return Boolean(match && Number(match[1]) <= (match[2] === '%' ? 100 : maximum))
}
export const editorialClasses = new Set('galaris-link-card galaris-media-audio galaris-media-video galaris-media-pdf image image-inline image_resized table table_resized image-style-side image-style-align-left image-style-align-center image-style-align-right image-style-block-align-left image-style-block-align-right marker-yellow marker-green marker-pink marker-blue pen-red pen-green'.split(' '))
for (const kind of ['', '-info', '-warning', '-question', '-error', '-stop', '-forbidden', '-search']) editorialClasses.add('galaris-callout' + kind)
export function validEditorialStyle(key: string, value: string): boolean {
  const raw = value.trim().toLowerCase()
  switch (key) {
    case 'text-align': return ['left', 'center', 'right', 'justify'].includes(raw)
    case 'color': case 'background-color': case 'border-color': return colors.test(raw)
    case 'width': case 'height': return length(raw)
    case 'padding': case 'border-width': case 'font-size': return length(raw, 100)
    case 'margin-left': case 'margin-right': return raw === 'auto' || length(raw, 320)
    case 'border-style': return ['none', 'solid', 'dashed', 'dotted', 'double', 'groove', 'ridge', 'inset', 'outset'].includes(raw)
    case 'border-collapse': return ['collapse', 'separate'].includes(raw)
    case 'border': { const match = /^(\d+(?:\.\d+)?px) (solid|dashed|dotted|double|groove|ridge|inset|outset) (.+)$/.exec(raw); return raw === 'none' || Boolean(match && length(match[1]!, 100) && colors.test(match[3]!)) }
    case 'vertical-align': return ['top', 'middle', 'bottom', 'baseline'].includes(raw)
    case 'float': return ['left', 'right', 'none'].includes(raw)
    case 'aspect-ratio': return /^[0-9.]{1,8}\s*\/\s*[0-9.]{1,8}$/.test(raw)
    case 'font-family': return raw.split(',').every(part => ['arial', 'helvetica', 'sans-serif', 'georgia', 'serif', 'times new roman', 'courier new', 'courier', 'monospace', 'verdana', 'tahoma', 'trebuchet ms'].includes(part.trim().replace(/^['"]|['"]$/g, '')))
    case 'list-style-type': return ['disc', 'circle', 'square', 'decimal', 'decimal-leading-zero', 'lower-roman', 'upper-roman', 'lower-latin', 'upper-latin', 'lower-alpha', 'upper-alpha'].includes(raw)
    default: return false
  }
}
