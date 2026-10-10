import Chart from 'chart.js/auto';
import Papa from 'papaparse';
import { MarketFluid } from './fluid.js';

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
  Check,
  MessageSquare,
  ArrowUpCircle,
  RotateCcw,
  Upload,
  Pencil,
} = window.lucide;

createIcons({
  icons: {
    Search, Brain, Newspaper, Bookmark, BookmarkPlus, Activity, Power, Plus, PlusCircle, Trash2, Briefcase, LayoutDashboard, Lock, ShieldLock, PieChart, Check, MessageSquare, ArrowUpCircle, RotateCcw, Upload, Pencil,
  }
});

// ── Utility Functions ──────────────────────────────────────────

/**
 * Format large numbers with commas or abbreviations (K, M, B)
 * @param {number} num - The number to format
 * @param {boolean} useAbbrev - Use abbreviations for large numbers (default: false)
 * @param {number} decimals - Decimal places for abbreviated numbers (default: 1)
 */
function formatNumber(num, useAbbrev = false, decimals = 1) {
  if (num == null || isNaN(num)) return '---';

  if (useAbbrev) {
    if (Math.abs(num) >= 1e9) {
      return (num / 1e9).toFixed(decimals) + 'B';
    } else if (Math.abs(num) >= 1e6) {
      return (num / 1e6).toFixed(decimals) + 'M';
    } else if (Math.abs(num) >= 1e3) {
      return (num / 1e3).toFixed(decimals) + 'K';
    }
  }

  return num.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

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
  currentNews: [],    // Full news cache — sliced on render
  thesis: [],         // Thesis history (populated after portfolio unlock)
  fxQuote: null,
  portfolioTotals: null,
  csvPreview: [],
  editingTicker: null,
  addingUnitsTicker: null,
  // Lock screen fluid simulation
  lockFluid: new MarketFluid(),
  isLocked: true,
  // Advisor state
  advisorWS: null,
  advisorStreaming: false,
  advisorCurrentMsgEl: null,   // <div> of the in-progress AI bubble
  advisorCurrentTextEl: null,  // text node / content div inside bubble
  advisorActiveBlocks: {},     // tool → <details> element (open thinking blocks)
  advisorHasMessages: false
};

// --- Initialization ---
document.addEventListener('DOMContentLoaded', () => {
  initCharts();
  initLockScreen();

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
  document.getElementById('import-portfolio-csv-btn').addEventListener('click', () => document.getElementById('portfolio-csv-input').click());
  document.getElementById('portfolio-csv-input').addEventListener('change', handlePortfolioCsvSelected);
  document.getElementById('confirm-csv-import-btn').addEventListener('click', importPortfolioCsv);
  document.getElementById('cancel-csv-import-btn').addEventListener('click', closePortfolioCsvPreview);
  document.getElementById('download-portfolio-csv-template').addEventListener('click', downloadPortfolioCsvTemplate);
  document.getElementById('add-units-form').addEventListener('submit', handleAddUnits);
  document.getElementById('cancel-add-units-btn').addEventListener('click', closeAddUnitsModal);
  document.getElementById('added-qty').addEventListener('input', calculateAddedUnits);
  document.getElementById('added-cost').addEventListener('input', calculateAddedUnits);
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
  document.getElementById('port-asset-type').addEventListener('change', handleAssetTypeChange);

  // Re-render news when count changes (no re-fetch needed — we cache the full list)
  document.getElementById('news-count').addEventListener('change', () => {
    renderNews(state.currentNews);
  });

  // Advisor event listeners
  document.getElementById('advisor-send-btn').addEventListener('click', handleAdvisorSend);
  document.getElementById('advisor-clear-btn').addEventListener('click', handleAdvisorClear);
  document.getElementById('advisor-input').addEventListener('keypress', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleAdvisorSend();
    }
  });

  // Auto-resize textarea
  document.getElementById('advisor-input').addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 120) + 'px';
  });

  // Starter prompts
  document.querySelectorAll('.starter-card').forEach(btn => {
    btn.addEventListener('click', () => {
      document.getElementById('advisor-input').value = btn.dataset.prompt;
      handleAdvisorSend();
    });
  });

  // Lock screen button
  document.getElementById('lock-screen-btn')?.addEventListener('click', lockScreen);

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

  // Prefetch prices for every watchlist ticker in parallel so they
  // show up on startup without needing a full analysis to have run first.
  if (state.watchlist.length > 0) {
    try {
      const res = await fetch('/api/watchlist/refresh', { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        state.watchlist = data.watchlist || state.watchlist;
        renderWatchlist();
      }
    } catch (err) {
      console.error('Watchlist price refresh failed:', err);
    }
  }

}

// --- Lock Screen ---
async function initLockScreen() {
  const lockEl   = document.getElementById('market-lockscreen');
  const canvas   = document.getElementById('lockscreen-canvas');
  const statusEl = document.getElementById('lockscreen-status');
  const enterBtn = document.getElementById('lockscreen-enter-btn');
  if (!lockEl || !canvas) return;

  state.lockFluid.init(canvas, false);

  await _refreshLockScreenData(statusEl);

  enterBtn.classList.remove('hidden');
  enterBtn.addEventListener('click', unlockScreen);
  lockEl.addEventListener('click', (e) => {
    if (e.target !== enterBtn && !enterBtn.classList.contains('hidden')) unlockScreen();
  });
}

function unlockScreen() {
  const lockEl = document.getElementById('market-lockscreen');
  if (!lockEl || lockEl.classList.contains('fading-out')) return;
  lockEl.classList.add('fading-out');
  state.lockFluid.pause();
  setTimeout(() => {
    lockEl.classList.add('hidden');
    lockEl.classList.remove('fading-out');
    state.isLocked = false;
  }, 650);
}

