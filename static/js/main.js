/**
 * 台灣ETF智慧選股與投資組合分析 - 前端主邏輯
 * 技術：原生 JavaScript + Plotly.js
 */

// ══════════════════════════════════════
// 全域狀態
// ══════════════════════════════════════
const STATE = {
  etfList:          [],       // 完整ETF清單
  filtered:         [],       // 篩選後顯示的ETF
  selected:         new Set(),    // 使用者勾選的ETF代碼
  period:           '1Y',     // 當前時間區間
  performanceData:  {},       // /api/performance 回傳資料
  corrData:         null,     // /api/correlation 回傳資料
  corrThreshold:    0.7,      // 相關係數排除門檻
  activeETFs:       [],       // 套用相關性篩選後的ETF清單
  portfolioResult:  null,     // /api/portfolio 回傳資料
  categoryFilter:   'all',
  exchangeFilter:   'all',
  searchQuery:      '',
};

// Plotly 暗色圖表主題設定
const PLOT_LAYOUT_BASE = {
  paper_bgcolor: 'rgba(6,13,27,0)',
  plot_bgcolor:  'rgba(6,13,27,0)',
  font:          { family: 'Space Grotesk, sans-serif', color: '#e8edf5', size: 12 },
  margin:        { t: 30, r: 20, b: 50, l: 60 },
  xaxis:         { gridcolor: '#1e3a5f', zerolinecolor: '#1e3a5f', color: '#6b8aaa' },
  yaxis:         { gridcolor: '#1e3a5f', zerolinecolor: '#1e3a5f', color: '#6b8aaa' },
  legend:        { bgcolor: 'rgba(13,27,46,0.8)', bordercolor: '#1e3a5f', borderwidth: 1 },
};

// ETF 類別顏色對應
const CAT_COLORS = {
  '市值型': '#64b4ff',
  '高股息': '#ffd700',
  '主題型': '#00d4ff',
  '債券型': '#b478ff',
  '槓桿型': '#ff4d6d',
  '期貨型': '#ffa03c',
  '其他':   '#888888',
};

// 常用組合 localStorage 鍵名
const PRESETS_KEY = 'etf_presets_v1';

// ══════════════════════════════════════
// 工具函式
// ══════════════════════════════════════

function showLoading(text = '資料載入中…') {
  document.getElementById('loading-text').textContent = text;
  document.getElementById('loading-overlay').classList.remove('hidden');
}
function hideLoading() {
  document.getElementById('loading-overlay').classList.add('hidden');
}

/** 格式化百分比（帶正負符號） */
function fmtPct(v, digits = 2) {
  if (v == null || isNaN(v)) return '—';
  const pct = (v * 100).toFixed(digits);
  return (v >= 0 ? '+' : '') + pct + '%';
}

/** 格式化數值（保留小數位） */
function fmtNum(v, digits = 2) {
  if (v == null || isNaN(v)) return '—';
  return Number(v).toFixed(digits);
}

/** 決定顯示顏色 class */
function colorClass(v) {
  return v >= 0 ? 'pos' : 'neg';
}

/** 解鎖 section */
function unlockSection(id) {
  const el = document.getElementById(id);
  el.classList.remove('locked');
  el.classList.add('active');
}

/** 非同步 fetch 包裝（統一錯誤處理） */
async function apiFetch(url, options = {}) {
  const resp = await fetch(url, options);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const data = await resp.json();
  if (!data.success) throw new Error(data.error || '未知錯誤');
  return data;
}

// ══════════════════════════════════════
// 初始化：載入ETF清單
// ══════════════════════════════════════

async function init() {
  showLoading('ETF清單載入中…');
  try {
    const listData = await apiFetch('/api/etf_list');

    STATE.etfList  = listData.data;
    STATE.filtered = [...STATE.etfList];

    document.getElementById('total-count').textContent = listData.count;
    renderETFTable();
    renderPresets(); // 載入已儲存的常用組合
  } catch (err) {
    alert('ETF清單載入失敗：' + err.message);
  } finally {
    hideLoading();
  }
}

