import Chart from 'chart.js/auto';

// Initialize Icons (using global lucide from CDN)
const {
  createIcons,
  Search,
  Brain,
  Newspaper,
  Bookmark,
  BookmarkPlus,
  Activity,
  Power,
  Plus,
  PlusCircle,
  Trash2,
  Briefcase,
  LayoutDashboard,
  Lock,
  ShieldLock,
  PieChart,
  Check
} = window.lucide;

createIcons({
  icons: {
    Search, Brain, Newspaper, Bookmark, BookmarkPlus, Activity, Power, Plus, PlusCircle, Trash2, Briefcase, LayoutDashboard, Lock, ShieldLock, PieChart, Check
  }
});

// App State
const state = {
  charts: {
    risk: null,
    sentiment: null,
    snapshotTrend: null,
    portfolioPie: null
  },
  watchlist: [],
  portfolio: [],
  history: [],
  activeTicker: null,
  activePrice: null,
  isUnlocked: false,
  activeTab: 'dashboard',
  marketData: {},     // Cache for lightweight price data
  currentNews: []     // Full news cache — sliced on render
};

// --- Initialization ---
document.addEventListener('DOMContentLoaded', () => {
  initCharts();
  checkStatus();
  fetchInitialData();
  fetchModels();
  checkPortfolioStatus();

  // Navigation
  document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });

  // Event Listeners
  document.getElementById('analyze-btn').addEventListener('click', handleAnalyze);
  document.getElementById('ticker-input').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') handleAnalyze();
  });
  document.getElementById('shutdown-btn').addEventListener('click', handleShutdown);
  document.getElementById('model-select').addEventListener('change', handleModelChange);
  document.getElementById('add-watchlist-btn').addEventListener('click', handleAddToWatchlist);
  document.getElementById('add-new-holding-btn').addEventListener('click', () => openPortfolioModal());
  document.getElementById('show-unlock-btn').addEventListener('click', () => document.getElementById('unlock-modal').classList.remove('hidden'));

  // Portfolio Security
  document.getElementById('unlock-form').addEventListener('submit', handleUnlock);
  document.getElementById('cancel-unlock').addEventListener('click', () => document.getElementById('unlock-modal').classList.add('hidden'));
  document.getElementById('lock-portfolio-btn').addEventListener('click', handleLock);
  document.getElementById('wipe-portfolio-btn-main').addEventListener('click', handleWipe);
  document.getElementById('portfolio-form').addEventListener('submit', handleSaveHolding);
  document.getElementById('cancel-port').addEventListener('click', () => document.getElementById('portfolio-modal').classList.add('hidden'));

  // Portfolio Input Logic — auto-calculate total cost as qty × cost-per-share
  document.getElementById('port-qty').addEventListener('input', calculateTotalCost);
  document.getElementById('port-cost-per-share').addEventListener('input', calculateTotalCost);

  // Re-render news when count changes (no re-fetch needed — we cache the full list)
  document.getElementById('news-count').addEventListener('change', () => {
    renderNews(state.currentNews);
  });

  // Poll status every 10s
  setInterval(checkStatus, 10000);
});

// --- API Calls ---
async function checkStatus() {
  try {
    const res = await fetch('/api/health');
    const data = await res.json();

    const ollamaDot = document.querySelector('#ollama-status .status-dot');
    const apiDot = document.querySelector('#api-status .status-dot');

    if (data.status === 'healthy') {
      apiDot.classList.add('online');
      if (data.ollama && data.ollama.ok) {
        ollamaDot.classList.add('online');
      } else {
        ollamaDot.classList.remove('online');
      }
    }
  } catch (err) {
    console.error('Status check failed:', err);
    document.querySelectorAll('.status-dot').forEach(dot => dot.classList.remove('online'));
  }
}

