<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import ContextMenu from "./components/ContextMenu.vue";
import DetailsPanel from "./components/DetailsPanel.vue";
import HoverPopover from "./components/HoverPopover.vue";
import QuotaOrb from "./components/QuotaOrb.vue";
import SettingsPanel from "./components/SettingsPanel.vue";

function currentView() {
  const hash = (location.hash || "#/orb").replace(/^#\/?/, "");
  const name = hash.split("?")[0] || "orb";
  if (["orb", "hover", "details", "settings", "menu"].includes(name)) return name;
  return "orb";
}

const view = ref(currentView());
const onHash = () => { view.value = currentView(); };

onMounted(() => window.addEventListener("hashchange", onHash));
onUnmounted(() => window.removeEventListener("hashchange", onHash));
</script>

<template>
  <QuotaOrb v-if="view === 'orb'" />
  <HoverPopover v-else-if="view === 'hover'" />
  <DetailsPanel v-else-if="view === 'details'" />
  <SettingsPanel v-else-if="view === 'settings'" />
  <ContextMenu v-else-if="view === 'menu'" />
</template>