// ══════════════════════════════════════
// ETF 表格渲染
// ══════════════════════════════════════

function applyFilters() {
  STATE.filtered = STATE.etfList.filter(etf => {
    const matchCat  = STATE.categoryFilter === 'all' || etf.category === STATE.categoryFilter;
    const matchExch = STATE.exchangeFilter === 'all' || etf.exchange  === STATE.exchangeFilter;
    const q = STATE.searchQuery.toLowerCase();
    const matchQ    = !q || etf.code.toLowerCase().includes(q) || etf.name.includes(q);
    return matchCat && matchExch && matchQ;
  });
  renderETFTable();
}

function renderETFTable() {
  const tbody = document.getElementById('etf-tbody');
  if (STATE.filtered.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="loading-row">無符合條件的ETF</td></tr>';
    return;
  }

  tbody.innerHTML = STATE.filtered.map(etf => {
    const checked = STATE.selected.has(etf.code) ? 'checked' : '';
    const selClass = STATE.selected.has(etf.code) ? 'selected' : '';
    const catClass = `cat-${etf.category}`;
    return `
      <tr class="${selClass}" data-code="${etf.code}">
        <td><input type="checkbox" class="etf-chk" data-code="${etf.code}" ${checked} /></td>
        <td><span class="etf-code">${etf.code.replace('.TW','.TW').replace('.TWO','.TWO')}</span></td>
        <td>${etf.name}</td>
        <td><span class="cat-badge ${catClass}">${etf.category}</span></td>
        <td><span class="exch-badge">${etf.exchange}</span></td>
      </tr>`;
  }).join('');

  // 勾選事件
  tbody.querySelectorAll('.etf-chk').forEach(chk => {
    chk.addEventListener('change', onCheckboxChange);
  });

  updateSelectedCount();
}

function onCheckboxChange(e) {
  const code = e.target.dataset.code;
  if (e.target.checked) {
    STATE.selected.add(code);
    e.target.closest('tr').classList.add('selected');
  } else {
    STATE.selected.delete(code);
    e.target.closest('tr').classList.remove('selected');
  }
  updateSelectedCount();
}

function updateSelectedCount() {
  const n = STATE.selected.size;
  document.getElementById('selected-count').textContent = n;
  document.getElementById('btn-analyze').disabled = n < 2;
  renderSelectedTags();
}

// ══════════════════════════════════════
// 已選ETF標籤顯示
// ══════════════════════════════════════

function renderSelectedTags() {
  const panel = document.getElementById('selected-tags-panel');
  const container = document.getElementById('selected-tags');

  if (STATE.selected.size === 0) {
    panel.classList.add('hidden');
    return;
  }

  panel.classList.remove('hidden');
  container.innerHTML = [...STATE.selected].map(code => {
    const etf = STATE.etfList.find(e => e.code === code);
    const name = etf ? etf.name : code;
    return `<span class="sel-tag">
      <span class="sel-tag-code">${code.replace('.TW', '').replace('.TWO', '')}</span>
      <span class="sel-tag-name">${name}</span>
      <button class="sel-tag-remove" data-code="${code}" title="移除">×</button>
    </span>`;
  }).join('');

  // 點 × 移除標的
  container.querySelectorAll('.sel-tag-remove').forEach(btn => {
    btn.addEventListener('click', e => {
      const code = e.currentTarget.dataset.code;
      STATE.selected.delete(code);
      renderETFTable();
      updateSelectedCount();
    });
  });
}

// ══════════════════════════════════════
// 常用組合（localStorage 永久記憶）
// ══════════════════════════════════════

function getPresets() {
  try { return JSON.parse(localStorage.getItem(PRESETS_KEY) || '{}'); }
  catch { return {}; }
}

function savePresetsData(presets) {
  localStorage.setItem(PRESETS_KEY, JSON.stringify(presets));
}

function saveCurrentPreset() {
  const nameInput = document.getElementById('preset-name-input');
  const name = nameInput.value.trim();
  if (!name) { alert('請輸入組合名稱'); return; }
  if (STATE.selected.size === 0) { alert('請先選擇至少一檔ETF'); return; }

  const presets = getPresets();
  presets[name] = [...STATE.selected];
  savePresetsData(presets);
  nameInput.value = '';
  renderPresets();
}