async function lockScreen() {
  const lockEl   = document.getElementById('market-lockscreen');
  const statusEl = document.getElementById('lockscreen-status');
  if (!lockEl) return;
  state.isLocked = true;
  lockEl.classList.remove('hidden');
  state.lockFluid.resume();
  statusEl.textContent = 'Refreshing world markets...';
  await _refreshLockScreenData(statusEl);
}

async function _refreshLockScreenData(statusEl) {
  const data = await state.lockFluid.refreshWorldState();
  if (data) {
    const parts = [];
    if (data.vix != null)
      parts.push(`VIX ${data.vix.toFixed(1)}`);
    if (data.overall_change_pct != null)
      parts.push(`Global ${data.overall_change_pct >= 0 ? '+' : ''}${data.overall_change_pct.toFixed(2)}%`);
    if (data.market_regime && data.market_regime !== 'Unknown')
      parts.push(data.market_regime);
    if (data.treasury_10y != null)
      parts.push(`10Y ${data.treasury_10y.toFixed(2)}%`);
    statusEl.textContent = parts.join(' · ') || 'World Markets';
  } else {
    statusEl.textContent = 'Market data unavailable';
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
  const holding = state.portfolio.find(item => item.ticker === ticker);
  const positionContext = holding ? {
    asset_type: holding.asset_type || 'equity',
    underlying_ticker: holding.underlying_ticker || null,
    cedears_per_underlying: holding.cedears_per_underlying || null,
    ratio_source: holding.ratio_source || null,
    ratio_as_of: holding.ratio_as_of || null,
    quantity: holding.quantity,
    cost_basis: holding.cost_basis,
    cost_currency: holding.cost_currency || 'USD'
  } : {};

  try {
    const res = await fetch('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ticker,
        include_sentiment: true,
        include_news: true,
        max_news: maxNews,
        ...positionContext
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
  const snapshot = data.market_snapshot;
  const quoteCurrency = snapshot.currency || null;
  state.activePrice = Number.isFinite(Number(snapshot.current_price)) ? Number(snapshot.current_price) : null;
  const priceEl = document.getElementById('price-display');
  priceEl.textContent = formatCurrencyAmount(state.activePrice, quoteCurrency);
  priceEl.style.background = '';
  priceEl.style.color = '';
  priceEl.style.border = '';
  const quoteMeta = document.getElementById('quote-meta');
  quoteMeta.textContent = `${snapshot.exchange || 'Exchange unknown'} · ${snapshot.quote_as_of || 'Date unknown'} · ${snapshot.quote_status || 'Freshness unknown'} · ${snapshot.quote_source || 'Source unknown'}`;
  quoteMeta.classList.remove('hidden');
  document.getElementById('volume-display').textContent = formatNumber(snapshot.volume, true);
  document.getElementById('high-display').textContent = formatCurrencyAmount(snapshot.high_52_week, quoteCurrency);
  document.getElementById('low-display').textContent = formatCurrencyAmount(snapshot.low_52_week, quoteCurrency);

  // NEW metrics
  const fundamentals = snapshot.underlying_snapshot || snapshot;
  const isCedear = snapshot.asset_type === 'cedear';
  document.getElementById('mktcap-label').textContent = isCedear ? 'Underlying Mkt Cap' : 'Mkt Cap';
  document.getElementById('pe-label').textContent = isCedear ? 'Underlying P/E' : 'P/E Ratio';
  document.getElementById('div-label').textContent = isCedear ? 'Underlying Div Yield' : 'Div Yield';
  if (document.getElementById('mktcap-display')) {
    const mktcap = fundamentals.market_cap;
    document.getElementById('mktcap-display').textContent = mktcap === null || mktcap === undefined
      ? 'N/A'
      : `${fundamentals.currency || 'Currency unknown'} ${formatNumber(mktcap, true, 2)}`;
  }
  if (document.getElementById('pe-display')) {
    document.getElementById('pe-display').textContent = fundamentals.pe_ratio === null || fundamentals.pe_ratio === undefined
      ? 'N/A'
      : fundamentals.pe_ratio.toFixed(2);
  }
  if (document.getElementById('div-display')) {
    document.getElementById('div-display').textContent = fundamentals.dividend_yield === null || fundamentals.dividend_yield === undefined
      ? 'N/A'
      : `${(fundamentals.dividend_yield * 100).toFixed(2)}%`;
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
  document.getElementById('advisor-section').classList.toggle('hidden', tab !== 'advisor');

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

  if (tab === 'advisor') {
    connectAdvisorWS();
    // Re-render icons for advisor tab
    createIcons({ icons: { ArrowUpCircle, RotateCcw, MessageSquare } });
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
      fetchThesisHistory();
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
    state.thesis = [];
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
  if (state.portfolio.length === 0) return;

  state.portfolio.forEach(item => delete state.marketData[item.ticker]);

  try {
    const res = await fetch('/api/portfolio/prices', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ positions: state.portfolio })
    });

    if (res.ok) {
      const data = await res.json();
      Object.entries(data.quotes || {}).forEach(([ticker, quote]) => {
        state.marketData[ticker] = quote;
      });
      state.fxQuote = data.fx || null;
      state.portfolioTotals = data.totals || null;
    }
  } catch (err) {
    console.error('Failed to batch fetch prices:', err);
  }
}

function formatCurrencyAmount(value, currency) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return 'Unavailable';
  const amount = formatNumber(Number(value));
  return currency ? `${escapeHtml(currency)} ${amount}` : `Unknown currency ${amount}`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, character => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  })[character]);
}

function groupedCurrencyTotals(totals) {
  return Object.entries(totals)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([currency, value]) => formatCurrencyAmount(value, currency))
    .join(' · ');
}

