<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { hasCjk, orbStyle, usageBand, WIN_SIZE } from "../orb/palette";
import {
  clamp as clampGeom,
  dockedPos as dockedPosGeom,
  edgeIfNear as edgeIfNearGeom,
  nearestEdge as nearestEdgeGeom,
  undockedPos as undockedPosGeom,
  type Edge,
  type ScreenRect,
} from "../orb/geometry";
import { OrbRenderer } from "../orb/renderer";
import * as api from "../api";
import {
  getOrbPosition,
  hideHover,
  isTauri,
  pointerOverShell,
  setOrbPosition,
  showDetails,
  showHover,
  showMenu,
  startDrag,
  virtualScreen,
} from "../shell";
import type { AppState } from "../types";

const BALL = WIN_SIZE;
const DRAG_THRESHOLD = 4;
const DOCK_SLIVER = 26;
const DOCK_SNAP_PX = 28;
const HIDE_DELAY_MS = 260;
const SLIDE_OUT_GRACE_MS = 800;

const state = ref<AppState | null>(null);
const targetPct = ref<number | null>(null);
const docked = ref(false);
const dockEdge = ref<Edge | null>(null);
const tempUndocked = ref(false);
const hovering = ref(false);
const canvasRef = ref<HTMLCanvasElement | null>(null);

let renderer: OrbRenderer | null = null;
let dragging = false;
let pressing = false;
let suppressClick = false;
let pressRoot = { x: 0, y: 0 };
let dragAnchor = { x: 0, y: 0 };
let winPos = { x: 0, y: 0 };
let screenCache: ScreenRect | null = null;
let pendingMove: { x: number; y: number } | null = null;
let moveInFlight = false;
let hideTimer = 0;
let pollTimer = 0;
let persistTimer = 0;
let leavingGraceUntil = 0;
let finishingDrag = false;
let unlistenDock: UnlistenFn | undefined;
let unlistenHover: UnlistenFn | undefined;
let unlistenProvider: UnlistenFn | undefined;

function clamp(x: number, y: number, screen: ScreenRect, allowDock: boolean) {
  return clampGeom(x, y, screen, BALL, DOCK_SLIVER, allowDock);
}
function nearestEdge(x: number, y: number, screen: ScreenRect) {
  return nearestEdgeGeom(x, y, screen, BALL);
}
function edgeIfNear(x: number, y: number, screen: ScreenRect) {
  return edgeIfNearGeom(x, y, screen, BALL, DOCK_SNAP_PX);
}
function dockedPos(x: number, y: number, edge: string, screen: ScreenRect) {
  return dockedPosGeom(x, y, edge, screen, BALL, DOCK_SLIVER);
}
function undockedPos(x: number, y: number, edge: string, screen: ScreenRect) {
  return undockedPosGeom(x, y, edge, screen, BALL, DOCK_SLIVER);
}

async function moveTo(x: number, y: number) {
  winPos = { x, y };
  await setOrbPosition(x, y);
}

function queueMove(x: number, y: number) {
  pendingMove = { x, y };
  if (moveInFlight) return;
  moveInFlight = true;
  requestAnimationFrame(() => {
    void flushMove();
  });
}

async function flushMove() {
  try {
    while (pendingMove) {
      const next = pendingMove;
      pendingMove = null;
      await moveTo(next.x, next.y);
    }
  } finally {
    moveInFlight = false;
    if (pendingMove) {
      moveInFlight = true;
      requestAnimationFrame(() => {
        void flushMove();
      });
    }
  }
}

function schedulePersist() {
  window.clearTimeout(persistTimer);
  persistTimer = window.setTimeout(() => {
    void api.saveWindowState({
      x: Math.round(winPos.x),
      y: Math.round(winPos.y),
      docked: docked.value,
      dock_edge: dockEdge.value,
    });
  }, 120);
}

function applySnapshot(next: AppState) {
  const first = state.value == null;
  state.value = next;
  // Window flags are local interaction state after the first load; polling
  // them back would undo a just-finished drag/dock before it is persisted.
  if (first) {
    docked.value = Boolean(next.window.docked);
    const edge = next.window.dock_edge;
    dockEdge.value = edge === "left" || edge === "right" || edge === "top" || edge === "bottom" ? edge : null;
  }
  if (next.snapshot.ok) {
    targetPct.value = next.snapshot.percent_used == null ? null : Math.min(100, Math.max(0, next.snapshot.percent_used));
  } else {
    targetPct.value = null;
  }
  renderer?.setTarget(targetPct.value);
}

