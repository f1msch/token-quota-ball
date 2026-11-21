<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import MeterBar from "./MeterBar.vue";
import * as api from "../api";
import { hideHover, isTauri, pointerOverShell } from "../shell";
import type { AppState } from "../types";

const POLL_MS = 2000;

const state = ref<AppState | null>(null);
let timer = 0;
let leaveTimer = 0;
const unlisten: UnlistenFn[] = [];

async function pull() {
  try {
    state.value = await api.getState();
  } catch {
    /* hover stays on last frame */
  }
}

function startPolling() {
  window.clearInterval(timer);
  void pull();
  timer = window.setInterval(pull, POLL_MS);
}

function stopPolling() {
  window.clearInterval(timer);
  timer = 0;
}

function onEnter() {
  window.clearTimeout(leaveTimer);
}

function onLeave() {
  // The orb cannot see the pointer once it is over this window. Hide from
  // here so the popover cannot stay pinned after the pointer moves away.
  window.clearTimeout(leaveTimer);
  leaveTimer = window.setTimeout(async () => {
    if (await pointerOverShell()) return;
    await hideHover();
  }, 220);
}

onMounted(async () => {
  if (!isTauri()) {
    // Browser preview: nothing emits show/hide, keep polling.
    startPolling();
    return;
  }
  // The window is pre-created hidden; only poll while it is actually shown.
  unlisten.push(await listen("quota://hover-shown", startPolling));
  unlisten.push(await listen("quota://hover-hidden", stopPolling));
  unlisten.push(await listen("quota://provider-changed", () => { void pull(); }));
});
onUnmounted(() => {
  stopPolling();
  window.clearTimeout(leaveTimer);
  for (const fn of unlisten) fn();
});

const snap = computed(() => state.value?.snapshot);
const rows = computed(() => {
  const view = snap.value;
  if (!view) return [];
  if (view.rows.length) return view.rows;
  return [{ key: "info", title: "状态", value: view.display_text, percent: view.percent_used, color: "#5a6a7a", detail: "" }];
});
const err = computed(() => {
  const view = snap.value;
  if (!view) return "正在获取用量…";
  if (!view.ok && view.error) return view.error;
  if (!view.ok && state.value?.loading) return "正在加载…";
  return "";
});
</script>

<template>
  <div class="hover glass-panel" @contextmenu.prevent @pointerenter="onEnter" @pointerleave="onLeave">
    <div class="title">{{ snap?.title || "用量" }}</div>
    <div v-if="err" class="sub">{{ err }}</div>
    <div class="rows">
      <MeterBar
        v-for="row in rows"
        :key="row.key"
        compact
        :title="row.title"
        :value="(!snap?.ok && err) ? '--' : row.value"
        :percent="(!snap?.ok && err) ? null : row.percent"
        :color="row.color"
      />
    </div>
  </div>
</template>

<style scoped>
.hover.glass-panel {
  margin: 4px;
  padding: 10px 12px;
  width: calc(100% - 8px);
  min-height: calc(100% - 8px);
  border: 0;
}
.title {
  font-size: 13px;
  font-weight: 650;
  line-height: 1.35;
  overflow-wrap: anywhere;
}
.sub {
  color: var(--muted);
  font-size: 11px;
  margin: 4px 0 6px;
  line-height: 1.4;
}
.rows { margin-top: 6px; }
</style>
