<script setup lang="ts">
import { computed } from "vue";
import MeterBar from "./MeterBar.vue";
import { formatDate, formatDuration, secondsUntil } from "../format";
import type { CursorDetails, GrokBotUsage } from "../types";

const props = defineProps<{ cursor: CursorDetails }>();

function grokDetail(g: GrokBotUsage): string {
  if (g.error) return `未能获取：${g.error}`;
  if (g.uses_pooled_enterprise) return "使用团队共享额度，无个人用量条";
  if (!g.show_meter) {
    const bits = ["当前套餐无包含的周额度"];
    if (g.trial_expires_at) bits.push(`试用到期 ${formatDate(g.trial_expires_at)}`);
    if (g.plan_label) bits.push(g.plan_label);
    return bits.join(" · ");
  }
  const bits: string[] = [];
  if (g.reset_at) bits.push(`周期剩余 ${formatDuration(secondsUntil(g.reset_at))}`);
  if (g.trial_expires_at) bits.push(`试用到期 ${formatDate(g.trial_expires_at)}`);
  if (g.plan_label) bits.push(g.plan_label);
  if (g.banked_reset_count > 0) bits.push(`可重置 ${g.banked_reset_count} 次`);
  return bits.join(" · ");
}

const creditDetail = computed(() => {
  const c = props.cursor.credits;
  if (!c) return "";
  const bits = [`${Math.round(c.remaining_percent)}% 剩余`];
  if (c.expires_at) bits.push(`到期 ${formatDate(c.expires_at)}`);
  return bits.join(" · ");
});
</script>

<template>
  <MeterBar
    title="First-Party Models"
    :value="`${Math.round(cursor.first_party_percent_used)}%`"
    :percent="cursor.first_party_percent_used"
    color="var(--fp)"
    :detail="`${cursor.first_party_tokens_text} tokens`"
  />
  <MeterBar
    title="API"
    :value="`${Math.round(cursor.api_percent_used)}%`"
    :percent="cursor.api_percent_used"
    color="var(--api)"
    :detail="`${cursor.api_tokens_text} tokens`"
  />
  <MeterBar
    title="Grok Bot"
    :value="cursor.grok_bot?.show_meter ? `${Math.round(cursor.grok_bot.usage_percent || 0)}%` : '--%'"
    :percent="cursor.grok_bot?.show_meter ? (cursor.grok_bot.usage_percent ?? 0) : null"
    color="var(--grok)"
    :detail="cursor.grok_bot ? grokDetail(cursor.grok_bot) : '未获取到 Grok Bot 用量'"
  />
  <MeterBar
    v-if="cursor.credits"
    title="Credits"
    :value="`${cursor.credits.remaining_text}/${cursor.credits.total_text} remaining`"
    :percent="cursor.credits.remaining_percent"
    color="var(--credit)"
    :detail="creditDetail"
  />

  <div class="models">
    <div class="models-head muted">模型明细（Tokens / 占用）</div>
    <div class="model-row head muted">
      <span>模型</span><span>Tokens</span><span>占用</span>
    </div>
    <div class="model-row">
      <span>API</span>
      <span>{{ cursor.api_tokens_text }}</span>
      <span>{{ cursor.api_percent_used.toFixed(1) }}%</span>
    </div>
    <div class="model-row">
      <span>First-Party Models</span>
      <span>{{ cursor.first_party_tokens_text }}</span>
      <span>{{ cursor.first_party_percent_used.toFixed(1) }}%</span>
    </div>
    <div v-for="m in cursor.first_party_models" :key="'fp-' + m.name" class="model-row indent">
      <span>{{ m.name }}</span><span>{{ m.tokens_text }}</span><span>{{ m.percent.toFixed(1) }}%</span>
    </div>
    <div v-for="m in cursor.api_models" :key="'api-' + m.name" class="model-row indent">
      <span>{{ m.name }}</span><span>{{ m.tokens_text }}</span><span>{{ m.percent.toFixed(1) }}%</span>
    </div>
  </div>
</template>

<style scoped>
.models {
  margin: 4px 0 0;
  background: #151d27;
  border-radius: 12px;
  padding: 10px 12px;
  max-height: 214px;
  overflow: auto;
}
.models::-webkit-scrollbar {
  width: 8px;
}
.models::-webkit-scrollbar-track {
  background: transparent;
}
.models::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.12);
  border-radius: 8px;
}
.models::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.2);
}
.models-head {
  font-size: 11px;
  letter-spacing: 0.04em;
  margin-bottom: 6px;
}
.model-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 86px 62px;
  gap: 8px;
  font-size: 12px;
  padding: 4px 6px;
  border-radius: 6px;
}
.model-row span:first-child {
  overflow-wrap: anywhere;
}
.model-row span:not(:first-child) {
  text-align: right;
  color: #c5d0db;
  font-variant-numeric: tabular-nums;
}
.model-row.head {
  padding-bottom: 6px;
  margin-bottom: 2px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 0;
}
.model-row.head span {
  color: var(--muted);
}
.model-row:not(.head):hover {
  background: rgba(255, 255, 255, 0.04);
}
.model-row.indent span:first-child {
  padding-left: 14px;
  color: var(--muted);
}
</style>
