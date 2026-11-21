<script setup lang="ts">
defineProps<{
  title: string;
  value: string;
  percent: number | null;
  color?: string;
  detail?: string;
  compact?: boolean;
}>();
</script>

<template>
  <div class="meter" :class="{ compact }">
    <div class="meter-head">
      <span class="meter-title">{{ title }}</span>
      <span class="meter-value">{{ value }}</span>
    </div>
    <div class="track" aria-hidden="true">
      <div
        class="fill"
        :style="{
          width: percent == null ? '0%' : Math.min(100, Math.max(0, percent)) + '%',
          background: color || 'var(--accent)',
        }"
      />
    </div>
    <div v-if="detail && !compact" class="meter-detail">{{ detail }}</div>
  </div>
</template>

<style scoped>
.meter { margin: 0 0 8px; }
.meter.compact { margin: 0 0 4px; }
.meter-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px 12px;
  align-items: start;
}
.meter-title {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.35;
  overflow-wrap: anywhere;
}
.compact .meter-title { font-size: 11px; }
.meter-value {
  color: var(--value);
  font-size: 12px;
  font-weight: 600;
  text-align: right;
  white-space: nowrap;
}
.compact .meter-value { font-size: 11px; }
.track {
  height: 8px;
  margin-top: 3px;
  background: var(--track);
  border-radius: 99px;
  overflow: hidden;
}
.compact .track { height: 7px; }
.fill {
  height: 100%;
  border-radius: inherit;
  min-width: 0;
  transition: width 0.7s cubic-bezier(0.22, 1, 0.36, 1), background 0.7s ease;
}
.meter-detail {
  color: var(--muted);
  font-size: 11px;
  margin-top: 3px;
  line-height: 1.4;
}
</style>
