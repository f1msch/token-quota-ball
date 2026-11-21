@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0\.."
if not exist "src\token_quota_ball\api\server.py" (
  echo 找不到项目根目录。请从仓库的 scripts 目录运行本脚本。
  exit /b 1
)

set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "OUT_DIR=src\tauri\binaries"
set "SPEC=packaging\token-quota-ball-api.spec"

where python >nul 2>nul
if errorlevel 1 (
  echo PATH 中未找到 Python。请安装 Python 3.10+ 后重试。
  exit /b 1
)

REM sidecar 输出被占用时 PyInstaller 也会失败
taskkill /F /IM token-quota-ball-api.exe >nul 2>nul
timeout /t 1 /nobreak >nul

echo 正在安装构建依赖...
python -m pip install -q -r requirements.txt -r requirements-build.txt
if errorlevel 1 exit /b 1

if not exist "%OUT_DIR%" mkdir "%OUT_DIR%"

echo 正在用 PyInstaller 冻结 Python API sidecar...
python -m PyInstaller --noconfirm --clean --distpath "%OUT_DIR%" --workpath "build\pyinstaller" "%SPEC%"
if errorlevel 1 (
  echo 后端冻结失败。
  exit /b 1
)

if not exist "%OUT_DIR%\token-quota-ball-api.exe" (
  echo 未找到预期产物：%OUT_DIR%\token-quota-ball-api.exe
  exit /b 1
)

echo.
echo Sidecar 已就绪：
echo   %OUT_DIR%\token-quota-ball-api.exe
exit /b 0
