/* OpenCrawlerLab 桌面控制台：仅与本机 127.0.0.1 服务通信。
   接口契约见 docs/DESKTOP_API.md，Python / Java / C++ 三版共用本文件。 */
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const FIELDS = ['concurrency', 'per_domain_concurrency', 'default_delay_ms',
    'per_domain_rps', 'max_pages', 'max_depth', 'time_budget_seconds',
    'storage', 'output_dir', 'extract_mode'];
  const CHECKS = ['respect_robots', 'obey_crawl_delay', 'adaptive_concurrency',
    'dedupe_content', 'follow_sitemaps'];
  const NUMERIC = new Set(['concurrency', 'per_domain_concurrency', 'default_delay_ms',
    'per_domain_rps', 'max_pages', 'max_depth', 'time_budget_seconds']);
  let defaults = null;
  let running = false;

  const api = async (path, options) => {
    const resp = await fetch(path, options);
    let body = {};
    try { body = await resp.json(); } catch (_) { /* 忽略非 JSON 响应 */ }
    if (!resp.ok) throw new Error(body.error || `HTTP ${resp.status}`);
    return body;
  };
  const post = (path, data) => api(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data || {})
  });
  const note = (text, kind) => { $('configNote').textContent = text; $('configNote').className = 'note ' + (kind || ''); };
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function fill(config) {
    $('seeds').value = (config.seeds || []).join('\n');
    FIELDS.forEach((k) => { if (config[k] !== undefined) $(k).value = config[k]; });
    CHECKS.forEach((k) => { if (config[k] !== undefined) $(k).checked = !!config[k]; });
  }
  function collect() {
    const cfg = {};
    FIELDS.forEach((k) => {
      const raw = $(k).value;
      cfg[k] = NUMERIC.has(k) ? (parseFloat(raw) || 0) : raw;
    });
    CHECKS.forEach((k) => { cfg[k] = $(k).checked; });
    cfg.seeds = $('seeds').value.split('\n').map((s) => s.trim()).filter(Boolean);
    return cfg;
  }
  function setRunning(value) {
    running = value;
    $('startBtn').disabled = value;
    $('stopBtn').disabled = !value;
    const badge = $('statusBadge');
    badge.className = 'badge' + (value ? ' running' : '');
    badge.innerHTML = '<i></i> ' + (value ? '正在抓取' : '空闲');
  }
  function renderStatus(s) {
    setRunning(!!s.running);
    if (s.version) $('versionLine').textContent = `桌面控制台 · v${s.version} · 通用合规爬虫`;
    const set = (k, v) => { const el = document.querySelector(`[data-k="${k}"]`); if (el) el.textContent = v; };
    set('requests', s.requests ?? 0); set('succeeded', s.succeeded ?? 0);
    set('items', s.items ?? 0); set('rps', (s.requests_per_second ?? 0).toFixed(2));
    set('queued', (s.frontier && s.frontier.queued) ?? 0);
    set('concurrency', s.adaptive && s.adaptive.enabled ? s.adaptive.limit : '固定');
    if (s.error) { $('statusBadge').className = 'badge error'; $('statusBadge').innerHTML = '<i></i> 出错'; note(s.error, 'bad'); }
    $('footerStatus').textContent = s.running
      ? `运行中 · 已用时 ${s.elapsed_seconds ?? 0}s · ${s.inflight ?? 0} 个请求进行中`
      : (s.summary ? `上次结束：${s.summary.stop_reason || '完成'}` : '服务已连接 · 等待启动');
  }
  function addLog(entry) {
    const box = $('logs');
    const line = document.createElement('div');
    line.className = 'log-line ' + esc(entry.level || 'INFO');
    line.innerHTML = `<span class="lv">${esc(entry.level)}</span><span>${esc(entry.message)}</span>`;
    box.appendChild(line);
    while (box.childElementCount > 200) box.removeChild(box.firstChild);
    box.scrollTop = box.scrollHeight;
  }
  async function refreshResults() {
    try {
      const data = await api('/api/results?limit=100');
      const rows = (data.items || []).slice().reverse();
      $('resultCount').textContent = `最近 ${rows.length} 条`;
      if (!rows.length) return;
      $('resultBody').innerHTML = rows.map((it) => {
        const d = it.data || it;
        const title = d.title || d.name || '(无标题)';
        const time = (it.fetched_at || it.timestamp || '').toString().slice(0, 19);
        return `<tr><td title="${esc(it.url)}">${esc(it.url)}</td><td>${esc(title)}</td>` +
          `<td>${esc(it.kind || 'page')}</td><td>${esc(time)}</td></tr>`;
      }).join('');
    } catch (e) { /* 结果接口暂不可用 */ }
  }

  $('startBtn').addEventListener('click', async () => {
    const cfg = collect();
    if (!cfg.seeds.length) { note('请至少填写一个起始 URL', 'bad'); return; }
    try {
      note('正在启动…');
      const result = await post('/api/start', cfg);
      renderStatus(result.status || {});
      note('任务已启动', 'ok');
      $('logs').innerHTML = '';
    } catch (e) { note(`启动失败：${e.message}`, 'bad'); }
  });
  $('stopBtn').addEventListener('click', async () => {
    try { await post('/api/stop'); note('已请求优雅停止，正在保存进度…', 'ok'); }
    catch (e) { note(`停止失败：${e.message}`, 'bad'); }
  });
  $('validateBtn').addEventListener('click', async () => {
    try {
      const r = await post('/api/validate', collect());
      note('配置有效' + (r.warnings && r.warnings.length ? ` · 提醒：${r.warnings.join('；')}` : ''), 'ok');
    } catch (e) { note(`配置无效：${e.message}`, 'bad'); }
  });
  $('resetBtn').addEventListener('click', () => { if (defaults) { fill(defaults); note('已恢复默认配置', 'ok'); } });
  $('exportBtn').addEventListener('click', () => { window.location.href = '/api/export'; });

  async function boot() {
    try {
      defaults = await api('/api/config');
      fill(defaults);
      renderStatus(await api('/api/status'));
      const logData = await api('/api/logs');
      (logData.items || []).forEach(addLog);
      await refreshResults();
      note('配置已加载，可以开始抓取', 'ok');
    } catch (e) { note(`无法连接本地服务：${e.message}`, 'bad'); }

    const stream = new EventSource('/api/events');
    stream.addEventListener('status', (ev) => {
      try { renderStatus(JSON.parse(ev.data)); } catch (_) { /* 忽略坏帧 */ }
    });
    stream.addEventListener('log', (ev) => {
      try { addLog(JSON.parse(ev.data)); } catch (_) { /* 忽略坏帧 */ }
    });
    stream.onopen = () => { $('footerStatus').dataset.live = '1'; };
    stream.onerror = () => { $('statusBadge').className = 'badge error'; };
    setInterval(refreshResults, 4000);
  }
  boot();
})();
