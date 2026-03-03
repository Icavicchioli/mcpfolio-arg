/**
 * fluid.js — Market Fluid D2Q9 Lattice Boltzmann simulator
 * Maps live financial data to swirling neon particles on a 2D canvas.
 *
 * Three components:
 *   LBMGrid        — D2Q9 Lattice Boltzmann physics
 *   ParticleSystem — Particle advection + rendering
 *   MarketFluid    — Public API: init / loadData / refresh / destroy
 */

// D2Q9 bounce-back table: OPP_DIR[i] gives the direction opposite to i
const OPP_DIR = [0, 2, 1, 4, 3, 7, 8, 5, 6];

// ── D2Q9 Lattice Boltzmann Grid ────────────────────────────────────────────

class LBMGrid {
  constructor(W, H, tau = 0.9) {
    this.W = W;
    this.H = H;
    this.tau   = tau;
    this.omega = 1.0 / tau;

    // D2Q9 velocity set
    this.cx = [ 0,  1, -1,  0,  0,  1, -1,  1, -1];
    this.cy = [ 0,  0,  0,  1, -1,  1,  1, -1, -1];
    this.wt = [4/9, 1/9, 1/9, 1/9, 1/9, 1/36, 1/36, 1/36, 1/36];
    this.Q  = 9;

    const N    = W * H * this.Q;
    this.f     = new Float32Array(N);
    this.fTemp = new Float32Array(N);

    // Solid obstacle map (1 = solid, 0 = fluid)
    this.solid = new Uint8Array(W * H);

    // Macroscopic velocity cached after each step()
    this._ux = new Float32Array(W * H);
    this._uy = new Float32Array(W * H);

    this.reset();
  }

