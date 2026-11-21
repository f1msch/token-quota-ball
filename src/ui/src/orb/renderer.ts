import { palette, rgb, visualFill, type Palette, type RGB } from "./palette";

/**
 * Canvas water orb. Water motion follows the selected demo schemes only:
 *  1. slow crescent meniscus — one long-wavelength swell plus a slower
 *     secondary, with the surface climbing the glass at the rim;
 *  6. underwater motes — fine dust wandering slowly on its own orbit, each mote
 *     twinkling on an independent, shallow tempo.
 * Level still eases continuously (every 1% of used quota is distinct).
 */
const VIEW = 96;
const CENTER = VIEW / 2;
const R_GLASS = 46.4;
const R_WATER = 44.0;
const TAU = Math.PI * 2;
const DUST_COUNT = 30;
// Amplitudes are slightly above a strict 44/104 scale of the demo so the
// crescent and motes stay readable on the 96px ball, without getting busy.
const MENISCUS = 4.2;
const MENISCUS_POWER = 4.4;
// Four incommensurate swells instead of two equal-length ones: the spatial and
// temporal ratios are far from simple fractions, so the surface never repeats a
// short pattern. Two of them breathe in amplitude on their own slow cycles.
const WAVE_A = 2.2;
const WAVE_B = 1.4;
const WAVE_C = 0.9;
const WAVE_D = 0.7;
const WAVE_MOD_A = 0.22;
const WAVE_MOD_B = 0.3;
// Worst-case rise above the flat baseline; the light band starts above this.
const WAVE_MAX =
  WAVE_A * (1 + WAVE_MOD_A) + WAVE_B * (1 + WAVE_MOD_B) + WAVE_C + WAVE_D;

interface DustMote {
  nx: number;
  ny: number;
  z: number;
  sp: number;
  ph: number;
  tw: number;
  size: number;
}

function lighten(c: RGB, t: number): RGB {
  return [
    Math.round(c[0] + (255 - c[0]) * t),
    Math.round(c[1] + (255 - c[1]) * t),
    Math.round(c[2] + (255 - c[2]) * t),
  ];
}

function darken(c: RGB, t: number): RGB {
  return [Math.round(c[0] * (1 - t)), Math.round(c[1] * (1 - t)), Math.round(c[2] * (1 - t))];
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}

function rand(s: number): number {
  const x = Math.sin(s * 127.1 + 311.7) * 43758.5453;
  return x - Math.floor(x);
}

export class OrbRenderer {
  private ctx: CanvasRenderingContext2D;
  private dpr = 1;
  private target: number | null = null;
  private display = 0;
  private time = 0;
  private raf = 0;
  private last = 0;
  private running = false;
  private dust: DustMote[] = [];

  constructor(private readonly canvas: HTMLCanvasElement) {
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("canvas 2d context unavailable");
    this.ctx = ctx;
    this.applySize();
    this.seedDust();
  }

  setTarget(pct: number | null): void {
    this.target = pct;
  }

  start(): void {
    if (this.running) return;
    this.running = true;
    this.last = performance.now();
    const frame = (now: number) => {
      if (!this.running) return;
      this.step(now);
      this.raf = requestAnimationFrame(frame);
    };
    this.raf = requestAnimationFrame(frame);
  }

  stop(): void {
    this.running = false;
    cancelAnimationFrame(this.raf);
  }

  private seedDust(): void {
    this.dust = [];
    for (let i = 0; i < DUST_COUNT; i += 1) {
      this.dust.push({
        nx: rand(i * 3.1 + 0.4) * 2 - 1,
        ny: rand(i * 5.7 + 0.4) * 2 - 1,
        z: rand(i * 8.3 + 0.4),
        sp: 0.015 + rand(i * 2.9) * 0.04,
        ph: rand(i * 11.1) * Math.PI * 2,
        tw: rand(i * 13.3) * Math.PI * 2,
        size: 0.45 + rand(i * 4.4) * 1.15,
      });
    }
  }

  private applySize(): void {
    this.dpr = Math.min(2.5, Math.max(1, window.devicePixelRatio || 1));
    this.canvas.width = Math.round(VIEW * this.dpr);
    this.canvas.height = Math.round(VIEW * this.dpr);
    this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
  }

  private fillFraction(): number {
    return visualFill(this.display);
  }

  private baseFillY(): number {
    const fill = this.fillFraction();
    return CENTER + R_WATER - 2 * R_WATER * fill;
  }

