//! Hover / details / settings / context-menu window commands.

use std::time::Duration;

use tauri::{AppHandle, Emitter, LogicalPosition, LogicalSize, Manager};

use crate::backend::shell_log;
use crate::constants::{
    DETAILS_H, DETAILS_W, HOVER_H, HOVER_W, MENU_H, MENU_PAD, MENU_PANEL_W, MENU_TOTAL_W, MENU_W,
    SETTINGS_H, SETTINGS_W,
};
use crate::geom::{ensure_window, logical_screen, orb_window, reveal_aux_window};
use crate::state::MenuPlaced;
#[cfg(windows)]
use crate::win32::{
    apply_menu_region, configure_frameless_shell, hwnd_of, scale_of, schedule_frameless,
    wait_for_hwnd, window_contains_cursor, GetAsyncKeyState, SetWindowPos, ShowWindow,
};
#[cfg(not(windows))]
fn wait_for_hwnd(_win: &tauri::WebviewWindow) {}
#[cfg(not(windows))]
fn schedule_frameless(_win: &tauri::WebviewWindow) {}
#[cfg(not(windows))]
fn configure_frameless_shell(_win: &tauri::WebviewWindow) {}

fn hide_hover_window(app: &AppHandle) {
    if let Some(win) = app.get_webview_window("hover") {
        let visible = win.is_visible().unwrap_or(false);
        let _ = win.hide();
        if visible {
            let _ = app.emit("quota://hover-hidden", true);
        }
    }
}

fn hide_details_window(app: &AppHandle) {
    if let Some(win) = app.get_webview_window("details") {
        let visible = win.is_visible().unwrap_or(false);
        let _ = win.hide();
        if visible {
            let _ = app.emit("quota://details-hidden", true);
        }
    }
}

#[cfg(windows)]
fn watch_details_outside_click(app: AppHandle) {
    use std::sync::atomic::{AtomicBool, Ordering};
    static WATCHING: AtomicBool = AtomicBool::new(false);
    if WATCHING.swap(true, Ordering::SeqCst) {
        return;
    }
    std::thread::spawn(move || {
        const VK_LBUTTON: i32 = 0x01;
        let button_down = || (unsafe { GetAsyncKeyState(VK_LBUTTON) } as u16 & 0x8000) != 0;
        while button_down() {
            std::thread::sleep(Duration::from_millis(16));
        }
        loop {
            let Some(win) = app.get_webview_window("details") else { break };
            if !win.is_visible().unwrap_or(false) {
                break;
            }
            if !button_down() {
                std::thread::sleep(Duration::from_millis(40));
                continue;
            }
            let in_orb = app
                .get_webview_window("orb")
                .map(|orb| window_contains_cursor(&orb))
                .unwrap_or(false);
            if !window_contains_cursor(&win) && !in_orb {
                hide_details_window(&app);
            }
            while button_down() {
                std::thread::sleep(Duration::from_millis(16));
            }
            std::thread::sleep(Duration::from_millis(40));
        }
        WATCHING.store(false, Ordering::SeqCst);
    });
}

#[cfg(not(windows))]
fn watch_details_outside_click(_app: AppHandle) {}

#[tauri::command]
pub fn show_hover(app: AppHandle) -> Result<(), String> {
    shell_log("show_hover");
    let win = ensure_window(&app, "hover", "#/hover", HOVER_W, HOVER_H, true).map_err(|e| {
        shell_log(format!("ensure hover failed: {e}"));
        e
    })?;
    reveal_aux_window(&app, &win, HOVER_W, HOVER_H, 10.0)?;
    let _ = app.emit("quota://hover-shown", true);
    Ok(())
}

#[tauri::command]
pub fn hide_hover(app: AppHandle) -> Result<(), String> {
    hide_hover_window(&app);
    Ok(())
}

#[tauri::command]
pub fn show_details(app: AppHandle) -> Result<(), String> {
    shell_log("show_details");
    let win = ensure_window(&app, "details", "#/details", DETAILS_W, DETAILS_H, false).map_err(|e| {
        shell_log(format!("ensure details failed: {e}"));
        e
    })?;
    hide_hover_window(&app);
    reveal_aux_window(&app, &win, DETAILS_W, DETAILS_H, 12.0)?;
    let _ = app.emit("quota://details-shown", true);
    let _ = win.set_focus();
    watch_details_outside_click(app.clone());
    Ok(())
}

#[tauri::command]
pub fn hide_details(app: AppHandle) -> Result<(), String> {
    hide_details_window(&app);
    Ok(())
}

