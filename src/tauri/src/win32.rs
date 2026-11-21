//! Windows 壳层细节：缩放、无边框、窗口 region 与 Win32 绑定。

use std::collections::HashMap;
use std::sync::{Mutex, OnceLock};
use std::time::Duration;
use tauri::{AppHandle, LogicalSize, Manager, WebviewWindow};

use crate::constants::{MENU_H, MENU_TOTAL_W, MENU_W, ORB_PAD, ORB_SIZE};

pub(crate) fn scale_of(win: &WebviewWindow) -> f64 {
    win.scale_factor().unwrap_or(1.0)
}

#[cfg(windows)]
pub(crate) fn virtual_screen_physical() -> (i32, i32, i32, i32) {
    const SM_XVIRTUALSCREEN: i32 = 76;
    const SM_YVIRTUALSCREEN: i32 = 77;
    const SM_CXVIRTUALSCREEN: i32 = 78;
    const SM_CYVIRTUALSCREEN: i32 = 79;
    unsafe {
        (
            GetSystemMetrics(SM_XVIRTUALSCREEN),
            GetSystemMetrics(SM_YVIRTUALSCREEN),
            GetSystemMetrics(SM_CXVIRTUALSCREEN),
            GetSystemMetrics(SM_CYVIRTUALSCREEN),
        )
    }
}

#[cfg(windows)]
pub(crate) fn apply_orb_region(win: &WebviewWindow) {
    use std::sync::atomic::{AtomicBool, Ordering};
    static APPLYING: AtomicBool = AtomicBool::new(false);
    if APPLYING.swap(true, Ordering::SeqCst) {
        return;
    }
    apply_orb_region_inner(win);
    APPLYING.store(false, Ordering::SeqCst);
}

fn apply_orb_region_inner(win: &WebviewWindow) {
    let Some(hwnd) = hwnd_of(win) else { return };
    if hwnd.is_null() {
        return;
    }
    let mut wr = RECT {
        left: 0,
        top: 0,
        right: 0,
        bottom: 0,
    };
    if unsafe { GetWindowRect(hwnd, &mut wr) } == 0 {
        return;
    }
    let width = wr.right - wr.left;
    let height = wr.bottom - wr.top;
    if width <= 0 || height <= 0 {
        return;
    }
    // Match the painted orb, which is centered in the window. If Windows still
    // enforces a minimum width, a left-aligned region would miss the circle.
    let side = width.min(height);
    let dpi = unsafe { GetDpiForWindow(hwnd) }.max(96);
    let scale = dpi as f64 / 96.0;
    let pad = (ORB_PAD * scale).round() as i32;
    let x0 = (width - side) / 2 + pad;
    let y0 = (height - side) / 2 + pad;
    let x1 = x0 + side - 2 * pad;
    let y1 = y0 + side - 2 * pad;
    if x1 <= x0 || y1 <= y0 {
        return;
    }
    let rgn = unsafe { CreateEllipticRgn(x0, y0, x1, y1) };
    if !rgn.is_null() {
        unsafe {
            SetWindowRgn(hwnd, rgn, 1);
        }
    }
}

/// Clip the always-wide menu window to the part that actually paints: the
/// parent column alone while collapsed, the full row while the provider
/// submenu is open. Resizing the region keeps the HWND geometry untouched,
/// which is what eliminates the hover flicker.
#[cfg(windows)]
pub(crate) fn apply_menu_region(win: &WebviewWindow, expanded: bool, sub_right: bool) {
    let Some(hwnd) = hwnd_of(win) else { return };
    if hwnd.is_null() {
        return;
    }
    // Size the region from the DPI scale, not from GetWindowRect: the region
    // is stored in window coordinates and stays valid when the (hidden) window
    // is still settling into its new size.
    let scale = scale_of(win).max(0.1);
    let total_w = (MENU_TOTAL_W * scale).round() as i32;
    let height = (MENU_H * scale).round() as i32;
    let parent_w = (MENU_W * scale).round() as i32;
    let (x0, x1) = if expanded {
        (0, total_w)
    } else if sub_right {
        (0, parent_w)
    } else {
        (total_w - parent_w, total_w)
    };
    if x1 <= x0 {
        return;
    }
    let rgn = unsafe { CreateRectRgn(x0, 0, x1, height) };
    if !rgn.is_null() {
        unsafe {
            SetWindowRgn(hwnd, rgn, 1);
        }
    }
}

#[cfg(windows)]
pub(crate) fn schedule_frameless(win: &WebviewWindow) {
    configure_frameless_shell(win);
    let delayed = win.clone();
    std::thread::spawn(move || {
        // WebView2 regularly restores WS_CAPTION after first init; keep
        // re-stripping well past the first paint, then a slower watchdog
        // started from setup covers later resets (for example on show()).
        let mut elapsed = 0_u64;
        for ms in [50_u64, 80, 160, 300, 500, 800, 1200, 2000, 3500, 6000, 9000] {
            let wait = ms.saturating_sub(elapsed);
            if wait > 0 {
                std::thread::sleep(Duration::from_millis(wait));
            }
            elapsed = ms;
            configure_frameless_shell(&delayed);
        }
    });
}

