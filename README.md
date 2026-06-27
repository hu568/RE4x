# RE4x SD Enhance

便携式 AI 图片/视频放大工具包。无需 CUDA、无需 PyTorch，开箱即用。

## 功能

- **图片放大**：基于 Real-ESRGAN ncnn Vulkan 引擎，支持 2x/3x/4x 放大
- **视频放大**：提取帧 → AI 放大 → 合成视频（保留原音频）
- **批量处理**：单张、多张、整个目录、视频文件
- **Web 界面**：浏览器访问 `http://localhost:5000`，拖拽上传即可

## 快速开始

### 1. 下载依赖文件

本仓库仅包含源码。运行前需下载以下文件放入 `tools/` 目录：

#### Real-ESRGAN 引擎 + 模型

从 [Real-ESRGAN Releases](https://github.com/xinntao/Real-ESRGAN/releases) 下载最新 Windows 包，解压后复制：

```
tools/
├── realesrgan-ncnn-vulkan.exe    # 引擎主程序
├── vcomp140.dll                   # VC++ 运行库
├── vcomp140d.dll                  # VC++ 调试运行库
└── models/                        # 模型文件
    ├── realesr-animevideov3-x2.bin
    ├── realesr-animevideov3-x2.param
    ├── realesr-animevideov3-x3.bin
    ├── realesr-animevideov3-x3.param
    ├── realesr-animevideov3-x4.bin
    ├── realesr-animevideov3-x4.param
    ├── realesrgan-x4plus.bin
    ├── realesrgan-x4plus.param
    ├── realesrgan-x4plus-anime.bin
    └── realesrgan-x4plus-anime.param
```

#### FFmpeg

从 [gyan.dev FFmpeg Builds](https://www.gyan.dev/ffmpeg/builds/) 下载 `ffmpeg-release-essentials.zip`，解压后复制：

```
tools/
├── ffmpeg.exe
└── ffprobe.exe
```

### 2. 启动服务

```
双击 start.bat
```

浏览器自动打开 `http://localhost:5000`。

## 可用模型

| 模型 | 适用场景 | 倍率 |
|------|---------|------|
| `realesr-animevideov3` | 动漫视频（推荐）| 2x / 3x / 4x |
| `realesrgan-x4plus` | 通用图片 | 4x |
| `realesrgan-x4plus-anime` | 动漫图片 | 4x |

## 开发

```bash
cd server
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python main.py

# 运行测试
.venv\Scripts\python -m pytest tests/ -v
```

## 构建

```bash
cd server
.venv\Scripts\pip install pyinstaller
.venv\Scripts\pyinstaller build.spec
# 输出: dist/sd-enhance-server/
```

## 许可

本项目源码基于 **GNU General Public License v3.0 (GPL-3.0)** 开源。详见 [LICENSE](LICENSE) 文件。

Real-ESRGAN（BSD-3-Clause）、FFmpeg（LGPL/GPL）等第三方组件遵循各自许可协议。
