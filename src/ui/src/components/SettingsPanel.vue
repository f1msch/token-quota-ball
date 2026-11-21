<script setup lang="ts">
import { onMounted, onUnmounted, reactive, ref } from "vue";
import * as api from "../api";
import { hideSettings } from "../shell";
import type { SettingsState } from "../types";

const tab = ref<"volc" | "deepseek">("volc");
const status = ref("");
const saving = ref(false);
const form = reactive({
  access_key_id: "",
  secret_access_key: "",
  session_token: "",
  account_type: "personal",
  seat_ids: "",
  api_key: "",
  reference_balance: "",
});

function apply(data: SettingsState) {
  form.access_key_id = data.volc_agent_plan.access_key_id;
  form.secret_access_key = data.volc_agent_plan.secret_access_key;
  form.session_token = data.volc_agent_plan.session_token;
  form.account_type = data.volc_agent_plan.account_type || "personal";
  form.seat_ids = data.volc_agent_plan.seat_ids.join(", ");
  form.api_key = data.deepseek.api_key;
  form.reference_balance = data.deepseek.reference_balance == null ? "" : String(data.deepseek.reference_balance);
  status.value = `配置保存在本机：${data.config_path}`;
}

function payload() {
  const refRaw = form.reference_balance.trim();
  let reference_balance: number | string = "";
  if (refRaw !== "") {
    const n = Number(refRaw);
    if (!Number.isFinite(n)) throw new Error("DeepSeek 参考额度必须是数字");
    reference_balance = n;
  }
  return {
    volc_agent_plan: {
      access_key_id: form.access_key_id,
      secret_access_key: form.secret_access_key,
      session_token: form.session_token,
      account_type: form.account_type,
      seat_ids: form.seat_ids,
    },
    deepseek: {
      api_key: form.api_key,
      reference_balance,
    },
  };
}

async function save() {
  saving.value = true;
  try {
    const data = await api.saveSettings(payload());
    apply(data);
    status.value = "已保存到本机配置文件";
  } catch (err) {
    status.value = err instanceof Error ? err.message : "保存失败";
  } finally {
    saving.value = false;
  }
}

async function testCurrent() {
  saving.value = true;
  try {
    const body = { ...payload(), provider_id: tab.value === "volc" ? "volc_agent_plan" : "deepseek" };
    status.value = "正在测试连接（不会写入配置）…";
    const snap = await api.testSettings(body);
    if (snap.ok) {
      status.value = `测试成功：${snap.title}  ${snap.display_text}  ${snap.subtitle}`.trim()
        + "。需要保留时请再点「保存」。";
    } else {
      status.value = snap.error || "测试未通过";
    }
  } catch (err) {
    status.value = err instanceof Error ? err.message : "测试失败";
  } finally {
    saving.value = false;
  }
}

function onKey(ev: KeyboardEvent) {
  if (ev.key === "Escape") hideSettings();
}

onMounted(async () => {
  window.addEventListener("keydown", onKey);
  try {
    apply(await api.getSettings());
  } catch (err) {
    status.value = err instanceof Error ? err.message : "读取配置失败";
  }
});
onUnmounted(() => window.removeEventListener("keydown", onKey));
</script>

<template>
  <div class="settings glass-panel">
    <header data-tauri-drag-region>
      <h1>提供方设置</h1>
      <button type="button" class="close" title="关闭" @click="hideSettings">关闭</button>
    </header>
    <p class="hint">
      密钥只保存在本机配置文件（路径见下方状态行），不要发给别人或贴到聊天里。
      安装版默认在 %APPDATA%\TokenQuotaBall\config\providers.json。
      Cursor、WorkBuddy 和 Trae 会自动读取本机已登录的桌面端，无需在此填写。
    </p>

    <div class="tabs">
      <button type="button" :class="{ on: tab === 'volc' }" @click="tab = 'volc'">火山方舟 Agent Plan</button>
      <button type="button" :class="{ on: tab === 'deepseek' }" @click="tab = 'deepseek'">DeepSeek</button>
    </div>

    <section v-if="tab === 'volc'">
      <p class="hint">
        对应火山引擎「火山方舟」个人/企业 Agent Plan 的 AFP 额度，不是豆包 App。
        Trae 的额度会自动读取本机登录态，不在这里填写。
        请使用 IAM 访问密钥，不要填模型推理 API Key。已保存的密钥以掩码显示，留空或保持掩码则不修改。
      </p>
      <label>Access Key ID<input v-model="form.access_key_id" autocomplete="off" /></label>
      <label>Secret Access Key<input v-model="form.secret_access_key" type="password" autocomplete="off" /></label>
      <label>
        临时 Session Token（一般留空）
        <input v-model="form.session_token" type="password" autocomplete="off" />
      </label>
      <p class="hint tight">
        仅在使用火山引擎 STS 临时凭证时才需要填写；日常长期 Access Key / Secret Key 请留空。
      </p>
      <fieldset>
        <legend>账户类型</legend>
        <label class="row"><input v-model="form.account_type" type="radio" value="personal" /> 个人版 GetAFPUsage</label>
        <label class="row"><input v-model="form.account_type" type="radio" value="enterprise" /> 企业版 GetSeatAFPUsage</label>
      </fieldset>
      <label>企业席位 ID（多个用逗号分隔；企业版必填）<input v-model="form.seat_ids" autocomplete="off" /></label>
    </section>

    <section v-else>
      <p class="hint">
        使用官方 GET /user/balance 查询余额。该接口没有周期额度上限，如需水位，请填写一个参考额度。
        已保存的 Key 以掩码显示，留空或保持掩码则不修改。
      </p>
      <label>API Key<input v-model="form.api_key" type="password" autocomplete="off" /></label>
      <label>参考额度（可选，仅用于水位）<input v-model="form.reference_balance" inputmode="decimal" /></label>
    </section>

    <p class="status">{{ status }}</p>
    <footer>
      <button type="button" :disabled="saving" @click="testCurrent">测试连接</button>
      <div class="btns">
        <button type="button" :disabled="saving" @click="save">保存</button>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.settings.glass-panel {
  margin: 8px;
  padding: 14px;
  width: calc(100% - 16px);
  height: calc(100% - 16px);
  overflow: auto;
  background: #101821;
  border: 0;
}
header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
h1 { margin: 0; font-size: 16px; }
.close {
  background: #1c2430;
  color: var(--text);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 8px;
  padding: 4px 10px;
}
.hint { color: var(--muted); font-size: 12px; line-height: 1.45; margin: 6px 0 10px; }
.hint.tight { margin: -2px 0 10px; }
.tabs { display: flex; gap: 6px; margin-bottom: 10px; }
.tabs button, footer button, .close {
  background: #1c2430;
  color: var(--text);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 8px;
  padding: 5px 10px;
}
.tabs button.on, button:hover { background: #2a3a4d; }
label { display: block; color: var(--muted); font-size: 12px; margin: 0 0 8px; }
input[type="text"], input[type="password"], input:not([type="radio"]) {
  display: block;
  width: 100%;
  margin-top: 4px;
  background: #151b24;
  color: var(--text);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 8px;
  padding: 6px 8px;
}
fieldset {
  border: 0;
  padding: 0;
  margin: 0 0 8px;
  color: var(--muted);
  font-size: 12px;
}
.row { display: flex; align-items: center; gap: 6px; margin: 4px 0; color: var(--text); }
.status { color: var(--muted); font-size: 12px; min-height: 1.4em; }
footer { display: flex; justify-content: space-between; align-items: center; }
.btns { display: flex; gap: 6px; }
</style>
