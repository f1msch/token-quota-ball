@echo off
setlocal
cd /d "%~dp0\.."
if not exist "src\tauri\tauri.conf.json" (
  echo 找不到项目根目录。请从仓库的 scripts 目录运行本脚本。
  pause
  exit /b 1
)

set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"

if exist "%USERPROFILE%\.cargo\env.bat" call "%USERPROFILE%\.cargo\env.bat"

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

where python >nul 2>nul
if errorlevel 1 (
  echo 未找到 Python。打独立安装包需要本机 Python 来冻结 API sidecar。
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

echo.
echo [1/2] 正在冻结 Python API sidecar...
call scripts\build-backend.bat
if errorlevel 1 (
  echo 后端冻结失败。
  pause
  exit /b 1
)

echo.
echo [2/2] 正在构建 Windows 发布版（NSIS 安装包 + exe）...
echo 若悬浮球正在运行，请先退出，否则 exe 可能被占用。
call npm run tauri:build
if errorlevel 1 (
  echo 构建失败。
  pause
  exit /b 1
)

echo.
echo 构建完成。可直接分发的文件（最终用户无需安装 Python）：
echo   src\tauri\target\release\token-quota-ball.exe
echo   src\tauri\target\release\token-quota-ball-api.exe
echo   src\tauri\target\release\bundle\nsis\
echo 发布到 GitHub 时，建议挂上 NSIS 安装包（或同时提供上述两个 exe）。
pause
