@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0\.."
if not exist "src\tauri\tauri.conf.json" (
  echo 找不到项目根目录。请从仓库的 scripts 目录运行本脚本。
  pause
  exit /b 1
)

set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"

if exist "%USERPROFILE%\.cargo\env.bat" call "%USERPROFILE%\.cargo\env.bat"

if exist "src\tauri\target\release\token-quota-ball.exe" (
  if exist "src\tauri\binaries\token-quota-ball-api.exe" (
    copy /Y "src\tauri\binaries\token-quota-ball-api.exe" "src\tauri\target\release\token-quota-ball-api.exe" >nul
  )
  if not exist "src\tauri\target\release\token-quota-ball-api.exe" (
    echo 已找到 release 主程序，但缺少 sidecar：token-quota-ball-api.exe
    echo 请先运行 scripts\build-tauri.bat，或继续进入开发模式。
    goto :dev
  )
  start "" "src\tauri\target\release\token-quota-ball.exe"
  goto :eof
)

:dev

where cargo >nul 2>nul
if errorlevel 1 (
  echo 未找到 Rust/cargo。请先安装 rustup，再重新运行本脚本。
  pause
  exit /b 1
)

where node >nul 2>nul
if errorlevel 1 (
  echo 未找到 Node.js。请先安装 Node.js，再重新运行本脚本。
  pause
  exit /b 1
)

if not exist "node_modules\@tauri-apps\cli" (
  echo 正在安装 Tauri CLI 与前端依赖，首次可能较慢...
  call npm install
  if errorlevel 1 exit /b 1
)
if not exist "src\ui\node_modules" (
  call npm --prefix src/ui install
  if errorlevel 1 exit /b 1
)

echo 正在启动 Token Quota Ball（Tauri 开发模式）...
echo 若已有实例在运行，请先在球上右键选择「退出」。
call npm run tauri:dev
