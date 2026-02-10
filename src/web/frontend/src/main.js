import Chart from 'chart.js/auto';

// Initialize Icons (using global lucide from CDN)
const {
  createIcons,
  Search,
  Brain,
  Newspaper,
  Bookmark,
  Activity,
  Power,
  Plus,
  PlusCircle,
  Trash2,
  Briefcase,
  LayoutDashboard,
  Lock,
  ShieldLock,
  RefreshCw
} = window.lucide;

createIcons({
  icons: {
    Search, Brain, Newspaper, Bookmark, Activity, Power, Plus, PlusCircle, Trash2, Briefcase, LayoutDashboard, Lock, ShieldLock, RefreshCw
  }
});

// App State
const state = {
  charts: {
    risk: null,
    sentiment: null,
    snapshotTrend: null,
    portfolioTrend: null
  },
  watchlist: [],
  portfolio: [],
  history: [],
  activeTicker: null,
  activePrice: null,
  isUnlocked: false,
  activeTab: 'dashboard',
  marketData: {} // Cache for lightweight price data
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
  document.getElementById('refresh-chart-btn').addEventListener('click', updatePortfolio);

  // Portfolio Input Logic
  document.getElementById('port-ticker-input').addEventListener('blur', handleTickerBlur);
  document.getElementById('port-qty').addEventListener('input', calculateCostBasis);

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

async function handleAnalyze() {
  const input = document.getElementById('ticker-input');
  const ticker = input.value.trim().toUpperCase();
  if (!ticker) return;

  state.activeTicker = ticker;
  setLoading(true);

  const maxNews = parseInt(document.getElementById('news-count').value) || 5;

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
      throw new Error(error.detail || 'Analysis failed');
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

// --- UI Updates ---
function updateUI(data) {
  // 1. Market Snapshot
  document.getElementById('ticker-display').textContent = data.ticker;
  state.activePrice = data.market_snapshot.current_price || 0;
  document.getElementById('price-display').textContent = `$${state.activePrice.toLocaleString(undefined, { minimumFractionDigits: 2 })}`;
  document.getElementById('volume-display').textContent = (data.market_snapshot.volume || 0).toLocaleString();
  document.getElementById('high-display').textContent = `$${(data.market_snapshot.high_52_week || 0).toFixed(2)}`;
  document.getElementById('low-display').textContent = `$${(data.market_snapshot.low_52_week || 0).toFixed(2)}`;

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

  // 5. News List
  renderNews(data.news);

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

  const portBtn = document.getElementById('add-portfolio-btn');
  portBtn.style.display = 'inline-flex';
  const isInPortfolio = state.portfolio.some(p => p.ticker === data.ticker);
  portBtn.innerHTML = isInPortfolio ? '<i data-lucide="briefcase"></i>' : '<i data-lucide="plus-circle"></i>';
  portBtn.title = isInPortfolio ? 'In Portfolio' : 'Add to Portfolio';

  createIcons({ icons: { BookmarkPlus, Check, Briefcase, PlusCircle } });
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

  container.innerHTML = news.map(item => `
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
    updatePortfolioTrendChart();
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
    body.innerHTML = '<tr><td colspan="7" class="placeholder">No holdings found</td></tr>';
    document.getElementById('total-value').textContent = '$0.00';
    document.getElementById('total-pl').textContent = '$0.00 (0.00%)';
    document.getElementById('total-pl').className = 'neutral';
    return;
  }

  let totalValue = 0;
  let totalCost = 0;

  body.innerHTML = state.portfolio.map(item => {
    // Priority: 1. Live Market Data, 2. History (if recently viewed), 3. Cost Basis (fallback)
    let currentPrice = item.cost_basis;

    if (state.marketData[item.ticker] && state.marketData[item.ticker].current_price) {
      currentPrice = state.marketData[item.ticker].current_price;
    } else {
      const hist = state.history.find(h => h.ticker === item.ticker);
      if (hist) currentPrice = hist.market_snapshot.current_price;
    }

    const value = item.quantity * currentPrice;
    const pl = value - (item.quantity * item.cost_basis);
    const plPercent = (item.quantity * item.cost_basis) > 0
      ? (pl / (item.quantity * item.cost_basis)) * 100
      : 0;

    totalValue += value;
    totalCost += (item.quantity * item.cost_basis);

    return `
      <tr>
        <td class="watchlist-ticker" onclick="selectTicker('${item.ticker}')">${item.ticker}</td>
        <td>$${currentPrice.toFixed(2)}</td>
        <td>${item.quantity}</td>
        <td>$${item.cost_basis.toFixed(2)}</td>
        <td>$${value.toFixed(2)}</td>
        <td class="${pl >= 0 ? 'plus' : 'minus'}">
          $${pl.toFixed(2)} (${plPercent.toFixed(2)}%)
        </td>
        <td>
          <button class="icon-btn danger" onclick="handleRemoveHolding('${item.ticker}')">
            <i data-lucide="trash-2"></i>
          </button>
        </td>
      </tr>
    `;
  }).join('');

  const totalPL = totalValue - totalCost;
  const totalPLPct = totalCost > 0 ? (totalPL / totalCost) * 100 : 0;

  document.getElementById('total-value').textContent = `$${totalValue.toLocaleString(undefined, { minimumFractionDigits: 2 })}`;
  const plEl = document.getElementById('total-pl');
  plEl.textContent = `$${totalPL.toFixed(2)} (${totalPLPct.toFixed(2)}%)`;
  plEl.className = totalPL >= 0 ? 'plus' : 'minus';

  createIcons({ icons: { Trash2 } });
}

function openPortfolioModal() {
  if (!state.isUnlocked) {
    document.getElementById('unlock-modal').classList.remove('hidden');
    return;
  }

  // Clear fields for new entry
  document.getElementById('port-ticker-input').value = '';
  document.getElementById('port-current-price').value = '';
  document.getElementById('port-qty').value = '';
  document.getElementById('port-cost').value = '';

  document.getElementById('port-modal-title').textContent = 'Add New Position';
  document.getElementById('portfolio-modal').classList.remove('hidden');
  // Focus on ticker input
  setTimeout(() => document.getElementById('port-ticker-input').focus(), 100);
}

async function handleTickerBlur(e) {
  const ticker = e.target.value.trim().toUpperCase();
  if (!ticker) return;

  // Try to find price in history first
  let price = 0;
  const hist = state.history.find(h => h.ticker === ticker);
  if (hist) {
    price = hist.market_snapshot.current_price;
  } else {
    // Attempt to fetch fresh data for the ticker
    try {
      document.getElementById('port-current-price').placeholder = 'Fetching...';
      const res = await fetch(`/api/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticker: ticker, model: 'llama3.2:3b' })
      });
      if (res.ok) {
        const data = await res.json();
        // The API returns { ticker, market_snapshot, ... }
        if (data.market_snapshot && data.market_snapshot.current_price) {
          price = data.market_snapshot.current_price;
        }
      }
    } catch (err) {
      console.error('Error fetching price:', err);
    } finally {
      document.getElementById('port-current-price').placeholder = '';
    }
  }

  if (price > 0) {
    document.getElementById('port-current-price').value = price.toFixed(2);
    calculateCostBasis();
  }
}

