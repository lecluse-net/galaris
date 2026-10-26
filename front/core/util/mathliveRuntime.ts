import { MathfieldElement, convertLatexToMarkup } from 'mathlive'
import DOMPurify from 'dompurify'
import 'mathlive/fonts.css'
import 'mathlive/static.css'
import staticCss from 'mathlive/static.css?inline'
import fontsCss from 'mathlive/fonts.css?inline'

// Vite bundles the fonts locally. Never fall back to MathLive's CDN defaults.
MathfieldElement.fontsDirectory = null
MathfieldElement.soundsDirectory = null
MathfieldElement.keypressSound = null
MathfieldElement.plonkSound = null
MathfieldElement.computeEngine = null
// Preserve the shadow keyboard sink and local SVG symbol references.
MathfieldElement.createHTML = html => DOMPurify.sanitize(html, { ADD_ATTR: ['contenteditable'], ADD_TAGS: ['use'] })

export { MathfieldElement, convertLatexToMarkup, staticCss, fontsCss }
