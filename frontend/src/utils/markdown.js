import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'

const markdown = new MarkdownIt({
  breaks: true,
  html: false,
  linkify: true,
  typographer: true
})
const renderCache = new Map()
const MAX_RENDER_CACHE_ITEMS = 100

const defaultLinkOpenRenderer = markdown.renderer.rules.link_open

markdown.renderer.rules.link_open = (tokens, index, options, env, self) => {
  const token = tokens[index]
  const targetIndex = token.attrIndex('target')
  const relIndex = token.attrIndex('rel')
  if (targetIndex < 0) {
    token.attrPush(['target', '_blank'])
  } else {
    token.attrs[targetIndex][1] = '_blank'
  }
  if (relIndex < 0) {
    token.attrPush(['rel', 'noopener noreferrer'])
  } else {
    token.attrs[relIndex][1] = 'noopener noreferrer'
  }
  return defaultLinkOpenRenderer
    ? defaultLinkOpenRenderer(tokens, index, options, env, self)
    : self.renderToken(tokens, index, options)
}

export function renderMarkdown(value) {
  const source = String(value || '')
  const cached = renderCache.get(source)
  if (cached !== undefined) {
    renderCache.delete(source)
    renderCache.set(source, cached)
    return cached
  }
  const raw = markdown.render(source)
  const rendered = DOMPurify.sanitize(raw, {
    ALLOWED_ATTR: ['href', 'target', 'rel', 'class'],
    ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto|tel):|[^a-z]|[a-z+.-]+(?:[^a-z+.-:]|$))/i
  })
  renderCache.set(source, rendered)
  while (renderCache.size > MAX_RENDER_CACHE_ITEMS) {
    renderCache.delete(renderCache.keys().next().value)
  }
  return rendered
}
