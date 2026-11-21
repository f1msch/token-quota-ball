//! Python / sidecar 后端的启动与握手。

use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};

const SIDECAR_NAME: &str = "token-quota-ball-api.exe";

fn project_root() -> PathBuf {
    if let Ok(root) = std::env::var("TOKEN_QUOTA_BALL_ROOT") {
        return PathBuf::from(root);
    }
    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Ok(cwd) = std::env::current_dir() {
        candidates.push(cwd);
    }
    candidates.push(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(".."));
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            candidates.push(dir.to_path_buf());
            candidates.push(dir.join(".."));
            candidates.push(dir.join("..").join(".."));
        }
    }
    for start in candidates {
        let mut cur = start;
        for _ in 0..8 {
            if cur.join("src").join("token_quota_ball").join("api").join("server.py").exists()
                && cur.join("pyproject.toml").exists()
            {
                return cur;
            }
            if cur.join("token_quota_ball").join("api").join("server.py").exists() {
                return cur;
            }
            if !cur.pop() {
                break;
            }
        }
    }
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..")
}

fn looks_like_source_tree(root: &Path) -> bool {
    root.join("pyproject.toml").is_file()
        && root
            .join("src")
            .join("token_quota_ball")
            .join("api")
            .join("server.py")
            .is_file()
}

fn appdata_home() -> PathBuf {
    if let Ok(appdata) = std::env::var("APPDATA") {
        return PathBuf::from(appdata).join("TokenQuotaBall");
    }
    PathBuf::from("TokenQuotaBall")
}

/// Runtime data root shared by the shell and backend.
/// Packaged/sidecar → %APPDATA%\\TokenQuotaBall；源码开发 → 仓库根目录。
fn runtime_home() -> PathBuf {
    if let Ok(home) = std::env::var("TOKEN_QUOTA_BALL_HOME") {
        return PathBuf::from(home);
    }
    let root = project_root();
    if looks_like_source_tree(&root) {
        return root;
    }
    appdata_home()
}

fn logs_dir() -> PathBuf {
    let dir = runtime_home().join("logs");
    let _ = std::fs::create_dir_all(&dir);
    dir
}

fn sidecar_candidates() -> Vec<PathBuf> {
    let mut out = Vec::new();
    if let Ok(explicit) = std::env::var("TOKEN_QUOTA_BALL_BACKEND") {
        out.push(PathBuf::from(explicit));
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            out.push(dir.join(SIDECAR_NAME));
            out.push(dir.join("binaries").join(SIDECAR_NAME));
            // Tauri resource dir on some layouts
            out.push(dir.join("resources").join(SIDECAR_NAME));
            out.push(dir.join("_up_").join(SIDECAR_NAME));
        }
    }
    // Dev only: look beside the Cargo crate. Never bake this path into
    // end-user installs as a required location.
    #[cfg(debug_assertions)]
    out.push(
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("binaries")
            .join(SIDECAR_NAME),
    );
    out
}

fn find_sidecar() -> Option<PathBuf> {
    for path in sidecar_candidates() {
        if path.is_file() {
            return Some(path);
        }
    }
    None
}

fn python_exe() -> PathBuf {
    if let Ok(p) = std::env::var("TOKEN_QUOTA_BALL_PYTHON") {
        return PathBuf::from(p);
    }
    PathBuf::from("python")
}

fn apply_no_window(cmd: &mut Command) {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
}

fn spawn_sidecar(sidecar: PathBuf) -> Result<(String, String, Child), String> {
    let home = appdata_home();
    // Keep the shell and Python backend on the same data root.
    std::env::set_var("TOKEN_QUOTA_BALL_HOME", &home);
    std::env::set_var("TOKEN_QUOTA_BALL_PACKAGED", "1");
    let mut cmd = Command::new(&sidecar);
    cmd.current_dir(sidecar.parent().unwrap_or_else(|| Path::new(".")))
        .env("TOKEN_QUOTA_BALL_PACKAGED", "1")
        .env("TOKEN_QUOTA_BALL_HOME", &home)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    apply_no_window(&mut cmd);
    shell_log(format!(
        "starting sidecar {} home={}",
        sidecar.display(),
        home.display()
    ));
    let child = cmd.spawn().map_err(|err| {
        format!(
            "无法启动内置后端 ({}): {err}",
            sidecar.display()
        )
    })?;
    handshake(child)
}