function loadPreset(name) {
  const presets = getPresets();
  const codes = presets[name];
  if (!codes || codes.length === 0) return;

  STATE.selected = new Set(codes);
  renderETFTable();
  updateSelectedCount();
}

function deletePreset(name) {
  if (!confirm(`確定刪除「${name}」組合？`)) return;
  const presets = getPresets();
  delete presets[name];
  savePresetsData(presets);
  renderPresets();
}

function renderPresets() {
  const container = document.getElementById('preset-list');
  const presets = getPresets();
  const names = Object.keys(presets);

  if (names.length === 0) {
    container.innerHTML = '<span class="preset-empty">尚無已儲存的組合，請先選擇ETF後輸入名稱儲存</span>';
    return;
  }

  container.innerHTML = names.map(name => {
    const codes = presets[name];
    const codeDisplay = codes
      .map(c => c.replace('.TW', '').replace('.TWO', ''))
      .join('、');
    return `
      <div class="preset-item">
        <div class="preset-info">
          <span class="preset-name">${name}</span>
          <span class="preset-count">${codes.length} 檔</span>
          <span class="preset-codes">${codeDisplay}</span>
        </div>
        <div class="preset-actions">
          <button class="btn-sm preset-load-btn" data-name="${name}">載入</button>
          <button class="btn-sm preset-del-btn" data-name="${name}">刪除</button>
        </div>
      </div>`;
  }).join('');

  container.querySelectorAll('.preset-load-btn').forEach(btn => {
    btn.addEventListener('click', () => loadPreset(btn.dataset.name));
  });
  container.querySelectorAll('.preset-del-btn').forEach(btn => {
    btn.addEventListener('click', () => deletePreset(btn.dataset.name));
  });
}

// ══════════════════════════════════════
// 第一步：開始分析（抓取績效 + 相關性）
// ══════════════════════════════════════

