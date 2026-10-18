/* Game Design Layers 1.1.0 (LeafLoom Design Studio Edition) — ordinary scripts, offline & HTTP MCP compatible. */
(function (global) {
  'use strict';

  var MESSAGE_TYPE = 'game-design-review';
  var COMMANDS = [
    'sync', 'select', 'hidden', 'locked', 'reset',
    'transform', 'reset-layer', 'align', 'z-order',
    'undo', 'redo', 'export-layer', 'import-transforms'
  ];
  var TYPE_NAMES = {
    group: '组件组', background: '背景', decoration: '装饰', image: '图片',
    text: '文字', button: '按钮', icon: '图标', board: '棋盘', cell: '格垫',
    avatar: '头像', character: '落位伙伴', svg: 'SVG', component: '组件', shape: '形状'
  };

  function checkOptions(options) {
    if (!options || typeof options.boardId !== 'string' || !options.boardId ||
        typeof options.session !== 'string' || !options.session) {
      throw new Error('图层审阅需要非空 boardId 和 session。');
    }
  }

  function isElement(element) {
    return element && element.nodeType === 1 && typeof element.getBoundingClientRect === 'function';
  }

  function round(value) { return Math.round((Number(value) || 0) * 100) / 100; }
  function string(value) { return value == null ? '' : String(value); }
  function send(target, payload) { if (target && typeof target.postMessage === 'function') target.postMessage(payload, '*'); }
  function matches(data, options) {
    return data && typeof data === 'object' && data.type === MESSAGE_TYPE &&
      data.boardId === options.boardId && data.session === options.session;
  }

  function sameOrigin(event, win) {
    return event.origin === win.location.origin || (win.location.protocol === 'file:' && event.origin === 'null');
  }

  function defaultTransform() {
    return {
      tx: 0, ty: 0, scaleX: 1, scaleY: 1, rotate: 0,
      flipX: false, flipY: false, opacity: null, zIndex: null, text: null
    };
  }

  function isTransformed(t) {
    if (!t) return false;
    return Boolean(
      round(t.tx) !== 0 || round(t.ty) !== 0 ||
      round(t.scaleX - 1) !== 0 || round(t.scaleY - 1) !== 0 ||
      round(t.rotate) !== 0 || t.flipX || t.flipY ||
      (t.opacity != null && t.opacity !== '') ||
      (t.zIndex != null && t.zIndex !== '') ||
      (t.text != null && t.text !== '')
    );
  }

  function normalizeTransform(raw, current) {
    var base = Object.assign(defaultTransform(), current || {});
    if (!raw || typeof raw !== 'object') return base;
    if (typeof raw.tx === 'number' && Number.isFinite(raw.tx)) base.tx = round(raw.tx);
    if (typeof raw.ty === 'number' && Number.isFinite(raw.ty)) base.ty = round(raw.ty);
    if (typeof raw.scaleX === 'number' && Number.isFinite(raw.scaleX)) base.scaleX = Math.max(0.05, Math.min(20, round(raw.scaleX)));
    if (typeof raw.scaleY === 'number' && Number.isFinite(raw.scaleY)) base.scaleY = Math.max(0.05, Math.min(20, round(raw.scaleY)));
    if (typeof raw.rotate === 'number' && Number.isFinite(raw.rotate)) {
      var deg = ((raw.rotate + 180) % 360 + 360) % 360 - 180;
      base.rotate = round(deg);
    }
    if (typeof raw.flipX === 'boolean') base.flipX = raw.flipX;
    if (typeof raw.flipY === 'boolean') base.flipY = raw.flipY;
    if (raw.opacity === null || raw.opacity === '') base.opacity = null;
    else if (typeof raw.opacity === 'number' && Number.isFinite(raw.opacity)) base.opacity = Math.max(0, Math.min(1, round(raw.opacity)));
    if (raw.zIndex === null || raw.zIndex === '') base.zIndex = null;
    else if (typeof raw.zIndex === 'number' && Number.isFinite(raw.zIndex)) base.zIndex = Math.round(raw.zIndex);
    else if (typeof raw.zIndex === 'string' && /^-?\d+$/.test(raw.zIndex.trim())) base.zIndex = Number.parseInt(raw.zIndex.trim(), 10);
    if (raw.text === null) base.text = null;
    else if (typeof raw.text === 'string') base.text = raw.text.slice(0, 600);
    return base;
  }

  function applySavedTransforms(root, layers, transformsMap) {
    if (!isElement(root) || !Array.isArray(layers) || !transformsMap || typeof transformsMap !== 'object') return;
    var doc = root.ownerDocument;
    var win = doc.defaultView;
    layers.forEach(function (layer) {
      if (!layer || !layer.id || !isElement(layer.element)) return;
      var entry = transformsMap[layer.id];
      if (!entry || typeof entry !== 'object') return;
      var t = normalizeTransform(entry);
      if (!isTransformed(t)) return;
      var el = layer.element;
      var isSvgChild = el.namespaceURI === 'http://www.w3.org/2000/svg' && el.localName !== 'svg';
      var ratioX = 1, ratioY = 1;
      if (isSvgChild && el.ownerSVGElement) {
        var svg = el.ownerSVGElement;
        var svgRect = svg.getBoundingClientRect();
        var vb = svg.viewBox && svg.viewBox.baseVal;
        if (vb && vb.width && svgRect.width) ratioX = vb.width / svgRect.width;
        if (vb && vb.height && svgRect.height) ratioY = vb.height / svgRect.height;
        el.style.transformBox = 'fill-box';
        el.style.transformOrigin = 'center';
      }
      var sx = round(t.scaleX * (t.flipX ? -1 : 1));
      var sy = round(t.scaleY * (t.flipY ? -1 : 1));
      var delta = 'translate(' + round(t.tx * ratioX) + 'px, ' + round(t.ty * ratioY) + 'px) rotate(' + round(t.rotate) + 'deg) scale(' + sx + ', ' + sy + ')';
      var computed = win.getComputedStyle(el).transform;
      el.style.transform = (computed && computed !== 'none') ? (delta + ' ' + computed) : delta;
      if (t.opacity != null) el.style.opacity = String(t.opacity);
      if (t.zIndex != null && !isSvgChild) {
        if (win.getComputedStyle(el).position === 'static') el.style.position = 'relative';
        el.style.zIndex = String(t.zIndex);
      }
      if (t.text != null && layer.type === 'text') el.textContent = t.text;
    });
  }

  function mountCanvas(options) {
    checkOptions(options);
    var root = options.root;
    if (!isElement(root)) throw new Error('图层审阅 root 必须是真实画板元素。');
    var doc = root.ownerDocument;
    var win = doc.defaultView;
    var host = options.host || win.parent;
    var layers = (options.layers || []).map(function (layer) {
      if (!layer || typeof layer.id !== 'string' || !layer.id || !isElement(layer.element)) {
        throw new Error('每个图层需要稳定 id 和真实 element。');
      }
      if (layer.element !== root && !root.contains(layer.element)) {
        throw new Error('图层元素不属于画板：' + layer.id);
      }
      return {
        id: layer.id, parentId: layer.parentId || null, name: string(layer.name || layer.id),
        type: string(layer.type || 'component'), element: layer.element,
        assetId: string(layer.assetId), registryId: string(layer.registryId),
        sourceRef: string(layer.sourceRef), composite: Boolean(layer.composite), paintOnly: Boolean(layer.paintOnly),
        downloadUrl: string(layer.downloadUrl), assetSha256: string(layer.assetSha256), vectorPath: string(layer.vectorPath),
        hidden: false, locked: false, children: [], depth: 0,
        transform: defaultTransform(), baseBounds: null
      };
    });
    var byId = new Map();
    layers.forEach(function (layer) {
      if (byId.has(layer.id)) throw new Error('重复图层 id：' + layer.id);
      byId.set(layer.id, layer);
    });
    layers.forEach(function (layer) {
      var chain = new Set([layer.id]);
      var parent = layer.parentId && byId.get(layer.parentId);
      if (layer.parentId && !parent) throw new Error('找不到父图层：' + layer.parentId);
      if (parent) parent.children.push(layer);
      while (parent) {
        if (chain.has(parent.id)) throw new Error('图层树包含循环：' + layer.id);
        chain.add(parent.id);
        layer.depth += 1;
        parent = parent.parentId && byId.get(parent.parentId);
      }
    });
    layers.forEach(function (layer) {
      if (layer.composite && layer.children.length) throw new Error('整组图像不能登记伪造的内部图层：' + layer.id);
    });

    var originalStyles = new Map();
    layers.forEach(function (layer) {
      var element = layer.element;
      if (!originalStyles.has(element)) {
        var computed = win.getComputedStyle(element);
        originalStyles.set(element, {
          visibilityValue: element.style.getPropertyValue('visibility'),
          visibilityPriority: element.style.getPropertyPriority('visibility'),
          paintHidden: element.classList.contains('gdl-paint-hidden'),
          transformValue: element.style.getPropertyValue('transform'),
          transformPriority: element.style.getPropertyPriority('transform'),
          transformOriginValue: element.style.getPropertyValue('transform-origin'),
          transformBoxValue: element.style.getPropertyValue('transform-box'),
          opacityValue: element.style.getPropertyValue('opacity'),
          zIndexValue: element.style.getPropertyValue('z-index'),
          positionValue: element.style.getPropertyValue('position'),
          computedTransform: computed.transform !== 'none' ? computed.transform : '',
          computedPosition: computed.position,
          textContent: layer.type === 'text' ? element.textContent : null
        });
      }
    });

    var destroyed = false;
    var selectedId = null;
    var focusId = null;
    var scheduled = 0;
    var lastState = '';
    var history = [];
    var future = [];
    var dragState = null;
    var suppressClickUntil = 0;

    var overlay = doc.createElement('div');
    overlay.className = 'gdl-selection';
    overlay.setAttribute('aria-hidden', 'true');
    overlay.style.cssText = 'display:none;position:fixed;pointer-events:none;box-sizing:border-box;z-index:2147483647;border:2px solid #4c7c60;';
    var label = doc.createElement('span');
    label.className = 'gdl-selection-label';
    label.style.cssText = 'position:absolute;left:-2px;bottom:100%;padding:3px 7px;background:#4c7c60;color:white;font:12px/1.4 sans-serif;white-space:nowrap;max-width:300px;overflow:hidden;text-overflow:ellipsis;';
    label.style.fontFamily = win.getComputedStyle(root).fontFamily;
    overlay.appendChild(label);

    var hud = doc.createElement('span');
    hud.className = 'gdl-hud';
    hud.hidden = true;
    overlay.appendChild(hud);

    var handleNames = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w', 'rotate'];
    var handleEls = {};
    handleNames.forEach(function (name) {
      var h = doc.createElement('div');
      h.className = 'gdl-handle gdl-handle-' + name;
      h.dataset.gdlHandle = name;
      overlay.appendChild(h);
      handleEls[name] = h;
    });

    var guideX = doc.createElement('div');
    guideX.className = 'gdl-guide gdl-guide-x';
    guideX.hidden = true;
    var guideY = doc.createElement('div');
    guideY.className = 'gdl-guide gdl-guide-y';
    guideY.hidden = true;

    var hostBody = doc.body || doc.documentElement;
    hostBody.appendChild(guideX);
    hostBody.appendChild(guideY);
    hostBody.appendChild(overlay);

    function artboardScale() {
      var rootRect = root.getBoundingClientRect();
      var w = root.offsetWidth || root.clientWidth || rootRect.width || 1;
      var h = root.offsetHeight || root.clientHeight || rootRect.height || 1;
      return {
        rootRect: rootRect,
        width: w,
        height: h,
        scaleX: (rootRect.width / w) || 1,
        scaleY: (rootRect.height / h) || 1
      };
    }

    function hasFlag(layer, flag) {
      var item = layer;
      while (item) {
        if (item[flag]) return true;
        item = item.parentId && byId.get(item.parentId);
      }
      return false;
    }

    function bounds(layer) {
      var rect = layer.element.getBoundingClientRect();
      var result = {left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom};
      if (layer.type === 'group') layer.children.forEach(function (child) {
        var childRect = bounds(child);
        if (!childRect.width || !childRect.height) return;
        result.left = Math.min(result.left, childRect.left);
        result.top = Math.min(result.top, childRect.top);
        result.right = Math.max(result.right, childRect.right);
        result.bottom = Math.max(result.bottom, childRect.bottom);
      });
      result.width = result.right - result.left;
      result.height = result.bottom - result.top;
      return result;
    }

    function artboardCoords(layer) {
      var rect = bounds(layer);
      var ab = artboardScale();
      return {
        x: round((rect.left - ab.rootRect.left) / ab.scaleX),
        y: round((rect.top - ab.rootRect.top) / ab.scaleY),
        width: round(rect.width / ab.scaleX),
        height: round(rect.height / ab.scaleY)
      };
    }

    function ensureBaseBounds() {
      layers.forEach(function (layer) {
        if (!layer.baseBounds && !isTransformed(layer.transform)) {
          var coords = artboardCoords(layer);
          if (coords.width > 0 || coords.height > 0) {
            layer.baseBounds = coords;
          }
        }
      });
    }

    function metadata(layer) {
      return {
        id: layer.id, parentId: layer.parentId, name: layer.name, type: layer.type,
        assetId: layer.assetId, registryId: layer.registryId, sourceRef: layer.sourceRef,
        composite: layer.composite, paintOnly: layer.paintOnly, hasChildren: layer.children.length > 0,
        downloadUrl: layer.downloadUrl, assetSha256: layer.assetSha256, vectorPath: layer.vectorPath,
        hidden: layer.hidden, locked: layer.locked,
        effectiveHidden: hasFlag(layer, 'hidden'), effectiveLocked: hasFlag(layer, 'locked'),
        transformed: isTransformed(layer.transform),
        transform: Object.assign({}, layer.transform)
      };
    }

    function inspect(layer) {
      if (!layer) return null;
      ensureBaseBounds();
      var coords = artboardCoords(layer);
      var base = layer.baseBounds || coords;
      var style = win.getComputedStyle(layer.element);
      var data = metadata(layer);
      data.x = coords.x;
      data.y = coords.y;
      data.width = coords.width;
      data.height = coords.height;
      data.baseX = base.x;
      data.baseY = base.y;
      data.baseWidth = base.width;
      data.baseHeight = base.height;
      data.opacity = style.opacity;
      data.zIndex = style.zIndex;
      data.visibility = style.visibility;
      data.display = style.display;
      data.fontFamily = style.fontFamily;
      data.fontSize = style.fontSize;
      data.fontWeight = style.fontWeight;
      data.lineHeight = style.lineHeight;
      data.color = style.color;
      data.text = layer.type === 'text' ? string(layer.element.textContent).trim().slice(0, 600) : '';
      return data;
    }

    function getTransformsMap() {
      var out = {};
      layers.forEach(function (layer) {
        if (isTransformed(layer.transform)) {
          out[layer.id] = Object.assign({}, layer.transform);
        }
      });
      return out;
    }

    function snapshot() {
      var ab = artboardScale();
      return {
        boardId: options.boardId, session: options.session, selectedId: selectedId,
        boardWidth: ab.width, boardHeight: ab.height,
        canUndo: history.length > 0, canRedo: future.length > 0,
        transforms: getTransformsMap(),
        layers: layers.map(metadata), selected: inspect(byId.get(selectedId))
      };
    }

    function message(action, force) {
      if (destroyed) return;
      var state = snapshot();
      var signature = JSON.stringify(state);
      if (!force && signature === lastState) return;
      lastState = signature;
      send(host, Object.assign({type: MESSAGE_TYPE, action: action}, state));
    }

    function restoreElement(element, original) {
      if (original.visibilityValue) element.style.setProperty('visibility', original.visibilityValue, original.visibilityPriority);
      else element.style.removeProperty('visibility');
      element.classList.toggle('gdl-paint-hidden', original.paintHidden);
      if (original.transformValue) element.style.setProperty('transform', original.transformValue, original.transformPriority);
      else element.style.removeProperty('transform');
      if (original.transformOriginValue) element.style.setProperty('transform-origin', original.transformOriginValue);
      else element.style.removeProperty('transform-origin');
      if (original.transformBoxValue) element.style.setProperty('transform-box', original.transformBoxValue);
      else element.style.removeProperty('transform-box');
      if (original.opacityValue) element.style.setProperty('opacity', original.opacityValue);
      else element.style.removeProperty('opacity');
      if (original.zIndexValue) element.style.setProperty('z-index', original.zIndexValue);
      else element.style.removeProperty('z-index');
      if (original.positionValue) element.style.setProperty('position', original.positionValue);
      else element.style.removeProperty('position');
      if (original.textContent !== null && element.textContent !== original.textContent) {
        element.textContent = original.textContent;
      }
    }

    function applyDomState() {
      ensureBaseBounds();
      originalStyles.forEach(function (original, element) { restoreElement(element, original); });
      layers.forEach(function (layer) {
        if (!hasFlag(layer, 'hidden')) return;
        if (layer.paintOnly) layer.element.classList.add('gdl-paint-hidden');
        else layer.element.style.setProperty('visibility', 'hidden', 'important');
      });

      var elementTransforms = new Map();
      layers.forEach(function (layer) {
        if (!isTransformed(layer.transform)) return;
        var t = layer.transform;
        if (t.text != null && layer.type === 'text') {
          layer.element.textContent = t.text;
        }
        var targets = [layer.element];
        if (layer.type === 'group') {
          layer.children.forEach(function (child) {
            if (!layer.element.contains(child.element) && targets.indexOf(child.element) < 0) {
              targets.push(child.element);
            }
          });
        }
        targets.forEach(function (el) {
          var existing = elementTransforms.get(el) || defaultTransform();
          existing.tx = round(existing.tx + t.tx);
          existing.ty = round(existing.ty + t.ty);
          existing.scaleX = round(existing.scaleX * t.scaleX);
          existing.scaleY = round(existing.scaleY * t.scaleY);
          existing.rotate = round(existing.rotate + t.rotate);
          if (t.flipX) existing.flipX = !existing.flipX;
          if (t.flipY) existing.flipY = !existing.flipY;
          if (t.opacity != null) existing.opacity = t.opacity;
          if (t.zIndex != null) existing.zIndex = t.zIndex;
          elementTransforms.set(el, existing);
        });
      });

      elementTransforms.forEach(function (t, el) {
        var orig = originalStyles.get(el);
        var isSvgChild = el.namespaceURI === 'http://www.w3.org/2000/svg' && el.localName !== 'svg';
        var ratioX = 1, ratioY = 1;
        if (isSvgChild && el.ownerSVGElement) {
          var svg = el.ownerSVGElement;
          var svgRect = svg.getBoundingClientRect();
          var vb = svg.viewBox && svg.viewBox.baseVal;
          if (vb && vb.width && svgRect.width) ratioX = vb.width / svgRect.width;
          if (vb && vb.height && svgRect.height) ratioY = vb.height / svgRect.height;
          el.style.transformBox = 'fill-box';
          el.style.transformOrigin = 'center';
        }
        var hasGeo = round(t.tx) !== 0 || round(t.ty) !== 0 || round(t.scaleX - 1) !== 0 || round(t.scaleY - 1) !== 0 || round(t.rotate) !== 0 || t.flipX || t.flipY;
        if (hasGeo) {
          var sx = round(t.scaleX * (t.flipX ? -1 : 1));
          var sy = round(t.scaleY * (t.flipY ? -1 : 1));
          var delta = 'translate(' + round(t.tx * ratioX) + 'px, ' + round(t.ty * ratioY) + 'px) rotate(' + round(t.rotate) + 'deg) scale(' + sx + ', ' + sy + ')';
          el.style.transform = orig && orig.computedTransform ? (delta + ' ' + orig.computedTransform) : delta;
        }
        if (t.opacity != null) el.style.opacity = String(t.opacity);
        if (t.zIndex != null && !isSvgChild) {
          if (orig && orig.computedPosition === 'static') el.style.position = 'relative';
          el.style.zIndex = String(t.zIndex);
        }
      });
    }

    function snapshotHistoryState() {
      var snap = {};
      layers.forEach(function (l) {
        if (isTransformed(l.transform)) snap[l.id] = Object.assign({}, l.transform);
      });
      return JSON.stringify(snap);
    }

    function restoreHistoryState(serialized) {
      var map = {};
      try { map = JSON.parse(serialized || '{}') || {}; } catch (unused) { map = {}; }
      layers.forEach(function (l) {
        l.transform = normalizeTransform(map[l.id]);
      });
      applyDomState();
      renderOverlay();
      message('state', true);
    }

    function pushHistory(prevSerialized) {
      var currentSerialized = snapshotHistoryState();
      if (prevSerialized === currentSerialized) return;
      history.push(prevSerialized);
      if (history.length > 50) history.shift();
      future.length = 0;
    }

    function renderOverlay() {
      if (destroyed) return;
      var layer = byId.get(selectedId);
      if (!layer || hasFlag(layer, 'hidden')) { overlay.style.display = 'none'; return; }
      var style = win.getComputedStyle(layer.element);
      var rect = bounds(layer);
      if (style.display === 'none' || style.visibility === 'hidden' || rect.width <= 0 || rect.height <= 0) {
        overlay.style.display = 'none'; return;
      }
      var locked = hasFlag(layer, 'locked');
      overlay.style.display = 'block';
      overlay.style.left = rect.left + 'px';
      overlay.style.top = rect.top + 'px';
      overlay.style.width = rect.width + 'px';
      overlay.style.height = rect.height + 'px';
      label.textContent = layer.name + (locked ? ' · 已锁定' : '');
      label.style.bottom = rect.top < 24 ? 'auto' : '100%';
      label.style.top = rect.top < 24 ? '100%' : 'auto';
      handleNames.forEach(function (name) {
        handleEls[name].hidden = locked;
      });
    }

    function refresh() {
      if (destroyed || scheduled) return;
      scheduled = win.requestAnimationFrame(function () {
        scheduled = 0;
        renderOverlay();
        message('state');
      });
    }

    function select(id) {
      if (id != null && !byId.has(id)) return;
      selectedId = id == null ? null : id;
      renderOverlay();
      message('state', true);
    }

    function reset() {
      layers.forEach(function (layer) {
        layer.hidden = false;
        layer.locked = false;
        layer.transform = defaultTransform();
      });
      history.length = 0;
      future.length = 0;
      selectedId = null;
      focusId = null;
      guideX.hidden = true;
      guideY.hidden = true;
      hud.hidden = true;
      applyDomState();
      renderOverlay();
      message('state', true);
    }

    function visibleHit(layer, x, y) {
      if (hasFlag(layer, 'hidden') || hasFlag(layer, 'locked')) return false;
      var element = layer.element;
      var style = win.getComputedStyle(element);
      if (style.display === 'none' || style.visibility === 'hidden' || style.visibility === 'collapse') return false;
      var rect = element.getBoundingClientRect();
      if (x < rect.left || x > rect.right || y < rect.top || y > rect.bottom || !rect.width || !rect.height) return false;
      var ancestor = element.parentElement;
      while (ancestor) {
        var ancestorStyle = win.getComputedStyle(ancestor);
        var clipRect = ancestor.getBoundingClientRect();
        var clipsX = /hidden|clip|auto|scroll/.test(ancestorStyle.overflowX);
        var clipsY = /hidden|clip|auto|scroll/.test(ancestorStyle.overflowY);
        if ((clipsX && (x < clipRect.left || x > clipRect.right)) ||
            (clipsY && (y < clipRect.top || y > clipRect.bottom))) return false;
        if (ancestor === root) break;
        ancestor = ancestor.parentElement;
      }
      if (typeof element.isPointInFill === 'function' && typeof element.getScreenCTM === 'function') {
        try {
          var matrix = element.getScreenCTM();
          if (matrix) {
            var point = new win.DOMPoint(x, y).matrixTransform(matrix.inverse());
            return (style.fill !== 'none' && element.isPointInFill(point)) ||
              (style.stroke !== 'none' && element.isPointInStroke(point));
          }
        } catch (unused) { /* Older SVG implementations retain rectangular selection. */ }
      }
      return true;
    }

    function stackPath(element) {
      var path = [];
      var current = element;
      while (current && current !== root.parentElement) {
        var style = win.getComputedStyle(current);
        var parentStyle = current.parentElement && win.getComputedStyle(current.parentElement);
        var positioned = style.position !== 'static' || (parentStyle && /flex|grid/.test(parentStyle.display));
        var context = current === root ||
          (positioned && style.zIndex !== 'auto') || /fixed|sticky/.test(style.position) ||
          Number.parseFloat(style.opacity) < 1 || style.transform !== 'none' ||
          style.filter !== 'none' || style.perspective !== 'none' ||
          style.isolation === 'isolate' || style.mixBlendMode !== 'normal' ||
          /paint|layout/.test(style.contain || '') || /transform|opacity/.test(style.willChange || '');
        if (context || current === element) {
          var z = positioned ? Number.parseInt(style.zIndex, 10) : 0;
          path.unshift({element: current, z: Number.isFinite(z) ? z : 0});
        }
        current = current.parentElement;
      }
      return path;
    }

    function deepestHit(x, y) {
      var hits = layers.filter(function (layer) { return visibleHit(layer, x, y); });
      var paths = new Map();
      hits.forEach(function (layer) { paths.set(layer, stackPath(layer.element)); });
      hits.sort(function (a, b) {
        if (a.element === b.element) return b.depth - a.depth;
        var ap = paths.get(a), bp = paths.get(b);
        for (var i = 0; i < Math.min(ap.length, bp.length); i += 1) {
          if (ap[i].element === bp[i].element) continue;
          if (ap[i].z !== bp[i].z) return bp[i].z - ap[i].z;
          if (!ap[i].element.contains(bp[i].element) && !bp[i].element.contains(ap[i].element)) {
            var stackPosition = ap[i].element.compareDocumentPosition(bp[i].element);
            if (stackPosition & 4) return 1;
            if (stackPosition & 2) return -1;
          }
          break;
        }
        if (a.element.contains(b.element)) return 1;
        if (b.element.contains(a.element)) return -1;
        var position = a.element.compareDocumentPosition(b.element);
        if (position & 4) return 1;
        if (position & 2) return -1;
        return b.depth - a.depth;
      });
      return hits[0] || null;
    }

    function chainFor(layer) {
      var chain = [];
      while (layer) {
        chain.unshift(layer);
        layer = layer.parentId && byId.get(layer.parentId);
      }
      return chain;
    }

    function atFocus(hit) {
      if (!hit) return null;
      var chain = chainFor(hit);
      var focusIndex = chain.findIndex(function (layer) { return layer.id === focusId; });
      if (focusIndex >= 0 && chain[focusIndex + 1]) return chain[focusIndex + 1];
      if (focusIndex >= 0) return chain[focusIndex];
      focusId = null;
      return chain[0];
    }

    function inRoot(event) {
      return event.target && (event.target === root || root.contains(event.target) || overlay.contains(event.target));
    }

    function block(event) {
      if (!inRoot(event)) return;
      event.preventDefault();
      event.stopImmediatePropagation();
    }

    function applyLayerPatch(layer, patch, recordHistory) {
      if (!layer || hasFlag(layer, 'locked')) return;
      ensureBaseBounds();
      var prev = recordHistory ? snapshotHistoryState() : null;
      var base = layer.baseBounds || artboardCoords(layer);
      var next = Object.assign({}, layer.transform);
      if (patch && typeof patch === 'object') {
        if (typeof patch.x === 'number' && Number.isFinite(patch.x)) next.tx = round(patch.x - base.x);
        if (typeof patch.y === 'number' && Number.isFinite(patch.y)) next.ty = round(patch.y - base.y);
        if (typeof patch.width === 'number' && Number.isFinite(patch.width) && base.width > 0) {
          next.scaleX = round(Math.max(4, patch.width) / base.width);
        }
        if (typeof patch.height === 'number' && Number.isFinite(patch.height) && base.height > 0) {
          next.scaleY = round(Math.max(4, patch.height) / base.height);
        }
        next = normalizeTransform(Object.assign(next, patch), layer.transform);
        if (typeof patch.x === 'number' && typeof patch.tx !== 'number') next.tx = round(patch.x - base.x);
        if (typeof patch.y === 'number' && typeof patch.ty !== 'number') next.ty = round(patch.y - base.y);
        if (typeof patch.width === 'number' && typeof patch.scaleX !== 'number' && base.width > 0) {
          next.scaleX = Math.max(0.05, Math.min(20, round(Math.max(4, patch.width) / base.width)));
        }
        if (typeof patch.height === 'number' && typeof patch.scaleY !== 'number' && base.height > 0) {
          next.scaleY = Math.max(0.05, Math.min(20, round(Math.max(4, patch.height) / base.height)));
        }
      }
      layer.transform = next;
      applyDomState();
      if (recordHistory) pushHistory(prev);
      renderOverlay();
      message('state', true);
    }

    function alignLayer(layer, mode) {
      if (!layer || hasFlag(layer, 'locked')) return;
      ensureBaseBounds();
      var ab = artboardScale();
      var cur = artboardCoords(layer);
      var tx = layer.transform.tx;
      var ty = layer.transform.ty;
      if (mode === 'left') tx -= cur.x;
      else if (mode === 'center-x') tx += (ab.width - cur.width) / 2 - cur.x;
      else if (mode === 'right') tx += ab.width - cur.width - cur.x;
      else if (mode === 'top') ty -= cur.y;
      else if (mode === 'center-y') ty += (ab.height - cur.height) / 2 - cur.y;
      else if (mode === 'bottom') ty += ab.height - cur.height - cur.y;
      applyLayerPatch(layer, {tx: round(tx), ty: round(ty)}, true);
    }

    function computeSnap(layer, candidateTx, candidateTy) {
      var ab = artboardScale();
      var base = layer.baseBounds || artboardCoords(layer);
      var w = base.width * layer.transform.scaleX;
      var h = base.height * layer.transform.scaleY;
      var x = base.x + candidateTx;
      var y = base.y + candidateTy;
      var threshold = 4;
      var snapX = null, snapY = null, guideScreenX = null, guideScreenY = null;

      var xTargets = [0, ab.width / 2, ab.width];
      var yTargets = [0, ab.height / 2, ab.height];
      layers.forEach(function (other) {
        if (other.id === layer.id || other.parentId !== layer.parentId || hasFlag(other, 'hidden')) return;
        var c = artboardCoords(other);
        if (c.width > 0 && c.height > 0) {
          xTargets.push(c.x, c.x + c.width / 2, c.x + c.width);
          yTargets.push(c.y, c.y + c.height / 2, c.y + c.height);
        }
      });

      var myXPoints = [x, x + w / 2, x + w];
      var bestDx = threshold + 1;
      myXPoints.forEach(function (pt) {
        xTargets.forEach(function (target) {
          var diff = target - pt;
          if (Math.abs(diff) < Math.abs(bestDx) && Math.abs(diff) <= threshold) {
            bestDx = diff;
            snapX = round(candidateTx + diff);
            guideScreenX = ab.rootRect.left + target * ab.scaleX;
          }
        });
      });

      var myYPoints = [y, y + h / 2, y + h];
      var bestDy = threshold + 1;
      myYPoints.forEach(function (pt) {
        yTargets.forEach(function (target) {
          var diff = target - pt;
          if (Math.abs(diff) < Math.abs(bestDy) && Math.abs(diff) <= threshold) {
            bestDy = diff;
            snapY = round(candidateTy + diff);
            guideScreenY = ab.rootRect.top + target * ab.scaleY;
          }
        });
      });

      return {
        tx: snapX != null ? snapX : round(candidateTx),
        ty: snapY != null ? snapY : round(candidateTy),
        guideX: guideScreenX,
        guideY: guideScreenY
      };
    }

    function onPointerDown(event) {
      if (!inRoot(event)) return;
      if (event.button !== 0) { block(event); return; }
      var handle = event.target && event.target.closest && event.target.closest('[data-gdl-handle]');
      if (handle) {
        block(event);
        var selected = byId.get(selectedId);
        if (!selected || hasFlag(selected, 'locked')) return;
        ensureBaseBounds();
        var rect = bounds(selected);
        dragState = {
          mode: handle.dataset.gdlHandle === 'rotate' ? 'rotate' : 'resize',
          handle: handle.dataset.gdlHandle,
          layer: selected,
          startX: event.clientX,
          startY: event.clientY,
          startTransform: Object.assign({}, selected.transform),
          startCoords: artboardCoords(selected),
          centerX: rect.left + rect.width / 2,
          centerY: rect.top + rect.height / 2,
          beforeHistory: snapshotHistoryState(),
          active: true
        };
        return;
      }

      block(event);
      if (event.detail > 1) return;
      var hit = atFocus(deepestHit(event.clientX, event.clientY));
      var target = byId.get(selectedId);
      if (!target || !visibleHit(target, event.clientX, event.clientY)) {
        target = hit;
      }
      if (!target || hasFlag(target, 'locked')) return;
      ensureBaseBounds();
      dragState = {
        mode: 'move',
        layer: target,
        hitLayer: hit,
        startX: event.clientX,
        startY: event.clientY,
        startTransform: Object.assign({}, target.transform),
        beforeHistory: snapshotHistoryState(),
        active: false
      };
    }

    function onPointerMove(event) {
      if (!dragState) return;
      block(event);
      var dxScreen = event.clientX - dragState.startX;
      var dyScreen = event.clientY - dragState.startY;
      if (!dragState.active) {
        if (Math.hypot(dxScreen, dyScreen) < 4) return;
        dragState.active = true;
        if (selectedId !== dragState.layer.id) {
          selectedId = dragState.layer.id;
        }
      }
      var ab = artboardScale();
      var dx = dxScreen / ab.scaleX;
      var dy = dyScreen / ab.scaleY;
      var layer = dragState.layer;
      var startT = dragState.startTransform;

      if (dragState.mode === 'move') {
        if (event.shiftKey) {
          if (Math.abs(dx) >= Math.abs(dy)) dy = 0;
          else dx = 0;
        }
        var rawTx = startT.tx + dx;
        var rawTy = startT.ty + dy;
        var snapped = event.altKey ? {tx: round(rawTx), ty: round(rawTy), guideX: null, guideY: null} : computeSnap(layer, rawTx, rawTy);
        layer.transform.tx = snapped.tx;
        layer.transform.ty = snapped.ty;
        if (snapped.guideX != null) {
          guideX.style.left = snapped.guideX + 'px';
          guideX.hidden = false;
        } else guideX.hidden = true;
        if (snapped.guideY != null) {
          guideY.style.top = snapped.guideY + 'px';
          guideY.hidden = false;
        } else guideY.hidden = true;
        applyDomState();
        var c = artboardCoords(layer);
        hud.textContent = c.x + ', ' + c.y;
        hud.hidden = false;
        renderOverlay();
        message('state');
      } else if (dragState.mode === 'resize') {
        var h = dragState.handle;
        var base = layer.baseBounds || dragState.startCoords;
        var startW = Math.max(4, base.width * startT.scaleX);
        var startH = Math.max(4, base.height * startT.scaleY);
        var newW = startW, newH = startH;
        var offsetTx = 0, offsetTy = 0;
        if (h.indexOf('e') >= 0) { newW = Math.max(8, startW + dx); offsetTx = (newW - startW) / 2; }
        if (h.indexOf('w') >= 0) { newW = Math.max(8, startW - dx); offsetTx = -(newW - startW) / 2; }
        if (h.indexOf('s') >= 0) { newH = Math.max(8, startH + dy); offsetTy = (newH - startH) / 2; }
        if (h.indexOf('n') >= 0) { newH = Math.max(8, startH - dy); offsetTy = -(newH - startH) / 2; }
        if (event.shiftKey && startW > 0 && startH > 0) {
          var ratio = startW / startH;
          if (Math.abs(newW - startW) >= Math.abs(newH - startH)) newH = newW / ratio;
          else newW = newH * ratio;
        }
        layer.transform.scaleX = round(newW / Math.max(1, base.width));
        layer.transform.scaleY = round(newH / Math.max(1, base.height));
        layer.transform.tx = round(startT.tx + offsetTx);
        layer.transform.ty = round(startT.ty + offsetTy);
        applyDomState();
        hud.textContent = Math.round(newW) + ' × ' + Math.round(newH);
        hud.hidden = false;
        renderOverlay();
        message('state');
      } else if (dragState.mode === 'rotate') {
        var angle = Math.atan2(event.clientY - dragState.centerY, event.clientX - dragState.centerX) * 180 / Math.PI + 90;
        var deg = ((angle + 180) % 360 + 360) % 360 - 180;
        if (event.shiftKey) deg = Math.round(deg / 15) * 15;
        layer.transform.rotate = round(deg);
        applyDomState();
        hud.textContent = layer.transform.rotate + '°';
        hud.hidden = false;
        renderOverlay();
        message('state');
      }
    }

    function onPointerUp(event) {
      if (!dragState) {
        if (inRoot(event)) block(event);
        return;
      }
      var wasActive = dragState.active;
      var beforeHistory = dragState.beforeHistory;
      dragState = null;
      guideX.hidden = true;
      guideY.hidden = true;
      hud.hidden = true;
      if (wasActive) {
        suppressClickUntil = Date.now() + 220;
        pushHistory(beforeHistory);
        renderOverlay();
        message('state', true);
      }
      if (inRoot(event)) block(event);
    }

    function onClick(event) {
      if (!inRoot(event)) return;
      block(event);
      if (Date.now() < suppressClickUntil) return;
      if (event.detail > 1) return;
      var hit = atFocus(deepestHit(event.clientX, event.clientY));
      select(hit && hit.id);
    }

    function onDoubleClick(event) {
      if (!inRoot(event)) return;
      block(event);
      var hit = deepestHit(event.clientX, event.clientY);
      if (!hit) return;
      var chain = chainFor(hit);
      var index = chain.findIndex(function (layer) { return layer.id === selectedId; });
      var target = index >= 0 ? (chain[index + 1] || chain[index]) : chain[0];
      if (target.children.length) focusId = target.id;
      else if (target.parentId) focusId = target.parentId;
      select(target.id);
    }

    function onKey(event) {
      if (!inRoot(event) && !selectedId) return;
      if (event.target && /INPUT|TEXTAREA|SELECT/.test(event.target.tagName)) return;
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'z') {
        event.preventDefault();
        if (event.shiftKey) {
          if (future.length) {
            var next = future.pop();
            history.push(snapshotHistoryState());
            restoreHistoryState(next);
          }
        } else if (history.length) {
          var prev = history.pop();
          future.push(snapshotHistoryState());
          restoreHistoryState(prev);
        }
        return;
      }
      if (event.key === 'Escape') {
        if (inRoot(event)) block(event);
        var selected = byId.get(selectedId);
        focusId = selected && selected.parentId;
        select(focusId);
        return;
      }
      var activeLayer = byId.get(selectedId);
      if (!activeLayer || hasFlag(activeLayer, 'locked')) return;
      var step = event.shiftKey ? 10 : 1;
      if (event.key === 'ArrowLeft') { event.preventDefault(); applyLayerPatch(activeLayer, {tx: round(activeLayer.transform.tx - step)}, true); }
      else if (event.key === 'ArrowRight') { event.preventDefault(); applyLayerPatch(activeLayer, {tx: round(activeLayer.transform.tx + step)}, true); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); applyLayerPatch(activeLayer, {ty: round(activeLayer.transform.ty - step)}, true); }
      else if (event.key === 'ArrowDown') { event.preventDefault(); applyLayerPatch(activeLayer, {ty: round(activeLayer.transform.ty + step)}, true); }
      else if (event.key === '[') { event.preventDefault(); applyLayerPatch(activeLayer, {zIndex: (activeLayer.transform.zIndex || 0) - 1}, true); }
      else if (event.key === ']') { event.preventDefault(); applyLayerPatch(activeLayer, {zIndex: (activeLayer.transform.zIndex || 0) + 1}, true); }
    }

    function inlineComputedStyles(sourceEl, cloneEl) {
      var computed = win.getComputedStyle(sourceEl);
      var cssText = '';
      for (var i = 0; i < computed.length; i += 1) {
        var prop = computed[i];
        cssText += prop + ':' + computed.getPropertyValue(prop) + ';';
      }
      cloneEl.style.cssText = cssText;
      var srcChildren = sourceEl.children || [];
      var cloneChildren = cloneEl.children || [];
      for (var j = 0; j < srcChildren.length; j += 1) {
        if (cloneChildren[j]) inlineComputedStyles(srcChildren[j], cloneChildren[j]);
      }
    }

    function exportLayer(layerId, format, scale) {
      var layer = byId.get(layerId || selectedId);
      if (!layer) return;
      var el = layer.element;
      var rect = bounds(layer);
      var ab = artboardScale();
      var w = Math.max(1, Math.round(rect.width / ab.scaleX));
      var h = Math.max(1, Math.round(rect.height / ab.scaleY));
      var exportScale = Math.max(1, Number(scale) || 1);
      var safeName = (options.boardId + '-' + layer.id).replace(/[^a-zA-Z0-9_\-\u4e00-\u9fa5]/g, '_');

      var clone = el.cloneNode(true);
      inlineComputedStyles(el, clone);
      clone.style.margin = '0';
      clone.style.transform = 'none';

      var svgString;
      if (el.namespaceURI === 'http://www.w3.org/2000/svg') {
        var wrapperSvg = doc.createElementNS('http://www.w3.org/2000/svg', 'svg');
        wrapperSvg.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
        wrapperSvg.setAttribute('width', String(w * exportScale));
        wrapperSvg.setAttribute('height', String(h * exportScale));
        wrapperSvg.setAttribute('viewBox', '0 0 ' + w + ' ' + h);
        if (el.ownerSVGElement) {
          var defs = el.ownerSVGElement.querySelector('defs');
          if (defs) wrapperSvg.appendChild(defs.cloneNode(true));
        }
        wrapperSvg.appendChild(clone);
        svgString = new win.XMLSerializer().serializeToString(wrapperSvg);
      } else {
        var xhtml = new win.XMLSerializer().serializeToString(clone);
        svgString = '<svg xmlns="http://www.w3.org/2000/svg" width="' + (w * exportScale) + '" height="' + (h * exportScale) + '" viewBox="0 0 ' + w + ' ' + h + '">' +
          '<foreignObject width="100%" height="100%"><div xmlns="http://www.w3.org/1999/xhtml" style="width:' + w + 'px;height:' + h + 'px;overflow:hidden;">' +
          xhtml + '</div></foreignObject></svg>';
      }

      var svgDataUrl = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svgString);
      if (format === 'svg') {
        send(host, {
          type: MESSAGE_TYPE, action: 'export-ready', boardId: options.boardId, session: options.session,
          layerId: layer.id, format: 'svg', filename: safeName + '.svg', dataUrl: svgDataUrl
        });
        return;
      }

      var img = new win.Image();
      img.onload = function () {
        try {
          var canvas = doc.createElement('canvas');
          canvas.width = w * exportScale;
          canvas.height = h * exportScale;
          var ctx = canvas.getContext('2d');
          ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
          var pngUrl = canvas.toDataURL('image/png');
          send(host, {
            type: MESSAGE_TYPE, action: 'export-ready', boardId: options.boardId, session: options.session,
            layerId: layer.id, format: 'png', filename: safeName + (exportScale > 1 ? '@' + exportScale + 'x' : '') + '.png', dataUrl: pngUrl
          });
        } catch (unused) {
          send(host, {
            type: MESSAGE_TYPE, action: 'export-ready', boardId: options.boardId, session: options.session,
            layerId: layer.id, format: 'svg', filename: safeName + '.svg', dataUrl: svgDataUrl
          });
        }
      };
      img.onerror = function () {
        send(host, {
          type: MESSAGE_TYPE, action: 'export-ready', boardId: options.boardId, session: options.session,
          layerId: layer.id, format: 'svg', filename: safeName + '.svg', dataUrl: svgDataUrl
        });
      };
      img.src = svgDataUrl;
    }

    function onMessage(event) {
      var data = event.data;
      if (event.source !== host || !sameOrigin(event, win) || !matches(data, options) || data.action !== 'command' || COMMANDS.indexOf(data.command) < 0) return;
      if (data.command === 'sync') { message('ready', true); return; }
      if (data.command === 'reset') { reset(); return; }
      if (data.command === 'select') {
        if (data.id == null || (typeof data.id === 'string' && byId.has(data.id))) {
          focusId = null;
          select(data.id);
        }
        return;
      }
      if (data.command === 'undo') {
        if (history.length) {
          var prev = history.pop();
          future.push(snapshotHistoryState());
          restoreHistoryState(prev);
        }
        return;
      }
      if (data.command === 'redo') {
        if (future.length) {
          var next = future.pop();
          history.push(snapshotHistoryState());
          restoreHistoryState(next);
        }
        return;
      }
      if (data.command === 'import-transforms') {
        var prevImport = snapshotHistoryState();
        var map = (data.value && typeof data.value === 'object') ? data.value : {};
        layers.forEach(function (l) {
          l.transform = normalizeTransform(map[l.id]);
        });
        applyDomState();
        pushHistory(prevImport);
        renderOverlay();
        message('state', true);
        return;
      }
      if (data.command === 'export-layer') {
        var opts = data.value || {};
        exportLayer(data.id || selectedId, opts.format || 'png', opts.scale || 1);
        return;
      }
      var layer = typeof data.id === 'string' && byId.get(data.id);
      if (!layer) return;
      if (data.command === 'reset-layer') {
        var prevReset = snapshotHistoryState();
        layer.transform = defaultTransform();
        applyDomState();
        pushHistory(prevReset);
        renderOverlay();
        message('state', true);
        return;
      }
      if (data.command === 'transform') {
        applyLayerPatch(layer, data.value, true);
        return;
      }
      if (data.command === 'align') {
        alignLayer(layer, string(data.value));
        return;
      }
      if (data.command === 'z-order') {
        var deltaZ = data.value === 'up' ? 1 : data.value === 'down' ? -1 : Number(data.value) || 0;
        applyLayerPatch(layer, {zIndex: (layer.transform.zIndex || 0) + deltaZ}, true);
        return;
      }
      if (typeof data.value !== 'boolean') return;
      layer[data.command] = data.value;
      if (data.command === 'hidden') applyDomState();
      renderOverlay();
      message('state', true);
    }

    if (options.initialTransforms && typeof options.initialTransforms === 'object') {
      ensureBaseBounds();
      layers.forEach(function (l) {
        if (options.initialTransforms[l.id]) l.transform = normalizeTransform(options.initialTransforms[l.id]);
      });
      applyDomState();
    }

    var blockedEvents = ['mousedown', 'mouseup', 'auxclick', 'contextmenu', 'submit', 'input', 'change', 'dragstart'];
    blockedEvents.forEach(function (name) { win.addEventListener(name, block, true); });
    win.addEventListener('pointerdown', onPointerDown, true);
    win.addEventListener('pointermove', onPointerMove, true);
    win.addEventListener('pointerup', onPointerUp, true);
    win.addEventListener('pointercancel', onPointerUp, true);
    win.addEventListener('click', onClick, true);
    win.addEventListener('dblclick', onDoubleClick, true);
    win.addEventListener('keydown', onKey, true);
    win.addEventListener('message', onMessage);
    win.addEventListener('resize', refresh);
    win.addEventListener('scroll', refresh, true);
    doc.addEventListener('load', refresh, true);
    var resizeObserver = win.ResizeObserver ? new win.ResizeObserver(refresh) : null;
    if (resizeObserver) {
      resizeObserver.observe(root);
      layers.forEach(function (layer) { resizeObserver.observe(layer.element); });
    }
    if (doc.fonts && doc.fonts.ready) doc.fonts.ready.then(refresh);
    message('ready', true);

    return {
      select: select, reset: reset, snapshot: snapshot,
      transform: function (id, patch) { applyLayerPatch(byId.get(id), patch, true); },
      importTransforms: function (map) {
        layers.forEach(function (l) { l.transform = normalizeTransform(map && map[l.id]); });
        applyDomState(); renderOverlay(); message('state', true);
      },
      destroy: function () {
        if (destroyed) return;
        destroyed = true;
        if (scheduled) win.cancelAnimationFrame(scheduled);
        originalStyles.forEach(function (original, element) { restoreElement(element, original); });
        if (resizeObserver) resizeObserver.disconnect();
        blockedEvents.forEach(function (name) { win.removeEventListener(name, block, true); });
        win.removeEventListener('pointerdown', onPointerDown, true);
        win.removeEventListener('pointermove', onPointerMove, true);
        win.removeEventListener('pointerup', onPointerUp, true);
        win.removeEventListener('pointercancel', onPointerUp, true);
        win.removeEventListener('click', onClick, true);
        win.removeEventListener('dblclick', onDoubleClick, true);
        win.removeEventListener('keydown', onKey, true);
        win.removeEventListener('message', onMessage);
        win.removeEventListener('resize', refresh);
        win.removeEventListener('scroll', refresh, true);
        doc.removeEventListener('load', refresh, true);
        guideX.remove();
        guideY.remove();
        overlay.remove();
      }
    };
  }

  function mountPanel(options) {
    checkOptions(options);
    if (!isElement(options.tree) || !isElement(options.inspector) || !options.frame) {
      throw new Error('图层面板需要 tree、inspector 容器与 frame。');
    }
    var tree = options.tree;
    var inspector = options.inspector;
    var doc = tree.ownerDocument;
    var win = doc.defaultView;
    var state = null;
    var destroyed = false;
    var expanded = new Set();
    var known = new Set();
    var rows = new Map();
    var treeSignature = '';
    var lockAspect = true;
    var statusText = '';
    tree.classList.add('gdl-tree');
    tree.setAttribute('role', 'tree');
    tree.setAttribute('aria-label', '画板图层');
    inspector.classList.add('gdl-inspector');
    tree.textContent = '正在连接画板…';
    inspector.textContent = '点击画布或图层树，查看组件属性。';

    function command(name, id, value) {
      if (destroyed || !options.frame.contentWindow) return;
      send(options.frame.contentWindow, {
        type: MESSAGE_TYPE, action: 'command', boardId: options.boardId,
        session: options.session, command: name, id: id, value: value
      });
    }

    function element(tag, className, text) {
      var node = doc.createElement(tag);
      if (className) node.className = className;
      if (text != null) node.textContent = text;
      return node;
    }

    function button(label, className, text, callback) {
      var node = element('button', className, text);
      node.type = 'button';
      node.setAttribute('aria-label', label);
      node.title = label;
      node.addEventListener('click', function (event) { event.stopPropagation(); callback(); });
      return node;
    }

    function triggerDownload(url, filename) {
      var link = doc.createElement('a');
      link.href = url;
      link.download = filename || 'layer-export';
      doc.body.appendChild(link);
      link.click();
      link.remove();
    }

    function notifyTop(type, payload) {
      var targets = [win.parent, win.top].filter(function (w, i, arr) { return w && w !== win && arr.indexOf(w) === i; });
      targets.forEach(function (target) {
        try { target.postMessage(Object.assign({type: type, boardId: options.boardId}, payload), '*'); } catch (unused) {}
      });
    }

    function renderTree() {
      var signature = JSON.stringify({layers: state.layers, selectedId: state.selectedId, expanded: Array.from(expanded)});
      if (signature === treeSignature) return;
      treeSignature = signature;
      tree.replaceChildren();
      rows.clear();
      var children = new Map();
      state.layers.forEach(function (layer) {
        if (!children.has(layer.parentId || null)) children.set(layer.parentId || null, []);
        children.get(layer.parentId || null).push(layer);
      });
      function append(layer, depth, container) {
        var item = element('div', 'gdl-tree-item');
        item.setAttribute('role', 'treeitem');
        item.setAttribute('aria-selected', String(layer.id === state.selectedId));
        item.dataset.layerId = layer.id;
        var descendants = children.get(layer.id) || [];
        if (descendants.length) item.setAttribute('aria-expanded', String(expanded.has(layer.id)));
        var row = element('div', 'gdl-tree-row');
        row.style.setProperty('--gdl-depth', depth);
        if (layer.id === state.selectedId) row.classList.add('gdl-is-selected');
        if (layer.effectiveHidden) row.classList.add('gdl-is-hidden');
        if (layer.effectiveLocked) row.classList.add('gdl-is-locked');
        if (layer.transformed) row.classList.add('gdl-is-transformed');
        var toggle = button(expanded.has(layer.id) ? '折叠' : '展开', 'gdl-tree-toggle', descendants.length ? (expanded.has(layer.id) ? '▾' : '▸') : '·', function () {
          if (!descendants.length) return;
          if (expanded.has(layer.id)) expanded.delete(layer.id); else expanded.add(layer.id);
          renderTree();
        });
        if (!descendants.length) { toggle.disabled = true; toggle.setAttribute('aria-hidden', 'true'); }
        var choose = button(layer.name, 'gdl-tree-name', layer.name, function () { command('select', layer.id); });
        if (layer.composite) choose.appendChild(element('span', 'gdl-composite-tag', '整组图像'));
        var visibility = button(layer.hidden ? '显示 ' + layer.name : '隐藏 ' + layer.name,
          'gdl-tree-action', layer.effectiveHidden ? '○' : '◉', function () { command('hidden', layer.id, !layer.hidden); });
        visibility.setAttribute('aria-pressed', String(layer.hidden));
        if (layer.effectiveHidden && !layer.hidden) visibility.title = '由父组隐藏；可在父组恢复显示';
        var lock = button(layer.locked ? '解锁 ' + layer.name : '锁定 ' + layer.name,
          'gdl-tree-action', layer.effectiveLocked ? '锁' : '—', function () { command('locked', layer.id, !layer.locked); });
        lock.setAttribute('aria-pressed', String(layer.locked));
        if (layer.effectiveLocked && !layer.locked) lock.title = '由父组锁定；仍可在树中查看';
        row.append(toggle, choose, visibility, lock);
        item.appendChild(row);
        if (descendants.length) {
          var group = element('div', 'gdl-tree-children');
          group.setAttribute('role', 'group');
          group.hidden = !expanded.has(layer.id);
          descendants.forEach(function (child) { append(child, depth + 1, group); });
          item.appendChild(group);
        }
        container.appendChild(item);
        rows.set(layer.id, row);
      }
      (children.get(null) || []).forEach(function (layer) { append(layer, 0, tree); });
      if (!state.layers.length) tree.textContent = '该画板尚未登记可审阅图层。';
    }

    function numberField(label, value, step, onChange, disabled) {
      var wrap = element('label', 'gdl-field');
      wrap.appendChild(element('span', '', label));
      var input = element('input');
      input.type = 'number';
      input.step = String(step || 1);
      input.value = String(round(value));
      input.disabled = Boolean(disabled);
      input.addEventListener('change', function () {
        var parsed = Number.parseFloat(input.value);
        if (Number.isFinite(parsed)) onChange(parsed);
      });
      wrap.appendChild(input);
      return wrap;
    }

    function renderInspector() {
      inspector.replaceChildren();
      var layer = state.selected;
      if (!layer) {
        inspector.appendChild(element('p', 'gdl-empty', '点击画布选择组件组，拖拽可调整位置/尺寸，双击进入下一层；也可从左侧直接选择。'));
        return;
      }
      inspector.appendChild(element('h3', 'gdl-property-title', layer.name));
      if (layer.composite) inspector.appendChild(element('p', 'gdl-notice', '整组图像：此素材内部尚未拆分，审阅到此图像为止。'));
      if (layer.effectiveHidden || layer.effectiveLocked) {
        inspector.appendChild(element('p', 'gdl-notice',
          [layer.effectiveHidden ? '当前隐藏（含父组状态）' : '', layer.effectiveLocked ? '当前锁定（含父组状态）' : ''].filter(Boolean).join('；')));
      }
      var list = element('dl', 'gdl-properties');
      function property(name, value) {
        list.appendChild(element('dt', '', name));
        list.appendChild(element('dd', '', value == null || value === '' ? '—' : string(value)));
      }
      property('图层 ID', layer.id);
      property('类型', TYPE_NAMES[layer.type] || layer.type);
      property('坐标', layer.x + ', ' + layer.y + ' px');
      property('尺寸', layer.width + ' × ' + layer.height + ' px');
      property('透明度', layer.opacity);
      property('层级', layer.zIndex === 'auto' ? '自动（DOM 顺序）' : layer.zIndex);
      if (layer.text) property('文字', layer.text);
      if (layer.type === 'text') {
        property('字体', layer.fontFamily);
        property('字号 / 字重', layer.fontSize + ' / ' + layer.fontWeight);
        property('行高', layer.lineHeight);
        property('颜色', layer.color);
      }
      if (layer.assetId) property('素材 ID', layer.assetId);
      if (layer.registryId) property('网页登记 ID', layer.registryId);
      property('来源', layer.sourceRef);
      inspector.appendChild(list);

      if (layer.assetId && typeof options.onInspectAsset === 'function') {
        inspector.appendChild(button('查看素材详情', 'gdl-asset-button', '查看素材详情', function () { options.onInspectAsset(layer.assetId); }));
      }

      var locked = layer.effectiveLocked;
      var t = layer.transform || defaultTransform();

      /* Figma-like Transform & Alignment Section */
      var transformSec = element('section', 'gdl-section');
      var secTitle = element('div', 'gdl-section-header');
      secTitle.appendChild(element('span', '', '图层变换与对齐 (Figma 模式)'));
      var lockRatioBtn = button('等比缩放锁定', 'gdl-tool-btn', lockAspect ? '🔒 等比' : '🔓 自由', function () {
        lockAspect = !lockAspect;
        renderInspector();
      });
      lockRatioBtn.setAttribute('aria-pressed', String(lockAspect));
      secTitle.appendChild(lockRatioBtn);
      transformSec.appendChild(secTitle);

      var alignBar = element('div', 'gdl-align-bar');
      [
        ['left', '⇤', '左对齐'],
        ['center-x', '⇥⇤', '水平居中'],
        ['right', '⇥', '右对齐'],
        ['top', '⇡', '顶对齐'],
        ['center-y', '⇣⇡', '垂直居中'],
        ['bottom', '⇣', '底对齐']
      ].forEach(function (item) {
        var btn = button(item[2], 'gdl-align-btn', item[1], function () { command('align', layer.id, item[0]); });
        btn.disabled = locked;
        alignBar.appendChild(btn);
      });
      transformSec.appendChild(alignBar);

      var grid = element('div', 'gdl-transform-grid');
      grid.appendChild(numberField('X', layer.x, 1, function (val) { command('transform', layer.id, {x: val}); }, locked));
      grid.appendChild(numberField('Y', layer.y, 1, function (val) { command('transform', layer.id, {y: val}); }, locked));
      grid.appendChild(numberField('W', layer.width, 1, function (val) {
        var patch = {width: Math.max(4, val)};
        if (lockAspect && layer.width > 0) patch.height = round(layer.height * (patch.width / layer.width));
        command('transform', layer.id, patch);
      }, locked));
      grid.appendChild(numberField('H', layer.height, 1, function (val) {
        var patch = {height: Math.max(4, val)};
        if (lockAspect && layer.height > 0) patch.width = round(layer.width * (patch.height / layer.height));
        command('transform', layer.id, patch);
      }, locked));
      grid.appendChild(numberField('旋转°', t.rotate || 0, 1, function (val) { command('transform', layer.id, {rotate: val}); }, locked));
      var currentOpacityPct = t.opacity != null ? Math.round(t.opacity * 100) : Math.round((Number.parseFloat(layer.opacity) || 1) * 100);
      grid.appendChild(numberField('透明%', currentOpacityPct, 5, function (val) {
        command('transform', layer.id, {opacity: Math.max(0, Math.min(100, val)) / 100});
      }, locked));

      if (layer.type === 'text') {
        var textWrap = element('label', 'gdl-field gdl-field-full');
        textWrap.appendChild(element('span', '', '文案'));
        var textInput = element('input');
        textInput.type = 'text';
        textInput.value = t.text != null ? t.text : layer.text;
        textInput.disabled = locked;
        textInput.addEventListener('change', function () {
          command('transform', layer.id, {text: textInput.value});
        });
        textWrap.appendChild(textInput);
        grid.appendChild(textWrap);
      }
      transformSec.appendChild(grid);

      var flipRow = element('div', 'gdl-button-row');
      var flipH = button('水平翻转', 'gdl-tool-btn', '⇋ 水平翻转', function () { command('transform', layer.id, {flipX: !t.flipX}); });
      flipH.setAttribute('aria-pressed', String(Boolean(t.flipX)));
      flipH.disabled = locked;
      var flipV = button('垂直翻转', 'gdl-tool-btn', '⇅ 垂直翻转', function () { command('transform', layer.id, {flipY: !t.flipY}); });
      flipV.setAttribute('aria-pressed', String(Boolean(t.flipY)));
      flipV.disabled = locked;
      var zUp = button('上移层级', 'gdl-tool-btn', '↑ 上移一层', function () { command('z-order', layer.id, 'up'); });
      zUp.disabled = locked;
      var zDown = button('下移层级', 'gdl-tool-btn', '↓ 下移一层', function () { command('z-order', layer.id, 'down'); });
      zDown.disabled = locked;
      flipRow.append(flipH, flipV, zUp, zDown);
      transformSec.appendChild(flipRow);

      var histRow = element('div', 'gdl-button-row');
      var undoBtn = button('撤销变换', 'gdl-tool-btn', '↶ 撤销', function () { command('undo'); });
      undoBtn.disabled = !state.canUndo;
      var redoBtn = button('重做变换', 'gdl-tool-btn', '↷ 重做', function () { command('redo'); });
      redoBtn.disabled = !state.canRedo;
      var resetLayerBtn = button('重置当前图层', 'gdl-tool-btn', '↺ 重置此层', function () { command('reset-layer', layer.id); });
      resetLayerBtn.disabled = !layer.transformed;
      histRow.append(undoBtn, redoBtn, resetLayerBtn);
      transformSec.appendChild(histRow);
      inspector.appendChild(transformSec);

      /* Dual-Mode Layer Export & Asset Download Section */
      var exportSec = element('section', 'gdl-section');
      exportSec.appendChild(element('div', 'gdl-section-header', '图层下载与导出'));
      if (layer.downloadUrl || layer.assetId) {
        var dlRow = element('div', 'gdl-button-row');
        var rawBtn = button('下载原始素材', 'gdl-export-btn', '下载原始素材 ↓', function () {
          if (typeof options.onDownloadAsset === 'function') {
            options.onDownloadAsset(layer);
          } else if (layer.downloadUrl) {
            triggerDownload(layer.downloadUrl, (layer.assetId || layer.id) + '.' + (layer.downloadUrl.split('.').pop() || 'png'));
          }
        });
        dlRow.appendChild(rawBtn);
        exportSec.appendChild(dlRow);
      }
      var exportGroup = element('div', 'gdl-export-group');
      exportGroup.appendChild(button('导出当前图层 PNG 1x', 'gdl-export-btn', 'PNG 1x', function () {
        command('export-layer', layer.id, {format: 'png', scale: 1});
      }));
      exportGroup.appendChild(button('导出当前图层 PNG 2x', 'gdl-export-btn', 'PNG 2x', function () {
        command('export-layer', layer.id, {format: 'png', scale: 2});
      }));
      exportGroup.appendChild(button('导出当前图层 SVG', 'gdl-export-btn', '导出 SVG', function () {
        command('export-layer', layer.id, {format: 'svg', scale: 1});
      }));
      exportSec.appendChild(exportGroup);
      inspector.appendChild(exportSec);

      /* LeafLoom Workspace Persistence & AI Reference Section */
      var hostSec = element('section', 'gdl-section');
      hostSec.appendChild(element('div', 'gdl-section-header', '项目保存与 AI 协同'));
      var hostRow = element('div', 'gdl-button-row');
      var saveBtn = button('保存图层修改到项目文件', 'gdl-tool-btn gdl-primary-btn', '保存到项目', function () {
        var payload = {boardId: options.boardId, transforms: state.transforms || {}};
        if (typeof options.onSaveTransforms === 'function') options.onSaveTransforms(payload.transforms, state);
        notifyTop('leafloom-design-save-transforms', payload);
        statusText = '已发送保存请求（' + Object.keys(state.transforms || {}).length + ' 处图层修改）';
        renderInspector();
      });
      var aiBtn = button('将选中图层添加到 AI 对话', 'gdl-tool-btn gdl-ai-btn', '添加到 AI 对话', function () {
        if (typeof options.onAddAiReference === 'function') options.onAddAiReference(layer, state);
        notifyTop('leafloom-design-ai-reference', {boardId: options.boardId, layer: layer});
        statusText = '已将图层「' + layer.name + '」添加到 AI 对话';
        renderInspector();
      });
      hostRow.append(saveBtn, aiBtn);
      hostSec.appendChild(hostRow);

      var patchRow = element('div', 'gdl-button-row');
      patchRow.appendChild(button('导出变更 JSON', 'gdl-tool-btn', '导出变更 JSON', function () {
        var blob = new win.Blob([JSON.stringify({boardId: options.boardId, transforms: state.transforms || {}}, null, 2)], {type: 'application/json'});
        var url = win.URL.createObjectURL(blob);
        triggerDownload(url, options.boardId + '-transforms.json');
        setTimeout(function () { win.URL.revokeObjectURL(url); }, 1000);
      }));
      if (statusText) {
        hostSec.appendChild(element('p', 'gdl-status-note', statusText));
      }
      hostSec.appendChild(patchRow);
      inspector.appendChild(hostSec);

      inspector.appendChild(element('p', 'gdl-property-hint', '支持画布拖拽移动、8 点缩放、旋转及方向键微调；坐标与尺寸以画板像素计。'));
    }

    function onMessage(event) {
      var data = event.data;
      if (destroyed || !data) return;
      if (data.type === 'leafloom-design-reload-transforms') {
        if (!data.boardId || data.boardId === options.boardId) {
          if (window.DESIGN_LAYER_TRANSFORMS && typeof window.DESIGN_LAYER_TRANSFORMS === 'object') {
            window.DESIGN_LAYER_TRANSFORMS[options.boardId] = data.transforms || {};
          }
          command('import-transforms', null, data.transforms || {});
        }
        return;
      }
      if (event.source !== options.frame.contentWindow || !sameOrigin(event, win) || !matches(data, options)) return;
      if (data.action === 'export-ready' && typeof data.dataUrl === 'string') {
        triggerDownload(data.dataUrl, data.filename || (data.layerId + '.' + (data.format || 'png')));
        return;
      }
      if ((data.action !== 'ready' && data.action !== 'state') || !Array.isArray(data.layers)) return;
      var ids = new Set();
      var valid = data.layers.every(function (layer) {
        if (!layer || typeof layer.id !== 'string' || !layer.id || ids.has(layer.id)) return false;
        ids.add(layer.id);
        return layer.parentId == null || typeof layer.parentId === 'string';
      });
      if (!valid || data.layers.some(function (layer) { return layer.parentId && !ids.has(layer.parentId); })) return;
      var incoming = new Map(data.layers.map(function (layer) { return [layer.id, layer]; }));
      if (data.layers.some(function (layer) {
        var seen = new Set([layer.id]);
        var item = layer;
        while (item.parentId) {
          if (seen.has(item.parentId)) return true;
          seen.add(item.parentId); item = incoming.get(item.parentId);
        }
        return false;
      })) return;
      state = data;
      if (window.DESIGN_LAYER_TRANSFORMS && typeof window.DESIGN_LAYER_TRANSFORMS === 'object') {
        window.DESIGN_LAYER_TRANSFORMS[options.boardId] = state.transforms || {};
      }
      state.layers.forEach(function (layer) {
        if (!known.has(layer.id) && !layer.parentId) expanded.add(layer.id);
        known.add(layer.id);
      });
      var selected = incoming.get(state.selectedId);
      while (selected && selected.parentId) {
        expanded.add(selected.parentId);
        selected = incoming.get(selected.parentId);
      }
      renderTree();
      renderInspector();
      notifyTop('leafloom-design-state', {
        action: data.action,
        boardId: options.boardId,
        selectedId: state.selectedId,
        selected: state.selected,
        transforms: state.transforms || {}
      });
    }

    function onLoad() { command('sync'); }
    win.addEventListener('message', onMessage);
    options.frame.addEventListener('load', onLoad);
    command('sync');
    return {
      reset: function () { statusText = ''; command('reset'); },
      command: command,
      importTransforms: function (transforms) { command('import-transforms', null, transforms || {}); },
      destroy: function () {
        if (destroyed) return;
        command('reset');
        destroyed = true;
        win.removeEventListener('message', onMessage);
        options.frame.removeEventListener('load', onLoad);
        tree.replaceChildren();
        inspector.replaceChildren();
        tree.classList.remove('gdl-tree');
        inspector.classList.remove('gdl-inspector');
        tree.removeAttribute('role');
        tree.removeAttribute('aria-label');
      }
    };
  }

  global.GameDesignLayers = Object.freeze({
    version: '1.1.0',
    mountCanvas: mountCanvas,
    mountPanel: mountPanel,
    applySavedTransforms: applySavedTransforms
  });
}(window));
