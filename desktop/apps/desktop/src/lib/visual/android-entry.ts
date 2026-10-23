// Entry for the Android WebView bundle (assets/diagram/visual.js), built by
// scripts/build-visual-bundle.mjs. Exposes the same renderer the desktop uses
// as `window.NeovarchVisual` for assets/diagram/host.html.
import {
  cardCss,
  exportSvg,
  frameDocument,
  measureHtml,
  mermaidPartialTitle,
  mermaidToVisual,
  partialTitle,
  prepareDiagram,
  prepareMermaid,
  prepareVisual,
  renderSpec,
  svgCardHeight
} from './index'

;(globalThis as unknown as { NeovarchVisual: unknown }).NeovarchVisual = {
  cardCss,
  exportSvg,
  frameDocument,
  measureHtml,
  mermaidPartialTitle,
  mermaidToVisual,
  partialTitle,
  prepareDiagram,
  prepareMermaid,
  prepareVisual,
  renderSpec,
  svgCardHeight
}