async function onAnalyze() {
  const tickers = [...STATE.selected];
  if (tickers.length < 2) { alert('請至少選擇 2 檔ETF'); return; }

  showLoading('抓取歷史資料中…（首次可能需要 20-60 秒）');
  try {
    const params = `tickers=${encodeURIComponent(tickers.join(','))}&period=${STATE.period}`;

    // 並行抓取績效 + 相關性
    const [perfData, corrData] = await Promise.all([
      apiFetch(`/api/performance?${params}`),
      apiFetch(`/api/correlation?${params}`),
    ]);

    STATE.performanceData = perfData.data;
    STATE.corrData        = corrData;
    STATE.activeETFs      = [...corrData.tickers]; // 初始全部包含

    // 渲染效率前緣 + 相關性熱力圖
    renderFrontier();
    renderCorrelationHeatmap();

    // 解鎖第二區
    unlockSection('section-portfolio');
    document.getElementById('btn-portfolio').disabled = false;
    document.getElementById('portfolio-result').classList.add('hidden');

    // 捲動到第二區
    document.getElementById('section-portfolio').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (err) {
    alert('分析失敗：' + err.message);
  } finally {
    hideLoading();
  }
}

// ══════════════════════════════════════
// 效率前緣散點圖
// ══════════════════════════════════════

function renderFrontier() {
  const data = STATE.performanceData;
  const benchmark = '0050.TW';

  const traces = [];
  const categories = {};

  Object.entries(data).forEach(([ticker, m]) => {
    const isBench = ticker === benchmark;
    const cat  = isBench ? '基準' : (STATE.etfList.find(e => e.code === ticker)?.category || '其他');
    if (!categories[cat]) categories[cat] = { x: [], y: [], text: [], marker: [] };
    categories[cat].x.push(m.annual_vol * 100);
    categories[cat].y.push(m.annual_return * 100);
    categories[cat].text.push(`${ticker}<br>年化報酬：${fmtPct(m.annual_return)}<br>年化波動：${fmtPct(m.annual_vol)}<br>Sharpe：${fmtNum(m.sharpe)}<br>MDD：${fmtPct(m.mdd)}`);
  });

  Object.entries(categories).forEach(([cat, vals]) => {
    traces.push({
      type: 'scatter',
      mode: 'markers+text',
      name: cat,
      x: vals.x, y: vals.y,
      text: vals.x.map((_, i) => {
        const ticker = STATE.performanceData ? Object.keys(STATE.performanceData).find(t => {
          const m = STATE.performanceData[t];
          return Math.abs(m.annual_vol * 100 - vals.x[i]) < 0.001 && Math.abs(m.annual_return * 100 - vals.y[i]) < 0.001;
        }) : '';
        return ticker ? ticker.replace('.TW','').replace('.TWO','') : '';
      }),
      textposition: 'top center',
      textfont: { size: 9, color: '#6b8aaa' },
      hovertext: vals.text,
      hoverinfo: 'text',
      marker: {
        size: 11,
        color: CAT_COLORS[cat] || '#888888',
        line: { width: 1.5, color: '#060d1b' },
        symbol: cat === '基準' ? 'diamond' : 'circle',
      },
    });
  });

  const layout = {
    ...PLOT_LAYOUT_BASE,
    margin: { t: 20, r: 20, b: 60, l: 70 },
    xaxis: { ...PLOT_LAYOUT_BASE.xaxis, title: { text: '年化波動率 (%)', standoff: 10 } },
    yaxis: { ...PLOT_LAYOUT_BASE.yaxis, title: { text: '年化報酬率 (%)', standoff: 10 } },
    hovermode: 'closest',
    dragmode: 'zoom',
    shapes: [{
      type: 'line', x0: 0, x1: 1, y0: 0, y1: 0,
      xref: 'paper', line: { color: '#1e3a5f', dash: 'dot', width: 1 },
    }],
  };

  Plotly.newPlot('chart-frontier', traces, layout, { responsive: true, displayModeBar: false });
}

// ══════════════════════════════════════
// 相關性熱力矩陣
// ══════════════════════════════════════

function renderCorrelationHeatmap() {
  const { tickers, matrix } = STATE.corrData;
  const threshold = STATE.corrThreshold;

  // 超出門檻的格子顏色加深
  const customdata = matrix.map(row => row.map(v => Math.abs(v) >= threshold ? '⚠ 高相關' : ''));

  const trace = {
    type: 'heatmap',
    x: tickers,
    y: tickers,
    z: matrix,
    zmin: -1, zmax: 1,
    colorscale: [
      [0,   '#ff4d6d'],
      [0.5, '#0d1b2e'],
      [1,   '#00d4ff'],
    ],
    hovertemplate: '<b>%{y}</b> vs <b>%{x}</b><br>相關係數：%{z:.4f}<extra></extra>',
    showscale: true,
    colorbar: {
      thickness: 12,
      outlinewidth: 0,
      tickfont: { color: '#6b8aaa', size: 10 },
      title: { text: 'r', font: { color: '#6b8aaa' } },
    },
  };

  const n = tickers.length;
  const h = Math.max(380, n * 38 + 80);

  const layout = {
    ...PLOT_LAYOUT_BASE,
    margin: { t: 20, r: 80, b: 100, l: 100 },
    height: h,
    xaxis: { ...PLOT_LAYOUT_BASE.xaxis, tickangle: -35 },
    yaxis: { ...PLOT_LAYOUT_BASE.yaxis, autorange: 'reversed' },
    annotations: matrix.flatMap((row, i) =>
      row.map((v, j) => ({
        x: j, y: i,
        text: v.toFixed(2),
        showarrow: false,
        font: {
          size: n > 10 ? 8 : 10,
          color: Math.abs(v) > 0.5 ? '#ffffff' : '#6b8aaa',
        },
      }))
    ),
  };

  Plotly.newPlot('chart-correlation', [trace], layout, { responsive: true, displayModeBar: false });
  updateActiveETFs();
}

/** 依相關係數門檻自動排除高相關ETF（貪婪算法） */
function updateActiveETFs() {
  const { tickers, matrix } = STATE.corrData;
  const threshold = STATE.corrThreshold;
  const excluded = new Set();

  for (let i = 0; i < tickers.length; i++) {
    if (excluded.has(i)) continue;
    for (let j = i + 1; j < tickers.length; j++) {
      if (excluded.has(j)) continue;
      if (Math.abs(matrix[i][j]) >= threshold) {
        // 排除夏普較低者
        const si = STATE.performanceData[tickers[i]]?.sharpe || 0;
        const sj = STATE.performanceData[tickers[j]]?.sharpe || 0;
        excluded.add(si >= sj ? j : i);
      }
    }
  }

  STATE.activeETFs = tickers.filter((_, i) => !excluded.has(i));

  // 更新提示
  const removedCount = tickers.length - STATE.activeETFs.length;
  const info = document.getElementById('corr-info');
  if (info) {
    info.textContent = removedCount > 0
      ? `已自動排除 ${removedCount} 檔高相關ETF，保留 ${STATE.activeETFs.length} 檔`
      : `所有ETF相關係數均低於門檻，保留 ${STATE.activeETFs.length} 檔`;
  }
}

// ══════════════════════════════════════
// 第二步：計算投資組合
// ══════════════════════════════════════

async function onCalculatePortfolio() {
  const tickers = STATE.activeETFs.length >= 2 ? STATE.activeETFs : [...STATE.selected];
  const method  = document.getElementById('method-select').value;

  showLoading('計算最佳投資組合中…');
  try {
    const result = await apiFetch('/api/portfolio', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tickers, method, period: STATE.period }),
    });

    STATE.portfolioResult = result;

    // 渲染結果
    renderPortfolioMetrics(result);
    renderPieChart(result);
    renderPortfolioTable(result);

    document.getElementById('portfolio-result').classList.remove('hidden');

    // 渲染第三區
    renderCumulativeReturns(result);
    renderSharpeBar(result);
    unlockSection('section-visual');

    document.getElementById('section-visual').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (err) {
    alert('投資組合計算失敗：' + err.message);
  } finally {
    hideLoading();
  }
}