  private step(now: number): void {
    const dt = clamp((now - this.last) / 1000, 0.001, 0.05);
    this.last = now;

    const goal = this.target ?? 0;
    const rate = this.target == null ? 2.6 : 3.8;
    this.display += (goal - this.display) * (1 - Math.exp(-dt * rate));
    if (Math.abs(goal - this.display) < 0.02) this.display = goal;

    this.time += dt;
    this.draw();
  }

  /**
   * Crescent surface: rim meniscus + four swells whose speeds are mutually
   * incommensurate (0.71 / 0.47 / 0.293 / 0.187 rad·s⁻¹) and two of which slowly
   * breathe in amplitude, so crests drift in and out instead of marching to a
   * fixed beat. Everything is a smooth function of time — no per-frame noise.
   */
  private surfaceY(x: number): number {
    const fillY = this.baseFillY();
    const nx = (x - CENTER) / R_WATER;
    const ny0 = (fillY - CENTER) / R_WATER;
    const xmax = Math.sqrt(Math.max(0.0001, 1 - ny0 * ny0));
    const u = clamp(Math.abs(nx) / xmax, 0, 1);
    const meniscus = MENISCUS * Math.pow(u, MENISCUS_POWER);
    const t = this.time;
    const drift = Math.sin(t * 0.061 + 0.6) * 0.9;
    const breathA = 1 + WAVE_MOD_A * Math.sin(t * 0.17 + 0.6);
    const breathB = 1 + WAVE_MOD_B * Math.sin(t * 0.113 + 2.1);
    const wave =
      WAVE_A * breathA * Math.sin(nx * 2.55 + t * 0.71 + drift) +
      WAVE_B * breathB * Math.sin(nx * 4.1 - t * 0.47 + 1.3) +
      WAVE_C * Math.sin(nx * 6.3 + t * 0.293 + drift * 0.7) +
      WAVE_D * Math.sin(nx * 1.15 - t * 0.187 + 0.4);
    return fillY - meniscus + wave;
  }

  private edgePoints(): { left: [number, number]; right: [number, number] } | null | "full" {
    const yMid = this.surfaceY(CENTER);
    if (yMid >= CENTER + R_WATER - 0.4) return null;
    if (yMid <= CENTER - R_WATER + 0.4) return "full";

    const find = (side: number): [number, number] => {
      let lo = CENTER;
      let hi = CENTER + side * R_WATER;
      for (let i = 0; i < 20; i += 1) {
        const mid = (lo + hi) * 0.5;
        const y = this.surfaceY(mid);
        const dx = mid - CENTER;
        const dy = y - CENTER;
        const inside = dx * dx + dy * dy <= R_WATER * R_WATER;
        if (inside) lo = mid;
        else hi = mid;
      }
      return [lo, this.surfaceY(lo)];
    };
    return { left: find(-1), right: find(1) };
  }

  private draw(): void {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, VIEW, VIEW);

    const pct = this.target == null ? null : this.display;
    const pal = palette(pct);

