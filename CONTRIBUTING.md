# 参与贡献

## 开发环境（Windows）

1. 安装 Python 3.10+、Node.js 20+、Rust 1.77.2+
2. `pip install -r requirements-dev.txt && pip install -e .`
3. `npm install && npm --prefix src/ui install`
4. 日常开发运行：`scripts\run-tauri.bat`

## 提 PR 前请先本地检查

```bat
pytest
npm run build:ui
cd src\tauri && cargo check
```

打独立安装包：`scripts\build-tauri.bat`（release 配置 + API sidecar）。

## 注意事项

- 不要提交 `config/providers.json`、`.env`、`logs/`、`run/`
- 尽量小步、聚焦地改动