function renderPortfolio() {
  const body = document.getElementById('portfolio-body');
  if (state.portfolio.length === 0) {
    body.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:2rem;color:var(--text-muted);">No holdings yet — click Add Position to get started.</td></tr>';
    document.getElementById('total-value').textContent = 'No holdings';
    document.getElementById('total-pl').textContent = 'Unavailable';
    document.getElementById('total-pl').className = 'neutral';
    document.getElementById('portfolio-breakdown').innerHTML = '<p class="placeholder" style="margin-top: 2rem;">No holdings yet.</p>';
    return;
  }

  const marketValueByCurrency = {};
  let pnlUnavailableCount = state.portfolioTotals?.not_comparable_positions ?? 0;

  const rows = state.portfolio.map(item => {
    const quote = state.marketData[item.ticker] || {};
    const currentPrice = quote.current_price !== null && quote.current_price !== undefined && Number.isFinite(Number(quote.current_price))
      ? Number(quote.current_price)
      : null;
    const quoteCurrency = quote.currency || null;
    const marketValue = currentPrice === null ? null : item.quantity * currentPrice;
    const costCurrency = item.cost_currency || 'USD';
    const metrics = quote.position_metrics || {};
    const pnl = typeof metrics.pnl === 'number' ? metrics.pnl : null;
    const pnlCurrency = metrics.pnl_currency || null;
    const pnlPercent = typeof metrics.pnl_percent === 'number' ? metrics.pnl_percent : null;

    if (marketValue !== null && quoteCurrency) {
      marketValueByCurrency[quoteCurrency] = (marketValueByCurrency[quoteCurrency] || 0) + marketValue;
    }
    const plClass = pnl === null ? 'neutral' : pnl >= 0 ? 'plus' : 'minus';
    const plSign = pnl !== null && pnl >= 0 ? '+' : '';
    const unitLabel = item.asset_type === 'cedear' ? 'CEDEARs' : 'shares';
    const exposure = item.asset_type === 'cedear'
      ? (quote.position_metrics?.underlying_equivalent_quantity === null || quote.position_metrics?.underlying_equivalent_quantity === undefined
        ? 'Underlying exposure unavailable'
        : `${formatNumber(quote.position_metrics.underlying_equivalent_quantity, false)} ${escapeHtml(item.underlying_ticker || 'underlying')} shares · ratio ${item.cedears_per_underlying} (${escapeHtml(quote.position_metrics.ratio_status)}; source ${escapeHtml(item.ratio_source || 'not provided')}; as of ${escapeHtml(item.ratio_as_of || 'unknown')})`)
      : '';
    const quoteStamp = `${escapeHtml(quote.quote_status || 'unknown')} · ${escapeHtml(quote.quote_as_of || 'date unknown')}`;
    const fxQuote = metrics.fx_quote;
    const fxNote = fxQuote
      ? `CCL ${formatNumber(fxQuote.ars_per_usd)} ARS/USD · ${escapeHtml(fxQuote.quote_as_of || 'date unknown')} · ${escapeHtml(fxQuote.source || 'source unknown')}`
      : metrics.fx_conversion_status && metrics.fx_conversion_status !== 'not_required'
        ? `CCL ${escapeHtml(metrics.fx_conversion_status)}`
        : '';
    const pnlDisplay = pnl === null
      ? `Unavailable<br><span class="portfolio-quote-note">${marketValue === null ? 'No quote' : `Cost ${escapeHtml(costCurrency)} · quote ${escapeHtml(quoteCurrency || 'currency unknown')}`}</span>`
      : `${plSign}${formatCurrencyAmount(Math.abs(pnl), pnlCurrency)}<br><span style="font-size:0.8em;opacity:0.8;">${plSign}${pnlPercent === null ? '' : `${pnlPercent.toFixed(2)}%`}</span>${fxNote ? `<br><span class="portfolio-quote-note">${fxNote}</span>` : ''}`;

    return `
      <tr>
        <td><span class="portfolio-ticker" data-analyze-ticker="${escapeHtml(item.ticker)}">${escapeHtml(item.ticker)}</span><br><span class="portfolio-quote-note">${escapeHtml(item.asset_type || 'equity')}${exposure ? ` · ${exposure}` : ''}</span></td>
        <td>${formatNumber(item.quantity, false)} ${unitLabel}</td>
        <td>${formatCurrencyAmount(item.cost_basis, costCurrency)}</td>
        <td>${formatCurrencyAmount(currentPrice, quoteCurrency)}<br><span class="portfolio-quote-note">${quoteStamp}</span></td>
        <td>${formatCurrencyAmount(marketValue, quoteCurrency)}</td>
        <td class="${plClass}">${pnlDisplay}</td>
        <td><div class="portfolio-row-actions">
          <button class="icon-btn small" data-add-units-ticker="${escapeHtml(item.ticker)}" title="Add units">
            <i data-lucide="plus"></i>
          </button>
          <button class="icon-btn small" data-edit-ticker="${escapeHtml(item.ticker)}" title="Edit position">
            <i data-lucide="pencil"></i>
          </button>
          <button class="icon-btn small danger-icon" data-remove-ticker="${escapeHtml(item.ticker)}" title="Remove">
            <i data-lucide="trash-2"></i>
          </button>
        </div></td>
      </tr>
    `;
  });

  body.innerHTML = rows.join('');

  body.querySelectorAll('[data-analyze-ticker]').forEach(element => {
    element.addEventListener('click', () => window.selectTicker(element.dataset.analyzeTicker));
  });
  body.querySelectorAll('[data-remove-ticker]').forEach(element => {
    element.addEventListener('click', () => window.handleRemoveHolding(element.dataset.removeTicker));
  });
  body.querySelectorAll('[data-edit-ticker]').forEach(element => {
    element.addEventListener('click', () => openPortfolioModal(element.dataset.editTicker));
  });
  body.querySelectorAll('[data-add-units-ticker]').forEach(element => {
    element.addEventListener('click', () => openAddUnitsModal(element.dataset.addUnitsTicker));
  });

  document.getElementById('total-value').textContent = groupedCurrencyTotals(marketValueByCurrency) || 'No current quotes';
  const plEl = document.getElementById('total-pl');
  const pnlByCurrency = state.portfolioTotals?.pnl_by_currency || {};
  const pnlPercentByCurrency = state.portfolioTotals?.pnl_percent_by_currency || {};
  const pnlSummary = Object.entries(pnlByCurrency)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([currency, value]) => {
      const percent = pnlPercentByCurrency[currency];
      const sign = value >= 0 ? '+' : '';
      return `${escapeHtml(currency)} ${sign}${formatNumber(value)}${percent === null ? '' : ` (${sign}${percent.toFixed(2)}%)`}`;
    })
    .join(' · ');
  plEl.textContent = `${pnlSummary || 'Unavailable'}${pnlUnavailableCount ? ` · ${pnlUnavailableCount} position(s) not comparable` : ''}`;
  const comparablePnls = Object.values(pnlByCurrency);
  plEl.className = comparablePnls.length === 0 ? 'neutral' : comparablePnls.every(value => value >= 0) ? 'plus' : 'minus';
  const usedCcl = state.portfolio.some(item => state.marketData[item.ticker]?.position_metrics?.fx_conversion_status === 'current_ccl');
  if (usedCcl && state.fxQuote?.ars_per_usd) {
    plEl.textContent += ` · CCL ${formatNumber(state.fxQuote.ars_per_usd)} ARS/USD (${escapeHtml(state.fxQuote.quote_as_of || 'date unknown')} · ${escapeHtml(state.fxQuote.source || 'source unknown')})`;
  }

  // Render per-holding breakdown sidebar
  renderPortfolioBreakdown();

  createIcons({ icons: { Trash2, Plus, Pencil } });
}