#[cfg(windows)]
static ORIG_WNDPROCS: OnceLock<Mutex<HashMap<isize, isize>>> = OnceLock::new();

#[cfg(windows)]
fn orig_wndproc(hwnd: *mut std::ffi::c_void) -> Option<isize> {
    let map = ORIG_WNDPROCS.get_or_init(|| Mutex::new(HashMap::new()));
    map.lock().ok()?.get(&(hwnd as isize)).copied()
}

#[cfg(windows)]
unsafe extern "system" fn chrome_wndproc(
    hwnd: *mut std::ffi::c_void,
    msg: u32,
    wp: usize,
    lp: isize,
) -> isize {
    const WM_NCCALCSIZE: u32 = 0x0083;
    const WM_NCPAINT: u32 = 0x0085;
    const WM_NCACTIVATE: u32 = 0x0086;
    const WM_SETTEXT: u32 = 0x000C;
    const WM_STYLECHANGED: u32 = 0x007D;
    if msg == WM_NCCALCSIZE {
        return 0;
    }
    if msg == WM_NCPAINT {
        return 0;
    }
    if msg == WM_NCACTIVATE {
        return 1;
    }
    if msg == WM_SETTEXT {
        let empty: [u16; 1] = [0];
        if let Some(orig) = orig_wndproc(hwnd) {
            return CallWindowProcW(orig, hwnd, msg, wp, empty.as_ptr() as isize);
        }
        return 0;
    }
    if msg == WM_STYLECHANGED {
        strip_caption_style(hwnd);
    }
    if let Some(orig) = orig_wndproc(hwnd) {
        CallWindowProcW(orig, hwnd, msg, wp, lp)
    } else {
        DefWindowProcW(hwnd, msg, wp, lp)
    }
}

#[cfg(windows)]
fn install_chrome_subclass(hwnd: *mut std::ffi::c_void) {
    if hwnd.is_null() {
        return;
    }
    const GWLP_WNDPROC: i32 = -4;
    let map = ORIG_WNDPROCS.get_or_init(|| Mutex::new(HashMap::new()));
    if let Ok(guard) = map.lock() {
        if guard.contains_key(&(hwnd as isize)) {
            return;
        }
    }
    unsafe {
        let prev = SetWindowLongPtrW(hwnd, GWLP_WNDPROC, chrome_wndproc as *const () as isize);
        if let Ok(mut guard) = map.lock() {
            guard.insert(hwnd as isize, prev);
        }
    }
}

