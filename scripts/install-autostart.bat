@echo off
cd /d "%~dp0\.."
if not exist "src\token_quota_ball\__main__.py" (
  echo 找不到项目根目录。请从仓库的 scripts 目录运行本脚本。
  pause
  exit /b 1
)
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
python -m token_quota_ball install-autostart
echo.
pause