#[tauri::command]
pub fn show_settings(app: AppHandle) -> Result<(), String> {
    shell_log("show_settings");
    let win = ensure_window(&app, "settings", "#/settings", SETTINGS_W, SETTINGS_H, false).map_err(|e| {
        shell_log(format!("ensure settings failed: {e}"));
        e
    })?;
    hide_hover_window(&app);
    if let Some(menu) = app.get_webview_window("menu") {
        let _ = menu.hide();
    }
    reveal_aux_window(&app, &win, SETTINGS_W, SETTINGS_H, 12.0)?;
    let _ = win.set_focus();
    Ok(())
}

#[tauri::command]
pub fn hide_settings(app: AppHandle) -> Result<(), String> {
    if let Some(win) = app.get_webview_window("settings") {
        let _ = win.hide();
    }
    Ok(())
}

#[tauri::command]
pub fn show_menu(app: AppHandle, x: f64, y: f64) -> Result<(), String> {
    shell_log(format!("show_menu {x},{y}"));
    let win = ensure_window(&app, "menu", "#/menu", MENU_TOTAL_W, MENU_H, true).map_err(|e| {
        shell_log(format!("ensure menu failed: {e}"));
        e
    })?;
    hide_hover_window(&app);
    let screen = logical_screen(&orb_window(&app)?);
    let mut px = x;
    let mut py = y;
    if px + MENU_W > screen.x + screen.width {
        px = screen.x + screen.width - MENU_W;
    }
    px = px.max(screen.x);
    if py + MENU_H > screen.y + screen.height {
        py = screen.y + screen.height - MENU_H;
    }
    py = py.max(screen.y);
    let right_room = px - MENU_PAD + MENU_TOTAL_W <= screen.x + screen.width - 2.0;
    let left_shift = MENU_TOTAL_W - MENU_PAD - MENU_PANEL_W;
    let left_room = px - left_shift >= screen.x + 2.0;
    let sub_right = right_room || !left_room;
    let mut wx = if sub_right {
        px - MENU_PAD
    } else {
        px - left_shift
    };
    wx = wx.max(screen.x).min(screen.x + screen.width - MENU_TOTAL_W);
    wait_for_hwnd(&win);
    configure_frameless_shell(&win);
    let _ = win.set_size(LogicalSize::new(MENU_TOTAL_W, MENU_H));
    if let Err(e) = win.set_position(LogicalPosition::new(wx, py)) {
        shell_log(format!("menu set_position failed: {e}"));
    }
    #[cfg(windows)]
    apply_menu_region(&win, false, sub_right);
    if let Err(e) = win.show() {
        shell_log(format!("tauri show menu failed: {e}"));
    }
    #[cfg(windows)]
    {
        if let Some(hwnd) = hwnd_of(&win) {
            const SW_SHOWNOACTIVATE: i32 = 4;
            const SWP_NOSIZE: u32 = 0x0001;
            const SWP_NOZORDER: u32 = 0x0004;
            const SWP_SHOWWINDOW: u32 = 0x0040;
            const SWP_NOACTIVATE: u32 = 0x0010;
            let scale = scale_of(&win).max(0.1);
            let ppx = (wx * scale).round() as i32;
            let ppy = (py * scale).round() as i32;
            unsafe {
                ShowWindow(hwnd, SW_SHOWNOACTIVATE);
                SetWindowPos(
                    hwnd,
                    std::ptr::null_mut(),
                    ppx,
                    ppy,
                    0,
                    0,
                    SWP_NOSIZE | SWP_NOZORDER | SWP_SHOWWINDOW | SWP_NOACTIVATE,
                );
            }
            configure_frameless_shell(&win);
        }
    }
    schedule_frameless(&win);
    let _ = app.emit(
        "quota://menu-placed",
        MenuPlaced {
            x: wx,
            y: py,
            sub_right,
        },
    );
    let _ = win.set_focus();
    Ok(())
}

#[tauri::command(rename_all = "snake_case")]
pub fn set_menu_region(app: AppHandle, expanded: bool, sub_right: bool) -> Result<(), String> {
    let Some(win) = app.get_webview_window("menu") else {
        return Ok(());
    };
    #[cfg(windows)]
    apply_menu_region(&win, expanded, sub_right);
    #[cfg(not(windows))]
    let _ = (win, expanded, sub_right);
    Ok(())
}

#[tauri::command]
pub fn hide_menu(app: AppHandle) -> Result<(), String> {
    if let Some(win) = app.get_webview_window("menu") {
        let _ = win.hide();
    }
    Ok(())
}
