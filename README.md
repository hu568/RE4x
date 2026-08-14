# RE4x SD Enhance

便携式 AI 图片/视频放大工具包 —— **桌面应用版 v2.0**。

无需 CUDA、无需 PyTorch、无需浏览器，双击即用。基于 pywebview（系统 WebView2）渲染的桌面 GUI，本地文件直接处理，不上传、不联网。

## 功能

- **图片放大**：基于 Real-ESRGAN ncnn Vulkan 引擎 + ffmpeg 两步管线（模型固定 4x → 缩放到目标），支持 1–8x 比例或精确目标尺寸
- **双模型混合**：两个模型的结果按比例 blend，兼顾清晰度与观感
- **批量处理**：单张、多文件、整个目录
- **视频放大**：提取帧 → AI 放大 → 合成视频（保留原音频，支持 MP4/MOV/GIF 输出）
- **桌面 GUI**：原生窗口 + 文件选择对话框，结果一键打开 / 另存为
- **运行日志**：每次使用自动写入 `logs/sd-enhance.log`（保留 7 天），「关于」弹窗可查看日志路径，出问题贴日志即可排查

## 快速开始

### 1. 下载依赖文件

本仓库仅包含源码。运行前需下载以下文件放入 `tools/` 目录：

#### Real-ESRGAN 引擎 + 模型

**方案 A（推荐，支持 spanv2）**：按 [engine-src/README.md](engine-src/README.md) 自构建 SPANV2 版引擎（Real-ESRGAN-ncnn-vulkan 改造，启用 depthwise + prepadding=16），编译出的 `realesrgan-ncnn-vulkan.exe` 放入 `tools/`。

**方案 B（原版）**：从 [Real-ESRGAN Releases](https://github.com/xinntao/Real-ESRGAN/releases) 下载最新 Windows 包，解压后复制（不含 spanv2 支持）：

```
tools/
├── realesrgan-ncnn-vulkan.exe    # 引擎主程序
├── vcomp140.dll                   # VC++ 运行库
└── models/                        # 模型文件（自动探测）
    ├── realesrgan-x4plus.bin
    ├── realesrgan-x4plus.param
    ├── realesrgan-x4plus-anime.bin
    ├── realesrgan-x4plus-anime.param
    ├── spanv2.bin                 # 可选：需 SPANV2 版引擎
    └── spanv2.param
```

> 模型自动探测：`tools/models/` 下任意 `.param` 文件都会出现在 GUI 的下拉框中，可自行增删。

#### FFmpeg（自构建最小版，约 7.5 MB）

推荐按 [ffmpeg-features.md](tools/ffmpeg-features.md) 自构建：ffmpeg 9.0 白名单 + 全静态，仅含本项目所需组件（ffprobe 不需要，程序会自动回退）。备选：从 [gyan.dev FFmpeg Builds](https://www.gyan.dev/ffmpeg/builds/) 下载 `ffmpeg-release-essentials.zip`，解压后复制 **bin\ffmpeg.exe**（约 103 MB）：

```
tools/
└── ffmpeg.exe
```

### 2. 启动

直接双击 **`sd-enhance-server.exe`**（位于程序根目录，与 `tools/` 平级）即可。

> **系统要求**：Windows 10/11（自带 WebView2 运行时 + .NET Framework 4.8）。
> 启动时自动检测 .NET Framework（需 4.7.2+）；pythonnet 加载失败会自动重试，netfx 失败自动回退 coreclr，确属缺失才弹窗提示安装指引。

## 可用模型

| 模型 | 适用场景 | 倍率 |
|------|---------|------|
| `realesrgan-x4plus-anime` | 动漫图片（默认推荐）| 4x |
| `realesrgan-x4plus` | 通用图片 | 4x |
| `spanv2` | 高效细节增强（NTIRE2026 Efficient SR，仅 0.5MB）| 4x |

> 统一管线：引擎固定跑 4x，再由 ffmpeg 缩放到用户目标（1–8x），任意倍率都能精确输出。
> `spanv2` 需配套 SPANV2 版引擎（见 [TOOLS.md](tools/TOOLS.md)）；引擎源码在 `engine-src/`。

## 开发

```bash
cd server
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python app.py        # 启动桌面 GUI（开发模式）

# 运行测试（真实引擎 + ffmpeg，无 mock）
.venv\Scripts\python -m pytest tests/ -v
```

> 从任何目录运行 `python server/app.py` 都能正确定位 `tools/`（dev 模式按文件位置推导项目根）。

## 构建

```bash
cd server
.venv\Scripts\pyinstaller build.spec --distpath .. --workpath ..\tools\build --clean
# 输出: 项目根目录的 sd-enhance-server.exe + _internal/

# 打包发行 zip（自动构建 + 收集 tools/ 全部运行时）
python package_release.py 2.0.0
```

## 目录结构

```
RE4x/
├── sd-enhance-server.exe       # 桌面应用（根目录，双击即用）
├── _internal/                  # PyInstaller 运行时数据（勿动）
├── tools/                      # 运行时（需自行下载，见上）
│   ├── realesrgan-ncnn-vulkan.exe
│   ├── ffmpeg.exe                 # 自构建最小版（约 7.5M，无需 ffprobe，见 tools/ffmpeg-features.md）
│   ├── vcomp140.dll
│   ├── models/                  # 模型 .param + .bin
├── server/                      # Python 源码
│   ├── app.py                   # pywebview 桌面入口
│   ├── core.py                  # 核心服务（管线/任务，无 Flask）
│   ├── gui_api.py               # JS↔Python 桥接（js_api）
│   ├── engine.py / mixer.py / resizer.py / models.py
│   ├── ui/index.html            # 桌面界面（单 HTML）
│   └── tests/                   # pytest 测试套件
└── package_release.py           # 发行包打包脚本
```

## 许可

本项目源码基于 **GNU General Public License v3.0 (GPL-3.0)** 开源。详见 [LICENSE](LICENSE) 文件。

Real-ESRGAN（BSD-3-Clause）、FFmpeg（LGPL/GPL）、pywebview（BSD）等第三方组件遵循各自许可协议。