function renderPortfolioBreakdown() {
  const container = document.getElementById('portfolio-breakdown');
  if (!container) return;

  const items = state.portfolio.map(item => {
    const quote = state.marketData[item.ticker] || {};
    const currentPrice = quote.current_price !== null && quote.current_price !== undefined && Number.isFinite(Number(quote.current_price))
      ? Number(quote.current_price)
      : null;
    const quoteCurrency = quote.currency || null;
    const metrics = quote.position_metrics || {};
    const pnl = typeof metrics.pnl === 'number' ? metrics.pnl : null;
    const pnlCurrency = metrics.pnl_currency || null;
    const pnlPercent = metrics.pnl_percent;
    const plClass = pnl === null ? 'neutral' : pnl >= 0 ? 'plus' : 'minus';
    const plSign = pnl !== null && pnl >= 0 ? '+' : '';
    const unitLabel = item.asset_type === 'cedear' ? 'CEDEARs' : 'shares';
    const exposure = quote.position_metrics?.underlying_equivalent_quantity;
    return `
      <div class="breakdown-item">
        <div class="breakdown-ticker">${escapeHtml(item.ticker)}</div>
        <div class="breakdown-detail">
          <span>${formatNumber(item.quantity, false)} ${unitLabel}${exposure === null || exposure === undefined ? '' : ` · ${formatNumber(exposure, false)} ${escapeHtml(item.underlying_ticker || 'underlying')} shares`}</span>
          <span class="${plClass}">${pnl === null ? 'P/L unavailable' : `${plSign}${formatCurrencyAmount(Math.abs(pnl), pnlCurrency)}${typeof pnlPercent === 'number' ? ` (${pnlPercent.toFixed(2)}%)` : ''}`}</span>
        </div>
      </div>
    `;
  });

  container.innerHTML = items.join('');
}

function openPortfolioModal(ticker = null) {
  if (!state.isUnlocked) {
    document.getElementById('unlock-modal').classList.remove('hidden');
    return;
  }

  const existing = ticker ? state.portfolio.find(item => item.ticker === ticker) : null;
  state.editingTicker = existing?.ticker || null;
  document.getElementById('port-ticker-input').value = existing?.ticker || '';
  document.getElementById('port-asset-type').value = existing?.asset_type || 'equity';
  document.getElementById('port-underlying-ticker').value = existing?.underlying_ticker || '';
  document.getElementById('port-cedears-ratio').value = existing?.cedears_per_underlying ?? '';
  document.getElementById('port-ratio-source').value = existing?.ratio_source || '';
  document.getElementById('port-ratio-date').value = existing?.ratio_as_of || '';
  document.getElementById('port-qty').value = existing?.quantity ?? '';
  document.getElementById('port-cost-per-share').value = existing?.cost_basis ?? '';
  document.getElementById('port-total-cost').value = existing
    ? (existing.quantity * existing.cost_basis).toFixed(2)
    : '';
  handleAssetTypeChange();
  document.getElementById('port-cost-currency').value = existing?.cost_currency || (existing?.asset_type === 'cedear' ? '' : 'USD');
  document.getElementById('port-ticker-input').readOnly = Boolean(existing);
  document.getElementById('port-modal-title').lastChild.textContent = existing ? ' Edit Position' : ' Add Position';
  document.getElementById('save-portfolio-item-btn').textContent = existing ? 'Save Changes' : 'Save Position';

  document.getElementById('portfolio-modal').classList.remove('hidden');
  createIcons({ icons: { PlusCircle } });
  setTimeout(() => document.getElementById('port-ticker-input').focus(), 100);
}

function handleAssetTypeChange() {
  const assetType = document.getElementById('port-asset-type').value;
  const isCedear = assetType === 'cedear';
  document.getElementById('cedear-fields').classList.toggle('hidden', !isCedear);
  document.getElementById('port-cost-currency').value = isCedear ? '' : 'USD';
  document.getElementById('port-cost-basis-label').textContent = isCedear
    ? 'Average Cost Per CEDEAR'
    : 'Average Cost Per Share / Unit';
  document.getElementById('port-ticker-input').placeholder = isCedear
    ? 'e.g. AAPL.BA'
    : 'e.g. AAPL, MSFT';
}

