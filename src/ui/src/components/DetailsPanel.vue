<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import CursorMeters from "./CursorMeters.vue";
import MeterBar from "./MeterBar.vue";
import * as api from "../api";
import { formatClock, formatDuration, secondsUntil, usageTone } from "../format";
import { hideDetails, isTauri } from "../shell";
import type { AppState } from "../types";

const POLL_MS = 2000;

const state = ref<AppState | null>(null);
const now = ref(Date.now());
let poll = 0;
let tick = 0;
const unlisten: UnlistenFn[] = [];

async function pull() {
  try {
    state.value = await api.getState();
  } catch (err) {
    statusText.value = err instanceof Error ? err.message : "刷新失败";
  }
}

function startPolling() {
  stopPolling();
  now.value = Date.now();
  void pull();
  poll = window.setInterval(pull, POLL_MS);
  tick = window.setInterval(() => { now.value = Date.now(); }, 1000);
}

function stopPolling() {
  window.clearInterval(poll);
  window.clearInterval(tick);
  poll = 0;
  tick = 0;
}

const statusText = ref("准备中…");
const snap = computed(() => state.value?.snapshot ?? null);
const cursor = computed(() => snap.value?.cursor ?? null);

const heroText = computed(() => {
  const view = snap.value;
  if (!view || !view.ok) {
    // A switch with no cached snapshot: say it is loading instead of "--".
    return state.value?.loading ? "加载中…" : "--";
  }
  return view.display_text;
});

const cycleText = computed(() => {
  const view = snap.value;
  if (!view) return "";
  void now.value;
  if (view.cursor?.cycle_end) {
    return `周期剩余 ${formatDuration(secondsUntil(view.cursor.cycle_end))}`;
  }
  return view.reset_fact;
});

const tone = computed(() => usageTone(snap.value?.ok ? snap.value?.percent_used : null));
const toneColor = computed(
  () =>
    ({
      ok: "var(--ok)",
      warn: "var(--warn)",
      danger: "var(--danger)",
      idle: "var(--accent)",
    })[tone.value] || "var(--accent)",
);

const footer = computed(() => {
  const view = snap.value;
  if (!view) return statusText.value;
  if (!view.ok) {
    if (state.value?.loading) return "正在加载…";
    return view.status === "unconfigured" ? "未配置" : (statusText.value || "刷新失败");
  }
  return view.fetched_at ? `更新于 ${formatClock(view.fetched_at)}` : statusText.value;
});

const message = computed(() => {
  const view = snap.value;
  if (!view) return "";
  if (!view.ok) {
    if (state.value?.loading) return "";
    return [view.error, view.notes].filter(Boolean).join("\n");
  }
  if (view.cursor?.hit_limit) return "已达到用量限制";
  return "";
});

function onKey(ev: KeyboardEvent) {
  if (ev.key === "Escape") hideDetails();
}

onMounted(async () => {
  window.addEventListener("keydown", onKey);
  if (!isTauri()) {
    // Browser preview: nothing emits show/hide, keep polling.
    startPolling();
    return;
  }
  unlisten.push(await listen("quota://details-shown", startPolling));
  unlisten.push(await listen("quota://details-hidden", stopPolling));
  unlisten.push(await listen("quota://provider-changed", () => { void pull(); }));
});
onUnmounted(() => {
  window.removeEventListener("keydown", onKey);
  stopPolling();
  for (const fn of unlisten) fn();
});
</script>

<template>
  <div class="details glass-panel" @contextmenu.prevent>
    <header data-tauri-drag-region>
      <div>
        <h1>{{ snap?.title || "用量" }}</h1>
        <p class="account">{{ snap?.account }}</p>
      </div>
      <p class="plan">{{ snap?.plan }}</p>
    </header>

    <section class="hero">
      <div class="hero-label">总用量</div>
      <div class="hero-row">
        <div class="hero-value" :class="'tone-' + tone">
          {{ heroText }}
        </div>
        <div class="cycle">{{ cycleText }}</div>
      </div>
      <div class="track">
        <div
          class="fill"
          :style="{
            width: (snap?.ok && snap?.percent_used != null ? Math.min(100, snap.percent_used) : 0) + '%',
            backgroundColor: toneColor,
          }"
        />
      </div>
    </section>

    <CursorMeters v-if="snap?.ok && cursor" :cursor="cursor" />

    <template v-else>
      <MeterBar
        v-for="row in snap?.rows || []"
        :key="row.key"
        :title="row.title"
        :value="snap?.ok ? row.value : '--'"
        :percent="snap?.ok ? row.percent : null"
        :color="row.color"
        :detail="row.detail"
      />
      <p v-if="snap && !snap.rows.length && snap.ok" class="muted">暂无明细</p>
    </template>

    <p v-if="message" class="msg">{{ message }}</p>

    <p class="updated muted">{{ footer }}</p>
  </div>
</template>

<style scoped>
.details.glass-panel {
  margin: 8px;
  padding: 16px;
  width: calc(100% - 16px);
  height: calc(100% - 16px);
  overflow: auto;
  display: flex;
  flex-direction: column;
  background: #101821;
  border: 0;
}
.details > * {
  flex: 0 0 auto;
}
.details::-webkit-scrollbar {
  width: 8px;
}
.details::-webkit-scrollbar-track {
  background: transparent;
}
.details::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.12);
  border-radius: 8px;
}
.details::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.2);
}
header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  padding-bottom: 12px;
  margin-bottom: 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.07);
}
h1 {
  margin: 0;
  font-size: 16px;
  font-weight: 650;
  line-height: 1.3;
  overflow-wrap: anywhere;
}
.account {
  margin: 3px 0 0;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.4;
}
.plan {
  margin: 0;
  max-width: 42%;
  padding: 3px 9px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.05);
  color: var(--muted);
  font-size: 11px;
  line-height: 1.5;
  text-align: right;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.hero {
  margin: 0 0 12px;
  padding: 12px 14px 14px;
  border-radius: 12px;
  background: linear-gradient(180deg, #1a2634, #131b26);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.07);
}
.hero-label {
  color: var(--muted);
  font-size: 11px;
  letter-spacing: 0.08em;
}
.hero-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 10px;
  margin-top: 2px;
}
.hero-value {
  font-size: 30px;
  font-weight: 650;
  line-height: 1.1;
  letter-spacing: -0.01em;
}
.cycle {
  color: var(--muted);
  font-size: 12px;
  padding-bottom: 4px;
  text-align: right;
}
.track {
  height: 10px;
  margin-top: 10px;
  background: rgba(255, 255, 255, 0.07);
  border-radius: 99px;
  overflow: hidden;
}
.fill {
  height: 100%;
  border-radius: inherit;
  background-image: linear-gradient(90deg, rgba(255, 255, 255, 0.32), rgba(255, 255, 255, 0) 55%);
  transition: width 0.7s cubic-bezier(0.22, 1, 0.36, 1), background-color 0.4s ease;
}
.msg {
  color: var(--muted);
  font-size: 12px;
  white-space: pre-wrap;
  margin: 8px 0 0;
}
.updated {
  margin: 10px 0 0;
  font-size: 11px;
}
</style>