// ══════════════════════════════════════
// 投資組合指標摘要列
// ══════════════════════════════════════

function renderPortfolioMetrics(result) {
  const m = result.portfolio_metrics;
  const methodLabel = { equal: '均等權重', market_cap: '市值加權', max_sharpe: '最大夏普比率', min_variance: '最小變異數' }[result.method] || result.method;

  // 移除舊的 metrics-strip（如有）
  const old = document.querySelector('#portfolio-result .metrics-strip');
  if (old) old.remove();

  const strip = document.createElement('div');
  strip.className = 'metrics-strip';
  strip.innerHTML = `
    <div class="metric-item">
      <div class="metric-label">配置方法</div>
      <div class="metric-value" style="font-size:1rem;color:#00d4ff">${methodLabel}</div>
    </div>
    <div class="metric-item">
      <div class="metric-label">年化報酬率</div>
      <div class="metric-value ${colorClass(m.annual_return)}">${fmtPct(m.annual_return)}</div>
    </div>
    <div class="metric-item">
      <div class="metric-label">年化波動率</div>
      <div class="metric-value" style="color:#ffa03c">${fmtPct(m.annual_vol)}</div>
    </div>
    <div class="metric-item">
      <div class="metric-label">Sharpe Ratio</div>
      <div class="metric-value" style="color:#ffd700">${fmtNum(m.sharpe)}</div>
    </div>
    <div class="metric-item">
      <div class="metric-label">最大回撤 (MDD)</div>
      <div class="metric-value neg">${fmtPct(m.mdd)}</div>
    </div>
  `;

  const resultDiv = document.getElementById('portfolio-result');
  resultDiv.insertBefore(strip, resultDiv.firstChild);
}

// ══════════════════════════════════════
// 圓餅圖（資產配置比例）
// ══════════════════════════════════════