function openAddUnitsModal(ticker) {
  if (!state.isUnlocked) {
    document.getElementById('unlock-modal').classList.remove('hidden');
    return;
  }
  const holding = state.portfolio.find(item => item.ticker === ticker);
  if (!holding) return;

  state.addingUnitsTicker = ticker;
  document.getElementById('add-units-position').textContent =
    `${holding.ticker}: ${formatNumber(holding.quantity, false)} units at ${formatCurrencyAmount(holding.cost_basis, holding.cost_currency || 'USD')} average cost.`;
  document.getElementById('added-cost-label').textContent = `Purchase cost per unit (${holding.cost_currency || 'USD'})`;
  document.getElementById('added-qty').value = '';
  document.getElementById('added-cost').value = '';
  document.getElementById('add-units-preview').textContent = '';
  document.getElementById('add-units-modal').classList.remove('hidden');
  setTimeout(() => document.getElementById('added-qty').focus(), 50);
}

function closeAddUnitsModal() {
  document.getElementById('add-units-modal').classList.add('hidden');
  state.addingUnitsTicker = null;
}

function calculateAddedUnits() {
  const holding = state.portfolio.find(item => item.ticker === state.addingUnitsTicker);
  const addedQuantity = parseFloat(document.getElementById('added-qty').value);
  const purchaseCost = parseFloat(document.getElementById('added-cost').value);
  const preview = document.getElementById('add-units-preview');
  if (!holding || !Number.isFinite(addedQuantity) || !Number.isFinite(purchaseCost) || addedQuantity <= 0 || purchaseCost <= 0) {
    preview.textContent = '';
    return;
  }
  const newQuantity = holding.quantity + addedQuantity;
  const newAverageCost = (holding.quantity * holding.cost_basis + addedQuantity * purchaseCost) / newQuantity;
  preview.textContent = `New total: ${formatNumber(newQuantity, false)} units · new average cost: ${formatCurrencyAmount(newAverageCost, holding.cost_currency || 'USD')}`;
}

async function handleAddUnits(event) {
  event.preventDefault();
  const holding = state.portfolio.find(item => item.ticker === state.addingUnitsTicker);
  if (!holding) return;
  const addedQuantity = parseFloat(document.getElementById('added-qty').value);
  const purchaseCost = parseFloat(document.getElementById('added-cost').value);
  if (!Number.isFinite(addedQuantity) || !Number.isFinite(purchaseCost) || addedQuantity <= 0 || purchaseCost <= 0) {
    alert('Enter a positive unit amount and purchase cost.');
    return;
  }

  const response = await fetch(`/api/portfolio/${encodeURIComponent(holding.ticker)}/add-units`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      quantity: addedQuantity,
      cost_basis: purchaseCost,
      cost_currency: holding.cost_currency || 'USD'
    })
  });
  if (!response.ok) {
    const error = await response.json();
    alert(error.detail || 'Could not add units.');
    return;
  }
  closeAddUnitsModal();
  await updatePortfolio();
}

function normalizePortfolioCsvHeader(header) {
  const normalized = String(header)
    .trim()
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[\s-]+/g, '_');
  const aliases = {
    symbol: 'ticker',
    simbolo: 'ticker',
    simbolo_local: 'ticker',
    cantidad: 'quantity',
    unidades: 'quantity',
    avg_cost: 'cost_basis',
    average_cost: 'cost_basis',
    ppc: 'cost_basis',
    costo_promedio: 'cost_basis',
    moneda: 'cost_currency',
    moneda_costo: 'cost_currency',
    currency: 'cost_currency',
    type: 'asset_type',
    tipo: 'asset_type',
    instrument_type: 'asset_type',
    underlying: 'underlying_ticker',
    subyacente: 'underlying_ticker',
    ratio: 'cedears_per_underlying',
    ratio_source: 'ratio_source',
    fuente_ratio: 'ratio_source',
    ratio_date: 'ratio_as_of',
    fecha_ratio: 'ratio_as_of'
  };
  return aliases[normalized] || normalized;
}

function parseCsvNumber(value) {
  if (value === null || value === undefined || String(value).trim() === '') return null;
  let normalized = String(value).trim().replace(/[\s$]/g, '');
  const comma = normalized.lastIndexOf(',');
  const dot = normalized.lastIndexOf('.');
  if (comma >= 0 && dot >= 0) {
    normalized = comma > dot
      ? normalized.replace(/\./g, '').replace(',', '.')
      : normalized.replace(/,/g, '');
  } else if (comma >= 0) {
    normalized = normalized.replace(',', '.');
  }
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

function handlePortfolioCsvSelected(event) {
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file) return;
  if (!state.isUnlocked) {
    document.getElementById('unlock-modal').classList.remove('hidden');
    return;
  }

  Papa.parse(file, {
    header: true,
    skipEmptyLines: 'greedy',
    transformHeader: normalizePortfolioCsvHeader,
    complete: result => showPortfolioCsvPreview(result, file.name)
  });
}

