/** Adapted from Modern-Office-Day-Icons 1.4.18, athena.svg, DrMcC0y (GPL-3.0).
 * Original artwork, credits and license: public/folder-icons/modern-office/.
 */
export const folderArtwork = {
  folder: {
    back: 'm15.761 6.6079c-.43988 0-.96075-.25793-1.1582-.57385l-.88477-1.4416c-.19645-.31542-.71731-.57335-1.1572-.57385l-9.6325-.013496c-.97275-.0014997-1.7196.70782-1.7196 1.5826l-.006 19.919h29.601v-17.615c0-.7768-.45688-1.2832-1.2572-1.2832z',
    paper: 'M28.964 13.415H3.225V9.8c0-.591.434-1.205 1.259-1.205h23.123c.839 0 1.358.613 1.358 1.205z',
    shadow: 'M29.381 10.636H2.631c-.811 0-1.621.737-1.621 1.475v8.768l29.992-.081v-8.686c0-.737-.811-1.475-1.621-1.475',
    lip: 'M29.383 11.128H2.633c-.811 0-1.617.737-1.617 1.475v8.768l29.972-.081v-8.686c0-.737-.795-1.475-1.605-1.475',
    front: 'M29.377 11.514H2.627c-.811 0-1.621.737-1.621 1.475v13.295c0 .975.8 1.718 1.783 1.718h26.427c.985 0 1.782-.742 1.782-1.718V12.99c0-.737-.811-1.475-1.621-1.475',
    edge: 'M.999 25.823v1.189c0 .976.801 1.718 1.783 1.718h26.434c.985 0 1.783-.742 1.783-1.718v-1.189',
  },
  'folder-open': {
    front: 'M30.15 14H6.5c-.85 0-1.52.52-1.75 1.35L1.1 26.1c-.35 1.1.5 1.902 1.689 1.902h25.927c.985 0 1.6-.62 1.8-1.55l1.3-10.85c.14-.9-.7-1.602-1.666-1.602Z',
    shadow: 'M30.15 13.1H6.5c-.85 0-1.52.52-1.75 1.35L1.1 25.2H30.4l1.416-10.498c.14-.9-.7-1.602-1.666-1.602Z',
    lip: 'M30.15 13.6H6.5c-.85 0-1.52.52-1.75 1.35L1.1 25.7H30.4l1.416-10.498c.14-.9-.7-1.602-1.666-1.602Z',
  },
} as const

type FolderPalette = { accent: string; light: string; dark: string }