async function fetchInitialData() {
  await Promise.all([
    updateWatchlist(),
    updateHistory()
  ]);

  // Auto-analyze the most recently updated watchlist item on startup
  if (state.watchlist.length > 0) {
    const sorted = [...state.watchlist].sort((a, b) => {
      const ta = a.last_updated ? new Date(a.last_updated) : new Date(a.added_at);
      const tb = b.last_updated ? new Date(b.last_updated) : new Date(b.added_at);
      return tb - ta;
    });
    const autoTicker = sorted[0].ticker;
    document.getElementById('ticker-input').value = autoTicker;
    handleAnalyze();
  }
}

async function updateWatchlist() {
  try {
    const res = await fetch('/api/watchlist');
    const data = await res.json();
    state.watchlist = data.watchlist || [];
    renderWatchlist();
  } catch (err) {
    console.error('Failed to fetch watchlist:', err);
  }
}

async function updateHistory() {
  try {
    const res = await fetch('/api/history');
    const data = await res.json();
    state.history = data.history || [];
  } catch (err) {
    console.error('Failed to fetch history:', err);
  }
}

async function fetchModels() {
  try {
    const res = await fetch('/api/config/models');
    const data = await res.json();
    const select = document.getElementById('model-select');

    select.innerHTML = (data.models || []).map(m => {
      const name = m.model || m.name || 'Unknown';
      return `
        <option value="${name}" ${name === data.active ? 'selected' : ''}>
          ${name}
        </option>
      `;
    }).join('') || '<option value="">No models found</option>';
  } catch (err) {
    console.error('Failed to fetch models:', err);
  }
}

function parseErrorDetail(detail) {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map(e => e.msg || JSON.stringify(e)).join(', ');
  return JSON.stringify(detail);
}

async function handleAnalyze() {
  const input = document.getElementById('ticker-input');
  const raw = input.value.trim().toUpperCase();
  if (!raw) return;

  // Detect "AAPL VS MSFT" comparison pattern (tickers up to 10 chars, matching backend limit)
  const vsMatch = raw.match(/^([A-Z]{1,10})\s+VS\s+([A-Z]{1,10})$/);
  if (vsMatch) {
    return handleCompare(vsMatch[1], vsMatch[2]);
  }

  const ticker = raw;
  state.activeTicker = ticker;
  setLoading(true);

  // Always fetch the input's max so changing count after analysis works from cache
  const newsCountEl = document.getElementById('news-count');
  const maxNews = parseInt(newsCountEl.max) || 20;

  try {
    const res = await fetch('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ticker,
        include_sentiment: true,
        include_news: true,
        max_news: maxNews
      })
    });

    if (!res.ok) {
      const error = await res.json();
      throw new Error(parseErrorDetail(error.detail) || 'Analysis failed');
    }

    const data = await res.json();
    updateUI(data);
    await updateWatchlist();
    await fetchTrendData(ticker); // NEW: Fetch trend data for chart
  } catch (err) {
    alert(`Error: ${err.message}`);
    console.error(err);
  } finally {
    setLoading(false);
  }
}

async function handleCompare(tickerA, tickerB) {
  state.activeTicker = null; // comparison has no single active ticker
  setLoading(true);

  try {
    const res = await fetch('/api/compare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticker_a: tickerA, ticker_b: tickerB })
    });

    if (!res.ok) {
      const error = await res.json();
      throw new Error(parseErrorDetail(error.detail) || 'Comparison failed');
    }

    const data = await res.json();
    updateCompareUI(data);
  } catch (err) {
    alert(`Error: ${err.message}`);
    console.error(err);
  } finally {
    setLoading(false);
  }
}