  reset() {
    const { W, H, Q, wt, f } = this;
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        const base = (y * W + x) * Q;
        for (let i = 0; i < Q; i++) {
          f[base + i] = wt[i]; // rest state: rho=1, u=0
        }
      }
    }
  }

  clearObstacles() {
    this.solid.fill(0);
  }

  /** Mark cells within the inner 70% of radius r as solid. */
  setObstacleCircle(cx, cy, r) {
    const { W, H, solid } = this;
    const innerR = r * 0.7;
    const r2     = innerR * innerR;
    const xMin   = Math.max(0,     Math.floor(cx - innerR));
    const xMax   = Math.min(W - 1, Math.ceil (cx + innerR));
    const yMin   = Math.max(0,     Math.floor(cy - innerR));
    const yMax   = Math.min(H - 1, Math.ceil (cy + innerR));
    for (let y = yMin; y <= yMax; y++) {
      for (let x = xMin; x <= xMax; x++) {
        if ((x - cx) ** 2 + (y - cy) ** 2 <= r2) {
          solid[y * W + x] = 1;
        }
      }
    }
  }

  getDensityAt(gx, gy) {
    const base = (gy * this.W + gx) * this.Q;
    let rho = 0;
    for (let i = 0; i < this.Q; i++) rho += this.f[base + i];
    return rho;
  }

  /**
   * Nudge all fluid cells toward equilibrium at background velocity (ux_bg, uy_bg).
   * Blend factor 0.005 keeps effective background velocity ~0.05 LBM units (CFL safe).
   */
  applyGlobalMomentum(ux_bg, uy_bg) {
    const { W, H, Q, cx, cy, wt, f, solid } = this;
    const usq = ux_bg * ux_bg + uy_bg * uy_bg;
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        const cell = y * W + x;
        if (solid[cell]) continue;
        const base = cell * Q;
        let rho = 0;
        for (let i = 0; i < Q; i++) rho += f[base + i];
        for (let i = 0; i < Q; i++) {
          const cu  = cx[i] * ux_bg + cy[i] * uy_bg;
          const feq = wt[i] * rho * (1.0 + 3.0 * cu + 4.5 * cu * cu - 1.5 * usq);
          f[base + i] += 0.005 * (feq - f[base + i]);
        }
      }
    }
  }

  step() {
    const { W, H, Q, cx, cy, wt, f, fTemp, _ux, _uy, solid } = this;
    const omega = this.omega;

    // ── Collision (BGK) ─────────────────────────────────────────
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        const cell = y * W + x;
        if (solid[cell]) continue;  // skip solid nodes
        const base = cell * Q;

        // Macroscopic density + velocity
        let rho = 0, ux = 0, uy = 0;
        for (let i = 0; i < Q; i++) {
          const fi = f[base + i];
          rho += fi;
          ux  += cx[i] * fi;
          uy  += cy[i] * fi;
        }
        if (rho > 1e-10) { ux /= rho; uy /= rho; }

        // Clamp for numerical stability (Mach < 0.3)
        if (ux >  0.25) ux =  0.25;
        if (ux < -0.25) ux = -0.25;
        if (uy >  0.25) uy =  0.25;
        if (uy < -0.25) uy = -0.25;

        _ux[cell] = ux;
        _uy[cell] = uy;

        // Post-collision distribution → fTemp
        const usq = ux * ux + uy * uy;
        for (let i = 0; i < Q; i++) {
          const cu  = cx[i] * ux + cy[i] * uy;
          const feq = wt[i] * rho * (1.0 + 3.0 * cu + 4.5 * cu * cu - 1.5 * usq);
          fTemp[base + i] = f[base + i] + omega * (feq - f[base + i]);
        }
      }
    }

    // ── Streaming (pull, with bounce-back for solid obstacles) ──
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        const cell = y * W + x;
        if (solid[cell]) continue;  // solid holds no fluid
        const base = cell * Q;
        for (let i = 0; i < Q; i++) {
          const nx = (x - cx[i] + W) % W;
          const ny = (y - cy[i] + H) % H;
          if (solid[ny * W + nx]) {
            // Full bounce-back: reflect from this cell's own post-collision state
            f[base + i] = fTemp[cell * Q + OPP_DIR[i]];
          } else {
            f[base + i] = fTemp[(ny * W + nx) * Q + i];
          }
        }
      }
    }
  }

  /**
   * Blend fluid at (sx,sy) toward equilibrium at velocity (ux,uy).
   * Mass-preserving; strength controls blend speed.
   */
  addMomentumSource(sx, sy, ux, uy, strength, radius = 4) {
    const { W, H, Q, cx, cy, wt, f, solid } = this;
    const r2    = radius * radius;
    const blend = Math.min(0.22, strength * 0.05);
    const usq   = ux * ux + uy * uy;
    const xMin  = Math.max(0,     Math.floor(sx - radius));
    const xMax  = Math.min(W - 1, Math.ceil (sx + radius));
    const yMin  = Math.max(0,     Math.floor(sy - radius));
    const yMax  = Math.min(H - 1, Math.ceil (sy + radius));

    for (let y = yMin; y <= yMax; y++) {
      for (let x = xMin; x <= xMax; x++) {
        if ((x - sx) ** 2 + (y - sy) ** 2 > r2) continue;
        if (solid[y * W + x] === 1) continue;  // skip solid cells
        const base = (y * W + x) * Q;

        let rho = 0;
        for (let i = 0; i < Q; i++) rho += f[base + i];

        for (let i = 0; i < Q; i++) {
          const cu  = cx[i] * ux + cy[i] * uy;
          const feq = wt[i] * rho * (1.0 + 3.0 * cu + 4.5 * cu * cu - 1.5 * usq);
          f[base + i] += blend * (feq - f[base + i]);
        }
      }
    }
  }

  getUx() { return this._ux; }
  getUy() { return this._uy; }

  /** Finite-difference vorticity: ∂uy/∂x − ∂ux/∂y */
  getCurlField() {
    const { W, H, _ux, _uy } = this;
    const curl = new Float32Array(W * H);
    for (let y = 1; y < H - 1; y++) {
      for (let x = 1; x < W - 1; x++) {
        const duyDx = (_uy[y * W + x + 1] - _uy[y * W + x - 1]) * 0.5;
        const duxDy = (_ux[(y + 1) * W + x] - _ux[(y - 1) * W + x]) * 0.5;
        curl[y * W + x] = duyDx - duxDy;
      }
    }
    return curl;
  }
}

// ── Particle System ────────────────────────────────────────────────────────