async function pull(force = false) {
  try {
    const next = force ? await api.refresh() : await api.getState();
    applySnapshot(next);
  } catch {
    /* keep last frame */
  }
}

const snap = computed(() => state.value?.snapshot);
const name = computed(() => (snap.value?.title || "用量").trim());
const text = computed(() => (snap.value ? snap.value.display_text : "…"));
const nameLong = computed(() => hasCjk(name.value) || name.value.length > 10);
const valueLong = computed(() => text.value.length >= 8);
const band = computed(() => usageBand(targetPct.value));
const styleVars = computed(() => orbStyle(targetPct.value));

function releaseCapture(ev: PointerEvent) {
  try {
    (ev.currentTarget as HTMLElement).releasePointerCapture(ev.pointerId);
  } catch {
    /* already released */
  }
}

function onPointerDown(ev: PointerEvent) {
  if (ev.button !== 0) return;
  pressing = true;
  dragging = false;
  suppressClick = false;
  pendingMove = null;
  pressRoot = { x: ev.screenX, y: ev.screenY };
  dragAnchor = { x: ev.screenX - winPos.x, y: ev.screenY - winPos.y };
  (ev.currentTarget as HTMLElement).setPointerCapture(ev.pointerId);
  void hideHover();
}

async function onPointerMove(ev: PointerEvent) {
  if (!pressing) return;
  if ((ev.buttons & 1) === 0) {
    // Lost the release outside the window; do not stay stuck in "pressing".
    if (dragging && !isTauri()) {
      pressing = false;
      await finishDrag();
    } else {
      pressing = false;
      dragging = false;
    }
    return;
  }
  if (dragging) {
    if (!isTauri()) moveFallback(ev);
    return;
  }
  const dx = ev.screenX - pressRoot.x;
  const dy = ev.screenY - pressRoot.y;
  if (dx * dx + dy * dy < DRAG_THRESHOLD * DRAG_THRESHOLD) return;

  dragging = true;
  void hideHover();
  releaseCapture(ev);

  if (isTauri()) {
    // macOS/Windows move loop: follows the cursor in the OS, no IPC per tick.
    try {
      await startDrag();
    } finally {
      await finishDrag();
    }
    return;
  }

  try {
    winPos = await getOrbPosition();
    screenCache = screenCache ?? await virtualScreen();
  } catch {
    /* keep last known */
  }
  dragAnchor = { x: pressRoot.x - winPos.x, y: pressRoot.y - winPos.y };
  moveFallback(ev);
}

function moveFallback(ev: PointerEvent) {
  const screen = screenCache;
  if (!screen) return;
  const next = clamp(ev.screenX - dragAnchor.x, ev.screenY - dragAnchor.y, screen, true);
  queueMove(next.x, next.y);
}

async function finishDrag() {
  if (finishingDrag) return;
  finishingDrag = true;
  try {
    dragging = false;
    pressing = false;
    suppressClick = true;
    const [pos, screen] = await Promise.all([getOrbPosition(), virtualScreen()]);
    screenCache = screen;
    winPos = pos;
    if (docked.value || tempUndocked.value) {
      docked.value = false;
      tempUndocked.value = false;
      dockEdge.value = null;
    }
    const edge = edgeIfNear(winPos.x, winPos.y, screen);
    if (edge) {
      docked.value = true;
      dockEdge.value = edge;
      const next = dockedPos(winPos.x, winPos.y, edge, screen);
      await moveTo(next.x, next.y);
    } else {
      const next = clamp(winPos.x, winPos.y, screen, false);
      if (next.x !== winPos.x || next.y !== winPos.y) await moveTo(next.x, next.y);
    }
    schedulePersist();
  } catch {
    /* stay where the OS left the window */
  } finally {
    finishingDrag = false;
  }
}

function onPointerCancel(ev: PointerEvent) {
  releaseCapture(ev);
  const wasDragging = dragging;
  pressing = false;
  dragging = false;
  if (wasDragging && !isTauri()) void finishDrag();
}