    this.drawGlassBody(pal);
    this.drawWater(pal);
    this.drawGlassFront();
  }

  private drawGlassBody(pal: Palette): void {
    const ctx = this.ctx;
    ctx.save();
    ctx.beginPath();
    ctx.arc(CENTER, CENTER, R_GLASS, 0, TAU);
    ctx.clip();

    const bg = ctx.createRadialGradient(
      CENTER - R_GLASS * 0.22,
      CENTER - R_GLASS * 0.3,
      R_GLASS * 0.06,
      CENTER,
      CENTER,
      R_GLASS * 1.02,
    );
    bg.addColorStop(0, rgb(lighten(pal.glass, 0.5), 0.98));
    bg.addColorStop(0.55, rgb(pal.glass, 0.98));
    bg.addColorStop(1, rgb(darken(pal.glass, 0.38), 0.99));
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, VIEW, VIEW);

    const upper = ctx.createLinearGradient(0, 0, 0, CENTER);
    upper.addColorStop(0, "rgba(255, 255, 255, 0.12)");
    upper.addColorStop(1, "rgba(255, 255, 255, 0)");
    ctx.fillStyle = upper;
    ctx.fillRect(0, 0, VIEW, CENTER);
    ctx.restore();
  }

  private waterPath(edges: { left: [number, number]; right: [number, number] } | "full"): Path2D {
    const path = new Path2D();
    if (edges === "full") {
      path.arc(CENTER, CENTER, R_WATER, 0, TAU);
      return path;
    }
    const x0 = edges.left[0];
    const x1 = edges.right[0];
    const steps = 64;
    path.moveTo(x0, edges.left[1]);
    for (let i = 1; i <= steps; i += 1) {
      const x = x0 + (x1 - x0) * (i / steps);
      path.lineTo(x, this.surfaceY(x));
    }
    const aR = Math.atan2(edges.right[1] - CENTER, edges.right[0] - CENTER);
    const aL = Math.atan2(edges.left[1] - CENTER, edges.left[0] - CENTER);
    path.arc(CENTER, CENTER, R_WATER, aR, aL, false);
    path.closePath();
    return path;
  }

  private drawWater(pal: Palette): void {
    const ctx = this.ctx;
    const edges = this.edgePoints();
    if (!edges) return;

    ctx.save();
    ctx.beginPath();
    ctx.arc(CENTER, CENTER, R_WATER, 0, TAU);
    ctx.clip();

    const water = this.waterPath(edges);
    const fillY = this.baseFillY();
    const top = edges === "full" ? CENTER - R_WATER : fillY - 16;
    const body = ctx.createLinearGradient(0, top, 0, CENTER + R_WATER);
    body.addColorStop(0, rgb(pal.crest, 0.92));
    body.addColorStop(0.16, rgb(pal.mid, 0.97));
    body.addColorStop(0.7, rgb(pal.deep, 1));
    body.addColorStop(1, rgb(darken(pal.deep, 0.18), 1));
    ctx.fillStyle = body;
    ctx.fill(water);

    // Quiet spherical volume — slightly brighter core, darker limb. Kept
    // modest so the fill stays saturated rather than milky.
    ctx.save();
    ctx.clip(water);
    const core = ctx.createRadialGradient(
      CENTER - R_WATER * 0.18,
      CENTER - R_WATER * 0.05,
      R_WATER * 0.05,
      CENTER,
      CENTER + R_WATER * 0.08,
      R_WATER * 0.98,
    );
    core.addColorStop(0, "rgba(255, 255, 255, 0.12)");
    core.addColorStop(0.3, rgb(lighten(pal.mid, 0.08), 0.06));
    core.addColorStop(0.65, "rgba(0, 0, 0, 0)");
    core.addColorStop(1, "rgba(0, 0, 0, 0.20)");
    ctx.fillStyle = core;
    ctx.fillRect(0, 0, VIEW, VIEW);

    if (edges !== "full") {
      // The band has to start above the tallest crest with zero alpha. Anchoring
      // it on the flat baseline put a rectangle edge at y = fillY - 2, which
      // showed up as a straight horizontal seam under every crest.
      const rise = MENISCUS + WAVE_MAX;
      const bandTop = fillY - rise - 1;
      const bandBottom = fillY + 10;
      const bandSpan = bandBottom - bandTop;
      const band = ctx.createLinearGradient(0, bandTop, 0, bandBottom);
      band.addColorStop(0, rgb(pal.crest, 0));
      band.addColorStop((fillY - 2 - bandTop) / bandSpan, rgb(pal.crest, 0.34));
      band.addColorStop((fillY + 2.8 - bandTop) / bandSpan, rgb(pal.foam, 0.12));
      band.addColorStop(1, "rgba(255, 255, 255, 0)");
      ctx.fillStyle = band;
      ctx.fillRect(0, bandTop, VIEW, bandSpan);
    }

    this.drawDust(pal, edges);
    ctx.restore();

    if (edges !== "full") this.drawSurface(pal, edges);
    ctx.restore();
  }

  private drawDust(pal: Palette, edges: { left: [number, number]; right: [number, number] } | "full"): void {
    const ctx = this.ctx;
    const t = this.time;
    const r2 = R_WATER * R_WATER * 0.9;
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    for (let i = 0; i < this.dust.length; i += 1) {
      const d = this.dust[i];
      // Closed-form wander: two slow, incommensurate orbits per mote. Being a
      // pure function of time keeps the drift continuous (no random jitter, no
      // wrap-around jump) and lets any frame be rendered from its timestamp.
      const wander = 0.055 + d.sp * 3.2;
      const ox =
        wander * Math.sin(t * 0.083 + d.ph) + wander * 0.45 * Math.sin(t * 0.037 + d.ph * 1.7 + 1.1);
      const oy =
        wander * 0.6 * Math.sin(t * 0.061 + d.ph * 1.3 + 0.5) + wander * 0.3 * Math.sin(t * 0.024 + d.ph * 2.1);
      const x = CENTER + (d.nx + ox) * R_WATER * 0.78;
      const y = CENTER + (d.ny + oy) * R_WATER * 0.78;
      if (edges !== "full" && y < this.surfaceY(x) + 1) continue;
      const dx = x - CENTER;
      const dy = y - CENTER;
      if (dx * dx + dy * dy > r2) continue;
      // Every mote twinkles on its own tempo (0.55–1.4 rad/s) plus a detuned
      // second harmonic, so no two brighten together. Depth is kept shallow so
      // it reads as distant starlight rather than blinking.
      const tempo = 0.55 + d.z * 0.85;
      const beat =
        Math.sin(t * tempo + d.tw) * 0.65 +
        Math.sin(t * tempo * 0.42 + d.tw * 1.9) * 0.35;
      const twinkle = 0.6 + 0.4 * (0.5 + 0.5 * beat);
      const a = (0.24 + d.z * 0.36) * twinkle;
      const sz = d.size * (0.6 + d.z * 0.7);
      const g = ctx.createRadialGradient(x, y, 0, x, y, sz * 2.2);
      g.addColorStop(0, rgb(pal.crest, a));
      g.addColorStop(0.4, rgb(pal.foam, a * 0.35));
      g.addColorStop(1, rgb(pal.foam, 0));
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(x, y, sz * 2.2, 0, TAU);
      ctx.fill();
    }
    ctx.restore();
  }

  private drawSurface(
    pal: Palette,
    edges: { left: [number, number]; right: [number, number] },
  ): void {
    const ctx = this.ctx;
    const x0 = edges.left[0];
    const x1 = edges.right[0];
    const steps = 56;
    const line = new Path2D();
    line.moveTo(x0, edges.left[1]);
    for (let i = 1; i <= steps; i += 1) {
      const x = x0 + (x1 - x0) * (i / steps);
      line.lineTo(x, this.surfaceY(x));
    }

    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.strokeStyle = rgb(pal.crest, 0.12);
    ctx.lineWidth = 2.6;
    ctx.stroke(line);
    ctx.strokeStyle = rgb(pal.foam, 0.3);
    ctx.lineWidth = 1.25;
    ctx.stroke(line);
    ctx.strokeStyle = rgb(pal.foam, 0.78);
    ctx.lineWidth = 0.7;
    ctx.stroke(line);

    const fillet = (pt: [number, number], inward: number) => {
      const [x, y] = pt;
      const g = ctx.createRadialGradient(x + inward * 1.4, y + 0.5, 0, x, y, 4.2);
      g.addColorStop(0, rgb(pal.foam, 0.7));
      g.addColorStop(0.4, rgb(pal.crest, 0.22));
      g.addColorStop(1, rgb(pal.crest, 0));
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(x, y, 4.2, 0, TAU);
      ctx.fill();
    };
    fillet(edges.left, 1);
    fillet(edges.right, -1);

    const mid = (x0 + x1) * 0.5;
    const swellX = mid + Math.sin(this.time * 0.62) * (x1 - x0) * 0.18;
    const swellY = this.surfaceY(swellX);
    const sg = ctx.createRadialGradient(swellX, swellY, 0, swellX, swellY, 10);
    sg.addColorStop(0, "rgba(255, 255, 255, 0.5)");
    sg.addColorStop(0.3, rgb(pal.foam, 0.22));
    sg.addColorStop(1, "rgba(255, 255, 255, 0)");
    ctx.fillStyle = sg;
    ctx.beginPath();
    ctx.ellipse(swellX, swellY, 10, 2.3, 0, 0, TAU);
    ctx.fill();
  }

  private drawGlassFront(): void {
    const ctx = this.ctx;
    ctx.save();
    ctx.beginPath();
    ctx.arc(CENTER, CENTER, R_GLASS, 0, TAU);
    ctx.clip();

    const inner = ctx.createRadialGradient(
      CENTER,
      CENTER + R_GLASS * 0.45,
      R_GLASS * 0.2,
      CENTER,
      CENTER,
      R_GLASS,
    );
    inner.addColorStop(0, "rgba(0, 8, 16, 0)");
    inner.addColorStop(1, "rgba(0, 8, 16, 0.18)");
    ctx.fillStyle = inner;
    ctx.fillRect(0, 0, VIEW, VIEW);
    ctx.restore();

    ctx.strokeStyle = "rgba(255, 255, 255, 0.26)";
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.arc(CENTER, CENTER, R_GLASS - 0.7, 0, TAU);
    ctx.stroke();

    ctx.strokeStyle = "rgba(255, 255, 255, 0.1)";
    ctx.lineWidth = 0.8;
    ctx.beginPath();
    ctx.arc(CENTER, CENTER, R_WATER + 1.2, 0, TAU);
    ctx.stroke();
  }
}