#[cfg(windows)]
fn strip_caption_style(hwnd: *mut std::ffi::c_void) {
    if hwnd.is_null() {
        return;
    }
    const GWL_STYLE: i32 = -16;
    const GWL_EXSTYLE: i32 = -20;
    const WS_POPUP: u32 = 0x8000_0000;
    const WS_VISIBLE: u32 = 0x1000_0000;
    const WS_CLIPSIBLINGS: u32 = 0x0400_0000;
    const WS_CLIPCHILDREN: u32 = 0x0200_0000;
    const WS_CAPTION_AND_CHROME: u32 = 0x00CF_0000;
    const WS_EX_WINDOWEDGE: u32 = 0x0000_0100;
    const WS_EX_CLIENTEDGE: u32 = 0x0000_0200;
    const WS_EX_DLGMODALFRAME: u32 = 0x0000_0001;
    const WS_EX_APPWINDOW: u32 = 0x0004_0000;
    const SWP_NOSIZE: u32 = 0x0001;
    const SWP_NOMOVE: u32 = 0x0002;
    const SWP_NOZORDER: u32 = 0x0004;
    const SWP_NOACTIVATE: u32 = 0x0010;
    const SWP_FRAMECHANGED: u32 = 0x0020;
    const DWMWA_NCRENDERING_POLICY: u32 = 2;
    const DWMNCRP_DISABLED: i32 = 1;
    const DWMWA_TRANSITIONS_FORCEDISABLED: u32 = 3;
    const DWMWA_BORDER_COLOR: u32 = 34;
    const DWMWA_CAPTION_COLOR: u32 = 35;
    const DWMWA_TEXT_COLOR: u32 = 36;
    const DWMWA_COLOR_NONE: u32 = 0xFFFFFFFE;
    unsafe {
        let style = GetWindowLongPtrW(hwnd, GWL_STYLE) as u32;
        let new_style = (style & !WS_CAPTION_AND_CHROME)
            | WS_POPUP
            | WS_CLIPSIBLINGS
            | WS_CLIPCHILDREN
            | (style & WS_VISIBLE);
        if new_style != style {
            SetWindowLongPtrW(hwnd, GWL_STYLE, new_style as isize);
        }
        let ex = GetWindowLongPtrW(hwnd, GWL_EXSTYLE) as u32;
        let new_ex = ex & !(WS_EX_WINDOWEDGE | WS_EX_CLIENTEDGE | WS_EX_DLGMODALFRAME | WS_EX_APPWINDOW);
        if new_ex != ex {
            SetWindowLongPtrW(hwnd, GWL_EXSTYLE, new_ex as isize);
        }
        let empty: [u16; 1] = [0];
        SetWindowTextW(hwnd, empty.as_ptr());
        SetWindowTheme(hwnd, empty.as_ptr(), empty.as_ptr());
        let policy = DWMNCRP_DISABLED;
        DwmSetWindowAttribute(
            hwnd,
            DWMWA_NCRENDERING_POLICY,
            &policy as *const i32 as *const std::ffi::c_void,
            std::mem::size_of::<i32>() as u32,
        );
        let disable: i32 = 1;
        DwmSetWindowAttribute(
            hwnd,
            DWMWA_TRANSITIONS_FORCEDISABLED,
            &disable as *const i32 as *const std::ffi::c_void,
            std::mem::size_of::<i32>() as u32,
        );
        let none = DWMWA_COLOR_NONE;
        DwmSetWindowAttribute(
            hwnd,
            DWMWA_BORDER_COLOR,
            &none as *const u32 as *const std::ffi::c_void,
            std::mem::size_of::<u32>() as u32,
        );
        DwmSetWindowAttribute(
            hwnd,
            DWMWA_CAPTION_COLOR,
            &none as *const u32 as *const std::ffi::c_void,
            std::mem::size_of::<u32>() as u32,
        );
        DwmSetWindowAttribute(
            hwnd,
            DWMWA_TEXT_COLOR,
            &none as *const u32 as *const std::ffi::c_void,
            std::mem::size_of::<u32>() as u32,
        );
        let margins = MARGINS {
            cx_left_width: -1,
            cx_right_width: -1,
            cy_top_height: -1,
            cy_bottom_height: -1,
        };
        DwmExtendFrameIntoClientArea(hwnd, &margins);
        SetWindowPos(
            hwnd,
            std::ptr::null_mut(),
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        );
    }
}

#[cfg(windows)]
pub(crate) fn window_needs_chrome_strip(hwnd: *mut std::ffi::c_void) -> bool {
    if hwnd.is_null() {
        return false;
    }
    const GWL_STYLE: i32 = -16;
    const WS_CAPTION_AND_CHROME: u32 = 0x00CF_0000;
    unsafe {
        let style = GetWindowLongPtrW(hwnd, GWL_STYLE) as u32;
        if style & WS_CAPTION_AND_CHROME != 0 {
            return true;
        }
        let mut buf = [0u16; 4];
        GetWindowTextW(hwnd, buf.as_mut_ptr(), buf.len() as i32) > 0
    }
}

pub(crate) fn configure_frameless_shell(win: &WebviewWindow) {
    // decorations(false) is not enough on Windows: WebView2/DWM can keep a
    // caption that paints a clipped title like "en Quota" onto a transparent
    // window, even after WS_CAPTION is cleared once. Empty the title, strip
    // chrome, disable NC rendering, and swallow NCCALCSIZE/NCPAINT.
    let _ = win.set_decorations(false);
    let _ = win.set_shadow(false);
    let _ = win.set_title("");
    #[cfg(windows)]
    {
        let Some(hwnd) = hwnd_of(win) else { return };
        if hwnd.is_null() {
            return;
        }
        install_chrome_subclass(hwnd);
        strip_caption_style(hwnd);
    }
}

#[cfg(windows)]
pub(crate) fn start_chrome_watchdog(app: AppHandle) {
    std::thread::spawn(move || {
        for i in 0..240 {
            std::thread::sleep(Duration::from_millis(if i < 40 { 250 } else { 1000 }));
            for label in ["orb", "hover", "details", "settings", "menu"] {
                if let Some(win) = app.get_webview_window(label) {
                    if let Some(hwnd) = hwnd_of(&win) {
                        if i < 24 || window_needs_chrome_strip(hwnd) {
                            configure_frameless_shell(&win);
                        }
                    }
                }
            }
        }
    });
}

pub(crate) fn configure_orb_shell(win: &WebviewWindow) {
    // Transparent WebView2 windows can swallow pointer events unless the shell
    // explicitly accepts them. Also drop caption styles so Windows will allow a
    // 108x108 window (SM_CXMINTRACK is 136px for captioned windows).
    let _ = win.set_ignore_cursor_events(false);
    configure_frameless_shell(win);
    let _ = win.set_size(LogicalSize::new(ORB_SIZE, ORB_SIZE));
    #[cfg(windows)]
    apply_orb_region(win);
}

