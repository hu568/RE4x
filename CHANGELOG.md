# Changelog

## v2.1.1 (2026-08-07)

### 🛠 修复

- **启动自检（.NET 环境）**: 新增 `_ensure_dotnet()`——启动时检测 .NET Framework 版本（需 4.7.2+，读取注册表 Release 值）并预加载 pythonnet（`import clr`）。此前若 .NET 组件缺失/过旧，`webview.start()` 会以晦涩的 traceback 崩溃（`Failed to resolve Python.Runtime.Loader.Initialize`）；现在会弹出明确的中文提示框（附 .NET Framework 4.8 下载指引）并记录日志，不再裸报错
- **文档**: README 补充系统要求（Win10/11 + .NET Framework 4.8 + WebView2）；RELEASE_INFO 版本号更新

## v2.1.0 (2026-08-07)

### ✨ 新功能：SPANV2 引擎与模型

- **SPANV2 引擎**: 引入子项目 RE+SPANV2（NTIRE2026）的引擎源码到 `engine-src/`——Real-ESRGAN-ncnn-vulkan 改造版（`WITH_LAYER_convolutiondepthwise` + prepadding=16），配套编译产物替换 `tools/realesrgan-ncnn-vulkan.exe`（5.9MB → 6.4MB）
- **spanv2 模型**: 新增 `tools/models/spanv2`（NTIRE2026 Efficient SR，param + bin 仅 0.5MB），GUI 模型下拉自动探测并显示 "SPANV2 (NTIRE2026)"；实测 220×220 → 440×440 放大成功
- **测试**: `test_models` 增加 spanv2 检测断言（≥3 模型）
- **文档**: README 下载指引改为「自构建 SPANV2 引擎 / 原版引擎」双方案；TOOLS.md 记录 spanv2 与引擎更新；`.gitignore` 忽略引擎 .bak 备份

### 📜 合规

- **GPL 合规记录**: `tools/ffmpeg-features.md` 记录 libx264 具体版本（MSYS2 0.165.r3222）与 zlib 外部依赖、对应源码获取途径，说明本项目代码不构成衍生作品

## v2.0.0 (2026-08-06)

### 🎨 重写 GUI：Web 版 → 桌面应用

- **pywebview 桌面壳**: 替代 Flask + 浏览器架构，原生窗口 + 系统 WebView2 渲染，双击 exe 即用（无需浏览器、无需 HTTP）
- **全新前端**: `server/ui/index.html` 重写为桌面风格（侧边导航 + 卡片布局 + 原生文件对话框），通过 `window.pywebview.api.*` 桥接 Python
- **架构重构**: 删除 `routes.py` / `main.py` / Flask 依赖，业务逻辑抽取为 `server/core.py`（`UpscaleService` + `TaskManager`），新增 `gui_api.py` 桥接层
- **本地路径直读**: 不再上传文件，直接处理本地路径，去掉 50MB 上传限制与 MIME 校验
- **模型加载竞态修复**: pywebview 的 `js_api` 异步注入，前端初始化改为监听 `pywebviewready` 事件（此前立即执行会导致模型下拉框永远为空）
- **exe 放根目录**: 打包输出到项目根目录（`sd-enhance-server.exe` + `_internal/` 与 `tools/` 平级），解压即见、双击即用；删除 `start.bat`；frozen 路径解析改为「exe 同级」（dev 模式按文件位置推导项目根，任意 cwd 启动都正确）
- **视频格式修复**: `parse_params` 曾把非 png/jpg 的 `output_format` 静默改写成 `'png'`，导致视频任务报荒谬的「Unsupported output format: png」——改为按任务类型白名单校验（图片 png/jpg，视频 mp4/avi/gif），格式不再被篡改
- **ffmpeg 9.0 兼容**: 视频提取帧改用 `-fps_mode cfr`（9.0 移除了 `-vsync`，旧参数会导致提取必然失败）
- **端到端视频测试**: 新增真实 mp4 放大测试（提取→4x→缩放→合成），此前测试无视频成功路径、两个 bug 均未被覆盖
- **视频按尺寸修复**: 视频任务此前忽略 width/height（`target_scale` 为空时静默退回 2x），现完整支持按尺寸模式——contain 等比缩放、cover 缩放后居中裁剪，均有真实视频端到端测试
- **运行日志**: 新增 `server/logutil.py`，每次启动自动写 `logs/sd-enhance.log`（每日轮转保留 7 天），记录启动信息、任务生命周期、引擎/ffmpeg 子进程命令与失败 stderr；GUI「关于」弹窗显示日志路径，dev/测试环境同样写日志
- **子进程无窗口**: 新增 `server/procutils.py`，所有 ffmpeg/引擎子进程调用统一走 `popen()`（Windows 下自动加 `CREATE_NO_WINDOW`）——修复 GUI 使用时反复弹出空命令行终端的问题（共 9 处 Popen 全覆盖）
- **ffmpeg 自构建**: 发行 ffmpeg 换为自构建白名单最小版（ffmpeg 9.0 全静态，仅本项目所需组件），`tools/ffmpeg.exe` 103M → **7.5M**；发行 zip 降至约 62MB（详见 [ffmpeg-features.md](tools/ffmpeg-features.md)）