function renderPieChart(result) {
  const tickers = result.tickers;
  const weights = tickers.map(t => result.weights[t]);
  const colors  = tickers.map(t => {
    const cat = STATE.etfList.find(e => e.code === t)?.category || '其他';
    return CAT_COLORS[cat] || '#888888';
  });

  const trace = {
    type: 'pie',
    labels: tickers.map(t => t.replace('.TW','').replace('.TWO','')),
    values: weights,
    hovertemplate: '<b>%{label}</b><br>權重：%{percent}<br>%{customdata}<extra></extra>',
    customdata: tickers.map(t => STATE.etfList.find(e => e.code === t)?.name || t),
    textinfo: 'label+percent',
    textfont: { size: 11, family: 'Rajdhani, sans-serif', color: '#e8edf5' },
    marker: {
      colors,
      line: { color: '#060d1b', width: 2 },
    },
    hole: 0.38,
  };

  const layout = {
    ...PLOT_LAYOUT_BASE,
    margin: { t: 20, r: 20, b: 20, l: 20 },
    height: 380,
    showlegend: false,
    annotations: [{
      text: `${result.tickers.length}<br><span style="font-size:10px">檔</span>`,
      x: 0.5, y: 0.5,
      font: { size: 22, family: 'Rajdhani', color: '#00d4ff' },
      showarrow: false,
    }],
  };

  Plotly.newPlot('chart-pie', [trace], layout, { responsive: true, displayModeBar: false });
}

// ══════════════════════════════════════
// 配置明細表格
// ══════════════════════════════════════

