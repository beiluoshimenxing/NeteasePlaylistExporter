# NeteasePlaylistExporter

面向 Windows 11 的中文桌面歌单元数据导出工具。扫码登录网易云音乐，选择歌单，导出保留原始顺序的 CSV 和 JSON，为后续歌曲匹配提供准确元数据。

**版本：v0.1.0 · Python 3.11+ · PySide6 · MIT**

## 下载与启动

到 [Releases](https://github.com/beiluoshimenxing/NeteasePlaylistExporter/releases/latest) 下载 `NeteasePlaylistExporter-v0.1.0-windows-x64.zip`，完整解压后双击 `NeteasePlaylistExporter.exe`。便携包已包含 Python 与 Qt 运行时，无需另行安装 Python。请保留 `_internal` 文件夹和 `download_mapping.json`，不要只移动 exe。

也可以下载源码 ZIP：安装 Windows 64 位 Python 3.11 或以上版本（包含 Python Launcher），解压后双击 `启动程序.cmd`。脚本会创建项目虚拟环境并联网安装依赖；首次启动需要等待安装完成。

## 使用步骤

1. 无有效会话时，程序显示二维码。使用网易云音乐 App 扫码并确认。
2. 如果接口返回安全验证代码 `8821` / `8830`，点击 **官方网页登录 / 安全验证**，在打开的网易云官方网页中点击“用户登录”，自行扫码并完成必要验证。成功后程序自动接入已授权会话，无需复制 Cookie。
3. 登录后自动加载当前账号可访问的歌单；双击歌单预览。也可在输入框粘贴完整歌单链接或数字 ID，读取有权限访问的公开歌单。短链接需先在浏览器展开。
4. 选择导出文件夹，点击“导出当前歌单”，或勾选多个歌单后批量导出。
5. 点击“打开导出位置”查看结果。每个批次使用独立子目录，保留此前结果。

程序不下载、不播放音频；不包含播放器或音乐库管理功能。它是独立社区工具，与网易云音乐不存在官方关联。

## 导出内容

| 文件 | 内容 |
| --- | --- |
| `歌单名称_歌单ID.csv` | UTF-8 BOM，方便 Windows Excel 打开；全部规范字段 |
| `歌单名称_歌单ID.json` | 歌单元数据、歌曲规范字段、原始歌曲与权限字段、时间及核对报告 |
| `歌单名称_歌单ID_download.csv` | 下游匹配用 `title,artist,album,length,song_id` |
| `歌单名称_歌单ID_report.json` | 平台总数、导出数、缺失 ID 数量、缺失字段及原始位置 |
| `批次报告.json` | 每个歌单的完成状态、错误与文件路径 |

规范字段包含：`playlist_id`、`position`、`song_id`、`title`、`artists`、`primary_artist`、`album`、`album_id`、`duration_ms`、`duration_seconds`、`release_date`、`track_number`、`disc_number`、`song_url`、`cover_url`、`availability`、`exported_at`。

- 全量 CSV 的 `artists` 为 JSON 数组文本，保留多歌手边界；下载 CSV 默认用 ` / ` 连接歌手。
- `length` 单位为秒，保留毫秒精度。映射可通过程序旁的 `download_mapping.json` 调整。
- 不删除标题中的 Live、Remix 等版本信息，不按标题去重，重复歌曲保留原始位置。
- 未知值使用 JSON null / CSV 空单元格；原始返回内容仍保存在 `raw_song` 中供追溯。
- 发行日期仅使用平台返回的有效毫秒时间戳转换为 UTC 日期，不猜测缺失日期。

## 完整性与限制

程序先读取 `trackCount` 和完整 `trackIds`，按每批 50 个 ID 补齐详情，再按原 ID 序列重建曲目列表。请求串行执行，最小间隔 450ms；网络异常最多重试三次并退避，缺失详情再补查两轮。结束时重新核对歌曲 ID、总数及更新时间；歌单变化时重新获取一次快照。

缺少重点字段、ID 列表截断或快照持续变化时，文件名加 `_不完整` 并生成缺失报告，不提示全部成功。已知 ID 的下架或灰色歌曲仍保留；无法获知的 ID 不会伪造。HTTP/API 限流会停止批次后续请求，安全验证由用户在官方页面完成。

`availability` 是当前会话的权限快照，不通过音频请求验证：

| 值 | 解释 |
| --- | --- |
| `playable_for_current_session` | 权限显示当前会话可播放 |
| `requires_subscription_or_purchase` | 需要订阅或购买，取决于账号权益 |
| `unavailable_or_restricted` | 平台标为下架或受限，无法据此区分原因 |
| `restricted_for_current_session` | 当前会话受限 |
| `metadata_unavailable` | 详情未取得，保留 ID 与位置 |
| `unknown` | 无足够权限信息 |

接口是官方站点现有接口，并非承诺稳定的公开 SDK，后续可能变化。完整性只针对平台向当前账号返回的可访问快照，无法恢复平台隐藏、删除或拒绝访问的数据。

## 隐私与安全

- 会话保存在 `%LOCALAPPDATA%\NeteasePlaylistExporter\session.dpapi`，使用当前 Windows 用户的 DPAPI 加密；目录偏好在同目录的 `config.json`。
- 启动后向官方确认会话；退出登录请求官方注销并清除本地会话；切换账号先退出再登录。
- 官方网页登录使用 Qt WebEngine 内存配置（off-the-record），不在磁盘持久化浏览器 Cookie；会话通过官方检查后才导入应用并加密保存。
- 不收集密码、手机号，不要求粘贴 Cookie，不把 Cookie、Token、二维码凭证或原始响应写入日志。
- 本工具不会向 GitHub、作者或第三方代理上传账号及歌单数据。联网用途为访问网易云官方接口、官方网页及其静态资源；源码首次安装依赖时还会访问 Python 包索引。
- 你自行导出的 JSON/CSV 包含歌单名称、创建者标识等内容，分享前请自行检查。仓库和发布包不包含任何真实账号、真实歌单导出、会话文件、截图或个人验收记录。

## 开发与测试

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe main.py
```

可选真实联网复核（只访问你提供的公开歌单，不加载保存的会话）：

```powershell
.venv\Scripts\python.exe verify_live.py --id <公开歌单ID>
```

`npe/api.py` 处理请求与认证，`storage.py` 管理本地加密会话，`service.py` 解析和核对完整性，`exporter.py` 生成文件，`gui.py` 实现界面，`browser_login.py` 承载用户操作的官方网页。

```powershell
.venv\Scripts\python.exe tools/build_windows.py
```

构建输出在 `dist/`。Windows 便携包未做代码签名；可用 Release 附带的 `SHA256SUMS.txt` 校验下载完整性。Qt/PySide6 等第三方组件的许可见包内 `THIRD_PARTY_NOTICES.md` 及 `third_party_licenses/`。

## 验证范围

30 项自动测试覆盖大型歌单分批、多歌手、重复位置、顺序、缺失重试、编码、JSON、批量导出、会话失效、限流和安全验证等；测试数据均为明确标注的模拟数据。发布前另已实际验证官方网页登录、账号歌单加载、重启会话复用和真实批量导出；观察到的平台缺失字段会被明确报告。真实账号、曲目、歌单 ID 及导出文件不随发布公开。

真实私人歌单和真实会话自然失效后的重新认证尚未完成端到端验收，不将模拟测试等同于这些场景已真实通过。

## 致谢与许可

接口路径和字段参考 [NeteaseCloudMusicApiEnhanced](https://github.com/NeteaseCloudMusicApiEnhanced/api-enhanced)，本项目独立实现，不打包其服务或依赖公共代理。

项目代码采用 [MIT License](LICENSE)。请遵守平台规则，仅导出自己有权访问的元数据。歌曲和封面等内容的权利归相应权利人，项目代码许可不授予相关内容的再分发权。