function showPortfolioCsvPreview(result, fileName) {
  const rows = [];
  const seen = new Set();
  const parseErrors = (result.errors || []).map(error => `CSV row ${error.row + 2}: ${error.message}`);

  if (!result.meta.fields?.includes('ticker') || !result.meta.fields?.includes('quantity') || !result.meta.fields?.includes('cost_basis')) {
    parseErrors.push('Required CSV columns: ticker, quantity, cost_basis.');
  }

  for (const [index, raw] of result.data.entries()) {
    const errors = [];
    const ticker = String(raw.ticker || '').trim().toUpperCase();
    const quantity = parseCsvNumber(raw.quantity);
    const cost_basis = parseCsvNumber(raw.cost_basis);
    const assetValue = String(raw.asset_type || '').trim().toLowerCase();
    const asset_type = assetValue === 'cedear' || assetValue === 'cedear (argentina)' ? 'cedear' : 'equity';
    const cost_currency = String(raw.cost_currency || (asset_type === 'cedear' ? '' : 'USD')).trim().toUpperCase();
    const ratio = parseCsvNumber(raw.cedears_per_underlying);
    const ratio_as_of = String(raw.ratio_as_of || '').trim() || null;

    if (!ticker) errors.push('Ticker is required.');
    if (quantity === null || quantity <= 0) errors.push('Quantity must be a positive number.');
    if (cost_basis === null || cost_basis <= 0) errors.push('Cost basis must be a positive number.');
    if (!/^[A-Z]{3}$/.test(cost_currency)) errors.push('Cost currency must be a three-letter code.');
    if (raw.cedears_per_underlying && (ratio === null || ratio <= 0)) errors.push('CEDEAR ratio must be a positive number.');
    if (ratio_as_of && !/^\d{4}-\d{2}-\d{2}$/.test(ratio_as_of)) errors.push('Ratio date must use YYYY-MM-DD.');
    if (ticker && seen.has(ticker)) errors.push('Duplicate ticker in CSV.');
    if (ticker) seen.add(ticker);

    rows.push({
      row: index + 2,
      errors,
      holding: {
        ticker,
        quantity,
        cost_basis,
        cost_currency,
        asset_type,
        underlying_ticker: String(raw.underlying_ticker || '').trim().toUpperCase() || null,
        cedears_per_underlying: ratio,
        ratio_source: String(raw.ratio_source || '').trim() || null,
        ratio_as_of,
        added_at: new Date().toISOString()
      }
    });
  }

  if (rows.length > 500) parseErrors.push('Import is limited to 500 holdings per file.');
  state.csvPreview = rows;
  const invalidRows = rows.filter(row => row.errors.length);
  const summary = document.getElementById('portfolio-csv-summary');
  summary.textContent = `${fileName}: ${rows.length} rows; ${rows.length - invalidRows.length} valid; ${invalidRows.length} with errors. Existing tickers will be updated; other holdings are retained.`;
  const errorBox = document.getElementById('portfolio-csv-errors');
  errorBox.textContent = [...parseErrors, ...invalidRows.map(row => `Row ${row.row}: ${row.errors.join(' ')}`)].join('\n');

  document.getElementById('portfolio-csv-preview-body').innerHTML = rows.slice(0, 30).map(row => {
    const item = row.holding;
    const cells = [item.ticker || '—', item.asset_type, item.quantity ?? '—', item.cost_basis ?? '—', item.cost_currency, item.underlying_ticker || '—', item.cedears_per_underlying ?? '—'];
    return `<tr class="${row.errors.length ? 'csv-row-error' : ''}">${cells.map(value => `<td>${escapeHtml(value)}</td>`).join('')}</tr>`;
  }).join('');
  if (rows.length > 30) errorBox.textContent += '\nOnly the first 30 rows are shown in the preview.';
  document.getElementById('confirm-csv-import-btn').disabled = rows.length === 0 || invalidRows.length > 0 || parseErrors.length > 0;
  document.getElementById('portfolio-csv-preview-modal').classList.remove('hidden');
}

async function importPortfolioCsv() {
  if (!state.isUnlocked || !state.csvPreview.length || state.csvPreview.some(row => row.errors.length)) return;
  const response = await fetch('/api/portfolio/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ holdings: state.csvPreview.map(row => row.holding) })
  });
  if (!response.ok) {
    const error = await response.json();
    alert(error.detail || 'CSV import failed.');
    return;
  }
  const result = await response.json();
  closePortfolioCsvPreview();
  await updatePortfolio();
  alert(`Imported ${result.added} new and updated ${result.updated} existing positions.`);
}

function closePortfolioCsvPreview() {
  document.getElementById('portfolio-csv-preview-modal').classList.add('hidden');
  state.csvPreview = [];
}

