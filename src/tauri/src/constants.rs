//! Shared window geometry constants.

pub const ORB_SIZE: f64 = 108.0;
#[allow(dead_code)]
pub const ORB_PAD: f64 = 2.0; // thin clip inset so the CSS status glow around the 96px orb is visible
pub const DOCK_SLIVER: f64 = 26.0;
pub const HOVER_W: f64 = 320.0;
pub const HOVER_H: f64 = 230.0;
pub const DETAILS_W: f64 = 400.0;
pub const DETAILS_H: f64 = 680.0;
pub const SETTINGS_W: f64 = 480.0;
pub const SETTINGS_H: f64 = 640.0;

// The context menu window always owns room for the provider submenu. Showing
// or hiding that submenu only switches the window region, never the window
// size/position, so hovering "切换额度" cannot make the menu flash.
pub const MENU_PANEL_W: f64 = 222.0; // .menu width in CSS
pub const MENU_W: f64 = MENU_PANEL_W + 8.0; // panel + 4px inset on both sides
pub const MENU_H: f64 = 280.0;
pub const MENU_SUB_W: f64 = 200.0;
pub const MENU_TOTAL_W: f64 = MENU_W + MENU_SUB_W;
pub const MENU_PAD: f64 = 4.0; // .menu inset inside the window