pub(crate) fn wait_for_hwnd(win: &WebviewWindow) {
    for _ in 0..50 {
        if hwnd_of(win).is_some() {
            return;
        }
        std::thread::sleep(Duration::from_millis(20));
    }
}

pub(crate) fn hwnd_of(win: &WebviewWindow) -> Option<*mut std::ffi::c_void> {
    #[cfg(windows)]
    {
        win.hwnd().ok().map(|h| h.0 as *mut std::ffi::c_void)
    }
    #[cfg(not(windows))]
    {
        let _ = win;
        None
    }
}

pub(crate) fn window_contains_cursor(win: &WebviewWindow) -> bool {
    #[cfg(windows)]
    {
        let Some(hwnd) = hwnd_of(win) else { return false };
        if !win.is_visible().unwrap_or(false) {
            return false;
        }
        let mut pt = POINT { x: 0, y: 0 };
        if unsafe { GetCursorPos(&mut pt) } == 0 {
            return false;
        }
        let mut rc = RECT { left: 0, top: 0, right: 0, bottom: 0 };
        if unsafe { GetWindowRect(hwnd, &mut rc) } == 0 {
            return false;
        }
        return pt.x >= rc.left && pt.x < rc.right && pt.y >= rc.top && pt.y < rc.bottom;
    }
    #[cfg(not(windows))]
    {
        let _ = win;
        false
    }
}

#[cfg(windows)]
#[repr(C)]
struct POINT {
    x: i32,
    y: i32,
}

#[cfg(windows)]
#[repr(C)]
struct RECT {
    left: i32,
    top: i32,
    right: i32,
    bottom: i32,
}

#[cfg(windows)]
#[link(name = "user32")]
extern "system" {
    fn GetSystemMetrics(n: i32) -> i32;
    fn GetDpiForWindow(hwnd: *mut std::ffi::c_void) -> u32;
    fn SetWindowRgn(hwnd: *mut std::ffi::c_void, hrgn: *mut std::ffi::c_void, redraw: i32) -> i32;
    fn GetCursorPos(pt: *mut POINT) -> i32;
    pub(crate) fn GetAsyncKeyState(vkey: i32) -> i16;
    fn GetWindowRect(hwnd: *mut std::ffi::c_void, rc: *mut RECT) -> i32;
    fn GetWindowLongPtrW(hwnd: *mut std::ffi::c_void, index: i32) -> isize;
    fn SetWindowLongPtrW(hwnd: *mut std::ffi::c_void, index: i32, new_long: isize) -> isize;
    pub(crate) fn SetWindowPos(
        hwnd: *mut std::ffi::c_void,
        insert_after: *mut std::ffi::c_void,
        x: i32,
        y: i32,
        cx: i32,
        cy: i32,
        flags: u32,
    ) -> i32;
    pub(crate) fn ShowWindow(hwnd: *mut std::ffi::c_void, cmd: i32) -> i32;
    fn SetWindowTextW(hwnd: *mut std::ffi::c_void, text: *const u16) -> i32;
    fn GetWindowTextW(hwnd: *mut std::ffi::c_void, text: *mut u16, max: i32) -> i32;
    fn CallWindowProcW(
        prev: isize,
        hwnd: *mut std::ffi::c_void,
        msg: u32,
        wp: usize,
        lp: isize,
    ) -> isize;
    fn DefWindowProcW(hwnd: *mut std::ffi::c_void, msg: u32, wp: usize, lp: isize) -> isize;
}

#[cfg(windows)]
#[repr(C)]
struct MARGINS {
    cx_left_width: i32,
    cx_right_width: i32,
    cy_top_height: i32,
    cy_bottom_height: i32,
}

#[cfg(windows)]
#[link(name = "dwmapi")]
extern "system" {
    fn DwmExtendFrameIntoClientArea(hwnd: *mut std::ffi::c_void, margins: *const MARGINS) -> i32;
    fn DwmSetWindowAttribute(
        hwnd: *mut std::ffi::c_void,
        attr: u32,
        value: *const std::ffi::c_void,
        size: u32,
    ) -> i32;
}

#[cfg(windows)]
#[link(name = "uxtheme")]
extern "system" {
    fn SetWindowTheme(hwnd: *mut std::ffi::c_void, sub_app: *const u16, sub_id: *const u16) -> i32;
}

#[cfg(windows)]
#[link(name = "gdi32")]
extern "system" {
    fn CreateEllipticRgn(x1: i32, y1: i32, x2: i32, y2: i32) -> *mut std::ffi::c_void;
    fn CreateRectRgn(x1: i32, y1: i32, x2: i32, y2: i32) -> *mut std::ffi::c_void;
}
