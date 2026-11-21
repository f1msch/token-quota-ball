mod aux_windows;
mod backend;
mod constants;
mod geom;
mod orb_cmds;
mod state;
#[cfg(windows)]
mod win32;

use std::sync::Mutex;

use tauri::Manager;

use aux_windows::{
    hide_details, hide_hover, hide_menu, hide_settings, set_menu_region, show_details, show_hover,
    show_menu, show_settings,
};
use backend::{shell_log, spawn_python_backend};
use constants::{DETAILS_H, DETAILS_W, HOVER_H, HOVER_W, MENU_H, MENU_TOTAL_W, SETTINGS_H, SETTINGS_W};
use geom::ensure_window;
use orb_cmds::{
    backend_info, get_orb_position, pointer_over_shell, quit_app, set_orb_position, start_drag,
    toggle_orb_dock, virtual_screen,
};
use state::Backend;
#[cfg(windows)]
use win32::{
    apply_orb_region, configure_frameless_shell, configure_orb_shell, hwnd_of,
    start_chrome_watchdog, window_needs_chrome_strip,
};
#[cfg(not(windows))]
fn configure_orb_shell(_win: &tauri::WebviewWindow) {}
#[cfg(not(windows))]
fn configure_frameless_shell(_win: &tauri::WebviewWindow) {}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let mut builder = tauri::Builder::default();
    builder = builder.plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
        if let Some(win) = app.get_webview_window("orb") {
            let _ = win.unminimize();
            let _ = win.show();
            let _ = win.set_focus();
        }
    }));
    builder
        .manage(Backend {
            url: Mutex::new(String::new()),
            token: Mutex::new(String::new()),
            python: Mutex::new(None),
        })
        .invoke_handler(tauri::generate_handler![
            backend_info,
            set_orb_position,
            get_orb_position,
            virtual_screen,
            show_hover,
            hide_hover,
            start_drag,
            show_details,
            hide_details,
            show_settings,
            hide_settings,
            show_menu,
            set_menu_region,
            hide_menu,
            pointer_over_shell,
            toggle_orb_dock,
            quit_app
        ])
        .setup(|app| {
            match spawn_python_backend() {
                Ok((url, token, child)) => {
                    if let Some(state) = app.try_state::<Backend>() {
                        if let Ok(mut slot) = state.url.lock() {
                            *slot = url;
                        }
                        if let Ok(mut slot) = state.token.lock() {
                            *slot = token;
                        }
                        if let Ok(mut slot) = state.python.lock() {
                            *slot = Some(child);
                        }
                    }
                }
                Err(err) => {
                    eprintln!("{err}");
                    app.dialog_error(&err);
                    app.handle().exit(0);
                    return Ok(());
                }
            }
            if let Some(orb) = app.get_webview_window("orb") {
                let _ = orb.show();
                let _ = orb.set_always_on_top(true);
                configure_orb_shell(&orb);
            }
            let handle = app.handle();
            for (label, hash, width, height, skip) in [
                ("hover", "#/hover", HOVER_W, HOVER_H, true),
                ("details", "#/details", DETAILS_W, DETAILS_H, false),
                ("settings", "#/settings", SETTINGS_W, SETTINGS_H, false),
                ("menu", "#/menu", MENU_TOTAL_W, MENU_H, true),
            ] {
                match ensure_window(handle, label, hash, width, height, skip) {
                    Ok(_) => shell_log(format!("precreated {label}")),
                    Err(e) => shell_log(format!("precreate {label} failed: {e}")),
                }
            }
            #[cfg(windows)]
            start_chrome_watchdog(app.handle().clone());
            Ok(())
        })
        .on_window_event(|window, event| {
            match event {
                tauri::WindowEvent::Resized(_)
                | tauri::WindowEvent::ScaleFactorChanged { .. }
                | tauri::WindowEvent::Focused(_) => {
                    if let Some(win) = window.app_handle().get_webview_window(window.label()) {
                        configure_frameless_shell(&win);
                    }
                }
                tauri::WindowEvent::Moved(_) => {
                    #[cfg(windows)]
                    if let Some(win) = window.app_handle().get_webview_window(window.label()) {
                        if let Some(hwnd) = hwnd_of(&win) {
                            if window_needs_chrome_strip(hwnd) {
                                configure_frameless_shell(&win);
                            }
                        }
                    }
                }
                _ => {}
            }
            if window.label() == "orb" {
                match event {
                    tauri::WindowEvent::Destroyed => {
                        window.app_handle().exit(0);
                    }
                    tauri::WindowEvent::Resized(_)
                    | tauri::WindowEvent::ScaleFactorChanged { .. } => {
                        if let Some(orb) = window.app_handle().get_webview_window("orb") {
                            #[cfg(windows)]
                            apply_orb_region(&orb);
                        }
                    }
                    _ => {}
                }
            }
            if let tauri::WindowEvent::Focused(false) = event {
                if window.label() == "menu" {
                    let _ = window.hide();
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building Token Quota Ball")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                if let Some(state) = app.try_state::<Backend>() {
                    if let Ok(mut child) = state.python.lock() {
                        if let Some(proc) = child.as_mut() {
                            let _ = proc.kill();
                            let _ = proc.wait();
                        }
                    }
                }
            }
        });
}

trait DialogExt {
    fn dialog_error(&self, message: &str);
}

impl DialogExt for tauri::App {
    fn dialog_error(&self, message: &str) {
        eprintln!("Token Quota Ball: {message}");
        #[cfg(windows)]
        {
            use std::ffi::OsStr;
            use std::os::windows::ffi::OsStrExt;
            let text: Vec<u16> = OsStr::new(message)
                .encode_wide()
                .chain(std::iter::once(0))
                .collect();
            let caption: Vec<u16> = OsStr::new("Token Quota Ball")
                .encode_wide()
                .chain(std::iter::once(0))
                .collect();
            unsafe {
                MessageBoxW(std::ptr::null_mut(), text.as_ptr(), caption.as_ptr(), 0x00000010);
            }
        }
    }
}

#[cfg(windows)]
#[link(name = "user32")]
extern "system" {
    fn MessageBoxW(
        hwnd: *mut std::ffi::c_void,
        text: *const u16,
        caption: *const u16,
        flags: u32,
    ) -> i32;
}