function updateCompareUI(data) {
  const { ticker_a, ticker_b, verdict, ai_analysis, news_a, news_b } = data;

  // Header: show both tickers
  document.getElementById('ticker-display').textContent = `${ticker_a} vs ${ticker_b}`;

  // Verdict in place of price badge
  const verdictColors = { [ticker_a]: '#16a34a', [ticker_b]: '#b45309', 'EQUAL': '#475569' };
  const priceEl = document.getElementById('price-display');
  priceEl.innerHTML = `<span style="font-size:0.6rem;letter-spacing:0.1em;opacity:0.85;display:block">VERDICT</span>${verdict}`;
  priceEl.style.background = verdictColors[verdict] || '#475569';
  priceEl.style.color = '#fff';
  priceEl.style.border = 'none';

  // Clear snapshot stats — not meaningful for a pair
  ['volume-display', 'high-display', 'low-display', 'mktcap-display', 'pe-display', 'div-display'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = '---';
  });

  // Reset risk gauge
  updateRiskChart(0);

  // Hide watchlist button — doesn't apply to a comparison
  document.getElementById('add-watchlist-btn').style.display = 'none';

  // AI analysis (markdown)
  const analysisEl = document.getElementById('analysis-text');
  if (ai_analysis) {
    analysisEl.innerHTML = window.marked ? window.marked.parse(ai_analysis) : `<p>${ai_analysis.replace(/\n/g, '<br>')}</p>`;
  } else {
    analysisEl.innerHTML = '<p class="placeholder">Comparison unavailable.</p>';
  }

  // News: show ticker_a news (fall back to ticker_b)
  state.currentNews = news_a || news_b || [];
  renderNews(state.currentNews);
}

// --- UI Updates ---
function updateUI(data) {
  // 1. Market Snapshot
  document.getElementById('ticker-display').textContent = data.ticker;
  state.activePrice = data.market_snapshot.current_price || 0;
  const priceEl = document.getElementById('price-display');
  priceEl.textContent = `$${state.activePrice.toLocaleString(undefined, { minimumFractionDigits: 2 })}`;
  priceEl.style.background = '';
  priceEl.style.color = '';
  priceEl.style.border = '';
  document.getElementById('volume-display').textContent = (data.market_snapshot.volume || 0).toLocaleString();
  document.getElementById('high-display').textContent = `$${(data.market_snapshot.high_52_week || 0).toFixed(2)}`;
  document.getElementById('low-display').textContent = `$${(data.market_snapshot.low_52_week || 0).toFixed(2)}`;

  // NEW metrics
  if (document.getElementById('mktcap-display')) {
    const mktcap = data.market_snapshot.market_cap;
    document.getElementById('mktcap-display').textContent = mktcap ?
      (mktcap >= 1e12 ? (mktcap / 1e12).toFixed(2) + 'T' : (mktcap / 1e9).toFixed(2) + 'B') : '---';
  }
  if (document.getElementById('pe-display')) {
    document.getElementById('pe-display').textContent = data.market_snapshot.pe_ratio ? data.market_snapshot.pe_ratio.toFixed(2) : '---';
  }
  if (document.getElementById('div-display')) {
    document.getElementById('div-display').textContent = data.market_snapshot.dividend_yield ? (data.market_snapshot.dividend_yield * 100).toFixed(2) + '%' : '0.00%';
  }

  // 2. Risk Chart
  updateRiskChart(data.risk_score);

  // 3. Sentiment Chart
  updateSentimentChart(data.sentiment);

  // 4. AI Analysis
  const analysisEl = document.getElementById('analysis-text');
  if (data.ai_analysis) {
    // Use marked if available, otherwise fallback
    if (window.marked) {
      analysisEl.innerHTML = window.marked.parse(data.ai_analysis);
    } else {
      analysisEl.innerHTML = `<p>${data.ai_analysis.replace(/\n/g, '<br>')}</p>`;
    }
  } else {
    analysisEl.innerHTML = '<p class="placeholder">Analysis unavailable.</p>';
  }

  // 5. News List — cache full result so count input works without re-fetching
  state.currentNews = data.news || [];
  renderNews(state.currentNews);

  const inWatchlist = state.watchlist.some(w => w.ticker === data.ticker);

  const watchBtn = document.getElementById('add-watchlist-btn');
  watchBtn.style.display = 'inline-flex';

  if (inWatchlist) {
    watchBtn.innerHTML = '<i data-lucide="check"></i> Saved';
    watchBtn.classList.add('active');
  } else {
    watchBtn.innerHTML = '<i data-lucide="bookmark-plus"></i> Watch';
    watchBtn.classList.remove('active');
  }

  createIcons({ icons: { BookmarkPlus, Check } });
}

