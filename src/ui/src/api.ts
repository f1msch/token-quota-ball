import type { AppState, SettingsState, Snapshot } from "./types";
import { backendInfo, type BackendInfo } from "./shell";

let info: BackendInfo | null = null;

export async function ensureBackend(retries = 40): Promise<BackendInfo> {
  if (info) return info;
  let lastError: unknown;
  for (let i = 0; i < retries; i++) {
    try {
      const next = await backendInfo();
      if (!next.url) throw new Error("backend url missing");
      const health = await fetch(`${next.url}/api/health`);
      if (!health.ok) throw new Error(`health ${health.status}`);
      info = next;
      return next;
    } catch (err) {
      lastError = err;
      await new Promise((r) => setTimeout(r, 250));
    }
  }
  throw lastError instanceof Error ? lastError : new Error("无法连接本地额度接口");
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const backend = await ensureBackend();
  const headers = new Headers(init.headers);
  headers.set("X-Quota-Token", backend.token);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(`${backend.url}${path}`, { ...init, headers });
  const data = (await res.json().catch(() => ({}))) as T & { error?: string };
  if (!res.ok) {
    throw new Error(data.error || `请求失败 (${res.status})`);
  }
  return data;
}

export function getState(): Promise<AppState> {
  return request<AppState>("/api/state");
}

export function refresh(providerId?: string): Promise<AppState> {
  return request<AppState>("/api/refresh", {
    method: "POST",
    body: JSON.stringify(providerId ? { provider_id: providerId } : {}),
  });
}

export function switchProvider(providerId: string): Promise<AppState> {
  return request<AppState>("/api/provider", {
    method: "POST",
    body: JSON.stringify({ provider_id: providerId }),
  });
}

export function saveWindowState(update: Record<string, unknown>): Promise<AppState> {
  return request<AppState>("/api/state", {
    method: "PUT",
    body: JSON.stringify(update),
  });
}

export function getSettings(): Promise<SettingsState> {
  return request<SettingsState>("/api/config");
}

export function saveSettings(body: Record<string, unknown>): Promise<SettingsState> {
  return request<SettingsState>("/api/config", {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export function testSettings(body: Record<string, unknown>): Promise<Snapshot> {
  return request<Snapshot>("/api/config/test", {
    method: "POST",
    body: JSON.stringify(body),
  });
}
