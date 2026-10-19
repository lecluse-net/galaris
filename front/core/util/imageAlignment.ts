export type ImageAlignment = 'left' | 'center' | 'right'

export function imageAlignment(image: HTMLElement): ImageAlignment {
  if (image.style.float === 'left' || image.style.float === 'right') return image.style.float
  if (image.matches('.image-style-side, .image-style-align-right, .image-style-block-align-right') || image.style.marginRight === '0px') return 'right'
  if (image.matches('.image-style-align-left, .image-style-block-align-left') || image.style.marginLeft === '0px') return 'left'
  return 'center'
}

export function alignImage(image: HTMLElement, alignment: ImageAlignment,
  wrap = image.matches('.image-style-side, .image-style-align-left, .image-style-align-right') || ['left', 'right'].includes(image.style.float)): void {
  for (const name of [...image.classList]) if (name.startsWith('image-style-')) image.classList.remove(name)
  const floating = wrap && alignment !== 'center'
  if (floating) image.classList.add('image-style-side')
  image.style.float = floating ? alignment : 'none'
  image.style.marginLeft = alignment === 'left' ? '0px' : floating ? '1.5em' : 'auto'
  image.style.marginRight = alignment === 'right' ? '0px' : floating ? '1.5em' : 'auto'
}