/** Only application-owned palette values and Vue useId() identifiers enter this markup. */
export function folderSvgContent(palette: FolderPalette | undefined, expanded: boolean, id: string, size = 24): string {
  if (size <= 32) return smallFolderSvgContent(palette, expanded, id, size)
  const color = (original: string, shade: keyof FolderPalette) => palette?.[shade] ?? original
  const ref = (name: string) => `url(#${id}-${name})`
  const paths = { ...folderArtwork.folder, ...(expanded ? folderArtwork['folder-open'] : {}) }
  return `<defs>
    <linearGradient id="${id}-body" gradientUnits="userSpaceOnUse" x1="30.617" x2="8.633" y1="27.285" y2="9.345">
      <stop stop-color="${color('#ffc937', 'accent')}"/><stop stop-color="${color('#ffeeba', 'light')}" offset="1"/>
    </linearGradient>
    <linearGradient id="${id}-back" gradientUnits="userSpaceOnUse" x1="14.186" x2="14.186" y1="10.624" y2="3.686">
      <stop stop-color="${color('#c8923d', 'dark')}"/><stop stop-color="${color('#fdbd19', 'accent')}" stop-opacity=".996" offset=".465"/>
    </linearGradient>
    <linearGradient id="${id}-shadow" gradientUnits="userSpaceOnUse" x1="30.842" x2=".79" y1="16.793" y2="16.793">
      <stop stop-color="${color('#c99e1e', 'dark')}"/><stop stop-color="${color('#f3b51f', 'accent')}" offset="1"/>
    </linearGradient>
    <linearGradient id="${id}-outline" gradientUnits="userSpaceOnUse" x1="30.452" x2="1.115" y1="14.428" y2="14.428">
      <stop stop-color="${color('#a9760c', 'dark')}" stop-opacity=".48"/><stop stop-color="${color('#a9760c', 'dark')}" stop-opacity=".3" offset="1"/>
    </linearGradient>
    <linearGradient id="${id}-lip" gradientUnits="userSpaceOnUse" x1="30.842" x2=".79" y1="17.293" y2="17.293">
      <stop stop-color="${color('#eddcad', 'light')}"/><stop stop-color="${color('#f1d886', 'accent')}" offset="1"/>
    </linearGradient>
    <filter id="${id}-relief" x="0" y="0" width="1" height="1">
      <feColorMatrix result="tint" values="1 0 0 0.05 0 0 1 0 0.05 0 0 0 1 0.05 0 0 0 0 1 0"/>
      <feColorMatrix values="0 0 0 -1 0 0 0 0 -1 0 0 0 0 -1 0 0 0 0 1 0"/>
      <feColorMatrix in="tint" values="1 0 0 0.05 0 0 1 0 0.05 0 0 0 1 0.05 0 0 0 0 1 0"/>
    </filter>
  </defs>
  <g transform="scale(2)">
  <path d="${paths.edge}" fill="${color('#ecaf24', 'accent')}" fill-opacity=".996"/>
  <path d="${paths.back}" fill="${ref('back')}" stroke="${ref('outline')}" stroke-width=".3" stroke-linejoin="round"/>
  <path d="${paths.paper}" fill="#f3ede8"/>
  <path d="${paths.shadow}" fill="${ref('shadow')}" filter="${ref('relief')}"/>
  <path d="${paths.lip}" fill="${ref('lip')}" filter="${ref('relief')}"/>
  <path d="${paths.front}" fill="${ref('body')}" stroke="${ref('outline')}" stroke-width=".3" stroke-linejoin="round"/>
  </g>`
}

/** Optical small-size drawing: whole-pixel panels, one crisp 1 px contour, no filters. */
function smallFolderSvgContent(palette: FolderPalette | undefined, expanded: boolean, id: string, size: number): string {
  const accent = palette?.accent ?? '#ffc937'
  const light = palette?.light ?? '#ffeeba'
  const dark = palette?.dark ?? '#a9760c'
  const snap = (position: number) => Math.round(position * size / 24)
  const left = 1.5
  const right = size - 1.5
  const top = snap(3) + .5
  const bottom = size - snap(3) - .5
  const tab = snap(10) + .5
  const shoulder = top + 2
  const faceTop = snap(expanded ? 11 : 9) + .5
  const faceLeft = expanded ? snap(5) + .5 : left
  const front = `M${faceLeft + 1} ${faceTop}H${right - 1}Q${right} ${faceTop} ${right} ${faceTop + 1}L${right - (expanded ? 1 : 0)} ${bottom - 1}Q${right - (expanded ? 1 : 0)} ${bottom} ${right - (expanded ? 2 : 1)} ${bottom}H${left + 1}Q${left} ${bottom} ${left} ${bottom - 1}L${faceLeft} ${faceTop + 1}Q${faceLeft} ${faceTop} ${faceLeft + 1} ${faceTop}Z`
  return `<defs>
    <linearGradient id="${id}-small-face" x2="0" y2="1">
      <stop stop-color="${light}" stop-opacity=".5"/><stop stop-color="${light}" stop-opacity=".08" offset="1"/>
    </linearGradient>
  </defs>
  <path d="M${left + 1} ${top}H${tab}L${tab + 2} ${shoulder}H${right - 1}Q${right} ${shoulder} ${right} ${shoulder + 1}V${bottom - 1}Q${right} ${bottom} ${right - 1} ${bottom}H${left + 1}Q${left} ${bottom} ${left} ${bottom - 1}V${top + 1}Q${left} ${top} ${left + 1} ${top}Z" fill="${accent}" stroke="${dark}" stroke-opacity=".4" stroke-linejoin="round"/>
  <path d="M${left + 2} ${snap(7)}H${right - 2}V${faceTop + 2}H${left + 2}Z" fill="#f3ede8"/>
  <path d="${front}" fill="${accent}"/>
  <path d="${front}" fill="url(#${id}-small-face)" stroke="${dark}" stroke-opacity=".4" stroke-linejoin="round"/>`
}