function renderWatchlist() {
  const container = document.getElementById('watchlist-items');
  if (state.watchlist.length === 0) {
    container.innerHTML = '<p class="placeholder" style="margin-top: 1rem">No tickers watched</p>';
    return;
  }

  container.innerHTML = state.watchlist.map(item => `
    <div class="watchlist-item glass" onclick="selectTicker('${item.ticker}')">
      <span class="watchlist-ticker">${item.ticker}</span>
      <div style="text-align: right">
        <span class="watchlist-price">${item.last_price ? '$' + item.last_price.toFixed(2) : '---'}</span>
        <button class="delete-btn" onclick="event.stopPropagation(); handleRemoveFromWatchlist('${item.ticker}')">
          <i data-lucide="trash-2"></i>
        </button>
      </div>
    </div>
  `).join('');
  createIcons({ icons: { Trash2 } });
}

function renderNews(news) {
  const container = document.getElementById('news-list');
  if (!news || news.length === 0) {
    container.innerHTML = '<p class="placeholder">No recent news found.</p>';
    return;
  }

  const count = parseInt(document.getElementById('news-count').value) || 5;
  const visible = news.slice(0, count);

  container.innerHTML = visible.map(item => `
    <a href="${item.link}" target="_blank" class="news-item">
      <div class="news-meta">
        <span>${item.publisher}</span>
        <span>${item.published_date.split(' ')[0]}</span>
      </div>
      <div class="news-title">${item.title}</div>
    </a>
  `).join('');
}


function setLoading(isLoading) {
  const spin = document.getElementById('loader-spinner');
  const icon = document.getElementById('search-icon');
  if (isLoading) {
    spin.classList.remove('hidden');
    icon.classList.add('hidden');
  } else {
    spin.classList.add('hidden');
    icon.classList.remove('hidden');
  }
}

async function handleModelChange(e) {
  const model = e.target.value;
  try {
    const res = await fetch('/api/config/model', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model })
    });
    const data = await res.json();
    console.log('Model switched to:', data.active);
  } catch (err) {
    console.error('Failed to change model:', err);
  }
}

// --- Navigation & Core UI ---
function switchTab(tab) {
  state.activeTab = tab;

  // Update Nav buttons
  document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tab);
  });

  // Toggle Sections
  document.getElementById('dashboard-section').classList.toggle('hidden', tab !== 'dashboard');
  document.getElementById('portfolio-section').classList.toggle('hidden', tab !== 'portfolio');

  // Watchlist sidebar: only visible on dashboard
  const watchlistPanel = document.getElementById('watchlist-panel');
  const mainEl = document.querySelector('main');
  if (tab === 'dashboard') {
    watchlistPanel.classList.remove('hidden');
    mainEl.classList.remove('no-sidebar');
  } else {
    watchlistPanel.classList.add('hidden');
    mainEl.classList.add('no-sidebar');
  }

  if (tab === 'portfolio') {
    updatePortfolioStateUI();
  }
}

function updatePortfolioStateUI() {
  const lockedEl = document.getElementById('portfolio-locked');
  const gridEl = document.getElementById('portfolio-grid');

  if (state.isUnlocked) {
    lockedEl.classList.add('hidden');
    gridEl.classList.remove('hidden');
    updatePortfolio();
  } else {
    lockedEl.classList.remove('hidden');
    gridEl.classList.add('hidden');
  }
}

async function fetchTrendData(ticker) {
  try {
    const res = await fetch(`/api/mcp/finance-server/get_trend_data?ticker=${ticker}&period=1mo`);
    const data = await res.json();
    if (data.points) {
      updateSnapshotTrendChart(data.points);
    }
  } catch (err) {
    console.error('Failed to fetch trend data:', err);
  }
}

