# Token Quota Ball

Windows 桌面额度悬浮球。屏幕上置顶显示一颗玻璃水球，用来查看已接入服务的账号用量。没有系统标题栏和方形边框，水位高度和颜色会随已用比例平滑变化。

![Token Quota Ball 演示](docs/screenshot.png)

*示意截图，数据为虚构，不涉及真实账号。左侧三颗小球分别示意低 / 中 / 高用量时的水位与颜色；右侧为一颗示例球及其悬停条。*

<p align="center">
  <img alt="Platform" src="https://img.shields.io/badge/platform-Windows-0078D4?style=flat-square">
  <img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-informational?style=flat-square">
</p>

## 支持的服务

本工具查看的是下列服务的账号额度，不是某一模型的单独用量。

- **Cursor**  
  自动读取本机已登录的 Cursor。球上显示 Included Usage 已用百分比。

- **WorkBuddy**（腾讯办公 Agent）  
  自动读取本机已登录的 WorkBuddy 桌面端。球上显示当前积分包已用比例；企业无限额度时显示「不限」。

- **Trae**  
  自动读取本机已登录的 Trae CN。球上显示积分已用比例。

- **DeepSeek**  
  在设置里填写 API Key。球上显示账户余额。官方接口没有周期额度上限；若填写了可选的「参考额度」，才会按「参考额度 − 余额」显示水位占比。

- **火山方舟 Agent Plan**（火山引擎）  
  在设置里填写火山引擎 IAM 访问密钥（不要填模型推理 API Key）。企业版还需填写席位 ID。球上显示近 5 小时、近 1 天、近 1 周、近 1 月四个时间窗口中，已用占比最高的一项（单位 AFP）。

未登录或未配置时，球上会显示 `--` 并说明原因，不会用假数据冒充真实额度。当前选中的提供方会记住。

## 下载安装

1. 打开 [Releases](../../releases)，下载最新的 **安装包**（文件名类似 `Token Quota Ball_x.x.x_x64-setup.exe`）。
2. 安装完成后，从开始菜单启动即可。
3. 使用安装包时，不必再安装 Python、Node.js 或 Rust。

请只开一个悬浮球。如果启动失败，可在任务管理器中结束残留的 `token-quota-ball.exe` 和 `token-quota-ball-api.exe`，然后再试一次。

### Release 里的文件分别是什么

| 文件 | 说明 |
|------|------|
| `Token Quota Ball_x.x.x_x64-setup.exe` | NSIS 安装包，会安装主程序和后端。普通用户下载这个即可。 |
| `token-quota-ball.exe` | 主程序（悬浮球窗口）。免安装试用时，需与下面的后端放在同一目录后运行。日常使用由安装包启动。 |
| `token-quota-ball-api.exe` | 额度查询后端。主程序会自动拉起，不要单独双击它作为入口。必须与主程序放在同一目录。 |

普通用户只需安装上面的安装包。如果拿到的是两个独立的 exe 文件，请把它们放在同一文件夹，再运行 `token-quota-ball.exe`。

## 怎么用

- **拖动**：按住球体移动，松开后会记住位置。拖到屏幕边缘松开可贴边隐藏；鼠标移上去会暂时滑出。
- **悬停**：查看用量条和状态，移开后自动收起。
- **单击**：打开详情，可查看账户、套餐、用量、重置时间等。点击窗外或按 `Esc` 关闭。
- **右键**：打开详情、刷新、切换额度、提供方设置、贴边隐藏或退出。

## 外观

- 玻璃质感水球，带柔和光晕；球上显示提供方名称和用量文案。
- 水位表示已用比例：偏低偏青绿，升高后转为暖黄，接近用尽时偏红，过渡平滑。
- 水面有缓慢波纹，水下有细小光尘。

## 配置提供方

Cursor、WorkBuddy、Trae 不用在本工具里填写密钥，使用本机已经登录的桌面端即可。在球体上右键，选择「切换额度」即可切换。

需要手动配置的只有：

- **火山方舟 Agent Plan**：填写火山引擎 IAM 的 Access Key ID 和 Secret Access Key（不要填模型推理 API Key）。企业版还需填写席位 ID。
- **DeepSeek**：填写 API Key；可选填写参考额度，仅用于水位显示。

在球体上右键，选择「提供方设置…」。可以先点「测试」（不会写入配置），确认无误后再「保存」。密钥只保存在本机，界面以掩码显示，请不要发给别人或贴到聊天里。

安装版的配置和日志位于：

`%APPDATA%\TokenQuotaBall\`

其中 `config\` 存放设置，`logs\` 存放日志和窗口位置。

若从源码运行，配置和日志默认在项目目录下的 `config\` 和 `logs\`。

## 隐私与安全

本工具只在本机查询额度：会读取本机已登录的 Cursor、WorkBuddy、Trae 会话，或你填写的火山方舟、DeepSeek 密钥。请仅用于自己的电脑和自己的账号。详见 [SECURITY.md](SECURITY.md)。

## 开机自启（可选）

如果是从源码使用，可以运行：

```bat
scripts\install-autostart.bat
scripts\uninstall-autostart.bat
```

这两条脚本需要本机已安装 Python。

如果是用安装包安装的，可以把开始菜单里的快捷方式复制到「启动」文件夹。

## 从源码运行

面向希望自己编译，或参与开发的人。普通用户请直接下载 Releases。

1. 安装 Python 3.10+、Node.js 20+、Rust 1.77.2+。
2. 安装 Python 依赖：`pip install -r requirements.txt`
3. 启动：`scripts\run-tauri.bat`（`scripts\run.bat` 作用相同）
4. 首次启动会自动安装前端依赖，可能较慢。若已经构建过完整的发布版，该脚本会优先启动已生成的程序；否则会进入开发模式。开发模式会打开一个命令行窗口，关闭该窗口后悬浮球也会退出。
5. 要打独立安装包，运行 `scripts\build-tauri.bat`。它会打包后端并生成 NSIS 安装包，最终用户无需再安装 Python。

更多开发约定见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可证

[MIT](LICENSE)
