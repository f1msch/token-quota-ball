//! Screen geometry and auxiliary window placement.

use tauri::{AppHandle, LogicalPosition, Manager, WebviewUrl, WebviewWindow, WebviewWindowBuilder};

use crate::backend::shell_log;
use crate::constants::ORB_SIZE;
use crate::state::ScreenRect;
#[cfg(windows)]
use crate::win32::{
    configure_frameless_shell, hwnd_of, scale_of, schedule_frameless, wait_for_hwnd,
    virtual_screen_physical, SetWindowPos, ShowWindow,
};

#[cfg(not(windows))]
fn scale_of(_win: &WebviewWindow) -> f64 {
    1.0
}
#[cfg(not(windows))]
fn wait_for_hwnd(_win: &WebviewWindow) {}
#[cfg(not(windows))]
fn schedule_frameless(_win: &WebviewWindow) {}
#[cfg(not(windows))]
fn configure_frameless_shell(_win: &WebviewWindow) {}

pub fn logical_screen(win: &WebviewWindow) -> ScreenRect {
    #[cfg(windows)]
    {
        let scale = scale_of(win).max(0.1);
        let (x, y, w, h) = virtual_screen_physical();
        return ScreenRect {
            x: x as f64 / scale,
            y: y as f64 / scale,
            width: w as f64 / scale,
            height: h as f64 / scale,
        };
    }
    #[cfg(not(windows))]
    {
        let _ = win;
        ScreenRect {
            x: 0.0,
            y: 0.0,
            width: 1920.0,
            height: 1080.0,
        }
    }
}

pub fn orb_window(app: &AppHandle) -> Result<WebviewWindow, String> {
    app.get_webview_window("orb")
        .ok_or_else(|| "找不到悬浮球窗口".to_string())
}

pub fn url_for(_app: &AppHandle, hash: &str) -> WebviewUrl {
    if cfg!(debug_assertions) {
        let url = format!("http://localhost:1420/{hash}");
        WebviewUrl::External(url.parse().expect("dev url"))
    } else {
        WebviewUrl::App(format!("/{hash}").into())
    }
}

pub fn ensure_window(
    app: &AppHandle,
    label: &str,
    hash: &str,
    width: f64,
    height: f64,
    skip_taskbar: bool,
) -> Result<WebviewWindow, String> {
    if let Some(existing) = app.get_webview_window(label) {
        return Ok(existing);
    }
    let win = WebviewWindowBuilder::new(app, label, url_for(app, hash))
        .title("")
        .inner_size(width, height)
        .decorations(false)
        .transparent(true)
        .shadow(false)
        .always_on_top(true)
        .resizable(false)
        .skip_taskbar(skip_taskbar)
        .visible(true)
        .focused(false)
        .build()
        .map_err(|err| format!("无法创建窗口 {label}: {err}"))?;
    wait_for_hwnd(&win);
    schedule_frameless(&win);
    let _ = win.hide();
    #[cfg(windows)]
    if let Some(hwnd) = hwnd_of(&win) {
        const SW_HIDE: i32 = 0;
        unsafe { ShowWindow(hwnd, SW_HIDE) };
    }
    Ok(win)
}

pub fn beside_orb_pos(
    app: &AppHandle,
    width: f64,
    height: f64,
    gap: f64,
) -> Result<(f64, f64, f64), String> {
    let orb = orb_window(app)?;
    let pos = orb.outer_position().map_err(|e| e.to_string())?;
    let scale = scale_of(&orb).max(0.1);
    let ox = pos.x as f64 / scale;
    let oy = pos.y as f64 / scale;
    let screen = logical_screen(&orb);
    let mut x = ox + ORB_SIZE + gap;
    let mut y = oy + (ORB_SIZE - height) / 2.0;
    if x + width > screen.x + screen.width - 6.0 {
        x = ox - width - gap;
    }
    if y < screen.y + 6.0 {
        y = screen.y + 6.0;
    }
    if y + height > screen.y + screen.height - 6.0 {
        y = screen.y + screen.height - height - 6.0;
    }
    Ok((x, y, scale))
}

pub fn place_beside_orb(
    app: &AppHandle,
    win: &WebviewWindow,
    width: f64,
    height: f64,
    gap: f64,
) -> Result<(), String> {
    let (x, y, scale) = beside_orb_pos(app, width, height, gap)?;
    if let Err(e) = win.set_position(LogicalPosition::new(x, y)) {
        shell_log(format!("set_position {} failed: {e}", win.label()));
        #[cfg(windows)]
        {
            let Some(hwnd) = hwnd_of(win) else {
                return Err(format!("set_position failed and no hwnd: {e}"));
            };
            const SWP_NOSIZE: u32 = 0x0001;
            const SWP_NOZORDER: u32 = 0x0004;
            const SWP_NOACTIVATE: u32 = 0x0010;
            let px = (x * scale).round() as i32;
            let py = (y * scale).round() as i32;
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
                return Err(format!("set_position failed: {e}; SetWindowPos failed"));
            }
        }
        #[cfg(not(windows))]
        {
            return Err(e.to_string());
        }
    }
    Ok(())
}

pub fn reveal_aux_window(
    app: &AppHandle,
    win: &WebviewWindow,
    width: f64,
    height: f64,
    gap: f64,
) -> Result<(), String> {
    wait_for_hwnd(win);
    configure_frameless_shell(win);
    if let Err(e) = place_beside_orb(app, win, width, height, gap) {
        shell_log(format!("place {} before show failed: {e}", win.label()));
    }
    let _ = win.show();
    configure_frameless_shell(win);
    let _ = win.set_always_on_top(true);
    schedule_frameless(win);
    if let Err(e) = place_beside_orb(app, win, width, height, gap) {
        shell_log(format!("place {} after show failed: {e}", win.label()));
    }
    #[cfg(windows)]
    {
        let Some(hwnd) = hwnd_of(win) else {
            return Err(format!("no hwnd for {}", win.label()));
        };
        let (x, y, scale) = beside_orb_pos(app, width, height, gap)?;
        let px = (x * scale).round() as i32;
        let py = (y * scale).round() as i32;
        const HWND_TOPMOST: *mut std::ffi::c_void = -1isize as *mut std::ffi::c_void;
        const SWP_NOSIZE: u32 = 0x0001;
        const SWP_NOACTIVATE: u32 = 0x0010;
        const SWP_SHOWWINDOW: u32 = 0x0040;
        const SW_SHOWNOACTIVATE: i32 = 4;
        unsafe { ShowWindow(hwnd, SW_SHOWNOACTIVATE) };
        let ok = unsafe {
            SetWindowPos(
                hwnd,
                HWND_TOPMOST,
                px,
                py,
                0,
                0,
                SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
            )
        };
        shell_log(format!(
            "reveal {} logical=({x:.1},{y:.1}) physical=({px},{py}) scale={scale:.2} SetWindowPos={ok} last={}",
            win.label(),
            std::io::Error::last_os_error()
        ));
        if ok == 0 {
            return Err(format!(
                "SetWindowPos {} failed: {}",
                win.label(),
                std::io::Error::last_os_error()
            ));
        }
        configure_frameless_shell(win);
    }
    Ok(())
}
