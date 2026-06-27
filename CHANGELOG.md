# Changelog

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
