import { invoke, isTauri as coreIsTauri } from "@tauri-apps/api/core";
import { emit } from "@tauri-apps/api/event";

export interface BackendInfo {
  url: string;
  token: string;
}

export interface ScreenRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export function isTauri(): boolean {
  if (typeof window === "undefined") return false;
  if (coreIsTauri()) return true;
  // Older dev/preview webviews expose only the internals bridge.
  return Boolean((window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__);
}

async function call<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  return invoke<T>(cmd, args);
}

export async function backendInfo(): Promise<BackendInfo> {
  if (isTauri()) {
    return call<BackendInfo>("backend_info");
  }
  return {
    url: import.meta.env.VITE_API_URL || "http://127.0.0.1:47891",
    token: import.meta.env.VITE_API_TOKEN || "",
  };
}

export async function setOrbPosition(x: number, y: number): Promise<void> {
  if (isTauri()) await call("set_orb_position", { x: Math.round(x), y: Math.round(y) });
}

/**
 * Hand the drag to the OS move loop. Resolves when the user releases the
 * button, which is also when the window has reached its final position.
 */
export async function startDrag(): Promise<void> {
  if (isTauri()) await call("start_drag");
}

export async function getOrbPosition(): Promise<{ x: number; y: number }> {
  if (isTauri()) return call("get_orb_position");
  return { x: 0, y: 0 };
}

export async function virtualScreen(): Promise<ScreenRect> {
  if (isTauri()) return call<ScreenRect>("virtual_screen");
  return { x: 0, y: 0, width: window.screen.width, height: window.screen.height };
}

export async function showHover(): Promise<void> {
  if (isTauri()) await call("show_hover");
}

export async function hideHover(): Promise<void> {
  if (isTauri()) await call("hide_hover");
}

export async function showDetails(): Promise<void> {
  if (isTauri()) await call("show_details");
}

export async function hideDetails(): Promise<void> {
  if (isTauri()) await call("hide_details");
}

export async function showSettings(): Promise<void> {
  if (isTauri()) await call("show_settings");
}

export async function hideSettings(): Promise<void> {
  if (isTauri()) await call("hide_settings");
}

export async function showMenu(x: number, y: number): Promise<void> {
  if (isTauri()) await call("show_menu", { x: Math.round(x), y: Math.round(y) });
}

export async function hideMenu(): Promise<void> {
  if (isTauri()) await call("hide_menu");
}

export async function quitApp(): Promise<void> {
  if (isTauri()) {
    await call("quit_app");
    return;
  }
  window.close();
}

export async function pointerOverShell(): Promise<boolean> {
  if (isTauri()) return invoke<boolean>("pointer_over_shell");
  return false;
}

/**
 * Tell every window that the active provider changed so the orb refreshes
 * immediately instead of waiting for its next poll tick.
 */
export async function broadcastProviderChanged(providerId: string): Promise<void> {
  if (!isTauri()) return;
  try {
    await emit("quota://provider-changed", { provider_id: providerId });
  } catch {
    /* windows still poll, only the instant update is skipped */
  }
}
