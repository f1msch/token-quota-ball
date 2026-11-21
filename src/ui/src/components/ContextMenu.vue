<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { invoke } from "@tauri-apps/api/core";
import * as api from "../api";
import { hideMenu, isTauri, quitApp, showDetails, showSettings, broadcastProviderChanged } from "../shell";
import type { AppState } from "../types";

const state = ref<AppState | null>(null);
const subOpen = ref(false);
const subOnRight = ref(true);
// Rust owns the window placement (wide enough for the submenu, clipped to the
// visible column). Until quota://menu-placed arrives the side is unknown, so
// the menu stays invisible instead of painting on the wrong side.
const placed = ref(!isTauri());

let closeTimer = 0;
let unlistenPlaced: UnlistenFn | null = null;

async function pull() {
  try {
    state.value = await api.getState();
  } catch {
    /* keep last */
  }
}

// Toggling the provider submenu only changes the Win32 window region; the
// window is never resized or moved while open, so the menu cannot flash.
async function setRegion(expanded: boolean) {
  if (!isTauri()) return;
  try {
    await invoke("set_menu_region", { expanded, sub_right: subOnRight.value });
  } catch {
    /* menu still renders, only the clipped area is larger */
  }
}

function dismiss() {
  subOpen.value = false;
  // Keep the preview usable: only reset the placement gate where hiding works.
  if (isTauri()) placed.value = false;
  void hideMenu();
}

async function switchTo(id: string) {
  // Flip the highlight and close the menu now; the API answers with the new
  // provider's cached snapshot (or a loading state) without waiting for the
  // network, and the slow fetch keeps running in the background.
  if (state.value) state.value = { ...state.value, provider_id: id };
  dismiss();
  try {
    state.value = await api.switchProvider(id);
    await broadcastProviderChanged(id);
  } catch {
    /* the orb keeps polling and settles on the backend value */
  }
}

function toggleDock() {
  void invoke("toggle_orb_dock").finally(dismiss);
}

function openDetails() {
  void showDetails();
  dismiss();
}

function openSettings() {
  void showSettings();
  dismiss();
}

function refresh() {
  void api.refresh().finally(dismiss);
}

async function openSub() {
  window.clearTimeout(closeTimer);
  if (subOpen.value) return;
  // The menu window is created once and then only hidden/shown, so the cached
  // state can still point at the provider that was active on the first open.
  // Refresh (without blocking the hover) so the highlight follows the switch.
  void pull();
  subOpen.value = true;
  await setRegion(true);
}

function scheduleCloseSub() {
  window.clearTimeout(closeTimer);
  closeTimer = window.setTimeout(async () => {
    closeTimer = 0;
    if (!subOpen.value) return;
    subOpen.value = false;
    await setRegion(false);
  }, 180);
}

function onRootContext(ev: MouseEvent) {
  // Right-click inside the menu must not reach the orb (that would re-open or
  // stack another menu), and WebView2 must not show its native menu either.
  ev.preventDefault();
  const target = ev.target as HTMLElement | null;
  if (target?.closest(".menu, .submenu")) return;
  dismiss();
}

onMounted(() => {
  subOpen.value = false;
  void pull();
  if (isTauri()) {
    void listen("quota://menu-placed", (event) => {
      const payload = event.payload as { sub_right?: boolean };
      subOnRight.value = payload?.sub_right !== false;
      subOpen.value = false;
      placed.value = true;
      // Each show is a new session: pull the state now so the first expansion
      // already marks the current provider instead of the one from last time.
      void pull();
    }).then((fn) => {
      unlistenPlaced = fn;
    });
  }
});

onUnmounted(() => {
  window.clearTimeout(closeTimer);
  if (unlistenPlaced) unlistenPlaced();
});
</script>

<template>
  <div class="menu-root" :class="{ 'sub-left': !subOnRight, placed }" @contextmenu="onRootContext">
    <div class="menu glass-panel">
      <button type="button" @click="openDetails">打开详情</button>
      <button type="button" @click="refresh">刷新</button>
      <div class="sep" />
      <div class="cascade" @pointerenter="openSub" @pointerleave="scheduleCloseSub">
        <button type="button" class="cascade-btn" :class="{ on: subOpen }" @click="openSub">
          <span>切换额度</span>
          <span class="arrow">▸</span>
        </button>
        <div v-if="subOpen" class="submenu glass-panel" @pointerenter="openSub" @pointerleave="scheduleCloseSub">
          <button
            v-for="p in state?.providers || []"
            :key="p.id"
            type="button"
            :class="{ on: p.id === state?.provider_id }"
            @click="switchTo(p.id)"
          >
            {{ p.title }}
          </button>
        </div>
      </div>
      <button type="button" @click="openSettings">提供方设置…</button>
      <div class="sep" />
      <button type="button" @click="toggleDock">{{ state?.window.docked ? "取消贴边" : "贴边隐藏" }}</button>
      <button type="button" class="danger" @click="quitApp">退出</button>
    </div>
  </div>
</template>

<style scoped>
.menu-root {
  width: 100%;
  height: 100%;
  position: relative;
  background: transparent;
  opacity: 0;
}
.menu-root.placed {
  opacity: 1;
  transition: opacity 110ms ease;
}
.menu.glass-panel {
  background: #101821;
  border-color: rgba(255, 255, 255, 0.08);
}
.menu {
  position: absolute;
  top: 4px;
  left: 4px;
  width: 222px;
  padding: 6px;
}
/* Parent panel hugs the right edge of the wide window when the submenu has to
   open towards the left (the window region is clipped to that column). */
.menu-root.sub-left .menu {
  left: auto;
  right: 4px;
}
button {
  display: block;
  width: 100%;
  text-align: left;
  background: transparent;
  color: var(--text);
  border: 0;
  border-radius: 8px;
  padding: 6px 10px;
  font-size: 13px;
}
button:hover,
button.on {
  background: #1c2a3a;
}
.cascade {
  position: relative;
}
.cascade-btn {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.arrow {
  color: var(--muted);
  font-size: 12px;
}
/* Painted (alpha > 0) bridge across the gap so moving the pointer from
   "切换额度" into the submenu never counts as leaving the cascade. */
.cascade::after {
  content: "";
  position: absolute;
  top: -6px;
  bottom: -6px;
  left: 100%;
  width: 8px;
  background: rgba(255, 255, 255, 0.01);
}
.menu-root.sub-left .cascade::after {
  left: auto;
  right: 100%;
}
.submenu.glass-panel {
  background: #101821;
  border-color: rgba(255, 255, 255, 0.08);
}
.submenu {
  position: absolute;
  top: -6px;
  left: calc(100% + 6px);
  width: 188px;
  padding: 6px;
  z-index: 2;
}
.menu-root.sub-left .submenu {
  left: auto;
  right: calc(100% + 6px);
}
.sep {
  height: 1px;
  margin: 4px 6px;
  background: rgba(255, 255, 255, 0.08);
}
.danger {
  color: #ffb3b8;
}
</style>