async function onPointerUp(ev: PointerEvent) {
  if (ev.button !== 0) return;
  const wasPressing = pressing;
  const wasDragging = dragging;
  releaseCapture(ev);
  if (!wasPressing) return;

  if (wasDragging) {
    // Tauri: the native loop finalizes in onPointerMove's await chain.
    if (isTauri()) return;
    pressing = false;
    await finishDrag();
    return;
  }

  pressing = false;
  if (suppressClick) {
    suppressClick = false;
    return;
  }

  if (tempUndocked.value) {
    docked.value = false;
    tempUndocked.value = false;
    dockEdge.value = null;
    schedulePersist();
  }
  void hideHover();
  await showDetails();
}

async function onEnter() {
  if (pressing || dragging) return;
  hovering.value = true;
  window.clearTimeout(hideTimer);
  hideTimer = 0;
  if (docked.value && !tempUndocked.value && dockEdge.value) {
    const screen = screenCache ?? await virtualScreen();
    screenCache = screen;
    tempUndocked.value = true;
    leavingGraceUntil = performance.now() + SLIDE_OUT_GRACE_MS;
    const next = undockedPos(winPos.x, winPos.y, dockEdge.value, screen);
    await moveTo(next.x, next.y);
    if (!hovering.value) return;
  }
  if (!dragging) await showHover();
}

function onLeave() {
  hovering.value = false;
  if (pressing || dragging) return;
  scheduleHide();
}

function scheduleHide(delay = HIDE_DELAY_MS) {
  window.clearTimeout(hideTimer);
  hideTimer = window.setTimeout(async () => {
    hideTimer = 0;
    if (pressing || dragging) return;
    // Sliding a docked ball inward can produce a synthetic leave; ignore it
    // briefly instead of hiding right after the slide-out.
    if (performance.now() < leavingGraceUntil) {
      scheduleHide(200);
      return;
    }
    if (await pointerOverShell()) return;
    await hideHover();
    await slideBack();
  }, delay);
}

async function slideBack() {
  if (pressing || dragging) return;
  if (!docked.value || !tempUndocked.value || !dockEdge.value) return;
  const screen = screenCache ?? await virtualScreen();
  tempUndocked.value = false;
  const next = dockedPos(winPos.x, winPos.y, dockEdge.value, screen);
  await moveTo(next.x, next.y);
}

function onContext(ev: MouseEvent) {
  ev.preventDefault();
  void hideHover();
  void showMenu(ev.screenX, ev.screenY);
}

onMounted(async () => {
  if (canvasRef.value) {
    renderer = new OrbRenderer(canvasRef.value);
    renderer.setTarget(targetPct.value);
    renderer.start();
  }
  try {
    const next = await api.getState();
    applySnapshot(next);
    const screen = await virtualScreen();
    screenCache = screen;
    let x = next.window.x;
    let y = next.window.y;
    if (typeof x !== "number" || typeof y !== "number") {
      x = screen.x + screen.width - BALL - 36;
      y = screen.y + Math.round(screen.height * 0.28);
    }
    if (docked.value) {
      const edge = dockEdge.value || nearestEdge(x, y, screen);
      dockEdge.value = edge;
      const pos = dockedPos(x, y, edge, screen);
      x = pos.x;
      y = pos.y;
    } else {
      const pos = clamp(x, y, screen, false);
      x = pos.x;
      y = pos.y;
    }
    await moveTo(x, y);
  } catch {
    // Even without API data the ball must know where it is so drag starts
    // from the real window origin instead of (0, 0).
    try {
      const [pos, screen] = await Promise.all([getOrbPosition(), virtualScreen()]);
      winPos = pos;
      screenCache = screen;
    } catch {
      /* first paint still works */
    }
  }
  pollTimer = window.setInterval(() => { void pull(false); }, 2000);
  window.setTimeout(() => { void pull(true); }, 200);
  if (isTauri()) {
    unlistenDock = await listen<{ docked: boolean; edge: string }>("quota://dock-changed", async (ev) => {
      docked.value = ev.payload.docked;
      const edge = ev.payload.edge;
      dockEdge.value = edge === "left" || edge === "right" || edge === "top" || edge === "bottom" ? edge : null;
      tempUndocked.value = false;
      try {
        winPos = await getOrbPosition();
      } catch { /* keep last */ }
      schedulePersist();
    });
    unlistenHover = await listen<boolean>("quota://hover-hidden", () => {
      void slideBack();
    });
    // Provider switches must land on the ball at once, not on the next poll.
    unlistenProvider = await listen("quota://provider-changed", () => {
      void pull(false);
    });
  }
});