class ParticleSystem {
  constructor(maxParticles) {
    this.maxParticles = maxParticles;
    this.particles    = [];
  }

  inject(x, y, color, count = 5) {
    const { r, g, b } = color;
    for (let i = 0; i < count; i++) {
      if (this.particles.length >= this.maxParticles) break;
      const life = 120 + Math.random() * 180;
      this.particles.push({
        x:       x + (Math.random() - 0.5) * 4,
        y:       y + (Math.random() - 0.5) * 4,
        vx:      (Math.random() - 0.5) * 0.3,
        vy:      (Math.random() - 0.5) * 0.3,
        life,
        maxLife: life,
        r, g, b,
      });
    }
  }

  step(uxField, uyField, W, H) {
    const ps = this.particles;
    for (let i = ps.length - 1; i >= 0; i--) {
      const p = ps[i];
      p.life -= 1;
      if (p.life <= 0) {
        ps[i] = ps[ps.length - 1];
        ps.pop();
        continue;
      }

      const gx  = Math.max(0, Math.min(W - 1, p.x | 0));
      const gy  = Math.max(0, Math.min(H - 1, p.y | 0));
      const idx = gy * W + gx;

      p.vx = p.vx * 0.92 + (uxField[idx] || 0) * 10 + (Math.random() - 0.5) * 0.04;
      p.vy = p.vy * 0.92 + (uyField[idx] || 0) * 10 + (Math.random() - 0.5) * 0.04;

      p.x += p.vx;
      p.y += p.vy;
      if (p.x <  0) p.x += W;
      if (p.x >= W) p.x -= W;
      if (p.y <  0) p.y += H;
      if (p.y >= H) p.y -= H;
    }
  }

