/* OpenCrawlerLab 桌面控制台 v0.3 · 零前端依赖，只与本机 127.0.0.1 服务通信。
   接口契约见 docs/DESKTOP_API.md，Python / Java / C++ 三版共用本文件（字节级一致）。
   设计原则：新字段优先、旧服务端降级可用；所有来自抓取结果的文本均转义后再渲染。 */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const FIELDS = ['concurrency', 'per_domain_concurrency', 'default_delay_ms',
    'per_domain_rps', 'max_pages', 'max_depth', 'time_budget_seconds',
    'storage', 'output_dir', 'extract_mode', 'user_agent'];
  const CHECKS = ['respect_robots', 'obey_crawl_delay', 'respect_nofollow',
    'adaptive_concurrency', 'dedupe_content', 'follow_sitemaps'];
  const NUMERIC = new Set(['concurrency', 'per_domain_concurrency', 'default_delay_ms',
    'per_domain_rps', 'max_pages', 'max_depth', 'time_budget_seconds']);
  const PRESET_KEY = 'opencrawler.presets.v1';
  const THEME_KEY = 'opencrawler.theme.v1';
  const IMPL_LABEL = { python: 'Python', java: 'Java 21', cpp: 'C++20', cxx: 'C++20' };

  const st = {
    defaults: null, info: null, running: false,
    rows: [], filtered: [], detailIndex: -1,
    logs: [], pendingLogs: [], paused: false,
    trend: [], lastSseAt: 0, stream: null, reconnectTimer: null,
    presets: {}, toastTimer: null
  };

  /* ------------------------------------------------------------ 基础工具 */
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const num = (v) => Number(v) || 0;
  const fmtInt = (v) => num(v).toLocaleString('zh-CN');
  const fmtBytes = (v) => {
    const n = num(v);
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    if (n < 1024 * 1024 * 1024) return `${(n / 1048576).toFixed(1)} MB`;
    return `${(n / 1073741824).toFixed(2)} GB`;
  };
  const fmtMs = (v) => {
    const n = num(v);
    return n > 0 ? (n >= 1000 ? `${(n / 1000).toFixed(2)} s` : `${Math.round(n)} ms`) : '—';
  };
  const clock = () => new Date().toTimeString().slice(0, 8);
  const rowData = (row) => (row && row.data && typeof row.data === 'object') ? row.data : (row || {});

  const api = async (path, options) => {
    const resp = await fetch(path, options);
    let body = {};
    try { body = await resp.json(); } catch (_) { /* 允许非 JSON 响应 */ }
    if (!resp.ok) {
      const err = new Error(body.error || `HTTP ${resp.status}`);
      err.status = resp.status;
      err.body = body;
      throw err;
    }
    return body;
  };
  const post = (path, data) => api(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data || {})
  });

  const note = (text, kind) => {
    const el = $('configNote');
    el.textContent = text || '';
    el.className = 'note ' + (kind || '');
  };
  const toast = (text, kind) => {
    const el = $('toast');
    if (!el) return;
    el.textContent = text;
    el.className = 'toast ' + (kind || '');
    el.hidden = false;
    clearTimeout(st.toastTimer);
    st.toastTimer = setTimeout(() => { el.hidden = true; }, 3200);
  };
  const fail = (label, e) => {
    note(`${label}：${e.message}`, 'bad');
    toast(`${label}：${e.message}`, 'bad');
  };

  const store = {
    get(key, fallback) {
      try { const v = localStorage.getItem(key); return v === null ? fallback : v; }
      catch (_) { return fallback; }
    },
    set(key, value) { try { localStorage.setItem(key, value); } catch (_) { /* 隐私模式 */ } }
  };

  /* ------------------------------------------------------------ 主题与实现标识 */
  const applyTheme = (theme) => {
    document.documentElement.setAttribute('data-theme', theme === 'light' ? 'light' : 'dark');
    store.set(THEME_KEY, theme === 'light' ? 'light' : 'dark');
  };
  const renderInfo = (info) => {
    if (!info) return;
    const impl = info.implementation || info.language || '';
    const label = IMPL_LABEL[impl] || impl || '未知实现';
    const version = info.version || '0.3.0';
    $('implBadge').textContent = `${label} · v${version}`;
    $('versionLine').textContent = `桌面控制台 · ${label} · ${info.platform || '本机'}`;
    if (Array.isArray(info.compliance_defaults) && info.compliance_defaults.length) {
      $('complianceBox').querySelector('span').textContent = info.compliance_defaults.join(' · ');
    }
    // 只有 Python 版提供 SQLite 后端；按实现裁剪选项，避免用户选到必然校验失败的值。
    const storage = $('storage');
    const sqlite = storage && storage.querySelector('option[value="sqlite"]');
    if (sqlite && impl && impl !== 'python') {
      if (storage.value === 'sqlite') storage.value = 'jsonl';
      sqlite.remove();
    }
  };

  /* ------------------------------------------------------------ 配置表单与预设 */
  const fill = (config) => {
    if (!config) return;
    $('seeds').value = (config.seeds || []).join('\n');
    FIELDS.forEach((k) => { if (config[k] !== undefined && $(k)) $(k).value = config[k]; });
    CHECKS.forEach((k) => { if (config[k] !== undefined && $(k)) $(k).checked = !!config[k]; });
  };
  const collect = () => {
    const cfg = {};
    FIELDS.forEach((k) => {
      if (!$(k)) return;
      const raw = $(k).value;
      cfg[k] = NUMERIC.has(k) ? (parseFloat(raw) || 0) : raw;
    });
    CHECKS.forEach((k) => { if ($(k)) cfg[k] = $(k).checked; });
    cfg.seeds = $('seeds').value.split('\n').map((s) => s.trim()).filter(Boolean);
    return cfg;
  };
  const readPresets = () => {
    try { const v = JSON.parse(store.get(PRESET_KEY, '{}')); return (v && typeof v === 'object') ? v : {}; }
    catch (_) { return {}; }
  };
  const renderPresets = (selected) => {
    const sel = $('presetSelect');
    const names = Object.keys(st.presets).sort();
    sel.innerHTML = '<option value="">— 未保存预设 —</option>' +
      names.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join('');
    if (selected && st.presets[selected]) sel.value = selected;
  };
  const savePreset = () => {
    const name = $('presetName').value.trim();
    if (!name) { note('请先填写预设名称', 'bad'); return; }
    st.presets[name] = collect();
    store.set(PRESET_KEY, JSON.stringify(st.presets));
    renderPresets(name);
    note(`预设「${name}」已保存`, 'ok');
  };
  const download = (filename, text, mime) => {
    const blob = new Blob([text], { type: mime || 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const rowsToCsv = (rows) => {
    const head = ['url', 'title', 'kind', 'status', 'elapsed_ms', 'fetched_at'];
    const cell = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
    const lines = [head.join(',')];
    rows.forEach((row) => {
      const d = rowData(row);
      lines.push([
        row.url || d.url || '', d.title || d.name || '', row.kind || d.kind || 'page',
        d.status ?? '', d.elapsed_ms ?? '',
        row.fetched_at || row.crawled_at || d.fetched_at || ''
      ].map(cell).join(','));
    });
    return '\ufeff' + lines.join('\r\n') + '\r\n';
  };

  /* ------------------------------------------------------------ 状态、指标与趋势 */
  const setRunning = (value) => {
    st.running = !!value;
    $('startBtn').disabled = st.running;
    $('stopBtn').disabled = !st.running;
  };
  const setConn = (state, text) => {
    const el = $('connBadge');
    el.className = 'conn ' + state;
    el.querySelector('span').textContent = text;
  };
  const renderStatus = (s) => {
    if (!s || typeof s !== 'object') return;
    setRunning(!!s.running);
    const set = (k, v) => { const el = document.querySelector(`[data-k="${k}"]`); if (el) el.textContent = v; };
    const f = s.frontier || {};
    set('requests', fmtInt(s.requests));
    set('succeeded', fmtInt(s.succeeded));
    set('failed', fmtInt(s.failed));
    set('skipped', fmtInt(s.skipped));
    set('items', fmtInt(s.items));
    set('duplicates', fmtInt(s.duplicates));
    set('bytes', fmtBytes(s.bytes));
    set('rps', num(s.requests_per_second).toFixed(2));
    set('queued', fmtInt(f.queued));
    set('done', fmtInt(f.done));
    set('inflight', fmtInt(s.inflight));
    const adaptive = s.adaptive || {};
    set('concurrency', adaptive.enabled ? adaptive.limit : '固定');
    $('adaptiveHint').textContent = adaptive.enabled ? 'AIMD 自适应' : '固定并发';

    st.trend.push(num(s.requests_per_second));
    if (st.trend.length > 60) st.trend.shift();
    drawTrend();

    const badge = $('statusBadge');
    if (s.error) {
      badge.className = 'badge error';
      badge.innerHTML = '<i></i> 出错';
      note(s.error, 'bad');
    } else {
      badge.className = 'badge' + (st.running ? ' running' : '');
      badge.innerHTML = '<i></i> ' + (st.running ? '正在抓取' : '空闲');
    }
    $('footerStatus').textContent = st.running
      ? `运行中 · 已用时 ${num(s.elapsed_seconds).toFixed(0)}s · ${fmtInt(s.inflight)} 个请求进行中`
      : (s.summary ? `上次结束：${s.summary.stop_reason || '完成'}` : '服务已连接 · 等待启动');
  };
  const drawTrend = () => {
    const line = $('trendLine');
    if (!line) return;
    const data = st.trend.length ? st.trend : [0];
    const max = Math.max(1, ...data);
    const step = data.length > 1 ? 600 / (data.length - 1) : 600;
    const points = data.map((v, i) =>
      `${(i * step).toFixed(1)},${(42 - (v / max) * 38).toFixed(1)}`).join(' ');
    line.setAttribute('points', points);
  };

  /* ------------------------------------------------------------ 结果表格与详情 */
  const renderResults = () => {
    const body = $('resultBody');
    const wrap = body.closest('.table-wrap');
    const scrollTop = wrap ? wrap.scrollTop : 0;
    $('resultCount').textContent = `显示 ${st.filtered.length} / 最近 ${st.rows.length} 条`;
    if (!st.filtered.length) {
      body.innerHTML = `<tr><td colspan="6" class="empty">${st.rows.length
        ? '没有符合筛选条件的结果' : '暂无结果，配置好后点击「开始抓取」'}</td></tr>`;
      return;
    }
    body.innerHTML = st.filtered.map((row, i) => {
      const d = rowData(row);
      const title = d.title || d.name || '(无标题)';
      const time = String(row.fetched_at || row.crawled_at || d.fetched_at || d.timestamp || '').slice(0, 19);
      const code = d.status ?? row.status ?? '';
      const codeClass = code >= 200 && code < 400 ? 'ok' : (code ? 'bad' : '');
      return `<tr data-i="${i}" tabindex="0" title="点击查看条目详情">` +
        `<td title="${esc(row.url || d.url || '')}">${esc(row.url || d.url || '')}</td>` +
        `<td>${esc(title)}</td><td>${esc(row.kind || d.kind || 'page')}</td>` +
        `<td class="code ${codeClass}">${esc(code)}</td><td>${fmtMs(d.elapsed_ms)}</td>` +
        `<td>${esc(time)}</td></tr>`;
    }).join('');
    if (wrap) wrap.scrollTop = scrollTop;
  };
  const openDetail = (index) => {
    const row = st.filtered[index];
    if (!row) return;
    st.detailIndex = index;
    $('detailPanel').hidden = false;
    $('detailJson').textContent = JSON.stringify(row, null, 2);
    const url = row.url || rowData(row).url || '';
    const link = $('openUrlLink');
    link.href = /^https?:\/\//i.test(url) ? url : '#';
    link.style.pointerEvents = url ? '' : 'none';
    link.style.opacity = url ? '' : '.45';
  };
  const closeDetail = () => { $('detailPanel').hidden = true; st.detailIndex = -1; };

  const refreshResults = async () => {
    const q = $('resultSearch').value.trim();
    const kind = $('resultKind').value;
    const params = new URLSearchParams({ limit: '300' });
    if (q) params.set('q', q);
    if (kind) params.set('kind', kind);
    try {
      const data = await api('/api/results?' + params.toString());
      st.rows = (data.items || []).slice().reverse();
      // 旧版服务端不认识 q/kind，这里再本地过滤一次，保证行为一致。
      const needle = q.toLowerCase();
      st.filtered = st.rows.filter((row) => {
        if (kind && String(row.kind || rowData(row).kind || 'page') !== kind) return false;
        if (!needle) return true;
        const d = rowData(row);
        return `${row.url || d.url || ''} ${d.title || d.name || ''}`.toLowerCase().includes(needle);
      });
      renderResults();
    } catch (e) { /* 服务重启期间静默，下一轮轮询自动恢复 */ }
  };

  /* ------------------------------------------------------------ 日志 */
  const renderLogs = () => {
    const box = $('logs');
    const wrapScroll = box.scrollTop;
    const level = $('logLevel').value;
    const needle = $('logSearch').value.trim().toLowerCase();
    const visible = st.logs.filter((e) =>
      (!level || e.level === level) &&
      (!needle || String(e.message || '').toLowerCase().includes(needle)));
    box.innerHTML = visible.map((e) =>
      `<div class="log-line ${esc(e.level || 'INFO')}">` +
      `<span class="ts">${esc(e.time || '')}</span>` +
      `<span class="lv">${esc(e.level || 'INFO')}</span>` +
      `<span>${esc(e.message)}</span></div>`).join('');
    $('logCount').textContent = `${visible.length} / ${st.logs.length} 条` +
      (st.paused ? ` · 已暂停（缓冲 ${st.pendingLogs.length}）` : '');
    if ($('autoScrollChk').checked) box.scrollTop = box.scrollHeight;
    else box.scrollTop = wrapScroll;
  };
  const addLog = (entry) => {
    if (!entry || typeof entry !== 'object') return;
    const item = {
      seq: entry.seq, level: entry.level || 'INFO',
      message: entry.message || '', source: entry.source || '', time: clock()
    };
    if (st.paused) { st.pendingLogs.push(item); renderLogs(); return; }
    st.logs.push(item);
    while (st.logs.length > 400) st.logs.shift();
    renderLogs();
  };
  const flushLogs = () => {
    st.logs.push(...st.pendingLogs);
    st.pendingLogs = [];
    while (st.logs.length > 400) st.logs.shift();
    renderLogs();
  };

  /* ------------------------------------------------------------ SSE 与轮询兜底 */
  const markSse = () => { st.lastSseAt = Date.now(); setConn('live', '实时'); };
  const connectSse = () => {
    if (typeof EventSource === 'undefined') { setConn('poll', '轮询模式'); return; }
    if (st.stream) { try { st.stream.close(); } catch (_) { /* 已关闭 */ } }
    const stream = new EventSource('/api/events');
    st.stream = stream;
    stream.addEventListener('status', (ev) => {
      markSse();
      try { renderStatus(JSON.parse(ev.data)); } catch (_) { /* 忽略坏帧 */ }
    });
    stream.addEventListener('log', (ev) => {
      markSse();
      try { addLog(JSON.parse(ev.data)); } catch (_) { /* 忽略坏帧 */ }
    });
    stream.onopen = () => setConn('live', '实时');
    stream.onerror = () => setConn('retry', '重连中');
  };
  const watchdog = () => {
    if (st.lastSseAt && Date.now() - st.lastSseAt > 20000) {
      setConn('poll', '轮询模式');
      if (!st.reconnectTimer) {
        st.reconnectTimer = setTimeout(() => { st.reconnectTimer = null; connectSse(); }, 15000);
      }
    }
  };
  const pollStatus = async () => {
    try {
      renderStatus(await api('/api/status'));
      if ($('connBadge').className.indexOf('poll') === -1 &&
          $('connBadge').className.indexOf('live') === -1) setConn('poll', '轮询模式');
    } catch (_) { setConn('down', '服务已断开'); }
  };

  /* ------------------------------------------------------------ 事件绑定 */
  const bind = () => {
    $('startBtn').addEventListener('click', async () => {
      const cfg = collect();
      if (!cfg.seeds.length) { note('请至少填写一个起始 URL', 'bad'); $('seeds').focus(); return; }
      try {
        note('正在启动…');
        const result = await post('/api/start', cfg);
        renderStatus(result.status || { running: true });
        setRunning(true);
        note('任务已启动', 'ok');
        st.logs = []; st.pendingLogs = []; renderLogs();
        addLog({ level: 'INFO', message: `任务启动：${cfg.seeds.length} 个种子，并发 ${cfg.concurrency}`, source: 'desktop' });
        refreshResults();
      } catch (e) { fail('启动失败', e); }
    });
    $('stopBtn').addEventListener('click', async () => {
      try { await post('/api/stop'); note('已请求优雅停止，正在保存进度…', 'ok'); toast('已请求优雅停止', 'ok'); }
      catch (e) { fail('停止失败', e); }
    });
    $('saveConfigBtn').addEventListener('click', async () => {
      try { await post('/api/config', collect()); note('配置已保存到服务端', 'ok'); }
      catch (e) { fail('保存失败', e); }
    });
    $('validateBtn').addEventListener('click', async () => {
      try {
        const r = await post('/api/validate', collect());
        if (r.valid === false) { note(`配置无效：${r.error || '未知原因'}`, 'bad'); return; }
        const warns = r.warnings || [];
        note('配置有效' + (warns.length ? ` · 提醒：${warns.join('；')}` : ''), 'ok');
      } catch (e) {
        const detail = (e.body && e.body.error) || e.message;
        note(`配置无效：${detail}`, 'bad');
      }
    });
    $('resetBtn').addEventListener('click', () => {
      if (st.defaults) { fill(st.defaults); note('已恢复默认配置', 'ok'); }
    });

    $('savePresetBtn').addEventListener('click', savePreset);
    $('loadPresetBtn').addEventListener('click', () => {
      const name = $('presetSelect').value;
      if (!name || !st.presets[name]) { note('请先选择一个预设', 'bad'); return; }
      fill(st.presets[name]); $('presetName').value = name;
      note(`已载入预设「${name}」（点击开始或保存配置生效）`, 'ok');
    });
    $('deletePresetBtn').addEventListener('click', () => {
      const name = $('presetSelect').value;
      if (!name) { note('请先选择一个预设', 'bad'); return; }
      delete st.presets[name];
      store.set(PRESET_KEY, JSON.stringify(st.presets));
      renderPresets(); note(`已删除预设「${name}」`, 'ok');
    });
    $('exportPresetBtn').addEventListener('click', () => {
      download('opencrawler-presets.json', JSON.stringify(st.presets, null, 2), 'application/json');
      note('预设已导出', 'ok');
    });
    $('importPresetBtn').addEventListener('click', () => $('presetFile').click());
    $('presetFile').addEventListener('change', (ev) => {
      const file = ev.target.files && ev.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => {
        try {
          const data = JSON.parse(String(reader.result));
          if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('不是预设对象');
          st.presets = Object.assign(st.presets, data);
          store.set(PRESET_KEY, JSON.stringify(st.presets));
          renderPresets(); note(`已导入 ${Object.keys(data).length} 个预设`, 'ok');
        } catch (e) { note(`导入失败：${e.message}`, 'bad'); }
      };
      reader.readAsText(file);
      ev.target.value = '';
    });

    $('themeBtn').addEventListener('click', () => {
      const next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
      applyTheme(next);
    });
    $('exportBtn').addEventListener('click', () => {
      const menu = $('exportMenu');
      menu.hidden = !menu.hidden;
      $('exportBtn').setAttribute('aria-expanded', String(!menu.hidden));
    });
    $('exportMenu').addEventListener('click', (ev) => {
      const kind = ev.target && ev.target.getAttribute('data-export');
      if (!kind) return;
      $('exportMenu').hidden = true;
      if (kind === 'jsonl') window.location.href = '/api/export';
      else {
        if (!st.filtered.length) { toast('当前没有可导出的结果', 'bad'); return; }
        download('opencrawler-items.csv', rowsToCsv(st.filtered), 'text/csv;charset=utf-8');
        toast(`已导出 ${st.filtered.length} 条 CSV`, 'ok');
      }
    });

    $('resultBody').addEventListener('click', (ev) => {
      const tr = ev.target.closest('tr[data-i]');
      if (tr) openDetail(Number(tr.getAttribute('data-i')));
    });
    $('resultBody').addEventListener('keydown', (ev) => {
      if (ev.key !== 'Enter') return;
      const tr = ev.target.closest('tr[data-i]');
      if (tr) openDetail(Number(tr.getAttribute('data-i')));
    });
    $('closeDetailBtn').addEventListener('click', closeDetail);
    ['resultSearch', 'resultKind'].forEach((id) => {
      $(id).addEventListener('input', refreshResults);
      $(id).addEventListener('change', refreshResults);
    });
    $('refreshResultsBtn').addEventListener('click', refreshResults);
    $('clearFilterBtn').addEventListener('click', () => {
      $('resultSearch').value = ''; $('resultKind').value = ''; refreshResults();
    });

    ['logLevel', 'logSearch'].forEach((id) => {
      $(id).addEventListener('input', renderLogs);
      $(id).addEventListener('change', renderLogs);
    });
    $('pauseLogBtn').addEventListener('click', () => {
      st.paused = !st.paused;
      $('pauseLogBtn').textContent = st.paused ? '继续' : '暂停';
      if (!st.paused) flushLogs(); else renderLogs();
    });
    $('clearLogBtn').addEventListener('click', () => {
      st.logs = []; st.pendingLogs = []; renderLogs();
    });

    document.addEventListener('keydown', (ev) => {
      const tag = String(ev.target && ev.target.tagName || '').toLowerCase();
      const typing = tag === 'input' || tag === 'textarea' || tag === 'select';
      if ((ev.ctrlKey || ev.metaKey) && ev.key === 'Enter') { ev.preventDefault(); $('startBtn').click(); }
      else if ((ev.ctrlKey || ev.metaKey) && ev.key === '.') { ev.preventDefault(); $('stopBtn').click(); }
      else if (ev.key === '/' && !typing) { ev.preventDefault(); $('resultSearch').focus(); }
      else if (ev.key === 'Escape') { closeDetail(); $('exportMenu').hidden = true; }
    });
    document.addEventListener('click', (ev) => {
      if (!ev.target.closest('.menu')) $('exportMenu').hidden = true;
    });
  };

  /* ------------------------------------------------------------ 启动 */
  const boot = async () => {
    applyTheme(store.get(THEME_KEY, 'dark'));
    st.presets = readPresets();
    renderPresets();
    bind();
    drawTrend();
    renderLogs();

    try { st.info = await api('/api/info'); } catch (_) { st.info = null; }
    try {
      st.defaults = await api('/api/config');
      fill(st.defaults);
    } catch (e) { note(`无法读取配置：${e.message}`, 'bad'); }
    try { renderInfo(st.info || { version: (await api('/api/status')).version }); }
    catch (_) { renderInfo(st.info || { version: '0.3.0' }); }
    if (!st.info) {
      // 旧版服务端没有 /api/info：只显示版本，不猜测实现语言。
      $('implBadge').textContent = '通用实现';
    }
    try {
      const logData = await api('/api/logs');
      (logData.items || []).forEach((e) => addLog(e));
    } catch (_) { /* 日志接口可选 */ }
    await refreshResults();
    try { renderStatus(await api('/api/status')); } catch (_) { /* 下一轮轮询 */ }
    note('配置已加载，可以开始抓取', 'ok');

    connectSse();
    setInterval(pollStatus, 3000);
    setInterval(refreshResults, 5000);
    setInterval(watchdog, 5000);
  };

  boot();
})();