function downloadPortfolioCsvTemplate() {
  const header = 'ticker,quantity,cost_basis,cost_currency,asset_type,underlying_ticker,cedears_per_underlying,ratio_source,ratio_as_of\n';
  const blob = new Blob([header], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = 'mcpfolio-portfolio-template.csv';
  anchor.click();
  URL.revokeObjectURL(url);
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
  const existing = state.editingTicker
    ? state.portfolio.find(item => item.ticker === state.editingTicker)
    : null;
  const asset_type = document.getElementById('port-asset-type').value;
  const cost_currency = document.getElementById('port-cost-currency').value;
  const cost_basis = parseFloat(document.getElementById('port-cost-per-share').value);
  const ratioInput = document.getElementById('port-cedears-ratio').value;
  const cedears_per_underlying = ratioInput ? parseFloat(ratioInput) : null;

  if (isNaN(quantity) || isNaN(cost_basis) || quantity <= 0 || cost_basis <= 0 || !cost_currency) {
    alert('Please enter a valid quantity, average cost per unit, and cost currency.');
    return;
  }
  if (ratioInput && (!Number.isFinite(cedears_per_underlying) || cedears_per_underlying <= 0)) {
    alert('The CEDEAR conversion ratio must be a positive number.');
    return;
  }

  const payload = {
    ticker,
    quantity,
    cost_basis,
    added_at: existing?.added_at || new Date().toISOString(),
    asset_type,
    cost_currency,
    underlying_ticker: asset_type === 'cedear'
      ? document.getElementById('port-underlying-ticker').value.trim().toUpperCase() || null
      : null,
    cedears_per_underlying: asset_type === 'cedear' ? cedears_per_underlying : null,
    ratio_source: asset_type === 'cedear'
      ? document.getElementById('port-ratio-source').value.trim() || null
      : null,
    ratio_as_of: asset_type === 'cedear'
      ? document.getElementById('port-ratio-date').value || null
      : null
  };

  try {
    const res = await fetch('/api/portfolio', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      document.getElementById('portfolio-modal').classList.add('hidden');
      state.editingTicker = null;
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
  if (!confirm('Shut down dashboard and Ollama?')) return;

  try {
    await fetch('/api/admin/shutdown', { method: 'POST' });
    // No need for second message - just close
    window.close();
  } catch (err) {
    console.error('Shutdown failed:', err);
    alert('Shutdown request failed. Please stop manually.');
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
              label: (ctx) => {
                const total = ctx.dataset.data.reduce((sum, value) => sum + Number(value || 0), 0);
                const percent = total > 0 ? (ctx.parsed / total) * 100 : 0;
                return ` ${ctx.label}: ${percent.toFixed(1)}% (${formatCurrencyAmount(ctx.parsed, ctx.dataset.label)})`;
              }
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

  const canvas = document.getElementById('portfolio-pie-chart');
  const note = document.getElementById('portfolio-allocation-note');
  const values = state.portfolio.map(item => {
    const quote = state.marketData[item.ticker] || {};
    const price = Number(quote.current_price);
    if (quote.current_price === null || quote.current_price === undefined || !Number.isFinite(price) || !quote.currency) return null;
    return { ticker: item.ticker, currency: quote.currency, value: item.quantity * price };
  }).filter(Boolean);
  const currencies = [...new Set(values.map(item => item.currency))];

  if (currencies.length !== 1) {
    canvas.classList.add('hidden');
    note.classList.remove('hidden');
    note.textContent = currencies.length > 1
      ? 'Allocation is shown separately by currency; no FX conversion is applied.'
      : 'Allocation is unavailable until current quotes with currency are available.';
    return;
  }

  canvas.classList.remove('hidden');
  note.classList.add('hidden');
  const labels = values.map(item => item.ticker);
  const data = values.map(item => item.value);

  state.charts.portfolioPie.data.labels = labels;
  state.charts.portfolioPie.data.datasets = [{
    label: currencies[0],
    data,
    backgroundColor: labels.map((_, i) => PIE_COLORS[i % PIE_COLORS.length]),
    borderWidth: 2,
    borderColor: 'rgba(12,15,23,0.8)'
  }];
  state.charts.portfolioPie.update();
}

function getRiskColor(score) {
  if (score > 70) return '#ef4444';
  if (score > 30) return '#f59e0b';
  return '#22c55e';
}

// --- Thesis History ---

async function fetchThesisHistory() {
  try {
    const res = await fetch('/api/thesis');
    if (!res.ok) return; // locked or error — silently skip
    const data = await res.json();
    state.thesis = data.thesis || [];
    renderThesisHistory();
  } catch (err) {
    console.error('Failed to fetch thesis history:', err);
  }
}

function renderThesisHistory() {
  const container = document.getElementById('thesis-history-body');
  if (!container) return;

  if (!state.thesis || state.thesis.length === 0) {
    container.innerHTML = '<p class="placeholder" style="margin-top:1rem;">No analyses recorded yet.</p>';
    return;
  }

  const REC_COLORS = {
    BUY: '#22c55e',
    HOLD: '#f59e0b',
    SELL: '#ef4444',
    CAUTION: '#f97316'
  };

  const rows = state.thesis.map((record, idx) => {
    const date = record.timestamp ? record.timestamp.split('T')[0] : '—';
    const rec = (record.recommendation || '—').toUpperCase();
    const recColor = REC_COLORS[rec] || '#64748b';
    const conf = record.confidence != null ? (record.confidence * 100).toFixed(0) + '%' : '—';
    const price = record.price != null ? '$' + record.price.toFixed(2) : '—';
    const keyRisk = record.key_risk ? record.key_risk.slice(0, 80) + (record.key_risk.length > 80 ? '…' : '') : '—';
    const analysisId = `thesis-expand-${idx}`;

    return `
      <div class="thesis-row" onclick="toggleThesisExpand('${analysisId}')">
        <div class="thesis-row-main">
          <span class="thesis-date">${date}</span>
          <span class="thesis-ticker">${record.ticker}</span>
          <span class="thesis-rec-badge" style="background:${recColor}22;color:${recColor};border-color:${recColor}44">${rec}</span>
          <span class="thesis-conf">${conf}</span>
          <span class="thesis-price">${price}</span>
          <span class="thesis-risk">${keyRisk}</span>
        </div>
        <div class="thesis-expand hidden" id="${analysisId}">
          ${window.marked ? window.marked.parse(record.ai_analysis || '') : (record.ai_analysis || '').replace(/\n/g, '<br>')}
        </div>
      </div>
    `;
  });

  container.innerHTML = `
    <div class="thesis-header-row">
      <span>Date</span>
      <span>Ticker</span>
      <span>Rec</span>
      <span>Confidence</span>
      <span>Price</span>
      <span>Key Risk</span>
    </div>
    ${rows.join('')}
  `;
}

window.toggleThesisExpand = (id) => {
  const el = document.getElementById(id);
  if (el) el.classList.toggle('hidden');
};

// ── Advisor Chat Functions ──────────────────────────────────────────

const TOOL_LABELS = {
  get_market_snapshot:    'Fetching market data',
  get_sentiment_data:     'Checking analyst sentiment',
  get_news:               'Reading latest news',
  get_macro_context:      'Checking macro environment',
  get_sector_peers:       'Finding sector peers',
  get_earnings_calendar:  'Looking up earnings calendar',
  get_fund_info:          'Fetching fund holdings',
  get_trend_data:         'Getting price trend',
};

function connectAdvisorWS() {
  if (state.advisorWS?.readyState === WebSocket.OPEN) return;
  const ws = new WebSocket(`ws://${location.host}/ws/advisor`);
  state.advisorWS = ws;

  ws.onopen = () => {
    console.log('Advisor WebSocket connected');
  };

  ws.onmessage = (e) => {
    try {
      handleAdvisorEvent(JSON.parse(e.data));
    } catch (err) {
      console.error('Failed to handle advisor event:', err);
    }
  };

  ws.onerror = (err) => {
    console.error('Advisor WebSocket error:', err);
  };

  ws.onclose = () => {
    console.log('Advisor WebSocket closed, reconnecting...');
    setTimeout(connectAdvisorWS, 2000);  // auto-reconnect
  };
}

function handleAdvisorEvent(event) {
  switch (event.type) {
    case 'token':
      ensureAIBubble();
      state.advisorCurrentTextEl.insertAdjacentText('beforeend', event.content);
      scrollChat();
      break;

    case 'tool_start':
      ensureAIBubble();
      const block = createThinkingBlock(event.tool, event.input);
      state.advisorCurrentMsgEl.querySelector('.msg-thinking-area').appendChild(block);
      state.advisorActiveBlocks[event.tool] = block;
      scrollChat();
      break;

    case 'tool_end':
      const b = state.advisorActiveBlocks[event.tool];
      if (b) closeThinkingBlock(b);
      delete state.advisorActiveBlocks[event.tool];
      break;

    case 'done':
      finalizeAIBubble();
      setAdvisorInputEnabled(true);
      break;

    case 'cleared':
      clearChatUI();
      break;

    case 'error':
      appendErrorBubble(event.message);
      setAdvisorInputEnabled(true);
      break;
  }
}

function ensureAIBubble() {
  if (state.advisorCurrentMsgEl) return;
  hideEmptyState();
  const el = document.createElement('div');
  el.className = 'msg msg-ai streaming';
  el.innerHTML = `
    <div class="msg-thinking-area"></div>
    <div class="msg-text"></div>`;
  document.getElementById('chat-messages').appendChild(el);
  state.advisorCurrentMsgEl  = el;
  state.advisorCurrentTextEl = el.querySelector('.msg-text');
}

function finalizeAIBubble() {
  if (!state.advisorCurrentMsgEl) return;
  const text = state.advisorCurrentTextEl.textContent;
  state.advisorCurrentTextEl.innerHTML = window.marked
    ? window.marked.parse(text)
    : text.replace(/\n/g, '<br>');
  state.advisorCurrentMsgEl.classList.remove('streaming');
  state.advisorCurrentMsgEl = null;
  state.advisorCurrentTextEl = null;
}

function appendUserBubble(text) {
  hideEmptyState();
  const el = document.createElement('div');
  el.className = 'msg msg-user';
  el.textContent = text;
  document.getElementById('chat-messages').appendChild(el);
  scrollChat();
}

function appendErrorBubble(message) {
  const el = document.createElement('div');
  el.className = 'msg msg-error';
  el.textContent = `Error: ${message}`;
  document.getElementById('chat-messages').appendChild(el);
  scrollChat();
}

function createThinkingBlock(tool, input) {
  const label  = TOOL_LABELS[tool] || tool;
  const ticker = input?.ticker ? ` for ${input.ticker.toUpperCase()}` : '';
  const el = document.createElement('details');
  el.className = 'thinking-block';
  // Start collapsed - user can click to expand
  el.innerHTML = `
    <summary>
      <span class="thinking-spinner"></span>
      <span class="thinking-label">${label}${ticker}</span>
      <span class="thinking-toggle"></span>
    </summary>
    <div class="thinking-body">
      <pre>${JSON.stringify(input, null, 2)}</pre>
    </div>`;
  return el;
}

function closeThinkingBlock(el) {
  el.removeAttribute('open');
  el.querySelector('.thinking-spinner').className = 'thinking-done';
}

function hideEmptyState() {
  const emptyEl = document.getElementById('advisor-empty');
  const messagesEl = document.getElementById('chat-messages');
  if (!state.advisorHasMessages) {
    emptyEl.classList.add('hidden');
    messagesEl.classList.remove('hidden');
    state.advisorHasMessages = true;
  }
}

function clearChatUI() {
  document.getElementById('chat-messages').innerHTML = '';
  document.getElementById('advisor-empty').classList.remove('hidden');
  document.getElementById('chat-messages').classList.add('hidden');
  state.advisorHasMessages = false;
  state.advisorCurrentMsgEl = null;
  state.advisorCurrentTextEl = null;
  state.advisorActiveBlocks = {};
}

function scrollChat() {
  const container = document.getElementById('chat-messages');
  if (container) {
    container.scrollTop = container.scrollHeight;
  }
}

function setAdvisorInputEnabled(enabled) {
  const input = document.getElementById('advisor-input');
  const sendBtn = document.getElementById('advisor-send-btn');
  input.disabled = !enabled;
  sendBtn.disabled = !enabled;
  state.advisorStreaming = !enabled;
}

async function handleAdvisorSend() {
  const input = document.getElementById('advisor-input');
  const text = input.value.trim();
  if (!text || state.advisorStreaming) return;

  // Check WebSocket connection
  if (!state.advisorWS || state.advisorWS.readyState !== WebSocket.OPEN) {
    console.error('WebSocket not connected, attempting to reconnect...');
    connectAdvisorWS();
    setTimeout(() => {
      if (state.advisorWS?.readyState === WebSocket.OPEN) {
        handleAdvisorSend();
      } else {
        alert('Connection to advisor service failed. Please refresh the page.');
      }
    }, 1000);
    return;
  }

  input.value = '';
  input.style.height = 'auto';
  setAdvisorInputEnabled(false);

  appendUserBubble(text);

  try {
    state.advisorWS.send(JSON.stringify({ message: text }));
  } catch (err) {
    console.error('Failed to send message:', err);
    appendErrorBubble('Failed to send message. Please try again.');
    setAdvisorInputEnabled(true);
  }
}

async function handleAdvisorClear() {
  if (state.advisorHasMessages) {
    if (!confirm('Start a new conversation? This will clear the current chat history.')) return;
  }
  state.advisorWS.send(JSON.stringify({ action: 'clear' }));
}
