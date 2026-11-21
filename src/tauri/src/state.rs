//! Shared app state and IPC payload types.

use serde::Serialize;
use std::process::Child;
use std::sync::Mutex;

pub struct Backend {
    pub url: Mutex<String>,
    pub token: Mutex<String>,
    pub python: Mutex<Option<Child>>,
}

#[derive(Serialize, Clone)]
pub struct BackendInfo {
    pub url: String,
    pub token: String,
}

#[derive(Serialize, Clone)]
pub struct Point {
    pub x: f64,
    pub y: f64,
}

#[derive(Serialize, Clone)]
pub struct ScreenRect {
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
}

#[derive(Serialize, Clone)]
pub struct DockChanged {
    pub docked: bool,
    pub edge: String,
}

#[derive(Serialize, Clone)]
pub struct MenuPlaced {
    pub x: f64,
    pub y: f64,
    pub sub_right: bool,
}
