"""Local HTTP API for the Tauri shell. Reuses existing providers; no quota logic in Rust."""

from .server import serve

__all__ = ["serve"]