onUnmounted(() => {
  renderer?.stop();
  renderer = null;
  window.clearInterval(pollTimer);
  window.clearTimeout(hideTimer);
  window.clearTimeout(persistTimer);
  void unlistenDock?.();
  void unlistenHover?.();
  void unlistenProvider?.();
});
</script>

<template>
  <div class="orb-stage">
    <div
      class="orb-hit"
      :class="['tone-' + band, { hovering }]"
      :style="styleVars"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerCancel"
      @pointerenter="onEnter"
      @pointerleave="onLeave"
      @contextmenu="onContext"
    >
      <div class="orb-glow" aria-hidden="true" />
      <div class="floating-orb" aria-label="额度悬浮球">
        <canvas ref="canvasRef" class="orb-canvas" aria-hidden="true" />
        <div class="orb-copy">
          <div class="orb-name" :class="{ 'is-long': nameLong }">{{ name }}</div>
          <div class="orb-value" :class="{ 'is-long': valueLong }">{{ text }}</div>
        </div>
        <!-- Topmost painted disc: WebView2 ignores alpha-0 pixels, so this faint
             film keeps the whole circle hittable even where glass is clear. -->
        <div class="orb-hit-film" aria-hidden="true" />
      </div>
    </div>
  </div>
</template>

<style scoped>
/* html/WebView backgrounds stay fully transparent. Only .floating-orb is the
   visual surface, avoiding a frame-in-frame. Windows WebView2 ignores mouse
   events on alpha-0 pixels, so .orb-hit and .orb-hit-film keep a faint circular
   fill as the topmost painted layer. Status glow lives in the 6px margin around
   the 96px orb; the Rust shell clips the window to a slightly larger circle.
   The water itself is drawn on a canvas: level easing stays continuous, the
   surface is a slow long-wavelength crescent meniscus, and fine dust drifts
   underwater. */
.orb-stage {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
  background: transparent;
}
.orb-hit {
  --c-glow-55: rgba(40, 180, 140, 0.7);
  --c-glow-28: rgba(40, 180, 140, 0.4);
  position: relative;
  width: 96px;
  height: 96px;
  border-radius: 50%;
  pointer-events: auto;
  cursor: grab;
  touch-action: none;
  user-select: none;
  background: transparent;
}
.orb-hit:active { cursor: grabbing; }

.orb-glow {
  position: absolute;
  inset: -6px;
  border-radius: 50%;
  pointer-events: none;
  z-index: 0;
  opacity: 0.72;
  box-shadow:
    0 0 10px 3px var(--c-glow-55),
    0 0 22px 7px var(--c-glow-28);
}
.tone-idle .orb-glow { opacity: 0.45; }

.floating-orb {
  position: relative;
  z-index: 1;
  width: 96px;
  height: 96px;
  border-radius: 50%;
  overflow: hidden;
  pointer-events: none;
}
.orb-canvas {
  position: absolute;
  inset: 0;
  width: 96px;
  height: 96px;
  display: block;
  pointer-events: none;
}

.orb-copy {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 2;
}
.orb-name {
  position: absolute;
  top: 13px;
  left: 12%;
  right: 12%;
  text-align: center;
  font-weight: 600;
  font-size: 9.5px;
  line-height: 1.2;
  color: rgba(248, 252, 255, 0.94);
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.38);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  word-break: break-word;
  overflow-wrap: anywhere;
}
.orb-name.is-long { font-size: 8px; }
.orb-value {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding-top: 10px;
  font-weight: 650;
  font-size: 17px;
  letter-spacing: 0.01em;
  font-variant-numeric: tabular-nums;
  color: rgba(255, 255, 255, 0.96);
  text-shadow: 0 1px 3px rgba(0, 16, 24, 0.42);
}
.orb-value.is-long { font-size: 13px; }

.orb-hit-film {
  position: absolute;
  inset: 0;
  z-index: 6;
  border-radius: 50%;
  pointer-events: none;
  background: rgba(8, 16, 24, 0.08);
}
</style>