// --- Portfolio Security & Logic ---
async function checkPortfolioStatus() {
  try {
    const res = await fetch('/api/portfolio');
    if (res.ok) {
      state.isUnlocked = true;
      const data = await res.json();
      state.portfolio = data.holdings || [];
      if (state.activeTab === 'portfolio') updatePortfolio();
    } else {
      state.isUnlocked = false;
    }
  } catch (err) {
    state.isUnlocked = false;
  }
}

async function handleUnlock(e) {
  e.preventDefault();
  const password = document.getElementById('portfolio-password').value;
  try {
    const res = await fetch('/api/portfolio/unlock', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password })
    });
    if (res.ok) {
      state.isUnlocked = true;
      document.getElementById('unlock-modal').classList.add('hidden');
      document.getElementById('portfolio-password').value = '';
      updatePortfolioStateUI();
    } else {
      alert('Invalid password');
    }
  } catch (err) {
    console.error('Unlock failed:', err);
  }
}

async function handleLock() {
  try {
    await fetch('/api/portfolio/lock', { method: 'POST' });
    state.isUnlocked = false;
    state.portfolio = [];
    updatePortfolioStateUI();
  } catch (err) {
    console.error('Lock failed:', err);
  }
}

async function handleWipe() {
  if (!confirm('EXTREMELY DANGEROUS: This will permanently delete your encrypted portfolio. Continue?')) return;
  try {
    await fetch('/api/portfolio/wipe', { method: 'POST' });
    state.isUnlocked = false;
    state.portfolio = [];
    updatePortfolioStateUI();
  } catch (err) {
    console.error('Wipe failed:', err);
  }
}

async function updatePortfolio() {
  try {
    const res = await fetch('/api/portfolio');
    const data = await res.json();
    state.portfolio = data.holdings || [];

    // Fetch fresh prices for all holdings in parallel
    await fetchPortfolioPrices();

    renderPortfolio();
    updatePortfolioPieChart();
  } catch (err) {
    console.error('Failed to update portfolio:', err);
  }
}

async function fetchPortfolioPrices() {
  const tickers = state.portfolio.map(p => p.ticker);
  if (tickers.length === 0) return;

  try {
    const res = await fetch('/api/portfolio/prices', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tickers })
    });

    if (res.ok) {
      const data = await res.json();
      // data.prices is { AAPL: 150.00, MSFT: 300.00 }
      Object.entries(data.prices).forEach(([ticker, price]) => {
        // Update our cache
        if (!state.marketData[ticker]) state.marketData[ticker] = {};
        state.marketData[ticker].current_price = price;
      });
    }
  } catch (err) {
    console.error('Failed to batch fetch prices:', err);
  }
}

