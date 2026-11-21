/** Continuous quota-to-visual mapping for the CSS orb.

Every 1% of used quota changes both fill height and color. Stops are spaced
across the full 0–100 range so mid values (e.g. 47% vs 48%) are distinct,
instead of holding one look until a late warning band.
*/
export const WIN_SIZE = 108;

export type RGB = [number, number, number];

export interface Palette {
  deep: RGB;
  mid: RGB;
  crest: RGB;
  foam: RGB;
  glow: RGB;
  glass: RGB;
}

// Light rendition of the same hue ramp: the water keeps its green → amber → red
// direction but sits higher in luminance, so the glass reads as clear instead of
// near-black.
const IDLE: Palette = {
  deep: [46, 62, 76],
  mid: [104, 128, 148],
  crest: [196, 212, 226],
  foam: [238, 245, 250],
  glow: [116, 148, 180],
  glass: [108, 126, 142],
};

const STOPS: Array<[number, Palette]> = [
  [0, { deep: [26, 108, 90], mid: [64, 204, 160], crest: [178, 255, 232], foam: [240, 255, 250], glow: [92, 214, 172], glass: [96, 124, 130] }],
  [34, { deep: [28, 112, 88], mid: [68, 208, 158], crest: [186, 255, 230], foam: [241, 255, 250], glow: [96, 216, 170], glass: [96, 124, 130] }],
  [68, { deep: [30, 118, 86], mid: [80, 216, 158], crest: [198, 255, 224], foam: [242, 255, 248], glow: [100, 218, 164], glass: [96, 124, 130] }],
  [82, { deep: [140, 96, 34], mid: [250, 198, 96], crest: [255, 242, 196], foam: [255, 251, 234], glow: [230, 182, 88], glass: [126, 108, 76] }],
  [93, { deep: [158, 60, 64], mid: [246, 128, 132], crest: [255, 216, 218], foam: [255, 242, 242], glow: [230, 110, 118], glass: [128, 86, 90] }],
  [100, { deep: [146, 48, 58], mid: [248, 116, 128], crest: [255, 210, 216], foam: [255, 240, 244], glow: [224, 96, 112], glass: [128, 82, 88] }],
];

function lerp(a: RGB, b: RGB, t: number): RGB {
  const u = Math.min(1, Math.max(0, t));
  return [
    Math.round(a[0] + (b[0] - a[0]) * u),
    Math.round(a[1] + (b[1] - a[1]) * u),
    Math.round(a[2] + (b[2] - a[2]) * u),
  ];
}

function mixPalette(a: Palette, b: Palette, t: number): Palette {
  return {
    deep: lerp(a.deep, b.deep, t),
    mid: lerp(a.mid, b.mid, t),
    crest: lerp(a.crest, b.crest, t),
    foam: lerp(a.foam, b.foam, t),
    glow: lerp(a.glow, b.glow, t),
    glass: lerp(a.glass, b.glass, t),
  };
}

export function clampPct(pct: number | null | undefined): number | null {
  if (pct == null || Number.isNaN(pct)) return null;
  return Math.min(100, Math.max(0, pct));
}

/** Fill fraction of the orb (12% puddle … 92% near the rim), matching the Tkinter orb. Linear in used %. */
export function visualFill(pct: number | null): number {
  const t = pct == null ? 0 : Math.min(1, Math.max(0, pct / 100));
  return 0.12 + 0.80 * t;
}

export function palette(pct: number | null): Palette {
  if (pct == null) return IDLE;
  const t = Math.min(100, Math.max(0, pct));
  if (t <= STOPS[0][0]) return STOPS[0][1];
  for (let i = 0; i < STOPS.length - 1; i++) {
    const [t0, c0] = STOPS[i];
    const [t1, c1] = STOPS[i + 1];
    if (t <= t1) return mixPalette(c0, c1, (t - t0) / Math.max(t1 - t0, 1e-6));
  }
  return STOPS[STOPS.length - 1][1];
}

export function rgb(c: RGB, alpha?: number): string {
  if (alpha == null) return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
  return `rgba(${c[0]}, ${c[1]}, ${c[2]}, ${alpha})`;
}

export function usageBand(pct: number | null): "idle" | "ok" | "warn" | "danger" {
  if (pct == null) return "idle";
  if (pct >= 95) return "danger";
  if (pct >= 80) return "warn";
  return "ok";
}

export function orbStyle(pct: number | null): Record<string, string> {
  const p = palette(pct);
  return {
    "--c-glow-55": rgb(p.glow, 0.7),
    "--c-glow-28": rgb(p.glow, 0.4),
  };
}

export function hasCjk(text: string): boolean {
  return /[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]/.test(text);
}
