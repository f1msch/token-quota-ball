//! Orb position, drag, dock, and backend info commands.

use std::time::Duration;

use tauri::{AppHandle, Emitter, LogicalPosition, Manager, State};

use crate::constants::{DOCK_SLIVER, ORB_SIZE};
use crate::geom::{logical_screen, orb_window};
use crate::state::{Backend, BackendInfo, DockChanged, Point, ScreenRect};
#[cfg(windows)]
use crate::win32::{
    apply_orb_region, hwnd_of, scale_of, window_contains_cursor, GetAsyncKeyState, SetWindowPos,
};
#[cfg(not(windows))]
fn scale_of(_win: &tauri::WebviewWindow) -> f64 {
    1.0
}
#[cfg(not(windows))]
fn window_contains_cursor(_win: &tauri::WebviewWindow) -> bool {
    false
}

#[tauri::command]
pub fn backend_info(state: State<Backend>) -> Result<BackendInfo, String> {
    let url = state.url.lock().map_err(|e| e.to_string())?.clone();
    let token = state.token.lock().map_err(|e| e.to_string())?.clone();
    if url.is_empty() {
        return Err("后端尚未就绪".into());
    }
    Ok(BackendInfo { url, token })
}

#[tauri::command]
pub fn set_orb_position(app: AppHandle, x: f64, y: f64) -> Result<(), String> {
    let win = orb_window(&app)?;
    #[cfg(windows)]
    if let Some(hwnd) = hwnd_of(&win) {
        let scale = scale_of(&win).max(0.1);
        let px = (x * scale).round() as i32;
        let py = (y * scale).round() as i32;
        const SWP_NOSIZE: u32 = 0x0001;
        const SWP_NOZORDER: u32 = 0x0004;
        const SWP_NOACTIVATE: u32 = 0x0010;
        let ok = unsafe {
            SetWindowPos(
                hwnd,
                std::ptr::null_mut(),
                px,
                py,
                0,
                0,
                SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE,
            )
        };
        if ok == 0 {
            return Err(format!(
                "SetWindowPos failed: {}",
                std::io::Error::last_os_error()
            ));
        }
        return Ok(());
    }
    win.set_position(LogicalPosition::new(x, y))
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub fn get_orb_position(app: AppHandle) -> Result<Point, String> {
    let win = orb_window(&app)?;
    let pos = win.outer_position().map_err(|e| e.to_string())?;
    let scale = scale_of(&win);
    Ok(Point {
        x: pos.x as f64 / scale,
        y: pos.y as f64 / scale,
    })
}

#[tauri::command]
pub fn virtual_screen(app: AppHandle) -> Result<ScreenRect, String> {
    let win = orb_window(&app)?;
    Ok(logical_screen(&win))
}

#[tauri::command]
pub async fn start_drag(app: AppHandle) -> Result<(), String> {
    let win = orb_window(&app)?;
    tauri::async_runtime::spawn_blocking(move || -> Result<(), String> {
        win.start_dragging().map_err(|e| e.to_string())?;
        #[cfg(windows)]
        unsafe {
            const VK_LBUTTON: i32 = 0x01;
            while (GetAsyncKeyState(VK_LBUTTON) as u16 & 0x8000) != 0 {
                std::thread::sleep(Duration::from_millis(16));
            }
            std::thread::sleep(Duration::from_millis(30));
        }
        Ok(())
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
pub fn pointer_over_shell(app: AppHandle) -> bool {
    for label in ["orb", "hover", "menu"] {
        if let Some(win) = app.get_webview_window(label) {
            if window_contains_cursor(&win) {
                return true;
            }
        }
    }
    false
}

#[tauri::command]
pub fn toggle_orb_dock(app: AppHandle) -> Result<(), String> {
    let win = orb_window(&app)?;
    let pos = win.outer_position().map_err(|e| e.to_string())?;
    let scale = scale_of(&win);
    let x = pos.x as f64 / scale;
    let y = pos.y as f64 / scale;
    let screen = logical_screen(&win);
    let cx = x + ORB_SIZE / 2.0;
    let cy = y + ORB_SIZE / 2.0;
    let docked = x < screen.x - 4.0
        || y < screen.y - 4.0
        || x + ORB_SIZE > screen.x + screen.width + 4.0
        || y + ORB_SIZE > screen.y + screen.height + 4.0;
    let mut dists = [
        ("left", cx - screen.x),
        ("right", screen.x + screen.width - cx),
        ("top", cy - screen.y),
        ("bottom", screen.y + screen.height - cy),
    ];
    dists.sort_by(|a, b| a.1.partial_cmp(&b.1).unwrap_or(std::cmp::Ordering::Equal));
    let edge = dists[0].0;
    let (nx, ny) = if docked {
        let pad = 8.0;
        match edge {
            "left" => (screen.x + pad, y),
            "right" => (screen.x + screen.width - ORB_SIZE - pad, y),
            "top" => (x, screen.y + pad),
            _ => (x, screen.y + screen.height - ORB_SIZE - pad),
        }
    } else {
        match edge {
            "left" => (screen.x - (ORB_SIZE - DOCK_SLIVER), y),
            "right" => (screen.x + screen.width - DOCK_SLIVER, y),
            "top" => (x, screen.y - (ORB_SIZE - DOCK_SLIVER)),
            _ => (x, screen.y + screen.height - DOCK_SLIVER),
        }
    };
    win.set_position(LogicalPosition::new(nx, ny))
        .map_err(|e| e.to_string())?;
    #[cfg(windows)]
    apply_orb_region(&win);
    let _ = app.emit(
        "quota://dock-changed",
        DockChanged {
            docked: !docked,
            edge: edge.to_string(),
        },
    );
    Ok(())
}

#[tauri::command]
pub fn quit_app(app: AppHandle, state: State<Backend>) -> Result<(), String> {
    if let Ok(mut child) = state.python.lock() {
        if let Some(proc) = child.as_mut() {
            let _ = proc.kill();
            let _ = proc.wait();
        }
        *child = None;
    }
    app.exit(0);
    Ok(())
}