  render(ctx, W, H, scale) {
    if (!this.particles.length) return;

    ctx.save();
    ctx.globalCompositeOperation = 'screen';

    // Group by color family to minimize state changes (4 possible colors)
    const COLORS = ['0,229,255', '255,48,96', '124,111,247', '245,158,11'];
    const groups = [[], [], [], []];
    for (const p of this.particles) {
      if      (p.r === 0)   groups[0].push(p);   // cyan
      else if (p.r === 255) groups[1].push(p);   // rose
      else if (p.r === 245) groups[3].push(p);   // amber
      else                  groups[2].push(p);   // accent/purple
    }

    for (let c = 0; c < 4; c++) {
      if (!groups[c].length) continue;
      const col = COLORS[c];
      ctx.fillStyle   = `rgb(${col})`;

      for (const p of groups[c]) {
        const alpha = p.life / p.maxLife;
        const x = p.x * scale;
        const y = p.y * scale;

        // Outer glow
        ctx.globalAlpha = alpha * 0.4;
        ctx.beginPath();
        ctx.arc(x, y, 2 + alpha * 2.5, 0, Math.PI * 2);
        ctx.fill();

        // Inner core
        ctx.globalAlpha = alpha * 0.8 + 0.1;
        ctx.beginPath();
        ctx.arc(x, y, 0.8 + alpha * 0.8, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    ctx.globalAlpha = 1;
    ctx.restore();
  }
}

// ── MarketFluid ────────────────────────────────────────────────────────────

export class MarketFluid {
  constructor() {
    this._canvas      = null;
    this._ctx         = null;
    this._lbm         = null;
    this._particles   = null;
    this._rafId       = null;
    this._isCompact   = false;
    this._sources     = [];   // [{x,y,ux,uy,strength,radius,color,ticker,...buoy fields}]
    this._stepCount   = 0;
    this._signals     = {};
    this._legendEl    = null;
    this._signalEl    = null;
    this._W           = 128;
    this._H           = 64;
    this._scale       = 1;
    this._resizeBound = null;
    this._marketUy    = 0;                     // cap-weighted market wind
    this._forceBufX   = new Float32Array(20);  // pre-allocated buoy force buffers (avoids GC)
    this._forceBufY   = new Float32Array(20);
    // World-market mode
    this._worldState    = null;   // { regions, vix, overall_change_pct, market_regime }
    this._regionSources = [];     // derived injection points (no labels, no buoys)
    this._palette       = 'neutral'; // 'bull' | 'bear' | 'volatile' | 'mixed'
  }

  /**
   * Attach to a canvas element and start the RAF loop.
   * @param {HTMLCanvasElement} canvas
   * @param {boolean} isCompact — use 96×48 grid and 400 particles (portfolio mode)
   */
  init(canvas, isCompact = false) {
    if (this._canvas) this.destroy();

    this._canvas    = canvas;
    this._ctx       = canvas.getContext('2d');
    this._isCompact = isCompact;
    this._W         = isCompact ? 96  : 128;
    this._H         = isCompact ? 48  : 64;
    const maxP      = isCompact ? 400 : 800;

    this._lbm       = new LBMGrid(this._W, this._H, 0.9);
    this._particles = new ParticleSystem(maxP);

    this._resizeBound = () => this._resizeCanvas();
    window.addEventListener('resize', this._resizeBound);
    this._resizeCanvas();
    this._startLoop();
  }

  _resizeCanvas() {
    const canvas = this._canvas;
    if (!canvas) return;
    const rect   = canvas.getBoundingClientRect();
    const w      = Math.round(rect.width)  || 800;
    const h      = Math.round(rect.height) || (this._isCompact ? 200 : 380);
    canvas.width  = w;
    canvas.height = h;
    this._scale   = Math.max(w / this._W, h / this._H);
  }

  /**
   * Map array of financial objects to fluid sources and reset simulation.
   * @param {Array<{ticker, price_change_pct, volume_ratio, volatility_52w, market_cap, pl_pct?}>} tickers
   */
  loadData(tickers) {
    if (!this._lbm) return;
    this._sources = [];
    const n = tickers.length;
    if (n === 0) return;

    this._lbm.reset();
    this._particles.particles = [];
    this._stepCount = 0;

    const vols   = tickers.map(t => t.volatility_52w || 0.2);
    const maxVol = Math.max(...vols, 0.01);

    tickers.forEach((data, i) => {
      // 2D staggered scatter: alternating rows so sources form a cloud, not a line
      let x, y;
      if (n === 1) {
        x = 0.5 * this._W;
        y = 0.5 * this._H;
      } else if (n === 2) {
        x = (i === 0 ? 0.30 : 0.70) * this._W;
        y = (i === 0 ? 0.35 : 0.65) * this._H + (Math.random() - 0.5) * 0.08 * this._H;
      } else {
        const row      = i % 2;
        const col      = Math.floor(i / 2);
        const colCount = Math.ceil(n / 2);
        x = (0.15 + (col / (colCount - 1 || 1)) * 0.70) * this._W;
        y = (row === 0 ? 0.35 : 0.65) * this._H + (Math.random() - 0.5) * 0.08 * this._H;
      }

      // Price change → vertical source velocity (bullish = up, bearish = down)
      const change = data.price_change_pct || 0;
      const ux     = (Math.random() - 0.5) * 0.01;
      const uy     = -Math.max(-0.18, Math.min(0.18, change * 0.04));

      // Volume ratio → injection strength
      const volRatio = Math.max(0.1, data.volume_ratio || 1.0);
      const strength = Math.min(2.0, Math.sqrt(volRatio) * 0.8);

      // 52-week volatility → viscosity (tau)
      const normVol     = (data.volatility_52w || 0.2) / maxVol;
      this._lbm.tau     = 0.6 + (1 - normVol) * 1.2;   // range [0.6, 1.8]
      this._lbm.omega   = 1.0 / this._lbm.tau;

      // Market cap → source radius
      const mktCap = data.market_cap || 1e9;
      const radius = Math.max(4, 4 + Math.log10(Math.max(1, mktCap / 1e9)) * 2);

      // Price direction → particle color
      const pctVal = data.pl_pct !== undefined ? data.pl_pct : change;
      const color  = pctVal > 0
        ? { r: 0,   g: 229, b: 255 }   // cyan  — bullish / profit
        : pctVal < 0
          ? { r: 255, g: 48,  b: 96  } // rose  — bearish / loss
          : { r: 124, g: 111, b: 247 }; // accent — neutral

      this._sources.push({
        x, y,
        ux, uy, strength, radius, color,
        ticker: data.ticker, changePct: change,
        // Buoy fields
        homeX: x, homeY: y,   // spring anchors (fixed after loadData)
        px: x,    py: y,      // current buoy position (drifts each tick)
        pvx: 0,   pvy: 0,     // buoy velocity
        localCurl: 0,          // updated every 180 steps for label tilt
      });
    });

    // Initialize solid obstacles at starting positions
    this._rebuildObstacles();

    this._renderLegend();
  }

  _rebuildObstacles() {
    this._lbm.clearObstacles();
    for (const src of this._sources) {
      this._lbm.setObstacleCircle(src.px, src.py, src.radius);
    }
  }

  /** Compute cap-weighted average market direction from all sources. */
  _computeMarketWind() {
    let wSum = 0, wTot = 0;
    for (const src of this._sources) {
      wSum += src.uy * src.strength;
      wTot += src.strength;
    }
    this._marketUy = wTot > 1e-8 ? wSum / wTot : 0;
  }

  /**
   * Apply spring, repulsion, and fluid drag forces to each buoy,
   * integrate positions, clamp, then rebuild obstacle map.
   */
  _updateSourcePositions(uxField, uyField) {
    const { _sources, _forceBufX, _forceBufY, _W, _H } = this;
    const n = _sources.length;
    if (n === 0) return;

    const k_spring = 0.004;
    const repStr   = 8;
    const minDist  = 4;
    const drag     = 0.08;
    const damping  = 0.88;
    const maxVel   = 0.5;

    // Zero force buffers (avoid GC from re-allocation)
    _forceBufX.fill(0);
    _forceBufY.fill(0);

    // Spring: pull each buoy back toward its home position
    for (let i = 0; i < n; i++) {
      const src = _sources[i];
      _forceBufX[i] += k_spring * (src.homeX - src.px);
      _forceBufY[i] += k_spring * (src.homeY - src.py);
    }

    // N² pairwise repulsion: push buoys apart
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const dx   = _sources[i].px - _sources[j].px;
        const dy   = _sources[i].py - _sources[j].py;
        const dist = Math.max(minDist, Math.sqrt(dx * dx + dy * dy));
        const F    = repStr / (dist * dist);
        const ux_u = dx / dist;
        const uy_u = dy / dist;
        _forceBufX[i] += F * ux_u;
        _forceBufY[i] += F * uy_u;
        _forceBufX[j] -= F * ux_u;
        _forceBufY[j] -= F * uy_u;
      }
    }

    // Fluid drag + integrate velocity + clamp + update position
    for (let i = 0; i < n; i++) {
      const src = _sources[i];
      const gx  = Math.max(0, Math.min(_W - 1, Math.floor(src.px)));
      const gy  = Math.max(0, Math.min(_H - 1, Math.floor(src.py)));
      const idx = gy * _W + gx;

      _forceBufX[i] += drag * ((uxField[idx] || 0) * 6 - src.pvx);
      _forceBufY[i] += drag * ((uyField[idx] || 0) * 6 - src.pvy);

      src.pvx = src.pvx * damping + _forceBufX[i];
      src.pvy = src.pvy * damping + _forceBufY[i];

      // Clamp velocity (CFL safety: ≤1 cell transition per tick)
      if (src.pvx >  maxVel) src.pvx =  maxVel;
      if (src.pvx < -maxVel) src.pvx = -maxVel;
      if (src.pvy >  maxVel) src.pvy =  maxVel;
      if (src.pvy < -maxVel) src.pvy = -maxVel;

      src.px = Math.max(2, Math.min(_W - 2, src.px + src.pvx));
      src.py = Math.max(2, Math.min(_H - 2, src.py + src.pvy));
    }

    this._rebuildObstacles();
  }

  _renderLegend() {
    if (!this._legendEl) return;
    this._legendEl.innerHTML = this._sources.map(s => {
      const hex = `rgb(${s.color.r},${s.color.g},${s.color.b})`;
      return `<div class="fluid-legend-chip" style="border-color:${hex};color:${hex}">${s.ticker}</div>`;
    }).join('');
  }

  _startLoop() {
    if (this._rafId) cancelAnimationFrame(this._rafId);
    const loop = () => {
      this._rafId = requestAnimationFrame(loop);
      this._tick();
    };
    this._rafId = requestAnimationFrame(loop);
  }

  pause() {
    if (this._rafId) {
      cancelAnimationFrame(this._rafId);
      this._rafId = null;
    }
  }

  resume() {
    if (!this._rafId && this._canvas) {
      this._startLoop();
    }
  }

  _tick() {
    if (!this._lbm || !this._ctx) return;

    if (this._sources.length === 0) {
      // ── World-market mode (or pre-load) ───────────────────────
      this._injectWorldParticles();
    } else {
      // ── Ticker-buoy mode ──────────────────────────────────────

      // 1. Compute cap-weighted market wind
      this._computeMarketWind();

      // 2. Apply global momentum bias (before step, so it bakes into collision)
      this._lbm.applyGlobalMomentum(0, this._marketUy * 0.3);

      // 3. Inject directed momentum at each buoy position
      for (const src of this._sources) {
        this._lbm.addMomentumSource(src.px, src.py, src.ux, src.uy, src.strength, src.radius);
      }
    }

    // LBM step — bounce-back active at solid obstacles
    this._lbm.step();

    // Read updated velocity fields
    const ux = this._lbm.getUx();
    const uy = this._lbm.getUy();

    if (this._sources.length > 0) {
      // Update buoy positions + rebuild obstacle map
      this._updateSourcePositions(ux, uy);

      // Inject particles every 2 frames at current buoy positions
      if (this._stepCount % 2 === 0) {
        for (const src of this._sources) {
          const cnt = Math.max(1, Math.round(src.strength * 3));
          this._particles.inject(src.px, src.py, src.color, cnt);
        }
      }

      // Re-evaluate signals every 180 LBM steps
      if (this._stepCount % 180 === 0) {
        this._evaluateSignals();
      }
    }

    // Advect particles through the velocity field
    this._particles.step(ux, uy, this._W, this._H);

    this._stepCount++;
    this._render();
  }

  _defaultWorldSources() {
    // Fallback injection points — lower uy so columns don't form
    const col = this._palette === 'volatile' ? { r: 245, g: 158, b: 11  }
              : this._palette === 'bull'     ? { r: 0,   g: 229, b: 255 }
              : this._palette === 'bear'     ? { r: 255, g: 48,  b: 96  }
              :                               { r: 124, g: 111, b: 247 };
    const W = this._W, H = this._H;
    return [
      { x: 0.18 * W, y: 0.38 * H, ux:  0.04, uy: -0.04, weight: 0.20, color: col },
      { x: 0.50 * W, y: 0.30 * H, ux:  0.00, uy: -0.05, weight: 0.30, color: col },
      { x: 0.82 * W, y: 0.38 * H, ux: -0.04, uy: -0.04, weight: 0.20, color: col },
      { x: 0.32 * W, y: 0.65 * H, ux:  0.05, uy: -0.03, weight: 0.15, color: col },
      { x: 0.68 * W, y: 0.65 * H, ux: -0.05, uy: -0.03, weight: 0.15, color: col },
    ];
  }

  _injectWorldParticles() {
    // Inject every 4 frames — less frequent = LBM has time to develop its own flow
    if (this._stepCount % 4 !== 0) return;

    const vix      = this._worldState?.vix ?? null;
    const overall  = this._worldState?.overall_change_pct ?? null;
    const strength = vix ? Math.max(0.4, Math.min(1.8, vix / 14)) : 0.8;

    // Gentle global bias — keeps some directional coherence without dominating
    const bias = overall != null ? Math.max(-0.06, Math.min(0.06, overall * 0.012)) : 0;
    this._lbm.applyGlobalMomentum(0, -0.015 - Math.abs(bias));

    // Use real region sources if available, otherwise fall back to defaults
    const sources = this._regionSources.length > 0
      ? this._regionSources
      : this._defaultWorldSources();

    // Oscillate injection positions slowly so the LBM develops complex flow patterns
    const t = this._stepCount * 0.008;
    for (const rs of sources) {
      const jx  = rs.x + Math.sin(t + rs.x * 0.08) * 7;
      const jy  = rs.y + Math.cos(t * 0.6 + rs.y * 0.06) * 5;
      const cnt = Math.max(1, Math.round(rs.weight * strength * 4));
      // Reduced strength so LBM flow isn't forced into rigid channels
      this._lbm.addMomentumSource(jx, jy, rs.ux ?? 0, rs.uy ?? 0, strength * 0.45, 6);
      this._particles.inject(jx, jy, rs.color, cnt);
    }
  }

  setWorldState(data) {
    this._worldState = data;
    if (!this._lbm) return;

    const { regions = [], vix, overall_change_pct, market_regime } = data;

    // VIX → tau
    let tau = 0.9;
    if (vix != null) {
      if (vix < 15)       tau = 1.4;
      else if (vix <= 25) tau = 1.4 - (vix - 15) / 10 * 0.65;
      else                tau = Math.max(0.54, 0.75 - (vix - 25) / 20 * 0.21);
    }
    this._lbm.tau   = tau;
    this._lbm.omega = 1.0 / tau;

    // Palette from regime
    if      (market_regime === 'High Volatility') this._palette = 'volatile';
    else if (market_regime === 'Bull')             this._palette = 'bull';
    else if (market_regime === 'Bear')             this._palette = 'bear';
    else                                           this._palette = 'mixed';

    // Region → position mapping
    const REGION_POS = {
      Americas:    { rx: 0.75, ry: 0.45 },
      Europe:      { rx: 0.50, ry: 0.35 },
      Asia:        { rx: 0.25, ry: 0.45 },
      Commodities: { rx: 0.50, ry: 0.70 },
      Crypto:      { rx: 0.80, ry: 0.65 },
    };

    this._regionSources = regions.map(r => {
      const pos = REGION_POS[r.name] || { rx: 0.5, ry: 0.5 };
      const x   = pos.rx * this._W;
      const y   = pos.ry * this._H;
      const uy  = -Math.max(-0.15, Math.min(0.15, r.change_pct * 0.03));
      const chg = r.change_pct;

      let color;
      if      (chg > 0.1)  color = { r: 0,   g: 229, b: 255 };   // cyan — positive
      else if (chg < -0.1) color = { r: 255, g: 48,  b: 96  };   // rose — negative
      else if (this._palette === 'volatile') color = { r: 245, g: 158, b: 11 }; // amber
      else                 color = { r: 124, g: 111, b: 247 };   // purple — neutral

      return { x, y, ux: 0, uy, weight: r.weight, color };
    });
  }

  async refreshWorldState() {
    try {
      const res  = await fetch('/api/market/state');
      if (!res.ok) return null;
      const data = await res.json();
      this.setWorldState(data);
      return data;
    } catch (err) {
      console.error('[MarketFluid] refreshWorldState error:', err);
      return null;
    }
  }

  _render() {
    const ctx    = this._ctx;
    const canvas = this._canvas;
    const W      = canvas.width;
    const H      = canvas.height;
    const scale  = this._scale;

    const cx = W / 2;
    const cy = H / 2;
    const gradient = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(W, H));
    gradient.addColorStop(0, '#0d0c1c'); // Brighter, purplish center
    gradient.addColorStop(1, '#06090f'); // Original dark blue at edges

    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, W, H);