function renderPortfolioTable(result) {
  const rows = result.etf_details
    .sort((a, b) => b.weight - a.weight)
    .map(d => {
      const name = STATE.etfList.find(e => e.code === d.ticker)?.name || d.ticker;
      const barW = Math.round(d.weight * 200);
      return `
        <tr>
          <td><span class="etf-code">${d.ticker.replace('.TW','').replace('.TWO','')}</span></td>
          <td>${name}</td>
          <td class="num">
            ${(d.weight * 100).toFixed(1)}%
            <span class="weight-bar" style="width:${barW}px"></span>
          </td>
          <td class="num ${colorClass(d.annual_return)}">${fmtPct(d.annual_return)}</td>
          <td class="num">${fmtPct(d.annual_vol)}</td>
          <td class="num ${d.sharpe >= 0 ? 'pos' : 'neg'}">${fmtNum(d.sharpe)}</td>
          <td class="num neg">${fmtPct(d.mdd)}</td>
        </tr>`;
    }).join('');

  document.getElementById('portfolio-table').innerHTML = `
    <table>
      <thead>
        <tr>
          <th>代碼</th><th>名稱</th><th>權重</th>
          <th>年化報酬</th><th>年化波動</th><th>Sharpe</th><th>MDD</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;
}

// ══════════════════════════════════════
// 累積報酬率走勢圖（合成折線圖）
// ══════════════════════════════════════

function renderCumulativeReturns(result) {
  const BENCHMARK = '0050.TW';
  const traces = [];

  // ── 各ETF個別走勢 ──
  result.tickers.forEach(ticker => {
    const perfData = STATE.performanceData[ticker];
    if (!perfData) return;
    const name = STATE.etfList.find(e => e.code === ticker)?.name || ticker;
    traces.push({
      type: 'scatter', mode: 'lines',
      name: ticker.replace('.TW','').replace('.TWO',''),
      x: perfData.dates,
      y: perfData.cumulative_returns.map(v => v * 100),
      hovertemplate: `<b>${name}</b><br>%{x}<br>累積報酬：%{y:.2f}%<extra></extra>`,
      line: { width: 1.2, dash: 'solid' },
      opacity: 0.55,
    });
  });

  // ── 投資組合整體走勢（粗線） ──
  traces.push({
    type: 'scatter', mode: 'lines',
    name: '▶ 投資組合',
    x: result.dates,
    y: result.portfolio_cumulative.map(v => v * 100),
    hovertemplate: '<b>投資組合</b><br>%{x}<br>累積報酬：%{y:.2f}%<extra></extra>',
    line: { width: 3, color: '#ffd700' },
  });

  // ── 基準走勢（虛線） ──
  const benchData = STATE.performanceData[BENCHMARK];
  if (benchData) {
    traces.push({
      type: 'scatter', mode: 'lines',
      name: '— 基準 0050',
      x: benchData.dates,
      y: benchData.cumulative_returns.map(v => v * 100),
      hovertemplate: '<b>基準 0050.TW</b><br>%{x}<br>累積報酬：%{y:.2f}%<extra></extra>',
      line: { width: 2, color: '#6b8aaa', dash: 'dash' },
    });
  }

  const layout = {
    ...PLOT_LAYOUT_BASE,
    margin: { t: 20, r: 30, b: 50, l: 70 },
    hovermode: 'x unified',
    xaxis: {
      ...PLOT_LAYOUT_BASE.xaxis,
      rangeslider: { visible: true, thickness: 0.06, bgcolor: '#0d1b2e' },
      rangeselector: {
        bgcolor: '#0d1b2e',
        bordercolor: '#1e3a5f',
        activecolor: '#1e3a5f',
        font: { color: '#6b8aaa' },
        buttons: [
          { count: 3,  label: '3M', step: 'month', stepmode: 'backward' },
          { count: 6,  label: '6M', step: 'month', stepmode: 'backward' },
          { count: 1,  label: '1Y', step: 'year',  stepmode: 'backward' },
          { step: 'all', label: '全部' },
        ],
      },
    },
    yaxis: {
      ...PLOT_LAYOUT_BASE.yaxis,
      title: { text: '累積報酬率 (%)', standoff: 10 },
      tickformat: '.1f',
      ticksuffix: '%',
    },
    legend: {
      ...PLOT_LAYOUT_BASE.legend,
      orientation: 'v',
      x: 1.01, y: 1,
      xanchor: 'left',
    },
    shapes: [{
      type: 'line', x0: 0, x1: 1, y0: 0, y1: 0,
      xref: 'paper', line: { color: '#1e3a5f', dash: 'dot', width: 1 },
    }],
  };

  Plotly.newPlot('chart-cumulative', traces, layout, { responsive: true, displayModeBar: true, displaylogo: false });
}

// ══════════════════════════════════════
// Sharpe Ratio 橫條比較圖
// ══════════════════════════════════════

function renderSharpeBar(result) {
  const BENCHMARK = '0050.TW';
  const items = [];

  // 各ETF
  result.etf_details.forEach(d => {
    const name = STATE.etfList.find(e => e.code === d.ticker)?.name || d.ticker;
    items.push({
      label: `${d.ticker.replace('.TW','').replace('.TWO','')} ${name}`,
      sharpe: d.sharpe, ret: d.annual_return, vol: d.annual_vol, mdd: d.mdd,
      type: 'etf',
    });
  });

  // 投資組合
  const pm = result.portfolio_metrics;
  items.push({
    label: '▶ 投資組合',
    sharpe: pm.sharpe, ret: pm.annual_return, vol: pm.annual_vol, mdd: pm.mdd,
    type: 'portfolio',
  });

  // 基準
  const bm = STATE.performanceData[BENCHMARK];
  if (bm) {
    items.push({
      label: '— 基準 0050.TW',
      sharpe: bm.sharpe, ret: bm.annual_return, vol: bm.annual_vol, mdd: bm.mdd,
      type: 'benchmark',
    });
  }

  // 依 Sharpe 排序
  items.sort((a, b) => a.sharpe - b.sharpe);

  const colors = items.map(d => {
    if (d.type === 'portfolio') return '#ffd700';
    if (d.type === 'benchmark') return '#6b8aaa';
    return d.sharpe >= 0 ? '#00d4ff' : '#ff4d6d';
  });

  const trace = {
    type: 'bar',
    orientation: 'h',
    x: items.map(d => d.sharpe),
    y: items.map(d => d.label),
    marker: { color: colors, line: { width: 0 } },
    hovertemplate: items.map(d =>
      `<b>${d.label}</b><br>Sharpe：${fmtNum(d.sharpe)}<br>年化報酬：${fmtPct(d.ret)}<br>年化波動：${fmtPct(d.vol)}<br>MDD：${fmtPct(d.mdd)}<extra></extra>`
    ),
    width: 0.7,
  };

  const h = Math.max(380, items.length * 36 + 80);

  const layout = {
    ...PLOT_LAYOUT_BASE,
    height: h,
    margin: { t: 20, r: 60, b: 50, l: 240 },
    xaxis: { ...PLOT_LAYOUT_BASE.xaxis, title: { text: 'Sharpe Ratio', standoff: 8 }, zeroline: true, zerolinecolor: '#2a5080', zerolinewidth: 1.5 },
    yaxis: { ...PLOT_LAYOUT_BASE.yaxis, tickfont: { size: 11 } },
    bargap: 0.35,
    shapes: [{
      type: 'line', x0: 0, x1: 0, y0: 0, y1: 1,
      xref: 'x', yref: 'paper',
      line: { color: '#2a5080', width: 1.5, dash: 'dot' },
    }],
  };

  Plotly.newPlot('chart-sharpe', [trace], layout, { responsive: true, displayModeBar: false });
}

// ══════════════════════════════════════
// 事件監聽器初始化
// ══════════════════════════════════════
// ══════════════════════════════════════

function bindEvents() {
  // ── 時間區間選擇 ──
  document.getElementById('period-group').addEventListener('click', e => {
    const btn = e.target.closest('.btn-period');
    if (!btn) return;
    document.querySelectorAll('.btn-period').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    STATE.period = btn.dataset.period;
  });

  // ── 類別篩選 ──
  document.getElementById('category-group').addEventListener('click', e => {
    const btn = e.target.closest('.btn-cat');
    if (!btn) return;
    document.querySelectorAll('.btn-cat').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    STATE.categoryFilter = btn.dataset.cat;
    applyFilters();
  });

  // ── 交易所篩選 ──
  document.querySelectorAll('.btn-exch').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.btn-exch').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      STATE.exchangeFilter = btn.dataset.exch;
      applyFilters();
    });
  });

  // ── 搜尋框 ──
  document.getElementById('search-box').addEventListener('input', e => {
    STATE.searchQuery = e.target.value;
    applyFilters();
  });

  // ── 全選 checkbox ──
  document.getElementById('chk-all').addEventListener('change', e => {
    const checked = e.target.checked;
    STATE.filtered.forEach(etf => {
      if (checked) STATE.selected.add(etf.code);
      else STATE.selected.delete(etf.code);
    });
    renderETFTable();
  });

  // ── 清除全部選擇 ──
  document.getElementById('btn-clear-all').addEventListener('click', () => {
    STATE.selected.clear();
    renderETFTable();
    updateSelectedCount();
  });

  // ── 儲存常用組合 ──
  document.getElementById('btn-save-preset').addEventListener('click', saveCurrentPreset);
  document.getElementById('preset-name-input').addEventListener('keydown', e => {
    if (e.key === 'Enter') saveCurrentPreset();
  });

  // ── 開始分析 ──
  document.getElementById('btn-analyze').addEventListener('click', onAnalyze);

  // ── 相關係數滑桿 ──
  const slider = document.getElementById('corr-slider');
  slider.addEventListener('input', () => {
    const val = parseFloat(slider.value);
    STATE.corrThreshold = val;
    document.getElementById('corr-val').textContent = val.toFixed(2);
  });

  // ── 套用相關性篩選 ──
  document.getElementById('btn-apply-corr').addEventListener('click', () => {
    if (STATE.corrData) {
      updateActiveETFs();
      renderCorrelationHeatmap();
    }
  });

  // ── 計算投資組合 ──
  document.getElementById('btn-portfolio').addEventListener('click', onCalculatePortfolio);

  // ── 加入相關性提示元素 ──
  const corrInfo = document.createElement('p');
  corrInfo.id = 'corr-info';
  corrInfo.style.cssText = 'font-size:0.8rem;color:#6b8aaa;margin:8px 0 20px;';
  document.getElementById('chart-correlation').after(corrInfo);
}

// ══════════════════════════════════════
// 程式進入點
// ══════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => {
  bindEvents();
  init();
});
