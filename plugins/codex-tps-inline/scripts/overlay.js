/* Adapted from Mie-coder/codex-tps (MIT). Local temporary UI; see NOTICE. */
(payload => {
  const NAME = '__codexTPSInline';
  const VERSION = 8;
  const ATTR = 'data-codex-tps-inline';
  const BUTTON_ATTR = 'data-codex-tps-toggle';
  const STORAGE_KEY = 'codex-tps-inline-enabled';
  const STYLE_ID = 'codex-tps-inline-style';
  const norm = value => {
    const id = String(value || '').replace(/^local:/, '');
    return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id) ? id.toLowerCase() : '';
  };
  const activeNodes = selector => Array.from(document.querySelectorAll(selector))
    .filter(node => !node.closest('[data-app-shell-active-page="false"]'));
  const activeThread = () => {
    for (const [selector, attribute] of [
      ['[data-above-composer-conversation-id]', 'data-above-composer-conversation-id'],
      ['[data-conversation-id]', 'data-conversation-id'],
      ['[data-app-action-sidebar-thread-active="true"]', 'data-app-action-sidebar-thread-id'],
    ]) {
      const ids = new Set(activeNodes(selector).map(node => norm(node.getAttribute(attribute))).filter(Boolean));
      if (ids.size) return ids.size === 1 ? ids.values().next().value : '';
    }
    return '';
  };
  // The backend uses the same identity lookup; this branch creates no UI.
  if (payload === null) return activeThread();
  if (window[NAME]?.version === VERSION) return window[NAME].update(payload);
  window[NAME]?.stop();
  const fmt = value => typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : '—';
  const count = value => typeof value === 'number' ? value.toLocaleString('zh-CN') : '—';
  let data = payload, timer, stopped = false, lastUpdate = Date.now();
  let enabled = true, button;
  try { enabled = window.localStorage.getItem(STORAGE_KEY) !== 'false'; } catch {}
  const expanded = new Set();
  const style = document.createElement('style');
  style.id = STYLE_ID;
  style.textContent = `
    [${BUTTON_ATTR}] {pointer-events:auto;flex:none;display:inline-flex;align-items:center;
      margin:0 8px 0 0;padding:5px 10px;border-radius:7px;cursor:pointer;
      border:1px solid color-mix(in srgb,CanvasText 18%,transparent);
      background:color-mix(in srgb,CanvasText 5%,transparent);color:var(--color-text-secondary,CanvasText);
      font:12px/1.4 "Segoe UI","Microsoft YaHei UI",-apple-system,sans-serif;-webkit-app-region:no-drag;}
    [${BUTTON_ATTR}]::before {content:"";width:5px;height:5px;border-radius:50%;margin-right:5px;background:currentColor;opacity:.55;}
    [${BUTTON_ATTR}][aria-pressed="true"] {color:var(--color-text,CanvasText);border-color:color-mix(in srgb,#49a877 50%,transparent);}
    [${BUTTON_ATTR}][aria-pressed="true"]::before {background:#49a877;opacity:1;}
    [${BUTTON_ATTR}]:focus-visible {outline:2px solid #3982f7;outline-offset:2px;}
    [${ATTR}] {display:block;box-sizing:border-box;max-width:100%;width:100%;margin:8px 0;
      color:var(--color-text-secondary,CanvasText);background:color-mix(in srgb,CanvasText 4%,transparent);
      border:1px solid color-mix(in srgb,CanvasText 13%,transparent);border-radius:8px;
      font:12px/1.6 "Segoe UI","Microsoft YaHei UI",-apple-system,sans-serif;overflow-wrap:anywhere;}
    [${ATTR}] summary{display:flex;align-items:center;flex-wrap:wrap;gap:4px 12px;
      cursor:pointer;padding:7px 10px;list-style:none;user-select:none;}
    [${ATTR}] summary::-webkit-details-marker{display:none}
    [${ATTR}] summary:focus-visible{outline:2px solid #3982f7;outline-offset:2px;border-radius:7px}
    [${ATTR}] strong{font-weight:600;color:var(--color-text,CanvasText);font-variant-numeric:tabular-nums}
    [${ATTR}] [data-tps-action]{margin-left:auto;white-space:nowrap}
    [${ATTR}] [data-tps-body]{border-top:1px solid color-mix(in srgb,CanvasText 10%,transparent);padding:12px}
    [${ATTR}] dl{margin:0;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:6px 18px;}
    [${ATTR}] dt,[${ATTR}] dd{margin:0;font:inherit} [${ATTR}] dd{text-align:right;font-variant-numeric:tabular-nums;max-width:280px}
    [${ATTR}] p{margin:9px 0 0;font:inherit;opacity:.78}
  `;
  document.head.append(style);

  function element(tag, text) {
    const el = document.createElement(tag);
    if (text !== undefined) el.textContent = text;
    return el;
  }

  function finalNode(turn) {
    const ids = new Set((turn.final_ids || []).map(id => encodeURIComponent(id)));
    // Exact IDs only. Never infer a match from reply text or DOM position.
    for (const node of activeNodes('[data-local-conversation-item-target-ids]')) {
      if ((node.getAttribute('data-local-conversation-item-target-ids') || '').split(/\s+/).some(id => ids.has(id))) {
        return node.closest('[data-local-conversation-final-assistant]') ||
          node.querySelector('[data-local-conversation-final-assistant]') || node;
      }
    }
    const keys = new Set([`assistant:${turn.turn_id}`, turn.turn_id,
      ...(turn.user_ids || []).map(id => `user:${id}`)]);
    for (const node of activeNodes('[data-content-search-turn-key],[data-content-search-assistant-turn-key],[data-turn-key]')) {
      if (keys.has(node.getAttribute('data-content-search-turn-key')) ||
          keys.has(node.getAttribute('data-content-search-assistant-turn-key')) ||
          keys.has(node.getAttribute('data-turn-key'))) {
        const replies = node.matches('[data-local-conversation-final-assistant]') ? [node] :
          Array.from(node.querySelectorAll('[data-local-conversation-final-assistant]'));
        if (replies.length === 1) return replies[0];
      }
    }
    if (turn.status === 'running') {
      // Before the final reply exists, use the exact active-thread composer slot.
      // Once the reply is rendered, the exact-ID match above moves the same chip.
      const thread = activeThread();
      const slots = activeNodes('[data-above-composer-portal]')
        .filter(node => node.getAttribute('data-above-composer-fixed-content-portal') === null &&
          norm(node.getAttribute('data-above-composer-conversation-id')) === thread);
      if (slots.length === 1) return slots[0];
    }
    return null;
  }

  function placement(node) {
    if (node.matches('[data-above-composer-portal]')) return {host: node, after: null};
    let scope = node;
    for (let depth = 0; depth < 3 && scope; depth++, scope = scope.parentElement) {
      // Do not ascend into a container shared by several replies.
      if (scope.querySelectorAll('[data-local-conversation-final-assistant]').length > 1) break;
      const times = scope.querySelectorAll('[data-assistant-message-sent-time]');
      if (times.length === 1 && times[0].parentElement?.parentElement) {
        const after = times[0].parentElement;
        return {host: after.parentElement, after};
      }
    }
    return {host: node, after: null};
  }

  function makeChip(turn, key) {
    const chip = element('details'); chip.setAttribute(ATTR, key); chip.lang = 'zh-CN';
    const summary = element('summary');
    const state = turn.status === 'running' ? '本轮实时均值' : turn.status === 'interrupted' ? '已中断均值' : '本轮平均';
    const primary = `${state} TPS ${fmt(turn.wall_tps)} tok/s`;
    summary.append(element('strong', primary));
    summary.append(element('span', `输出 ${count(turn.output_tokens)} tok`));
    if (turn.status === 'running') {
      const age = turn.reported_at == null ? null : Math.max(0, Date.now() / 1000 - turn.reported_at);
      summary.append(element('span', age == null ? '等待计数报告' : `计数 ${fmt(age)} 秒前`));
    }
    const action = element('span', '提示详情 ▾'); action.setAttribute('data-tps-action', ''); summary.append(action);
    const body = element('div'); body.setAttribute('data-tps-body', '');
    const dl = element('dl');
    const rows = [
      ['总输出（含推理）', `${count(turn.output_tokens)} tokens`],
      ['整轮耗时', `${fmt(turn.wall_seconds)} 秒`],
      ['模型', turn.models?.length > 1 ? `混合模型：${turn.models.join(' / ')}` : turn.models?.[0] || '未记录'],
    ];
    rows.forEach(([label, value]) => dl.append(element('dt', label), element('dd', value)));
    body.append(dl,
      element('p', '平均 TPS = 本轮已报告输出 token ÷ 整轮耗时。每秒刷新，token 计数在模型请求完成后更新。'),
      element('p', '输出已含推理与工具调用；耗时含工具与请求等待。不是逐秒解码速度。'));
    if (turn.notes?.length) body.append(element('p', `统计说明：${turn.notes.join('；')}`));
    chip.append(summary, body); chip.open = expanded.has(key);
    summary.setAttribute('aria-expanded', String(chip.open));
    chip.addEventListener('toggle', () => {
      if (chip.open) expanded.add(key); else expanded.delete(key);
      summary.setAttribute('aria-expanded', String(chip.open));
      action.textContent = chip.open ? '收起详情 ▴' : '提示详情 ▾';
    });
    chip.__signature = JSON.stringify(turn);
    return chip;
  }

  function render() {
    timer = null;
    if (stopped) return;
    const newTab = activeNodes('[data-app-shell-workspace-layout-toggle="main"]')[0];
    const toolbar = newTab?.closest('[data-app-shell-header-slot-content]') ||
      newTab?.closest('[data-app-shell-header-slot="end"]');
    if (!button) {
      button = element('button'); button.type = 'button'; button.setAttribute(BUTTON_ATTR, '');
      button.addEventListener('click', () => api.setEnabled(!enabled));
    }
    button.textContent = enabled ? 'TPS 开' : 'TPS 关';
    button.setAttribute('aria-pressed', String(enabled));
    button.setAttribute('aria-label', enabled ? '关闭 TPS 统计' : '开启 TPS 统计');
    button.title = enabled ? 'TPS 已开启；点击关闭统计' : 'TPS 已关闭；点击恢复统计';
    if (toolbar && button.parentElement !== toolbar) toolbar.prepend(button);
    else if (!toolbar) button.remove();
    const thread = activeThread();
    const existing = new Map(Array.from(document.querySelectorAll(`[${ATTR}]`), el => [el.getAttribute(ATTR), el]));
    const kept = new Set();
    if (enabled && thread && thread === norm(data.thread_id)) {
      for (const turn of data.turns || []) {
        const node = finalNode(turn);
        if (!node) continue;
        const {host, after} = placement(node);
        const key = `${thread}/${turn.turn_id}`;
        let chip = existing.get(key);
        if (chip && chip.__signature !== JSON.stringify(turn)) {chip.remove(); chip = null;}
        if (!chip) chip = makeChip(turn, key);
        if (after && (chip.parentElement !== host || chip.previousElementSibling !== after)) after.after(chip);
        else if (!after && chip.parentElement !== host) host.append(chip);
        kept.add(chip);
      }
    }
    document.querySelectorAll(`[${ATTR}]`).forEach(chip => {if (!kept.has(chip)) chip.remove();});
    return {ok: true, thread_id: thread, rendered: kept.size, enabled, toggle_rendered: button.isConnected};
  }

  function schedule(records) {
    if (records.every(r => r.target.nodeType === 1 && (r.target.closest(`[${ATTR}],[${BUTTON_ATTR}]`) || r.target.id === STYLE_ID))) return;
    if (!timer) timer = setTimeout(render, 120);
  }
  const observer = new MutationObserver(schedule);
  observer.observe(document.body, {childList:true, subtree:true, attributes:true,
    attributeFilter:['data-app-action-sidebar-thread-active','data-conversation-id',
      'data-above-composer-conversation-id','data-app-shell-active-page',
      'data-local-conversation-item-target-ids','data-content-search-turn-key',
      'data-content-search-assistant-turn-key','data-turn-key']});
  const watchdog = setInterval(() => {if (Date.now() - lastUpdate > 15000) api.stop();}, 5000);
  const onStorage = event => {if (event.key === STORAGE_KEY) {enabled = event.newValue !== 'false'; render();}};
  window.addEventListener('storage', onStorage);
  const api = {
    version: VERSION,
    isEnabled() { return enabled; },
    setEnabled(value) {
      enabled = Boolean(value);
      try { window.localStorage.setItem(STORAGE_KEY, String(enabled)); } catch {}
      return render();
    },
    update(next) { data = next; lastUpdate = Date.now(); return render(); },
    stop() {
      stopped = true; observer.disconnect(); clearTimeout(timer); clearInterval(watchdog);
      document.querySelectorAll(`[${ATTR}]`).forEach(el => el.remove()); style.remove();
      button?.remove(); window.removeEventListener('storage', onStorage);
      delete window[NAME];
    },
  };
  window[NAME] = api;
  return render();
})