### 📦 缩小发行包体积

- **精简 ffmpeg**: 全功能构建（295MB）→ gyan.dev essentials 精简构建（约 105MB）
- **模型精简**: 移除 `realesr-animevideov3` 系列（3.7MB），发行包仅保留 `realesrgan-x4plus` + `realesrgan-x4plus-anime`
- **移除调试运行库**: 删除 `vcomp140d.dll`
- **打包瘦身**: 移除 Flask/Werkzeug/cryptography 依赖，`build.spec` 改用 `collect_all('pywebview')` + `console=False`
- **默认模型调整**: `realesr-animevideov3` → `realesrgan-x4plus-anime`

### ✅ 测试

- `test_routes.py`（Flask API 测试）重写为 `test_core.py`（`UpscaleService` 测试：参数校验/单图管线/批量/目录/视频/zip），覆盖保持

### 📝 文档

- README / AGENTS.md 全面更新为新架构；修正 AGENTS.md 中"二进制已追踪"的过时描述

## v1.0.1 (2026-08-05)

### 🔒 安全加固

- **修复路径穿越漏洞**: `/api/results/<task_id>/...` 端点增加严格 task-id 格式校验（8 位十六进制）与 `os.path.commonpath` 目录边界检查，杜绝通过编码分隔符读取任意文件 (#380b6e6)
- **上传文件名清洗**: 保存上传文件前对文件名做 `basename` 处理，路径分隔符/穿越组件不再进入保存路径 (#380b6e6)
- **前端自 XSS 防护**: Web UI 中文件名、错误消息等用户可控内容插入 DOM 前统一转义 (#380b6e6)

### 🛠 修复

- **GPU 并发锁**: 视频帧批量放大期间全局锁覆盖整个引擎执行期，避免与单张请求并发抢占 GPU (#380b6e6)
- **参数校验**: 所有端点的 `scale`（0.1–8）与 `mix_ratio`（0–1）统一校验，拒绝非法/NaN/越界值返回 400 而非 500 (#380b6e6)
- **文档修正**: `/api/upscale/dir` 说明如实声明按设计可处理任意本地目录，避免误导 (#380b6e6)

### ✅ 测试

- 新增路径穿越、参数校验、NaN 拒绝等 10 个回归测试，完整套件 56 项全部通过 (#380b6e6)

## v1.0.0 (2026-06-27)

### ✨ 新功能

- **Flask 后端服务**: 实现完整的放大 API 路由、任务管理、统一放大管线 (#7db779c)
- **Web UI**: 基于真实 API 驱动的四标签页界面 — 单张/批量/目录/视频处理 (#7752e81)
- **统一放大管线**: 模型固定 4x → ffmpeg Lanczos 缩放到目标，支持 1x-8x 及精确尺寸 (#7db779c)
- **视频处理**: 提取帧 → 逐帧 AI 放大 → ffmpeg 合成（保留原音频）(#7db779c)
- **双级放大器混合**: 通过 ffmpeg blend 滤镜混合两个模型的放大结果 (#7752e81)
- **自动模型探测**: 扫描 `tools/models/*.param` 动态加载可用模型 (#6f862ec)
- **一键启动脚本**: `start.bat` 自动检测开发/生产模式并打开浏览器 (#46f449f)
- **PyInstaller 打包**: `build.spec` 配置，支持构建独立 exe 分发 (#664c5bc)
- **图片缩放/裁剪**: 统一管线第二步，支持 cover（裁剪）和 contain（适应）模式 (#664c5bc)

### 🛠 工程化

- **测试套件**: pytest 集成测试覆盖 engine/mixer/routes/resizer (#46f449f)
- **打包脚本**: `package_release.py` 自动构建并打包发行 zip (#664c5bc)
- **GPU 并发锁**: `threading.Lock` 确保同一时间只有一个引擎进程运行 (#7db779c)
- **路径感知**: 开发模式（python main.py）和生产模式（PyInstaller exe）自动切换路径 (#6f862ec)

### 🐛 修复

- **start.bat 编码**: 修复 GBK 编码兼容性和 CMD 语法（goto labels 替代 else if）(#4be8a1d)

### 📦 依赖

- Real-ESRGAN ncnn Vulkan — AI 图片放大引擎（需自行下载）
- FFmpeg — 视频处理、图片缩放/裁剪/混合（需自行下载）