    // Particles (screen blend for neon glow)
    this._particles.render(ctx, this._W, this._H, scale);

    // Ticker labels + glow rings (using buoy positions px/py)
    ctx.save();
    ctx.globalCompositeOperation = 'source-over';
    for (const src of this._sources) {
      const sx = src.px * scale;
      const sy = src.py * scale;
      const { r, g, b } = src.color;

      // Glow ring at buoy position
      ctx.beginPath();
      ctx.arc(sx, sy, src.radius * scale * 0.35, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(${r},${g},${b},0.4)`;
      ctx.lineWidth   = 1;
      ctx.stroke();

      // Ticker label — tilts with local vorticity
      const fs     = this._isCompact ? 9 : 11;
      const labelY = sy - src.radius * scale * 0.5 - 3;
      const shiver = src.localCurl > 0.008 ? (Math.random() - 0.5) * src.localCurl * 8 : 0;

      ctx.save();
      ctx.translate(sx, labelY + shiver);
      ctx.rotate(src.localCurl * 12);
      ctx.font        = `bold ${fs}px "Outfit", sans-serif`;
      ctx.fillStyle   = `rgba(${r},${g},${b},0.92)`;
      ctx.textAlign   = 'center';
      ctx.shadowBlur  = 10;
      ctx.shadowColor = `rgba(${r},${g},${b},0.7)`;
      ctx.fillText(src.ticker, 0, 0);
      ctx.shadowBlur  = 0;
      ctx.restore();

      // Price-change % subtitle — un-rotated, drawn outside the transform
      if (src.changePct !== undefined) {
        const fs2 = this._isCompact ? 8 : 10;
        ctx.font        = `${fs2}px "Outfit", sans-serif`;
        ctx.fillStyle   = `rgba(${r},${g},${b},0.92)`;
        ctx.textAlign   = 'center';
        ctx.globalAlpha = 0.7;
        const sign = src.changePct >= 0 ? '+' : '';
        ctx.fillText(sign + src.changePct.toFixed(1) + '%', sx, sy - src.radius * scale * 0.5 + 12);
        ctx.globalAlpha = 1;
      }
    }
    ctx.restore();
  }

  _evaluateSignals() {
    const curl = this._lbm.getCurlField();
    const ux   = this._lbm.getUx();
    const uy   = this._lbm.getUy();
    const W    = this._W;
    const H    = this._H;
    const half = 6; // half-size of 12×12 evaluation region

    for (const src of this._sources) {
      const cx = Math.floor(src.px);  // use buoy position
      const cy = Math.floor(src.py);
      let sumCurl = 0, sumUy = 0, count = 0;

      for (let y = Math.max(0, cy - half); y < Math.min(H, cy + half); y++) {
        for (let x = Math.max(0, cx - half); x < Math.min(W, cx + half); x++) {
          const idx = y * W + x;
          sumCurl += Math.abs(curl[idx]);
          sumUy   += uy[idx];
          count++;
        }
      }
      if (count === 0) continue;

      const avgCurl = sumCurl / count;
      const avgUy   = Math.abs(sumUy / count);
      src.localCurl = avgCurl;  // store for reactive label tilt
      this._signals[src.ticker] =
        avgCurl > 0.012 ? 'vortex'  :
        avgUy   > 0.015 ? 'laminar' : null;
    }

    this._updateSignalBadges();
  }

  _updateSignalBadges() {
    if (!this._signalEl) return;
    const badges = this._sources
      .filter(src => this._signals[src.ticker])
      .map(src => {
        const type  = this._signals[src.ticker];
        const icon  = type === 'vortex' ? '↺' : '▸';
        const label = type === 'vortex' ? 'Vortex' : 'Laminar';
        return `<span class="signal-badge ${type}">${src.ticker} ${icon} ${label}</span>`;
      });
    this._signalEl.innerHTML = badges.join('');
  }

  /** Return a snapshot of the current vortex/laminar signals per ticker. */
  getSignals() {
    return { ...this._signals };
  }

  /** Fetch fresh data from the backend and reload the simulation. */
  async refresh(apiScope) {
    try {
      const res = await fetch(`/api/fluid/data?scope=${apiScope}`);
      if (!res.ok) return;
      const data = await res.json();
      if (data.tickers && data.tickers.length > 0) {
        this.loadData(data.tickers);
      }
    } catch (err) {
      console.error('[MarketFluid] refresh error:', err);
    }
  }

  setLegendEl(el) { this._legendEl = el; }
  setSignalEl(el)  { this._signalEl = el; }

  destroy() {
    if (this._rafId) { cancelAnimationFrame(this._rafId); this._rafId = null; }
    if (this._resizeBound) window.removeEventListener('resize', this._resizeBound);
    this._lbm       = null;
    this._particles = null;
    this._canvas    = null;
    this._ctx       = null;
  }
}