fn spawn_python_module() -> Result<(String, String, Child), String> {
    let root = project_root();
    if !looks_like_source_tree(&root) {
        return Err(
            "未找到内置后端，也找不到源码树。请重新安装 Token Quota Ball，或从仓库用开发模式启动。"
                .into(),
        );
    }
    // Dev: keep config/logs under the repo unless the user overrode HOME.
    if std::env::var_os("TOKEN_QUOTA_BALL_HOME").is_none() {
        std::env::set_var("TOKEN_QUOTA_BALL_HOME", &root);
    }
    let python = python_exe();
    let mut cmd = Command::new(&python);
    let src = root.join("src");
    let pythonpath = match std::env::var("PYTHONPATH") {
        Ok(existing) if !existing.is_empty() => format!("{};{}", src.display(), existing),
        _ => src.display().to_string(),
    };
    cmd.args(["-m", "token_quota_ball.api"])
        .current_dir(&root)
        .env("PYTHONPATH", pythonpath)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    apply_no_window(&mut cmd);
    shell_log(format!(
        "starting python -m token_quota_ball.api root={}",
        root.display()
    ));
    let child = cmd.spawn().map_err(|err| {
        format!(
            "无法启动 Python 后端 ({}): {err}",
            python.display()
        )
    })?;
    handshake(child)
}

fn drain_stderr(child: &mut Child) {
    if let Some(stderr) = child.stderr.take() {
        let log_path = logs_dir().join("backend-stderr.log");
        std::thread::spawn(move || {
            use std::io::{BufRead, BufReader, Write};
            let mut log = std::fs::OpenOptions::new()
                .create(true)
                .append(true)
                .open(&log_path)
                .ok();
            let reader = BufReader::new(stderr);
            for line in reader.lines().flatten() {
                if let Some(f) = log.as_mut() {
                    let _ = writeln!(f, "{line}");
                }
                eprintln!("[backend] {line}");
            }
        });
    }
}

fn handshake(mut child: Child) -> Result<(String, String, Child), String> {
    drain_stderr(&mut child);
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "后端没有标准输出".to_string())?;
    let mut reader = BufReader::new(stdout);
    let mut line = String::new();
    // Handshake: "READY 127.0.0.1:PORT TOKEN"
    loop {
        line.clear();
        let n = reader
            .read_line(&mut line)
            .map_err(|err| format!("读取后端握手失败: {err}"))?;
        if n == 0 {
            let code = child.try_wait().ok().and_then(|s| s).map(|s| s.to_string());
            if code.as_deref().unwrap_or("").contains("2") {
                return Err("Token Quota Ball 已在运行。请先右键「退出」后再启动。".into());
            }
            return Err("后端提前退出，未发出 READY。若已有实例在运行，请先右键退出。".into());
        }
        let trimmed = line.trim();
        if let Some(rest) = trimmed.strip_prefix("READY ") {
            let mut parts = rest.split_whitespace();
            let addr = parts.next().ok_or("READY 行缺少地址")?;
            let token = parts.next().ok_or("READY 行缺少令牌")?;
            let url = format!("http://{addr}");
            // Keep consuming leftover stdout so the pipe cannot fill.
            std::thread::spawn(move || {
                let mut sink = String::new();
                while reader.read_line(&mut sink).unwrap_or(0) > 0 {
                    sink.clear();
                }
            });
            return Ok((url, token.to_string(), child));
        }
    }
}

pub(crate) fn spawn_python_backend() -> Result<(String, String, Child), String> {
    // Prefer the frozen sidecar so release installs do not need system Python.
    if let Some(sidecar) = find_sidecar() {
        return spawn_sidecar(sidecar);
    }
    spawn_python_module()
}

pub(crate) fn shell_log(msg: impl AsRef<str>) {
    let path = logs_dir().join("tauri-shell.log");
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(&path) {
        use std::io::Write;
        let _ = writeln!(f, "{}", msg.as_ref());
    }
    eprintln!("[token-quota-ball] {}", msg.as_ref());
}
