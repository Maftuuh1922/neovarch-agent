// Sanitising agent-written SVG / HTML for ```visual cards.
//
// Defence in depth: the markup is cleaned here with a private DOMPurify
// instance (no scripts, event handlers, foreignObject, forms, media or embeds;
// links only to in-document fragments or data: images; CSS without url() /
// @import to anything but data: images), then shown inside an
// `<iframe sandbox="">` whose CSP forbids every network fetch (desktop) or a
// shadow root inside an offline WebView page that may not navigate (Android).

import createDOMPurify from 'dompurify'

type Purifier = ReturnType<typeof createDOMPurify>

let purifier: Purifier | null = null

const CSS_URL = /url\(\s*(['"]?)(?!data:image\/)[^)]*\1\s*\)/gi
const CSS_IMPORT = /@import[^;]*;?/gi
const CSS_EXPR = /expression\s*\(|-moz-binding|behavior\s*:/gi

export function cleanCss(css: string): string {
  return String(css).replace(CSS_IMPORT, '').replace(CSS_URL, 'none').replace(CSS_EXPR, '')
}

function safeHref(value: string): boolean {
  const v = value.trim().toLowerCase()

  return v.startsWith('#') || /^data:image\/(png|jpe?g|gif|webp);/.test(v)
}

function instance(): Purifier {
  if (purifier) {
    return purifier
  }

  const p = createDOMPurify(window)

  p.addHook('uponSanitizeElement', node => {
    if (node.nodeName.toLowerCase() === 'style' && node.textContent) {
      node.textContent = cleanCss(node.textContent)
    }
  })

  p.addHook('uponSanitizeAttribute', (_node, data) => {
    const name = data.attrName.toLowerCase()

    if (name === 'style') {
      data.attrValue = cleanCss(data.attrValue)
    } else if ((name === 'href' || name === 'xlink:href' || name === 'src') && !safeHref(data.attrValue)) {
      data.keepAttr = false
    }
  })

  purifier = p

  return p
}

const FORBID_TAGS = [
  'script',
  'foreignObject',
  'iframe',
  'object',
  'embed',
  'form',
  'input',
  'textarea',
  'select',
  'button',
  'link',
  'meta',
  'base',
  'audio',
  'video',
  'animate',
  'set',
  'animateMotion',
  'animateTransform'
]

export function sanitizeSvg(svg: string): string {
  return String(
    instance().sanitize(svg, {
      ADD_TAGS: ['style'],
      FORBID_TAGS,
      USE_PROFILES: { svg: true, svgFilters: true }
    })
  )
}

export function sanitizeHtml(html: string): string {
  return String(
    instance().sanitize(html, {
      ADD_TAGS: ['style'],
      FORBID_ATTR: ['srcset', 'action', 'formaction', 'ping'],
      FORBID_TAGS,
      FORCE_BODY: true,
      USE_PROFILES: { html: true, svg: true, svgFilters: true }
    })
  )
}