function renderPortfolio() {
  const body = document.getElementById('portfolio-body');
  if (state.portfolio.length === 0) {
    body.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:2rem;color:var(--text-muted);">No holdings yet — click Add Position to get started.</td></tr>';
    document.getElementById('total-value').textContent = '$0.00';
    document.getElementById('total-pl').textContent = '$0.00 (0.00%)';
    document.getElementById('total-pl').className = 'neutral';
    document.getElementById('portfolio-breakdown').innerHTML = '<p class="placeholder" style="margin-top: 2rem;">No holdings yet.</p>';
    return;
  }

  let totalValue = 0;
  let totalCost = 0;

  const rows = state.portfolio.map(item => {
    // cost_basis is per-share. Resolve current price from cache > history > fallback to cost_basis.
    let currentPrice = item.cost_basis;
    if (state.marketData[item.ticker]?.current_price) {
      currentPrice = state.marketData[item.ticker].current_price;
    } else {
      const hist = state.history.find(h => h.ticker === item.ticker);
      if (hist) currentPrice = hist.market_snapshot.current_price;
    }

    const totalItemCost = item.quantity * item.cost_basis;
    const value = item.quantity * currentPrice;
    const pl = value - totalItemCost;
    const plPercent = totalItemCost > 0 ? (pl / totalItemCost) * 100 : 0;

    totalValue += value;
    totalCost += totalItemCost;

    const plClass = pl >= 0 ? 'plus' : 'minus';
    const plSign = pl >= 0 ? '+' : '';

    return `
      <tr>
        <td><span class="portfolio-ticker" onclick="selectTicker('${item.ticker}')">${item.ticker}</span></td>
        <td>${item.quantity.toLocaleString(undefined, { maximumFractionDigits: 4 })}</td>
        <td>$${item.cost_basis.toFixed(2)}</td>
        <td>$${currentPrice.toFixed(2)}</td>
        <td>$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
        <td class="${plClass}">${plSign}$${Math.abs(pl).toFixed(2)}<br><span style="font-size:0.8em;opacity:0.8;">${plSign}${plPercent.toFixed(2)}%</span></td>
        <td>
          <button class="icon-btn small danger-icon" onclick="handleRemoveHolding('${item.ticker}')" title="Remove">
            <i data-lucide="trash-2"></i>
          </button>
        </td>
      </tr>
    `;
  });

  body.innerHTML = rows.join('');

  const totalPL = totalValue - totalCost;
  const totalPLPct = totalCost > 0 ? (totalPL / totalCost) * 100 : 0;
  const plSign = totalPL >= 0 ? '+' : '';

  document.getElementById('total-value').textContent = `$${totalValue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const plEl = document.getElementById('total-pl');
  plEl.textContent = `${plSign}$${Math.abs(totalPL).toFixed(2)} (${plSign}${totalPLPct.toFixed(2)}%)`;
  plEl.className = totalPL >= 0 ? 'plus' : 'minus';

  // Render per-holding breakdown sidebar
  renderPortfolioBreakdown();

  createIcons({ icons: { Trash2 } });
}

function renderPortfolioBreakdown() {
  const container = document.getElementById('portfolio-breakdown');
  if (!container) return;

  const items = state.portfolio.map(item => {
    let currentPrice = item.cost_basis;
    if (state.marketData[item.ticker]?.current_price) {
      currentPrice = state.marketData[item.ticker].current_price;
    }
    const value = item.quantity * currentPrice;
    const pl = value - (item.quantity * item.cost_basis);
    const plClass = pl >= 0 ? 'plus' : 'minus';
    const plSign = pl >= 0 ? '+' : '';
    return `
      <div class="breakdown-item">
        <div class="breakdown-ticker">${item.ticker}</div>
        <div class="breakdown-detail">
          <span>${item.quantity.toLocaleString(undefined, { maximumFractionDigits: 4 })} shares</span>
          <span class="${plClass}">${plSign}$${Math.abs(pl).toFixed(2)}</span>
        </div>
      </div>
    `;
  });

  container.innerHTML = items.join('');
}

function openPortfolioModal() {
  if (!state.isUnlocked) {
    document.getElementById('unlock-modal').classList.remove('hidden');
    return;
  }

  // Clear fields for new entry
  document.getElementById('port-ticker-input').value = '';
  document.getElementById('port-qty').value = '';
  document.getElementById('port-cost-per-share').value = '';
  document.getElementById('port-total-cost').value = '';

  document.getElementById('portfolio-modal').classList.remove('hidden');
  createIcons({ icons: { PlusCircle } });
  setTimeout(() => document.getElementById('port-ticker-input').focus(), 100);
}

function calculateTotalCost() {
  const qty = parseFloat(document.getElementById('port-qty').value);
  const costPerShare = parseFloat(document.getElementById('port-cost-per-share').value);

  if (!isNaN(qty) && !isNaN(costPerShare) && qty > 0 && costPerShare > 0) {
    document.getElementById('port-total-cost').value = (qty * costPerShare).toFixed(2);
  } else {
    document.getElementById('port-total-cost').value = '';
  }
}

async function handleSaveHolding(e) {
  e.preventDefault();
  const ticker = document.getElementById('port-ticker-input').value.trim().toUpperCase();
  if (!ticker) return;

  const quantity = parseFloat(document.getElementById('port-qty').value);
  // cost_basis stored as per-share cost
  const cost_basis = parseFloat(document.getElementById('port-cost-per-share').value);

  if (isNaN(quantity) || isNaN(cost_basis) || quantity <= 0 || cost_basis <= 0) {
    alert('Please enter valid shares and cost per share.');
    return;
  }

  try {
    const res = await fetch('/api/portfolio', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticker, quantity, cost_basis, added_at: new Date().toISOString() })
    });
    if (res.ok) {
      document.getElementById('portfolio-modal').classList.add('hidden');
      await updatePortfolio();
    } else {
      const err = await res.json();
      alert(err.detail || 'Failed to save position.');
    }
  } catch (err) {
    console.error('Failed to save holding:', err);
  }
}

window.handleRemoveHolding = async (ticker) => {
  if (!confirm(`Remove ${ticker} from portfolio?`)) return;
  try {
    await fetch(`/api/portfolio/${ticker}`, { method: 'DELETE' });
    await updatePortfolio();
  } catch (err) {
    console.error('Failed to remove holding:', err);
  }
};

async function handleShutdown() {
  if (!confirm('Are you sure you want to SHUT DOWN the dashboard and Ollama?')) return;

  try {
    const res = await fetch('/api/admin/shutdown', { method: 'POST' });
    const data = await res.json();
    alert(data.message);
    window.close();
  } catch (err) {
    console.error('Shutdown failed:', err);
  }
}

async function handleAddToWatchlist() {
  if (!state.activeTicker) return;

  try {
    const res = await fetch(`/api/watchlist/${state.activeTicker}`, { method: 'POST' });
    if (res.ok) {
      await updateWatchlist();
      const addBtn = document.getElementById('add-watchlist-btn');
      addBtn.innerHTML = '<i data-lucide="bookmark"></i>';
      createIcons({ icons: { Bookmark } });
    }
  } catch (err) {
    console.error('Failed to add to watchlist:', err);
  }
}

window.handleRemoveFromWatchlist = async (ticker) => {
  try {
    await fetch(`/api/watchlist/${ticker}`, { method: 'DELETE' });
    await updateWatchlist();
  } catch (err) {
    console.error('Failed to remove from watchlist:', err);
  }
};

window.selectTicker = (ticker) => {
  document.getElementById('ticker-input').value = ticker;
  handleAnalyze();
};

// --- Charts Logic ---
function initCharts() {
  // Risk Gauge
  const riskCtx = document.getElementById('risk-chart').getContext('2d');
  state.charts.risk = new Chart(riskCtx, {
    type: 'doughnut',
    data: {
      datasets: [{
        data: [0, 100],
        backgroundColor: [getRiskColor(0), 'rgba(255,255,255,0.05)'],
        borderWidth: 0,
        circumference: 180,
        rotation: 270,
        cutout: '85%'
      }]
    },
    options: {
      aspectRatio: 2,
      plugins: { legend: { display: false }, tooltip: { enabled: false } }
    }
  });

  // Sentiment Bars
  const sentCtx = document.getElementById('sentiment-chart').getContext('2d');
  state.charts.sentiment = new Chart(sentCtx, {
    type: 'bar',
    data: {
      labels: ['Buy', 'Strong Buy', 'Hold', 'Sell', 'Strong Sell'],
      datasets: [{
        label: 'Analyst Count',
        data: [0, 0, 0, 0, 0],
        backgroundColor: ['#22c55e', '#15803d', '#f59e0b', '#ef4444', '#b91c1c'],
        borderRadius: 4
      }]
    },
    options: {
      indexAxis: 'y',
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false }, ticks: { color: '#94a3b8' } },
        y: { grid: { display: false }, ticks: { color: '#94a3b8' } }
      }
    }
  });

  // Snapshot Trend
  const snapCtx = document.getElementById('snapshot-trend-chart').getContext('2d');
  state.charts.snapshotTrend = new Chart(snapCtx, {
    type: 'line',
    data: { labels: [], datasets: [{ data: [], borderColor: '#3b82f6', tension: 0.4, fill: true, backgroundColor: 'rgba(59, 130, 246, 0.1)' }] },
    options: {
      plugins: { legend: { display: false } },
      scales: { x: { display: false }, y: { display: false } },
      elements: { point: { radius: 0 } }
    }
  });

  // Portfolio pie chart is initialized lazily on first portfolio open (canvas is hidden at load)
}

function updateRiskChart(score) {
  const color = getRiskColor(score);
  state.charts.risk.data.datasets[0].data = [score, 100 - score];
  state.charts.risk.data.datasets[0].backgroundColor = [color, 'rgba(255,255,255,0.05)'];
  state.charts.risk.update();

  const label = document.getElementById('risk-level');
  label.textContent = score > 70 ? 'High Risk' : score > 30 ? 'Medium Risk' : 'Low Risk';
  label.style.color = color;
}

function updateSentimentChart(sentiment) {
  if (!sentiment || sentiment.length === 0) return;

  // Aggregate the last record
  const last = sentiment[sentiment.length - 1];
  const chartData = [
    last.buy || 0,
    last.strongBuy || 0,
    last.hold || 0,
    last.sell || 0,
    last.strongSell || 0
  ];

  state.charts.sentiment.data.datasets[0].data = chartData;
  state.charts.sentiment.update();
}

function updateSnapshotTrendChart(points) {
  state.charts.snapshotTrend.data.labels = points.map(p => p.date);
  state.charts.snapshotTrend.data.datasets[0].data = points.map(p => p.price);
  state.charts.snapshotTrend.update();
}

function updatePortfolioPieChart() {
  if (!state.portfolio.length) return;

  // Lazy-initialize the pie chart on first call (canvas was hidden at page load)
  if (!state.charts.portfolioPie) {
    const pieCtx = document.getElementById('portfolio-pie-chart').getContext('2d');
    state.charts.portfolioPie = new Chart(pieCtx, {
      type: 'doughnut',
      data: {
        labels: [],
        datasets: [{
          data: [],
          backgroundColor: [],
          borderWidth: 2,
          borderColor: 'rgba(12,15,23,0.8)'
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            display: true,
            position: 'right',
            labels: { color: '#94a3b8', padding: 14, font: { size: 12 } }
          },
          tooltip: {
            callbacks: {
              label: (ctx) => ` ${ctx.label}: ${ctx.parsed.toFixed(1)}%`
            }
          }
        }
      }
    });
  }

  const PIE_COLORS = [
    '#3b82f6', '#8b5cf6', '#22c55e', '#f59e0b',
    '#ef4444', '#06b6d4', '#ec4899', '#f97316',
    '#a855f7', '#14b8a6'
  ];

  let totalValue = 0;
  const values = state.portfolio.map(item => {
    const price = state.marketData[item.ticker]?.current_price || item.cost_basis;
    const val = item.quantity * price;
    totalValue += val;
    return { ticker: item.ticker, value: val };
  });

  const labels = values.map(v => v.ticker);
  const data = values.map(v => totalValue > 0 ? (v.value / totalValue) * 100 : 0);

  state.charts.portfolioPie.data.labels = labels;
  state.charts.portfolioPie.data.datasets[0].data = data;
  state.charts.portfolioPie.data.datasets[0].backgroundColor = labels.map((_, i) => PIE_COLORS[i % PIE_COLORS.length]);
  state.charts.portfolioPie.update();
}

function getRiskColor(score) {
  if (score > 70) return '#ef4444';
  if (score > 30) return '#f59e0b';
  return '#22c55e';
}