function calculateCostBasis() {
  const priceVal = document.getElementById('port-current-price').value;
  const qtyVal = document.getElementById('port-qty').value;

  const price = parseFloat(priceVal);
  const qty = parseFloat(qtyVal);

  if (!isNaN(price) && !isNaN(qty) && price > 0 && qty > 0) {
    const total = price * qty;
    document.getElementById('port-cost').value = total.toFixed(2);
  }
}

async function handleSaveHolding(e) {
  e.preventDefault();
  const ticker = document.getElementById('port-ticker-input').value.trim().toUpperCase();
  if (!ticker) return;

  const quantity = parseFloat(document.getElementById('port-qty').value);
  const cost_basis = parseFloat(document.getElementById('port-cost').value);

  try {
    const res = await fetch('/api/portfolio', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticker, quantity, cost_basis, added_at: new Date().toISOString() })
    });
    if (res.ok) {
      document.getElementById('portfolio-modal').classList.add('hidden');
      updatePortfolioStateUI();
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
    if (state.activeTicker === ticker.toUpperCase()) {
      const portBtn = document.getElementById('add-portfolio-btn');
      portBtn.innerHTML = '<i data-lucide="plus-circle"></i>';
      createIcons({ icons: { PlusCircle } });
    }
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

  // Portfolio Trend
  const portCtx = document.getElementById('portfolio-trend-chart').getContext('2d');
  state.charts.portfolioTrend = new Chart(portCtx, {
    type: 'line',
    data: { labels: [], datasets: [{ label: 'Total Value', data: [], borderColor: '#8b5cf6', tension: 0.4 }] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8' } },
        y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8' } }
      }
    }
  });
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

async function updatePortfolioTrendChart() {
  // Aggregated historical portfolio value chart (requires fetching multiple trends)
  // For simplicity now, we show the trend of the first holding as a demo,
  // or a placeholder if multiple.
  if (state.portfolio.length === 0) return;

  const mainTicker = state.portfolio[0].ticker;
  try {
    const res = await fetch(`/api/mcp/finance-server/get_trend_data?ticker=${mainTicker}&period=1mo`);
    const data = await res.json();
    if (data.points) {
      state.charts.portfolioTrend.data.labels = data.points.map(p => p.date);
      state.charts.portfolioTrend.data.datasets[0].data = data.points.map(p => p.price * state.portfolio[0].quantity);
      state.charts.portfolioTrend.update();
    }
  } catch (err) {
    console.error('Failed to update portfolio trend:', err);
  }
}

function getRiskColor(score) {
  if (score > 70) return '#ef4444';
  if (score > 30) return '#f59e0b';
  return '#22c55e';
}
