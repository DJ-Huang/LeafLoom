/* LeafLoom Studio runtime. The same renderer runs in the isolated editor origin and exports. */
(function (global) {
  'use strict';

  const VERSION = 1;
  const handles = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'];
  const unitless = new Set(['opacity', 'zIndex', 'fontWeight', 'lineHeight', 'flex', 'flexGrow', 'flexShrink', 'order', 'aspectRatio', 'scale', 'zoom', 'columnCount', 'gridColumn', 'gridColumnStart', 'gridColumnEnd', 'gridRow', 'gridRowStart', 'gridRowEnd', 'animationIterationCount', 'fillOpacity', 'strokeOpacity', 'strokeMiterlimit', 'fontSizeAdjust', 'lineClamp']);
  const layoutKeys = new Set(['x', 'y', 'width', 'height', 'rotate', 'scaleX', 'scaleY', 'transform', 'transformOrigin', 'position', 'left', 'top', 'right', 'bottom', 'zIndex', 'opacity', 'layout']);
  const blockedKeys = new Set(['__proto__', 'prototype', 'constructor']);
  const moduleLoggers = new Map();
  let loggerSequence = 0;
  const clone = value => value == null ? value : JSON.parse(JSON.stringify(value));
  const finite = (value, fallback) => typeof value === 'number' && Number.isFinite(value) ? value : fallback;
  const rounded = value => Math.round(value * 100) / 100;
  const escaped = value => String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
  const cssValue = (key, value) => typeof value === 'number' && !unitless.has(key.replace(/-([a-z])/g, (_, char) => char.toUpperCase())) ? value + 'px' : String(value);

  function splitSelectors(value) {
    const parts = []; let depth = 0, quote = '', start = 0;
    for (let index = 0; index < value.length; index += 1) {
      const char = value[index];
      if (char === '\\') { index += 1; continue; }
      if (quote) { if (char === quote) quote = ''; continue; }
      if (char === '"' || char === "'") quote = char;
      else if (char === '(' || char === '[') depth += 1;
      else if (char === ')' || char === ']') depth -= 1;
      else if (char === ',' && !depth) { parts.push(value.slice(start, index)); start = index + 1; }
    }
    parts.push(value.slice(start)); return parts;
  }

  function resourceUrl(path, base) {
    if (!path) return '';
    try {
      path = String(path).replace(/__STUDIO_ASSET__\//g, base || '');
      const url = new URL(String(path), base || global.location.href);
      return ['http:', 'https:', 'file:', 'data:', 'blob:'].includes(url.protocol) ? url.href : '';
    } catch (_) { return ''; }
  }

  function responsiveSources(value, resolve) {
    const result = []; let index = 0;
    value = String(value);
    while (index < value.length) {
      while (index < value.length && /[\t\n\f\r ,]/.test(value[index])) index += 1;
      const start = index;
      while (index < value.length && !/[\t\n\f\r ]/.test(value[index])) index += 1;
      let url = value.slice(start, index), descriptors = '';
      if (!url) break;
      if (/,$/.test(url)) url = url.replace(/,+$/, '');
      else {
        const descriptorStart = index; let depth = 0;
        while (index < value.length) {
          const char = value[index];
          if (char === '(') depth += 1;
          else if (char === ')') depth = Math.max(0, depth - 1);
          else if (char === ',' && !depth) break;
          index += 1;
        }
        descriptors = value.slice(descriptorStart, index).trim();
        if (value[index] === ',') index += 1;
      }
      const resolved = url && resolve(url);
      if (resolved) result.push(resolved + (descriptors ? ' ' + descriptors : ''));
    }
    return result.join(', ');
  }

  // Rewrite type selectors outside strings and attribute selectors only.
  // This also covers :is(html.dark, body.ready), without changing [title="body"].
  function documentSelectors(value, htmlRoot, bodyRoot) {
    let result = '', quote = '', brackets = 0;
    for (let index = 0; index < value.length;) {
      const char = value[index];
      if (char === '\\') { result += value.slice(index, index + 2); index += 2; continue; }
      if (quote) { if (char === quote) quote = ''; result += char; index += 1; continue; }
      if (char === '"' || char === "'") quote = char;
      else if (char === '[') brackets += 1;
      else if (char === ']') brackets -= 1;
      if (!quote && !brackets) {
        const rest = value.slice(index);
        if (/^:root(?![\w-])/.test(rest)) { result += ':is(' + htmlRoot + ',:root)'; index += 5; continue; }
        if (!index || /[\s>+~,(|]/.test(value[index - 1])) {
          const match = /^(html|body)(?![\w-])/i.exec(rest);
          if (match) { result += match[1].toLowerCase() === 'html' ? htmlRoot : bodyRoot; index += match[0].length; continue; }
        }
      }
      result += char; index += 1;
    }
    return result;
  }

  function presetFrames(name) {
    return ({
      fade: [{ opacity: 0 }, { opacity: 1 }],
      'fade-in': [{ opacity: 0 }, { opacity: 1 }],
      slide: [{ opacity: 0, translate: '0 24px' }, { opacity: 1, translate: '0 0' }],
      scale: [{ opacity: 0, scale: '.8' }, { opacity: 1, scale: '1' }],
      bounce: [{ translate: '0 0' }, { translate: '0 -16px', offset: .5 }, { translate: '0 0' }],
      breathe: [{ scale: '1' }, { scale: '1.045', offset: .5 }, { scale: '1' }],
      spin: [{ rotate: '0deg' }, { rotate: '360deg' }],
      pulse: [{ opacity: 1 }, { opacity: .5, offset: .5 }, { opacity: 1 }]
    })[name] || null;
  }

  function animationOptions(config) {
    const iterations = ['infinite', 'Infinity'].includes(String(config.iterations)) || config.iterations === Infinity || config.loop ? Infinity : Math.max(1, finite(Number(config.iterations), 1));
    return { duration: Math.max(1, finite(Number(config.duration), 600)), delay: Math.max(0, finite(Number(config.delay), 0)), iterations, easing: config.easing || 'ease-in-out', fill: 'both' };
  }

  // A dependency registry also works for file:// exports: dependencies included in the
  // document become Blob modules instead of native file imports (which browsers block).
  function moduleRegistry(document, base) {
    const sources = new Map();
    Object.entries(document.scripts || {}).forEach(([id, raw]) => {
      const item = typeof raw === 'string' ? { source: raw, path: id } : raw;
      if (!item || typeof item.source !== 'string') return;
      const record = { source: item.source, path: item.path || id };
      sources.set(id, record);
      sources.set(resourceUrl(record.path, base), record);
    });
    return sources;
  }

  function mount(root, document, options) {
    if (!root || !root.ownerDocument) throw new Error('Studio requires a DOM root.');
    if (!document || !Array.isArray(document.pages)) throw new Error('Invalid Studio document.');
    const doc = root.ownerDocument;
    const win = doc.defaultView;
    const settings = Object.assign({ mode: 'preview', selectedIds: [] }, options || {});
    const base = resourceUrl(settings.assetBase || './', win.location.href);
    const emit = (type, payload) => { if (typeof settings.onMessage === 'function') settings.onMessage(Object.assign({ type }, payload || {})); };
    let model = clone(document);
    let currentPageId = settings.pageId || (model.pages[0] && model.pages[0].id);
    let mode = settings.mode;
    let selected = new Set(settings.selectedIds || []);
    let decorated = new Set();
    let generation = 0;
    let disposed = false;
    let zoom = 1;
    const cameras = new Map();
    let tool = 'select';
    let spaceDown = false;
    let panGesture = null;
    let gesture = null;
    let textEdit = null;
    let gestureFrame = 0;
    const gestureWork = [];
    let hovered = null;
    let previewNodeId = settings.previewNodeId || null;
    let navigationContext = {};
    let renderedEntries = [];
    let authoredTexts = new Map();
    let editable = new Map();
    let cleanup = [];
    let urls = [];
    let overlayEntries = [];
    let overlayStop = null;
    const runtimeState = Object.create(null);
    const tracked = { listeners: 0, timers: 0, frames: 0, animations: 0 };
    const htmlFrames = new Map();
    const viewport = doc.createElement('div');
    viewport.className = 'studio-viewport';
    viewport.setAttribute('tabindex', '0');
    const stage = doc.createElement('div');
    stage.className = 'studio-stage';
    viewport.appendChild(stage);
    root.replaceChildren(viewport);

    function report(error, nodeId, lineOffset) {
      const message = error && error.message ? error.message : String(error);
      const stack = error && error.stack || '';
      const location = stack.match(/(?:blob:[^\s)]+|studio-script[^\s)]+):(\d+):(\d+)/);
      emit('studio-error', { nodeId: nodeId || null, message, line: location ? Math.max(1, Number(location[1]) - (lineOffset || 0)) : undefined });
      if (!settings.onMessage) {
        let box = viewport.querySelector('.studio-runtime-error');
        if (!box) { box = doc.createElement('div'); box.className = 'studio-runtime-error'; viewport.appendChild(box); }
        box.textContent = (nodeId ? nodeId + ': ' : '') + message;
      }
    }

    function asset(id) {
      const entry = model.assets && model.assets[id];
      return resourceUrl(entry ? entry.path || entry.src : id, base);
    }

    function materialize(value) { return typeof value === 'string' ? value.replace(/__STUDIO_ASSET__\//g, base) : value; }

    function resolvedStyle(node) {
      const shared = node.props && node.props.styleId && model.styles && model.styles[node.props.styleId];
      return Object.assign({}, shared && (shared.style || shared), node.style);
    }

    function applyLayout(entry, style) {
      const el = entry.wrapper;
      const s = style || {};
      if (entry.authored) {
        el.style.cssText = entry.authoredCss || '';
        ['width', 'height', 'position', 'left', 'top', 'right', 'bottom', 'zIndex', 'opacity', 'transformOrigin'].forEach(key => {
          if (s[key] != null) el.style[key] = cssValue(key, s[key]);
        });
        // Individual translate leaves authored transforms, perspective and layout intact.
        if (s.x != null || s.y != null) el.style.translate = finite(s.x, 0) + 'px ' + finite(s.y, 0) + 'px';
        if (s.rotate != null) el.style.rotate = finite(s.rotate, 0) + 'deg';
        if (s.scaleX != null || s.scaleY != null) el.style.scale = finite(s.scaleX, 1) + ' ' + finite(s.scaleY, 1);
        if (s.transform != null) el.style.transform = s.transform;
        contentStyle(el, s);
        scopeAnimationNames(el.style, entry.scope.keyframes);
        return;
      }
      el.style.position = s.position || (entry.flow ? 'relative' : 'absolute');
      el.style.left = cssValue('left', s.x == null ? s.left == null ? 0 : s.left : s.x);
      el.style.top = cssValue('top', s.y == null ? s.top == null ? 0 : s.top : s.y);
      el.style.width = cssValue('width', s.width == null ? 160 : s.width);
      el.style.height = cssValue('height', s.height == null ? 80 : s.height);
      el.style.opacity = s.opacity == null ? '1' : String(s.opacity);
      el.style.zIndex = s.zIndex == null ? '' : String(s.zIndex);
      el.style.transformOrigin = s.transformOrigin || '0 0';
      el.style.transform = 'rotate(' + finite(s.rotate, 0) + 'deg) scale(' + finite(s.scaleX, 1) + ',' + finite(s.scaleY, 1) + ')' + (s.transform ? ' ' + s.transform : '');
      if (s.right != null && s.x == null && s.left == null) { el.style.left = 'auto'; el.style.right = cssValue('right', s.right); }
      if (s.bottom != null && s.y == null && s.top == null) { el.style.top = 'auto'; el.style.bottom = cssValue('bottom', s.bottom); }
      if (entry.flow) { el.style.flexShrink = '0'; el.style.left = ''; el.style.top = ''; }
    }

    function contentStyle(el, style) {
      Object.entries(style || {}).forEach(([key, value]) => {
        if (layoutKeys.has(key) || blockedKeys.has(key) || value == null || typeof value === 'object') return;
        try { if (key.startsWith('--')) el.style.setProperty(key, String(materialize(value))); else el.style[key] = cssValue(key, materialize(value)); } catch (_) { /* Ignore unsupported CSS properties. */ }
      });
      if (style && ['row', 'column', 'grid'].includes(style.layout)) {
        el.style.display = style.layout === 'grid' ? 'grid' : 'flex';
        if (style.layout !== 'grid') el.style.flexDirection = style.layout;
      }
    }

    function placeholder(el, message) { el.classList.add('studio-missing'); el.textContent = message; }

    function makeScope(prefix, nodes, context) {
      const scope = { prefix, refs: new Map(), domIds: new Map() };
      const collect = items => (items || []).forEach(node => {
        const id = node.props && node.props.attributes && node.props.attributes.id;
        if (id) scope.domIds.set(String(id), prefix + '__dom_' + id);
        if (node.props && node.props.html && node.props.tag === 'svg') {
          const svg = new win.DOMParser().parseFromString('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">' + node.props.html + '</svg>', 'image/svg+xml');
          [...svg.documentElement.querySelectorAll('[id]')].forEach(item => scope.domIds.set(item.id, prefix + '__dom_' + item.id));
        }
        collect(node.children);
      });
      collect(nodes);
      if (context && context.version === 1) [context.html, context.body, ...(context.ancestors || [])].forEach(item => {
        const id = item && item.attributes && item.attributes.id;
        if (id) scope.domIds.set(String(id), prefix + '__dom_' + id);
      });
      return scope;
    }

    function localReferences(value, scope) {
      return String(value).replace(/url\(\s*(['"]?)#([^)'"\s]+)\1\s*\)/g, (all, quote, id) => 'url(#' + (scope.domIds.get(id) || id) + ')')
        .replace(/^#(.+)$/, (all, id) => '#' + (scope.domIds.get(id) || id));
    }

    function pageStyles(page, parent, scope) {
      if (!page.css && !page.authoredContext) return;
      parent.dataset.studioPageScope = scope.prefix;
      const boundary = '[data-studio-page-scope="' + scope.prefix.replace(/["\\]/g, '\\$&') + '"]';
      const temporary = doc.createElement('style'); temporary.media = 'not all'; temporary.textContent = materialize(page.css || '');
      doc.head.appendChild(temporary);
      const keyframes = scope.keyframes = new Map();
      function collectKeyframes(list) {
        [...list].forEach(rule => {
          if (rule.type === 7) keyframes.set(rule.name, scope.prefix + '__keyframe_' + rule.name);
          else if (rule.cssRules) collectKeyframes(rule.cssRules);
        });
      }
      function references(text, selector) {
        let result = localReferences(text, scope);
        if (selector) scope.domIds.forEach((to, from) => { result = result.replace(new RegExp('#' + from.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(?![\\w-])', 'g'), '#' + win.CSS.escape(to)); });
        return result.replace(/url\(\s*(['"]?)([^)'"\s]+)\1\s*\)/g, (all, quote, path) => path.startsWith('#') || path.startsWith('data:') ? all : 'url("' + resourceUrl(path, resourceUrl(page.basePath || './', base)) + '")');
      }
      function rules(list) {
        return [...list].map(rule => {
          if (rule.type === 1) {
            const selectors = splitSelectors(references(rule.selectorText, true)).map(part => {
              if (page.authoredContext && page.authoredContext.version === 1) return boundary + ' ' + documentSelectors(part.trim(), 'studio-document-html:where([data-studio-document-root="html"])', 'studio-document-body:where([data-studio-document-root="body"])');
              const value = part.trim().replace(/(^|\s)(?:html|body|:root)(?=[\s.#:[>+~]|$)/g, '$1' + boundary);
              return value.includes(boundary) ? value : boundary + ' ' + value;
            }).join(',');
            scopeAnimationNames(rule.style, keyframes);
            return selectors + '{' + references(rule.style.cssText) + '}';
          }
          // @import cannot be scoped by prefixing selectors. Capture expands
          // readable imports; leave inaccessible remote sheets out of the host.
          if (rule.type === 3) return '';
          if (rule.type === 7) { rule.name = keyframes.get(rule.name) || rule.name; return references(rule.cssText); }
          if (rule.cssRules && rule.type !== 7) return rule.cssText.slice(0, rule.cssText.indexOf('{') + 1) + rules(rule.cssRules) + '}';
          return references(rule.cssText);
        }).join('\n');
      }
      let css = '';
      try { collectKeyframes(temporary.sheet.cssRules); css = rules(temporary.sheet.cssRules); } catch (error) { report(error); }
      temporary.remove();
      if (page.authoredContext && page.authoredContext.version === 1) {
        css = ':where(' + boundary + ' [data-studio-document-root="html"]){display:block;font-family:"Times New Roman",serif;font-size:16px;line-height:normal;color:black;text-align:start;}' +
          ':where(' + boundary + ' [data-studio-document-root="html"]:not([dir])){direction:ltr;}' +
          ':where(' + boundary + ' [data-studio-document-root="body"]){display:block;margin:8px;}' +
          ':where(' + boundary + ') *,:where(' + boundary + ') .studio-authored{box-sizing:content-box;}' + css;
      }
      const style = doc.createElement('style'); style.textContent = css; parent.prepend(style);
    }

    function authoredAttributes(el, attributes, scope) {
      Object.entries(attributes || {}).forEach(([key, value]) => {
        if (/^on/i.test(key) || /^data-studio-/i.test(key) || key === 'srcdoc' || blockedKeys.has(key)) return;
        let text = localReferences(materialize(value), scope);
        if (key === 'id') text = scope.domIds.get(String(value)) || scope.prefix + '__dom_' + value;
        if (['src', 'poster', 'href', 'xlink:href'].includes(key) && !String(value).startsWith('#')) text = resourceUrl(text, base);
        if (key === 'srcset' || key === 'imagesrcset') text = responsiveSources(value, path => resourceUrl(path, base));
        try { el.setAttribute(key, text); } catch (_) { /* Invalid authored attribute names are inert. */ }
      });
    }

    function pageRoot(page, parent, scope) {
      const context = page.authoredContext;
      if (!context || context.version !== 1) return parent;
      let target = parent;
      const roots = [{...context.html, tag: 'html'}, {...context.body, tag: 'body'}, ...(context.ancestors || [])];
      roots.forEach((item, index) => {
        let tag = String(item.tag || 'div').toLowerCase();
        if (index < 2) tag = index ? 'studio-document-body' : 'studio-document-html';
        else if (!/^[a-z][\w-]*$/.test(tag) || ['script', 'style', 'link', 'iframe', 'object', 'embed', 'base', 'meta'].includes(tag)) tag = 'div';
        const element = doc.createElement(tag);
        authoredAttributes(element, item.attributes, scope);
        if (index < 2) element.dataset.studioDocumentRoot = index ? 'body' : 'html';
        target.appendChild(element); target = element;
      });
      return target;
    }

    function scopeAnimationNames(style, names) {
      if (!names || !names.size) return;
      ['animation-name', '-webkit-animation-name'].forEach(property => {
        const value = style.getPropertyValue(property);
        if (!value) return;
        const renamed = splitSelectors(value).map(name => {
          const trimmed = name.trim(), unquoted = trimmed.replace(/^(['"])(.*)\1$/, '$2');
          return names.has(unquoted) ? win.CSS.escape(names.get(unquoted)) : trimmed;
        }).join(', ');
        if (renamed !== value) style.setProperty(property, renamed, style.getPropertyPriority(property));
      });
    }

    function renderAuthored(node, parent, scope, chain, ownerId, entries) {
      const props = node.props || {};
      if (props.textNode === true) {
        const text = doc.createTextNode(node.hidden ? '' : String(props.text == null ? '' : props.text));
        parent.appendChild(text);
        if (ownerId == null) authoredTexts.set(node.id, { node, visual: text });
        return;
      }
      let tag = String(props.tag || (node.type === 'image' ? 'img' : node.type === 'button' ? 'button' : 'div')).toLowerCase();
      if (!/^[a-z][\w-]*$/.test(tag) || ['script', 'style', 'link', 'iframe', 'object', 'embed', 'base', 'meta'].includes(tag)) tag = 'div';
      const isSvg = tag === 'svg' || parent.namespaceURI === 'http://www.w3.org/2000/svg';
      const el = isSvg ? doc.createElementNS('http://www.w3.org/2000/svg', tag) : doc.createElement(tag);
      authoredAttributes(el, props.attributes, scope);
      el.classList.add('studio-node', 'studio-authored');
      el.dataset.studioNode = node.id;
      const entry = { node, wrapper: el, visual: el, scope, flow: false, authored: true, authoredCss: el.style.cssText, editable: ownerId == null, ownerId: ownerId || node.id };
      scope.refs.set(node.id, entry); entries.push(entry);
      if (ownerId == null) { el.dataset.studioSelectId = node.id; editable.set(node.id, entry); }
      const style = resolvedStyle(node);
      applyLayout(entry, style); contentStyle(el, style);
      if (node.hidden) el.style.display = 'none';
      if (props.assetId && tag === 'img') el.setAttribute('src', asset(props.assetId));
      else if (props.src && tag === 'img') el.setAttribute('src', resourceUrl(props.src, base));
      if (tag === 'img' && props.fit) el.style.objectFit = props.fit;
      if (tag === 'img' && props.objectPosition) el.style.objectPosition = props.objectPosition;
      if (props.text != null) el.appendChild(doc.createTextNode(String(props.text)));
      if (isSvg && props.html) {
        const svg = new win.DOMParser().parseFromString('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">' + materialize(props.html) + '</svg>', 'image/svg+xml');
        const parseError = svg.querySelector('parsererror');
        if (parseError) { report(new Error('Invalid SVG source: ' + parseError.textContent), node.id); el.textContent = 'Invalid SVG'; return entry; }
        [...svg.documentElement.querySelectorAll('script, foreignObject')].forEach(item => item.remove());
        [...svg.documentElement.querySelectorAll('*')].forEach(item => {
          [...item.attributes].forEach(attribute => {
            if (/^on/i.test(attribute.name)) item.removeAttribute(attribute.name);
            else item.setAttribute(attribute.name, attribute.name === 'id' ? scope.domIds.get(attribute.value) || attribute.value : localReferences(attribute.value, scope));
          });
        });
        [...svg.documentElement.childNodes].forEach(child => el.appendChild(doc.importNode(child, true)));
      }
      parent.appendChild(el);
      renderNodes(node.children, el, scope, chain, ownerId, false, entries);
      return entry;
    }

    function customHtml(html, css) {
      html = materialize(html);
      const policy = mode === 'edit' ? '<meta http-equiv="Content-Security-Policy" content="script-src &apos;none&apos;; object-src &apos;none&apos;">' : '';
      const logger = mode === 'preview' ? '<script>(()=>{const send=(type,data)=>parent.postMessage(Object.assign({type},data),"*");addEventListener("error",e=>send("studio-custom-error",{message:e.message,line:e.lineno}));addEventListener("unhandledrejection",e=>send("studio-custom-error",{message:String(e.reason&&e.reason.message||e.reason)}));for(const level of ["log","info","warn","error","debug"]){const original=console[level];console[level]=(...args)=>{send("studio-custom-console",{level,args:args.map(value=>{try{return typeof value==="string"?value:JSON.stringify(value)}catch(_){return String(value)}})});original.apply(console,args)}}})();<\/script>' : '';
      const head = '<meta charset="utf-8">' + policy + '<base href="' + escaped(base) + '"><style>html,body{margin:0;width:100%;height:100%;box-sizing:border-box}*{box-sizing:inherit}' + materialize(String(css || '')).replace(/<\/style/gi, '<\\/style') + '</style>' + logger;
      if (/<html[\s>]/i.test(html)) return /<head(?:\s[^>]*)?>/i.test(html) ? String(html).replace(/<head(?:\s[^>]*)?>/i, value => value + head) : String(html).replace(/<html(?:\s[^>]*)?>/i, value => value + '<head>' + head + '</head>');
      return '<!doctype html><html><head>' + head + '</head><body>' + materialize(html) + '</body></html>';
    }

    function renderNodes(nodes, parent, scope, chain, ownerId, flow, entries) {
      (nodes || []).forEach(node => renderNode(node, parent, scope, chain, ownerId, flow, entries));
    }

    function renderNode(node, parent, scope, chain, ownerId, flow, entries) {
      if (!node || !node.id) return;
      if (node.type === 'element' || node.props && node.props.authored) return renderAuthored(node, parent, scope, chain, ownerId, entries);
      const wrapper = doc.createElement('div');
      const visual = doc.createElement(node.type === 'button' ? 'button' : 'div');
      wrapper.className = 'studio-node';
      visual.className = 'studio-content';
      wrapper.id = scope.prefix + '__' + node.id;
      wrapper.dataset.studioNode = node.id;
      const entry = { node, wrapper, visual, scope, flow, locked: !!node.locked, editable: ownerId == null, ownerId: ownerId || node.id };
      entries.push(entry);
      scope.refs.set(node.id, entry);
      if (ownerId == null) {
        wrapper.dataset.studioSelectId = node.id;
        editable.set(node.id, entry);
      }
      const style = resolvedStyle(node);
      applyLayout(entry, style);
      contentStyle(visual, style);
      scopeAnimationNames(visual.style, scope.keyframes);
      wrapper.hidden = !!node.hidden;
      wrapper.appendChild(visual);
      parent.appendChild(wrapper);
      const props = node.props || {};
      if (node.type === 'text' || node.type === 'button') {
        visual.textContent = props.text == null ? node.type === 'button' ? 'Button' : 'Text' : String(props.text);
        visual.style.whiteSpace = visual.style.whiteSpace || 'pre-wrap';
        if (node.type === 'button') visual.type = 'button';
      } else if (node.type === 'image' || node.type === 'svg') {
        const image = doc.createElement('img');
        image.alt = String(props.alt || node.name || '');
        image.loading = 'lazy'; image.decoding = 'async'; image.draggable = false;
        image.src = props.assetId ? asset(props.assetId) : props.svg ? 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(materialize(props.svg)) : resourceUrl(props.src || props.path, base);
        image.style.objectFit = props.fit || props.objectFit || style.objectFit || 'contain';
        image.style.objectPosition = props.objectPosition || 'center';
        image.addEventListener('error', () => { placeholder(visual, 'Missing image: ' + (node.name || node.id)); });
        visual.appendChild(image);
      } else if (node.type === 'html') {
        const frame = doc.createElement('iframe');
        frame.title = node.name || 'Custom HTML';
        frame.setAttribute('sandbox', mode === 'preview' ? 'allow-scripts allow-forms allow-popups' : '');
        frame.srcdoc = customHtml(props.html || '', props.css || '');
        visual.appendChild(frame);
        htmlFrames.set(frame.contentWindow, node.id);
      } else if (node.type === 'page') {
        const target = model.pages.find(page => page.id === props.pageId);
        const key = 'page:' + props.pageId;
        if (!target) placeholder(visual, 'Missing page: ' + props.pageId);
        else if (chain.has(key)) placeholder(visual, 'Cyclic page embedding');
        else {
          const embedded = doc.createElement('div');
          embedded.style.cssText = 'position:relative;width:' + finite(target.width, 1280) + 'px;height:' + finite(target.height, 720) + 'px;transform-origin:0 0;';
          const ew = finite(Number(node.style && node.style.width), target.width), eh = finite(Number(node.style && node.style.height), target.height);
          embedded.style.transform = 'scale(' + ew / finite(target.width, 1280) + ',' + eh / finite(target.height, 720) + ')';
          visual.appendChild(embedded);
          const childScope = makeScope(wrapper.id + '__page', target.nodes, target.authoredContext);
          pageStyles(target, embedded, childScope);
          renderNodes(target.nodes, pageRoot(target, embedded, childScope), childScope, new Set([...chain, key]), ownerId || node.id, false, entries);
        }
      } else if (node.type === 'instance') {
        const component = model.components && model.components[props.componentId];
        const key = 'component:' + props.componentId;
        if (!component || !component.node) placeholder(visual, 'Missing component: ' + props.componentId);
        else if (chain.has(key)) placeholder(visual, 'Cyclic component nesting');
        else {
          const componentRoot = clone(component.node);
          function override(item) {
            const patch = props.overrides && props.overrides[item.id];
            if (patch) { item.style = Object.assign({}, item.style, patch.style); item.props = Object.assign({}, item.props, patch.props); }
            (item.children || []).forEach(override);
          }
          override(componentRoot);
          componentRoot.style = Object.assign({}, componentRoot.style, { x: 0, y: 0, width: '100%', height: '100%' });
          const childScope = makeScope(wrapper.id + '__instance', [componentRoot]);
          childScope.keyframes = scope.keyframes;
          renderNode(componentRoot, visual, childScope, new Set([...chain, key]), ownerId || node.id, false, entries);
        }
      }
      const s = style;
      renderNodes(node.children, visual, scope, chain, ownerId, s.layout && s.layout !== 'free' || s.display === 'flex' || s.display === 'grid', entries);
      return entry;
    }

    function syncSelection() {
      const next = mode === 'edit' ? selected : new Set();
      new Set([...decorated, ...next]).forEach(id => {
        const entry = editable.get(id);
        if (!entry) return;
        entry.wrapper.classList.toggle('studio-selected', next.has(id));
        [...entry.wrapper.children].filter(child => child.classList.contains('studio-handle')).forEach(child => child.remove());
        if (next.has(id) && next.size === 1 && !entry.authored && !isLocked(entry)) handles.forEach(handle => {
          const grip = doc.createElement('span'); grip.className = 'studio-handle'; grip.dataset.handle = handle; entry.wrapper.appendChild(grip);
        });
      });
      decorated = new Set(next);
    }

    function select(ids, notify) {
      selected = new Set((ids || []).filter(id => editable.has(id)));
      syncSelection();
      if (notify) emit('studio-selection', { ids: [...selected] });
    }

    const cameraKey = () => JSON.stringify([model.id, currentPageId, mode]);
    const camera = () => cameras.get(cameraKey());
    const clampZoom = value => Math.min(8, Math.max(.03, value));

    function cameraChanged() {
      const view = camera();
      if (view) emit('studio-camera', { pageId: currentPageId, zoom: view.zoom, centerX: view.x, centerY: view.y, tool });
    }

    function applyCamera() {
      const page = model.pages.find(item => item.id === currentPageId), view = camera();
      if (!page || !view || disposed) return;
      zoom = view.zoom;
      stage.style.width = Math.max(1, finite(page.width, 1280)) + 'px';
      stage.style.height = Math.max(1, finite(page.height, 720)) + 'px';
      stage.style.transform = 'translate(' + (-view.x * zoom) + 'px,' + (-view.y * zoom) + 'px) scale(' + zoom + ')';
      viewport.style.backgroundPosition = (viewport.clientWidth / 2 - view.x * zoom) + 'px ' + (viewport.clientHeight / 2 - view.y * zoom) + 'px';
      cameraChanged();
    }

    function fit() {
      const page = model.pages.find(item => item.id === currentPageId);
      if (!page || disposed) return;
      const width = Math.max(1, finite(page.width, 1280)), height = Math.max(1, finite(page.height, 720));
      cameras.set(cameraKey(), { zoom: Math.min(1.5, clampZoom(Math.min((viewport.clientWidth - 80) / width, (viewport.clientHeight - 80) / height))), x: width / 2, y: height / 2, automatic: true });
      applyCamera();
    }

    function restoreCamera() {
      if (!camera() || camera().automatic) fit();
      else applyCamera();
    }

    function setZoom(value, anchor) {
      if (typeof value !== 'number' || !Number.isFinite(value) || disposed) return;
      if (!camera()) fit();
      const view = camera();
      if (!view) return;
      const next = clampZoom(value), bounds = viewport.getBoundingClientRect();
      const x = anchor ? anchor.x - bounds.left - viewport.clientWidth / 2 : 0;
      const y = anchor ? anchor.y - bounds.top - viewport.clientHeight / 2 : 0;
      view.x += x * (1 / view.zoom - 1 / next);
      view.y += y * (1 / view.zoom - 1 / next);
      view.zoom = next; view.automatic = false;
      applyCamera();
    }

    function fitSelection() {
      const bounds = [...selected].map(id => editable.get(id)).filter(entry => entry && !entry.node.hidden).map(entry => entry.wrapper.getBoundingClientRect()).filter(rect => rect.width > 0 && rect.height > 0);
      if (!bounds.length) return;
      const board = stage.getBoundingClientRect();
      const left = Math.min(...bounds.map(rect => rect.left)), top = Math.min(...bounds.map(rect => rect.top));
      const right = Math.max(...bounds.map(rect => rect.right)), bottom = Math.max(...bounds.map(rect => rect.bottom));
      const width = (right - left) / zoom, height = (bottom - top) / zoom;
      cameras.set(cameraKey(), { zoom: clampZoom(Math.min((viewport.clientWidth - 96) / Math.max(1, width), (viewport.clientHeight - 96) / Math.max(1, height))), x: ((left + right) / 2 - board.left) / zoom, y: ((top + bottom) / 2 - board.top) / zoom, automatic: false });
      applyCamera();
    }

    function syncTool() {
      viewport.classList.toggle('studio-hand', mode === 'edit' && (tool === 'hand' || spaceDown));
      viewport.classList.toggle('studio-panning', !!panGesture);
      if ((tool === 'hand' || spaceDown) && hovered) { hovered.classList.remove('studio-hovered'); hovered = null; }
    }

    function setTool(value) {
      if (value !== 'select' && value !== 'hand') return;
      cancelGesture(); finishTextEdit(false); tool = value; syncTool(); cameraChanged();
    }

    function finishPan() {
      if (!panGesture) return;
      const completed = panGesture; panGesture = null;
      if (viewport.hasPointerCapture(completed.pointerId)) viewport.releasePointerCapture(completed.pointerId);
      syncTool();
    }

    function wheel(event) {
      if (mode !== 'edit' || textEdit || gesture || panGesture) return;
      event.preventDefault();
      if (event.ctrlKey || event.metaKey) setZoom(zoom * Math.exp(-event.deltaY * .01), { x: event.clientX, y: event.clientY });
      else {
        const view = camera(); if (!view) return;
        const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? viewport.clientHeight : 1;
        view.x += (event.shiftKey && !event.deltaX ? event.deltaY : event.deltaX) * unit / zoom;
        view.y += (event.shiftKey && !event.deltaX ? 0 : event.deltaY) * unit / zoom;
        view.automatic = false; applyCamera();
      }
    }

    function releasePreview() {
      generation += 1;
      cleanup.splice(0).reverse().forEach(fn => { try { fn(); } catch (error) { report(error); } });
      urls.splice(0).forEach(url => win.URL.revokeObjectURL(url));
      overlayEntries = [];
      overlayStop = null;
      Object.keys(runtimeState).forEach(key => delete runtimeState[key]);
      stage.querySelectorAll('.studio-overlay').forEach(el => el.remove());
    }

    function redraw() {
      finishTextEdit(true);
      cancelGesture();
      releasePreview();
      editable = new Map(); authoredTexts = new Map(); renderedEntries = []; decorated = new Set();
      stage.replaceChildren();
      htmlFrames.clear();
      hovered = null;
      viewport.classList.toggle('studio-editing', mode === 'edit');
      viewport.classList.toggle('studio-previewing', mode === 'preview');
      syncTool();
      const page = model.pages.find(item => item.id === currentPageId);
      if (!page) { placeholder(stage, 'Page not found'); return; }
      if (mode === 'preview' && page.migration) navigationContext = Object.assign({}, navigationContext, page.migration.contextSource && page.migration.contextSource.context || page.migration.contextDefaults);
      stage.classList.remove('studio-missing');
      stage.style.background = page.background || '#fff';
      const fontRules = Object.values(model.assets || {}).filter(item => /\.(woff2?|ttf|otf)(?:$|[?#])/i.test(item.path || '')).map(item => '@font-face{font-family:"' + String(item.fontFamily || item.name || item.id).replace(/["\\]/g, '\\$&') + '";src:url("' + asset(item.id) + '");font-display:swap;}').join('\n');
      if (fontRules) { const fonts = doc.createElement('style'); fonts.textContent = fontRules; stage.appendChild(fonts); }
      const scope = makeScope('page_' + page.id, page.nodes, page.authoredContext);
      pageStyles(page, stage, scope);
      renderNodes(page.nodes, pageRoot(page, stage, scope), scope, new Set(['page:' + page.id]), null, false, renderedEntries);
      select([...selected], false);
      restoreCamera();
      if (mode === 'preview') {
        const pageEntry = { node: { id: page.id, props: page.props, script: page.script, animation: page.animation }, wrapper: stage, visual: stage, scope, ownerId: page.id };
        startPreview(previewNodeId ? renderedEntries : [pageEntry, ...renderedEntries]);
      }
    }

    // Compute once at gesture start. Translation cancels when converting a delta;
    // every parent rotation/scale, including canvas zoom, remains in the inverse.
    function deltaConverter(element) {
      let matrix = new win.DOMMatrix();
      for (let current = element; current && current !== doc.documentElement; current = current.parentElement) {
        const computed = win.getComputedStyle(current);
        let local = new win.DOMMatrix();
        const rotation = computed.rotate || 'none';
        if (/^-?[\d.]+deg$/.test(rotation)) local = local.rotate(parseFloat(rotation));
        const scale = computed.scale || 'none';
        if (scale !== 'none') { const values = scale.split(/\s+/).map(Number); local = local.scale(values[0] || 1, values[1] || values[0] || 1); }
        if (computed.transform && computed.transform !== 'none') local = local.multiply(new win.DOMMatrix(computed.transform));
        matrix = local.multiply(matrix);
      }
      const inverse = matrix.inverse();
      return (x, y) => ({ x: inverse.a * x + inverse.c * y, y: inverse.b * x + inverse.d * y });
    }

    function isLocked(entry) {
      for (let el = entry.wrapper; el && el !== stage; el = el.parentElement) {
        const id = el.dataset && el.dataset.studioSelectId;
        if (id && editable.get(id) && editable.get(id).node.locked) return true;
      }
      return false;
    }

    function pointerDown(event) {
      if (mode !== 'edit' || ![0, 1].includes(event.button) || gesture || panGesture) return;
      if (event.button === 1 || tool === 'hand' || spaceDown) {
        event.preventDefault(); finishTextEdit(false); viewport.focus({ preventScroll: true });
        const view = camera(); if (!view) return;
        panGesture = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, centerX: view.x, centerY: view.y };
        viewport.setPointerCapture(event.pointerId); syncTool(); return;
      }
      if (textEdit && textEdit.entry.visual.contains(event.target)) return;
      if (textEdit) finishTextEdit(false);
      viewport.focus({ preventScroll: true });
      const wrapper = event.target.closest('[data-studio-select-id]');
      if (!wrapper || !stage.contains(wrapper)) { select([], true); return; }
      const entry = editable.get(wrapper.dataset.studioSelectId);
      if (!entry) return;
      event.preventDefault();
      const handle = event.target.dataset.handle || null;
      if (event.shiftKey && !handle) {
        const next = new Set(selected); next.has(entry.node.id) ? next.delete(entry.node.id) : next.add(entry.node.id); select([...next], true);
        if (!selected.has(entry.node.id)) return;
      } else if (!selected.has(entry.node.id)) select([entry.node.id], true);
      if (isLocked(entry)) return;
      const targets = (handle ? [entry] : [...selected].map(id => editable.get(id))).filter(item => item && !isLocked(item) && !item.flow);
      // A selected descendant follows its selected ancestor naturally.
      const top = targets.filter(item => !targets.some(other => other !== item && other.wrapper.contains(item.wrapper)));
      if (!top.length) return;
      gesture = { pointerId: event.pointerId, capture: entry.wrapper, x: event.clientX, y: event.clientY, dx: 0, dy: 0, handle, targets: top.map(item => {
        const original = clone(resolvedStyle(item.node));
        return { entry: item, original, startX: finite(original.x, item.authored ? 0 : item.wrapper.offsetLeft), startY: finite(original.y, item.authored ? 0 : item.wrapper.offsetTop), convert: deltaConverter(handle ? item.wrapper : item.wrapper.parentElement), width: item.wrapper.offsetWidth, height: item.wrapper.offsetHeight, patch: null };
      }) };
      gestureWork.length = 0;
      viewport.classList.add('studio-dragging');
      if (!handle) top.forEach(item => { item.wrapper.style.willChange = 'translate'; });
      gesture.capture.setPointerCapture(event.pointerId);
    }

    function updateGesture() {
      gestureFrame = 0;
      if (!gesture) return;
      const workStarted = win.performance.now();
      const g = gesture;
      g.targets.forEach(target => {
        const delta = target.convert(g.dx, g.dy);
        const s = target.original;
        let patch;
        if (!g.handle) { patch = target.patch || {}; patch.x = rounded(target.startX + delta.x); patch.y = rounded(target.startY + delta.y); }
        else {
          const west = g.handle.includes('w'), north = g.handle.includes('n');
          const dw = g.handle.includes('w') || g.handle.includes('e') ? delta.x * (west ? -1 : 1) : 0;
          const dh = g.handle.includes('n') || g.handle.includes('s') ? delta.y * (north ? -1 : 1) : 0;
          let width = Math.max(1, target.width + dw), height = Math.max(1, target.height + dh);
          if (target.entry.node.props && target.entry.node.props.lockAspectRatio) {
            const ratio = target.width / Math.max(1, target.height);
            if (g.handle === 'n' || g.handle === 's' || Math.abs(dh) > Math.abs(dw)) width = height * ratio;
            else height = width / ratio;
          }
          const offsetX = west ? target.width - width : 0, offsetY = north ? target.height - height : 0;
          const radians = finite(s.rotate, 0) * Math.PI / 180;
          const tx = offsetX * finite(s.scaleX, 1), ty = offsetY * finite(s.scaleY, 1);
          patch = { width: rounded(width), height: rounded(height), x: rounded(finite(s.x, 0) + tx * Math.cos(radians) - ty * Math.sin(radians)), y: rounded(finite(s.y, 0) + tx * Math.sin(radians) + ty * Math.cos(radians)) };
        }
        target.patch = patch;
        if (!g.handle) {
          const left = target.entry.authored ? 0 : target.startX;
          const top = target.entry.authored ? 0 : target.startY;
          target.entry.wrapper.style.translate = (patch.x - left) + 'px ' + (patch.y - top) + 'px';
        } else applyLayout(target.entry, Object.assign({}, s, patch));
      });
      if (gestureWork.length === 240) gestureWork.shift();
      gestureWork.push(win.performance.now() - workStarted);
    }

    function pointerMove(event) {
      if (panGesture && event.pointerId === panGesture.pointerId) {
        const view = camera();
        view.x = panGesture.centerX - (event.clientX - panGesture.x) / zoom;
        view.y = panGesture.centerY - (event.clientY - panGesture.y) / zoom;
        view.automatic = false; applyCamera(); return;
      }
      if (!gesture || event.pointerId !== gesture.pointerId) return;
      gesture.dx = event.clientX - gesture.x; gesture.dy = event.clientY - gesture.y;
      if (!gestureFrame) gestureFrame = win.requestAnimationFrame(updateGesture);
    }

    function cancelGesture() {
      finishPan();
      if (!gesture) return;
      if (gestureFrame) win.cancelAnimationFrame(gestureFrame);
      gestureFrame = 0;
      viewport.classList.remove('studio-dragging');
      gesture.targets.forEach(target => { target.entry.wrapper.style.willChange = ''; if (!target.entry.authored) target.entry.wrapper.style.translate = ''; applyLayout(target.entry, target.original); });
      if (gesture.capture.hasPointerCapture(gesture.pointerId)) gesture.capture.releasePointerCapture(gesture.pointerId);
      gesture = null;
    }

    function pointerUp(event) {
      if (panGesture && event.pointerId === panGesture.pointerId) { finishPan(); return; }
      if (!gesture || event.pointerId !== gesture.pointerId) return;
      if (gestureFrame) win.cancelAnimationFrame(gestureFrame);
      updateGesture();
      const completed = gesture;
      gesture = null;
      viewport.classList.remove('studio-dragging');
      if (completed.capture.hasPointerCapture(completed.pointerId)) completed.capture.releasePointerCapture(completed.pointerId);
      if (Math.hypot(completed.dx, completed.dy) < 2) { completed.targets.forEach(target => { target.entry.wrapper.style.willChange = ''; if (!target.entry.authored) target.entry.wrapper.style.translate = ''; applyLayout(target.entry, target.original); }); return; }
      const commands = completed.targets.map(target => {
        Object.assign(target.entry.node.style || (target.entry.node.style = {}), target.patch);
        target.entry.wrapper.style.willChange = '';
        if (!target.entry.authored) target.entry.wrapper.style.translate = '';
        applyLayout(target.entry, Object.assign({}, target.original, target.patch));
        return { type: 'node.update', page_id: currentPageId, node_id: target.entry.node.id, patch: { style: target.patch } };
      });
      emit('studio-commit', { commands, label: completed.handle ? 'Resize elements' : 'Move elements' });
    }

    function finishTextEdit(cancel) {
      if (!textEdit) return;
      const active = textEdit; textEdit = null;
      const element = active.entry.visual;
      const text = element.innerText == null ? element.textContent : element.innerText;
      element.removeAttribute('contenteditable');
      element.style.userSelect = active.userSelect;
      element.removeEventListener('blur', active.blur);
      if (cancel) { element.textContent = active.original; return; }
      if (text === active.original) return;
      active.entry.node.props = Object.assign({}, active.entry.node.props, { text });
      emit('studio-commit', { label: 'Edit text', commands: [{ type: 'node.update', page_id: currentPageId, node_id: active.entry.node.id, patch: { props: { text } } }] });
    }

    function doubleClick(event) {
      if (mode !== 'edit' || tool === 'hand' || spaceDown) return;
      const wrapper = event.target.closest('[data-studio-select-id]');
      const entry = wrapper && editable.get(wrapper.dataset.studioSelectId);
      if (!entry || isLocked(entry) || (entry.node.children || []).length || !(entry.node.type === 'text' || entry.node.type === 'button' || entry.authored && entry.node.props && entry.node.props.text != null)) return;
      cancelGesture(); finishTextEdit(false); select([entry.node.id], true);
      const el = entry.visual;
      const original = entry.node.props && entry.node.props.text || '';
      const blur = () => finishTextEdit(false);
      textEdit = { entry, original, userSelect: el.style.userSelect, blur };
      el.setAttribute('contenteditable', 'plaintext-only'); el.style.userSelect = 'text'; el.addEventListener('blur', blur); el.focus();
      const range = doc.createRange(); range.selectNodeContents(el);
      const selection = win.getSelection(); selection.removeAllRanges(); selection.addRange(range);
      event.preventDefault();
    }

    function sourceModule(source, path, registry, active, resources) {
      const chain = active || new Set();
      const cache = resources.cache;
      const key = path + '\0' + source;
      if (cache.has(key)) return cache.get(key);
      if (chain.has(path)) throw new Error('Circular local script dependency: ' + path);
      const next = new Set([...chain, path]);
      const resolve = specifier => {
        const resolved = resourceUrl(specifier, resourceUrl(path, base));
        const record = registry.get(specifier) || registry.get(resolved);
        if (record) return sourceModule(record.source, record.path, registry, next, resources);
        if (/^[./]/.test(specifier)) {
          if (resolved.startsWith('file:')) throw new Error('Export must include script dependency: ' + specifier);
          return resolved;
        }
        return specifier;
      };
      // Literal imports are resolved relative to the module's project path, never a Blob URL.
      const rewritten = source.replace(/(\b(?:import|export)\s+(?:[^'";]*?\s+from\s*)?)(['"])([^'"\n]+)\2/g, (all, before, quote, specifier) => before + quote + resolve(specifier) + quote)
        .replace(/(\bimport\s*\(\s*)(['"])([^'"\n]+)\2/g, (all, before, quote, specifier) => before + quote + resolve(specifier) + quote);
      const blob = new win.Blob([rewritten + '\n//# sourceURL=studio-script/' + encodeURIComponent(path) + '\n'], { type: 'text/javascript' });
      const url = win.URL.createObjectURL(blob);
      urls.push(url); resources.urls.push(url); cache.set(key, url); return url;
    }

    function startPreview(entries) {
      const token = generation;
      let groupDisposed = false;
      const groupCleanup = [];
      const resources = { cache: new Map(), urls: [] };
      const stopGroup = () => {
        if (groupDisposed) return;
        groupDisposed = true;
        cleanup = cleanup.filter(fn => fn !== stopGroup);
        groupCleanup.splice(0).reverse().forEach(fn => { try { fn(); } catch (error) { report(error); } });
      };
      cleanup.push(stopGroup);
      function nativePresetFrames(entry, frames) {
        if (!entry.authored) return frames;
        const computed = win.getComputedStyle(entry.visual);
        const tokens = value => value.match(/(?:\([^)]*\)|[^\s])+/g) || [];
        const translate = computed.translate === 'none' ? ['0px', '0px'] : tokens(computed.translate);
        const scale = computed.scale === 'none' ? [1, 1] : tokens(computed.scale).map(Number);
        const rotation = computed.rotate === 'none' ? '0deg' : computed.rotate;
        const length = value => /^-?[\d.]+$/.test(value) ? value + 'px' : value;
        return frames.map(frame => {
          const result = Object.assign({}, frame);
          if (frame.translate) {
            const delta = tokens(frame.translate);
            result.translate = 'calc(' + length(translate[0] || '0px') + ' + ' + length(delta[0] || '0px') + ') calc(' + length(translate[1] || '0px') + ' + ' + length(delta[1] || '0px') + ')' + (translate[2] ? ' ' + translate[2] : '');
          }
          if (frame.scale) {
            const factor = tokens(frame.scale).map(Number);
            result.scale = finite(scale[0], 1) * factor[0] + ' ' + finite(scale[1], finite(scale[0], 1)) * (factor[1] == null ? factor[0] : factor[1]) + (scale[2] == null ? '' : ' ' + scale[2]);
          }
          if (frame.rotate) {
            if (/^-?[\d.]+(?:deg|rad|grad|turn)$/.test(rotation)) result.rotate = 'calc(' + rotation + ' + ' + frame.rotate + ')';
            else { delete result.rotate; result.transform = (computed.transform === 'none' ? '' : computed.transform + ' ') + 'rotate(' + frame.rotate + ')'; }
          }
          if (frame.opacity != null) result.opacity = finite(Number(computed.opacity), 1) * Number(frame.opacity);
          return result;
        });
      }
      const registry = moduleRegistry(model, base);
      const sharedEvents = new win.EventTarget();
      const frameCallbacks = new Set();
      let frameId = 0;
      const tick = time => {
        if (disposed || groupDisposed || token !== generation) return;
        frameCallbacks.forEach(item => { try { item.fn(time); } catch (error) { report(error, item.nodeId); } });
        frameId = frameCallbacks.size ? win.requestAnimationFrame(tick) : 0;
      };
      groupCleanup.push(() => {
        if (frameId) win.cancelAnimationFrame(frameId);
        frameCallbacks.clear(); resources.cache.clear();
        resources.urls.forEach(url => win.URL.revokeObjectURL(url));
        const old = new Set(resources.urls); urls = urls.filter(url => !old.has(url));
        resources.urls = [];
      });
      function context(entry) {
        const owned = [];
        const guard = fn => (...args) => { if (disposed || groupDisposed || token !== generation) return; try { return fn(...args); } catch (error) { report(error, entry.node.id); } };
        const own = (fn, kind) => {
          let active = true;
          if (kind) tracked[kind] += 1;
          const stop = () => { if (!active) return; active = false; if (kind) tracked[kind] -= 1; fn(); };
          if (disposed || groupDisposed || token !== generation) stop(); else owned.push(stop);
          return stop;
        };
        groupCleanup.push(() => owned.splice(0).reverse().forEach(fn => { try { fn(); } catch (error) { report(error, entry.node.id); } }));
        const on = (target, type, listener, opts) => {
          if (typeof target === 'string') { opts = listener; listener = type; type = target; target = entry.visual; }
          const wrapped = guard(listener); target.addEventListener(type, wrapped, opts); return own(() => target.removeEventListener(type, wrapped, opts), 'listeners');
        };
        const animate = (frames, opts, element) => {
          const animation = (element || entry.visual).animate(frames, opts);
          own(() => animation.cancel(), 'animations'); return animation;
        };
        const stateKey = entry.wrapper.id;
        if (!runtimeState[stateKey]) runtimeState[stateKey] = {};
        const logger = {};
        ['log', 'info', 'warn', 'error', 'debug'].forEach(level => {
          logger[level] = (...args) => {
            emit('studio-console', { nodeId: entry.node.id, level, args: args.map(value => { try { return typeof value === 'string' ? value : JSON.stringify(value); } catch (_) { return String(value); } }) });
          };
        });
        return {
          el: entry.visual, root: stage, nodeId: entry.node.id, pageId: currentPageId,
          props: Object.assign({}, Object.fromEntries(Object.entries(entry.node.script && entry.node.script.parameters || {}).map(([name, descriptor]) => [name, descriptor && descriptor.default])), entry.node.props && entry.node.props.parameters, entry.node.script && entry.node.script.props),
          state: runtimeState[stateKey], console: logger,
          find: id => { const found = entry.scope.refs.get(id); return found ? found.visual : null; },
          on, animate,
          onEvent: (name, fn) => on(sharedEvents, name, event => fn(event.detail)),
          emit: (name, detail) => sharedEvents.dispatchEvent(new win.CustomEvent(name, { detail })),
          setTimeout: (fn, delay) => { let stop; const id = win.setTimeout(guard(() => { stop(); fn(); }), delay); stop = own(() => win.clearTimeout(id), 'timers'); return id; },
          setInterval: (fn, delay) => { const id = win.setInterval(guard(() => { if (!doc.hidden) fn(); }), Math.max(1, delay)); own(() => win.clearInterval(id), 'timers'); return id; },
          onFrame: fn => { const item = { fn, nodeId: entry.node.id }; frameCallbacks.add(item); if (!frameId) frameId = win.requestAnimationFrame(tick); return own(() => frameCallbacks.delete(item), 'frames'); },
          assets: { resolve: asset },
          navigate: (pageId, context) => navigate(pageId, context),
          open: pageId => openOverlay(pageId),
          close: () => closeOverlay(),
          parameters: entry.node.script && entry.node.script.parameters || {},
          signal: (() => { const abort = new win.AbortController(); own(() => abort.abort()); return abort.signal; })()
        };
      }
      entries.forEach(entry => {
        if (previewNodeId && entry.ownerId !== previewNodeId && !entry.wrapper.closest('[data-studio-select-id="' + win.CSS.escape(previewNodeId) + '"]')) return;
        if (entry.node.hidden) return;
        const props = entry.node.props || {};
        const binding = entry.node.script || {};
        const moduleId = binding.moduleId || props.scriptId;
        const reusable = moduleId && model.scripts && model.scripts[moduleId];
        const script = typeof reusable === 'string' ? Object.assign({ source: reusable }, binding) : Object.assign({}, reusable, binding);
        if (script.source) entry.node.script = script;
        const ctx = context(entry);
        const animation = entry.node.animation;
        if (animation) {
          const definition = presetFrames(animation.preset);
          if (definition) {
            const frames = nativePresetFrames(entry, definition);
            const play = () => ctx.animate(frames, animationOptions(animation));
            if (animation.trigger === 'click') ctx.on('click', play);
            else if (animation.trigger === 'hover') ctx.on('mouseenter', play);
            else play();
          }
        }
        const action = props.action && typeof props.action === 'object' ? props.action : { type: props.action, pageId: props.pageId };
        const targetPage = props.navigateTo || action.pageId || props.pageId;
        if (action.type === 'close') ctx.on('click', () => ctx.close());
        if (targetPage && entry.node.type !== 'page' && (props.navigateTo || action.type === 'navigate' || action.type === 'open')) ctx.on('click', () => {
          const context = Object.assign({}, action.contextDefaults, navigationContext, action.context);
          const destination = action.contextTarget && context[action.contextTarget] || targetPage;
          if (action.type === 'open') ctx.open(destination);
          else ctx.navigate(destination, context);
        });
        if (!script || typeof script.source !== 'string' || !script.source.trim()) return;
        let source = script.source;
        if (!/\bexport\s+(?:default\s+|(?:async\s+)?function\s+mount|(?:const|let|var)\s+mount|\{[^}]*\bmount\b)/.test(source)) source += '\nexport { mount };\n';
        let lineOffset = 0;
        if (!/\b(?:const|let|var|function|class|import)\s+console\b/.test(source)) {
          const loggerId = 'logger_' + (++loggerSequence);
          moduleLoggers.set(loggerId, ctx.console);
          groupCleanup.push(() => moduleLoggers.delete(loggerId));
          source = 'const console=globalThis.LeafLoomStudio.loggerFor("' + loggerId + '");\n' + source;
          lineOffset = 1;
        }
        const path = script.path || 'Design/Scripts/' + entry.node.id + '.js';
        try {
          const url = sourceModule(source, path, registry, null, resources);
          import(url).then(module => {
            if (disposed || groupDisposed || token !== generation) return;
            const start = module.mount || module.default;
            if (typeof start !== 'function') throw new Error('Script must export mount(ctx).');
            return Promise.resolve(start(ctx)).then(stop => {
              if (typeof stop !== 'function') return;
              if (disposed || groupDisposed || token !== generation) { try { stop(); } catch (_) {} }
              else groupCleanup.push(() => { try { stop(); } catch (error) { report(error, entry.node.id); } });
            });
          }).catch(error => { if (!disposed && !groupDisposed && token === generation) report(error, entry.node.id, lineOffset); });
        } catch (error) { report(error, entry.node.id, lineOffset); }
      });
      return stopGroup;
    }

    function update(nextDocument, nextOptions) {
      const next = nextOptions || {};
      const nextPageId = next.pageId || currentPageId;
      const nextMode = next.mode || mode;
      const oldPage = model.pages.find(page => page.id === currentPageId);
      const newPage = nextDocument.pages.find(page => page.id === nextPageId);
      const equal = (left, right) => JSON.stringify(left) === JSON.stringify(right);
      const metadata = page => { const value = Object.assign({}, page); delete value.nodes; return value; };
      let reusable = model.id === nextDocument.id && mode === 'edit' && nextMode === 'edit' && currentPageId === nextPageId && oldPage && newPage && equal(metadata(oldPage), metadata(newPage));
      if (reusable) reusable = ['assets', 'components', 'styles', 'scripts'].every(key => equal(model[key], nextDocument[key]));
      const changes = [];
      function inspect(before, after) {
        if (!Array.isArray(before) || !Array.isArray(after) || before.length !== after.length) return false;
        return before.every((oldNode, index) => {
          const newNode = after[index], nativeText = authoredTexts.get(oldNode.id), entry = editable.get(oldNode.id);
          if (nativeText) {
            if (oldNode.id !== newNode.id || oldNode.type !== newNode.type || !newNode.props?.authored || newNode.props.textNode !== true || (newNode.children || []).length) return false;
            changes.push({ entry: nativeText, oldNode, newNode, nativeText: true });
            return true;
          }
          if (!entry || oldNode.id !== newNode.id || oldNode.type !== newNode.type) return false;
          const oldProps = oldNode.props || {}, newProps = newNode.props || {};
          // Authored parents render their own text before child elements. Rebuild
          // that mixed content instead of leaving stale text or replacing children.
          if (entry.authored && (newNode.children || []).length && oldProps.text !== newProps.text) return false;
          if (!equal(oldProps, newProps) && (['instance', 'page', 'html', 'svg'].includes(oldNode.type) || !equal(oldProps.attributes, newProps.attributes) || oldProps.styleId !== newProps.styleId || oldProps.html !== newProps.html)) return false;
          if (!equal(oldNode.style, newNode.style) || !equal(oldProps, newProps) || oldNode.hidden !== newNode.hidden) changes.push({ entry, oldNode, newNode });
          return inspect(oldNode.children || [], newNode.children || []);
        });
      }
      if (reusable) reusable = inspect(oldPage.nodes || [], newPage.nodes || []);
      cancelGesture();
      if (nextDocument.id !== model.id) cameras.clear();
      model = clone(nextDocument); currentPageId = nextPageId; mode = nextMode;
      if (mode === 'edit') navigationContext = {};
      previewNodeId = next.previewNodeId || null;
      if (!reusable) { redraw(); if (next.selectedIds) select(next.selectedIds, false); return false; }
      changes.forEach(({ entry, oldNode, newNode, nativeText }) => {
        const props = newNode.props || {};
        if (nativeText) { entry.node = newNode; entry.visual.textContent = newNode.hidden ? '' : String(props.text == null ? '' : props.text); return; }
        const oldStyle = resolvedStyle(oldNode), newStyle = resolvedStyle(newNode);
        Object.keys(oldStyle).forEach(key => { if (!(key in newStyle) && !layoutKeys.has(key)) entry.visual.style.removeProperty(key.replace(/[A-Z]/g, match => '-' + match.toLowerCase())); });
        entry.node = newNode;
        applyLayout(entry, newStyle); contentStyle(entry.visual, newStyle);
        if (entry.authored && newNode.hidden) entry.wrapper.style.display = 'none';
        else entry.wrapper.hidden = !!newNode.hidden;
        if ((!textEdit || textEdit.entry !== entry) && (['text', 'button'].includes(newNode.type) || entry.authored && !(newNode.children || []).length && props.text != null)) entry.visual.textContent = String(props.text || '');
        if (newNode.type === 'image') {
          let image = entry.authored ? entry.visual : entry.visual.querySelector('img');
          if (!image && !entry.authored) { image = doc.createElement('img'); entry.visual.replaceChildren(image); entry.visual.classList.remove('studio-missing'); }
          if (image) { image.src = props.assetId ? asset(props.assetId) : resourceUrl(props.src, base); image.style.objectFit = props.fit || props.objectFit || newStyle.objectFit || 'contain'; image.style.objectPosition = props.objectPosition || 'center'; }
        }
      });
      function relink(nodes) { (nodes || []).forEach(node => { const entry = editable.get(node.id); if (entry) entry.node = node; relink(node.children); }); }
      relink(model.pages.find(page => page.id === currentPageId).nodes);
      select(next.selectedIds || [...selected], false);
      return true;
    }

    function navigate(pageId, context) {
      let page = model.pages.find(item => item.id === pageId);
      if (!page) { report('Page not found: ' + pageId); return; }
      if (context && typeof context === 'object') navigationContext = Object.assign({}, navigationContext, context);
      const alternate = page.migration && Array.isArray(page.migration.contextVariants) && page.migration.contextVariants.find(variant => Object.entries(variant.context || {}).every(([key, value]) => navigationContext[key] === value));
      if (alternate) { const target = model.pages.find(item => item.id === alternate.pageId); if (target) { page = target; pageId = target.id; } }
      if (page.loaded === false) { emit('studio-load-page', { pageId, action: 'navigate' }); return; }
      currentPageId = pageId; previewNodeId = null; redraw();
      emit('studio-navigate', { pageId });
    }

    function openOverlay(pageId) {
      const page = model.pages.find(item => item.id === pageId);
      if (!page) { report('Page not found: ' + pageId); return null; }
      if (page.loaded === false) { emit('studio-load-page', { pageId, action: 'open' }); return null; }
      closeOverlay();
      const overlay = doc.createElement('div'); overlay.className = 'studio-overlay';
      const board = doc.createElement('div'); board.className = 'studio-overlay-stage';
      board.style.width = finite(page.width, 640) + 'px'; board.style.height = finite(page.height, 480) + 'px';
      overlay.appendChild(board); stage.appendChild(overlay);
      overlayEntries = [];
      const scope = makeScope('overlay_' + page.id, page.nodes, page.authoredContext);
      pageStyles(page, board, scope);
      renderNodes(page.nodes, pageRoot(page, board, scope), scope, new Set(['page:' + page.id]), '__overlay', false, overlayEntries);
      overlayStop = startPreview(overlayEntries);
      return overlay;
    }

    function closeOverlay() {
      if (overlayStop) overlayStop();
      overlayStop = null;
      stage.querySelectorAll('.studio-overlay').forEach(el => { el.querySelectorAll('iframe').forEach(frame => htmlFrames.delete(frame.contentWindow)); el.remove(); }); overlayEntries = [];
    }

    const onVisibility = () => {
      const running = renderedEntries.concat(overlayEntries).flatMap(entry => entry.visual.getAnimations ? entry.visual.getAnimations() : []);
      running.forEach(animation => { if (doc.hidden) animation.pause(); else animation.play(); });
    };
    const htmlMessage = event => {
      const nodeId = htmlFrames.get(event.source);
      if (!nodeId || !event.data || mode !== 'preview') return;
      if (event.data.type === 'studio-custom-error') emit('studio-error', { nodeId, message: String(event.data.message), line: event.data.line });
      else if (event.data.type === 'studio-custom-console') emit('studio-console', { nodeId, level: event.data.level, args: event.data.args });
    };
    const hoverOver = event => {
      if (mode !== 'edit' || gesture || panGesture || tool === 'hand' || spaceDown) return;
      const next = event.target.closest('[data-studio-select-id]');
      if (next === hovered) return;
      if (hovered) hovered.classList.remove('studio-hovered');
      hovered = next;
      if (hovered) hovered.classList.add('studio-hovered');
    };
    const hoverOut = event => {
      if (gesture || !hovered || viewport.contains(event.relatedTarget)) return;
      hovered.classList.remove('studio-hovered'); hovered = null;
    };
    const keyDown = event => {
      if (textEdit && (event.key === 'Escape' || event.key === 'Enter' && !event.shiftKey)) { event.preventDefault(); finishTextEdit(event.key === 'Escape'); viewport.focus({ preventScroll: true }); return; }
      if (event.key === 'Escape') { cancelGesture(); if (mode === 'edit') select([], true); else closeOverlay(); return; }
      if (mode !== 'edit' || event.target.isContentEditable || event.target.closest('input, textarea')) return;
      const key = event.key.toLowerCase(), modifier = event.metaKey || event.ctrlKey;
      if (key === ' ' && !modifier) { event.preventDefault(); spaceDown = true; syncTool(); return; }
      if (!modifier && !event.altKey && ['v', 'h'].includes(key)) { event.preventDefault(); setTool(key === 'h' ? 'hand' : 'select'); return; }
      if (event.shiftKey && event.code === 'Digit1') { event.preventDefault(); fit(); return; }
      if (event.shiftKey && event.code === 'Digit2') { event.preventDefault(); fitSelection(); return; }
      if (modifier && ['+', '=', '-', '0'].includes(key)) { event.preventDefault(); setZoom(key === '0' ? 1 : zoom * (key === '-' ? 1 / 1.2 : 1.2)); return; }
      let action = null;
      if (modifier && key === 'z') action = event.shiftKey ? 'redo' : 'undo';
      else if (modifier && key === 'y') action = 'redo';
      else if (modifier && key === 'd') action = 'duplicate';
      else if (key === 'delete' || key === 'backspace') action = 'delete';
      if (action) { event.preventDefault(); emit('studio-shortcut', { action }); }
    };
    const keyUp = event => { if (event.key === ' ') { spaceDown = false; syncTool(); } };
    const blur = () => { spaceDown = false; cancelGesture(); syncTool(); };
    viewport.addEventListener('wheel', wheel, { passive: false });
    viewport.addEventListener('pointerdown', pointerDown);
    viewport.addEventListener('pointermove', pointerMove);
    viewport.addEventListener('pointerover', hoverOver);
    viewport.addEventListener('pointerout', hoverOut);
    viewport.addEventListener('pointerup', pointerUp);
    viewport.addEventListener('pointercancel', cancelGesture);
    viewport.addEventListener('dblclick', doubleClick);
    viewport.addEventListener('lostpointercapture', cancelGesture);
    viewport.addEventListener('keydown', keyDown);
    win.addEventListener('keyup', keyUp);
    win.addEventListener('blur', blur);
    doc.addEventListener('visibilitychange', onVisibility);
    win.addEventListener('message', htmlMessage);
    const resize = new win.ResizeObserver(restoreCamera); resize.observe(viewport);
    redraw();
    return {
      version: VERSION,
      update,
      select: ids => select(ids, false), fit, fitSelection, setZoom, setTool,
      get camera() { return Object.assign({}, camera(), { tool }); },
      setMode: (next, nodeId) => { mode = next === 'preview' ? 'preview' : 'edit'; if (mode === 'edit') navigationContext = {}; previewNodeId = nodeId || null; redraw(); },
      navigate, openOverlay,
      get document() { return clone(model); },
      get debugStats() {
        const work = [...gestureWork].sort((a, b) => a - b);
        return Object.assign({ renderedNodes: renderedEntries.length, objectUrls: urls.length, previewGroups: cleanup.length, handles: stage.querySelectorAll('.studio-handle').length, gestureWorkSamples: work.length, gestureWorkP95Ms: work.length ? work[Math.ceil(work.length * .95) - 1] : 0, gestureWorkMaxMs: work.length ? work[work.length - 1] : 0 }, tracked);
      },
      dispose: () => {
        if (disposed) return;
        finishTextEdit(true); cancelGesture(); disposed = true; releasePreview(); resize.disconnect();
        doc.removeEventListener('visibilitychange', onVisibility);
        win.removeEventListener('message', htmlMessage);
        win.removeEventListener('keyup', keyUp); win.removeEventListener('blur', blur); htmlFrames.clear();
        root.replaceChildren();
      }
    };
  }

  function bridge(root) {
    const params = new URLSearchParams(global.location.search);
    const session = params.get('session');
    const rawOrigin = params.get('parentOrigin');
    let parentOrigin = null;
    try { const parsed = new URL(rawOrigin); if (['http:', 'https:'].includes(parsed.protocol) && parsed.origin === rawOrigin) parentOrigin = parsed.origin; } catch (_) {}
    if (!session || !parentOrigin || global.parent === global) return null;
    let instance = null;
    const send = payload => global.parent.postMessage(Object.assign({}, payload, { session }), parentOrigin);
    const listener = event => {
      if (event.source !== global.parent || event.origin !== parentOrigin || !event.data || event.data.session !== session) return;
      const data = event.data;
      try {
        if (data.type === 'studio-init') {
          if (instance) instance.update(data.document, { pageId: data.pageId, mode: data.mode || 'edit', selectedIds: data.selectedIds, previewNodeId: data.previewNodeId });
          else instance = mount(root, data.document, { pageId: data.pageId, mode: data.mode || 'edit', assetBase: data.assetBase || global.location.origin + '/', selectedIds: data.selectedIds, previewNodeId: data.previewNodeId, onMessage: send });
          send({ type: 'studio-rendered', pageId: data.pageId });
        } else if (instance && data.type === 'studio-select') instance.select(data.ids);
        else if (instance && data.type === 'studio-mode') instance.setMode(data.mode, data.previewNodeId);
        else if (instance && data.type === 'studio-fit') data.selection ? instance.fitSelection() : instance.fit();
        else if (instance && data.type === 'studio-zoom') instance.setZoom(data.zoom);
        else if (instance && data.type === 'studio-tool') instance.setTool(data.tool);
        else if (instance && data.type === 'studio-navigate') instance.navigate(data.pageId);
        else if (instance && data.type === 'studio-open') instance.openOverlay(data.pageId);
      } catch (error) { send({ type: 'studio-error', message: error.message }); }
    };
    global.addEventListener('message', listener);
    send({ type: 'studio-ready', version: VERSION });
    return { dispose: () => { global.removeEventListener('message', listener); if (instance) instance.dispose(); } };
  }

  global.LeafLoomStudio = Object.freeze({ version: VERSION, mount, bridge, resourceUrl, presetFrames, animationOptions, loggerFor: id => moduleLoggers.get(id) || global.console });
  if (global.document) {
    const boot = () => {
      const root = global.document.getElementById('studio-root');
      if (!root) return;
      if (global.STUDIO_DOCUMENT) global.LeafLoomStudioInstance = mount(root, global.STUDIO_DOCUMENT, Object.assign({ assetBase: './', mode: 'preview' }, global.STUDIO_OPTIONS || {}));
      else global.LeafLoomStudioBridge = bridge(root);
    };
    if (global.document.readyState === 'loading') global.document.addEventListener('DOMContentLoaded', boot, { once: true }); else boot();
  }
})(typeof window !== 'undefined' ? window : globalThis);
