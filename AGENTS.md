# RE4x — SD Enhance 图片后期处理工具链

## 项目性质

这是一个 **便携式图片/视频放大工具包（桌面应用版 v2.0）**。无需安装、无需 CUDA/PyTorch、无需浏览器，双击 exe 即用。GUI 基于 **pywebview**（系统 WebView2 渲染 HTML 界面 + Python 桥接），不再使用 Flask/HTTP。

> **注意**：Git 仓库仅包含 Python 源码。大型二进制文件（引擎、ffmpeg、模型）**不被 git 追踪**（见 `.gitignore`），需自行下载，详见 [README.md](README.md)。

## 目录结构

```
RE4x/
├── sd-enhance-server.exe           # 桌面应用（根目录，双击即用，PyInstaller onedir）
├── _internal/                       # PyInstaller 运行时数据（勿动）
├── tools/                       # 可执行工具（gitignored，需下载）
│   ├── realesrgan-ncnn-vulkan.exe   # AI 图片放大引擎
│   ├── ffmpeg.exe                    # 视频处理（精简版 essentials 构建，无需 ffprobe）
│   ├── vcomp140.dll                  # VC++ 运行库
│   └── models/                      # ESRGAN 模型（.param + .bin）
├── server/                      # Python 源码（git 追踪）
│   ├── app.py                   # pywebview 桌面入口
│   ├── core.py                  # 核心服务：TaskManager + 统一管线 + 单图/批量/目录/视频（无 Flask）
│   ├── gui_api.py               # js_api 桥接：文件对话框、任务提交、结果操作
│   ├── engine.py                # realesrgan-ncnn-vulkan.exe 封装
│   ├── mixer.py                 # 双级放大器混合（ffmpeg blend）
│   ├── resizer.py               # ffmpeg 缩放/裁剪（统一管线第二步）
│   ├── models.py                # 模型自动探测
│   ├── ui/index.html            # 桌面界面（单 HTML，pywebview 渲染）
│   ├── tests/                   # pytest 测试套件（真实引擎，无 mock）
│   ├── requirements*.txt        # Python 依赖（pywebview + pillow）
│   └── build.spec               # PyInstaller 构建配置（collect_all pywebview）
├── test-data/                   # 测试素材
├── package_release.py           # 发行包打包脚本（构建到根目录 + 打 zip）
├── README.md                    # 面向用户的说明
└── AGENTS.md                    # 本文件（开发文档）
```

## 快速启动

```bash
# 方式一：双击根目录 sd-enhance-server.exe（生产模式）
# 直接打开桌面窗口（无需浏览器、无需 start.bat）

# 方式二：开发模式
cd server
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python app.py     # 打开桌面 GUI

# 方式三：打包构建（输出到项目根目录）
cd server
.venv\Scripts\pyinstaller build.spec --distpath .. --workpath ..\tools\build --clean
# 输出: 根目录 sd-enhance-server.exe + _internal/
```

## 核心命令（引擎原始 CLI）

### 单张图片放大

```bash
# 默认模型（realesrgan-x4plus-anime，4x 放大）
tools/realesrgan-ncnn-vulkan.exe -i test-data/input.jpg -o output.png

# 指定模型和放大倍数
tools/realesrgan-ncnn-vulkan.exe -i input.jpg -o output.png -n realesrgan-x4plus -s 4

# 批量处理目录
tools/realesrgan-ncnn-vulkan.exe -i input_folder -o output_folder -n realesrgan-x4plus-anime -s 4 -f jpg
```

### 动漫视频放大（三步走）

```bash
# 1. 提取帧（先创建 tmp_frames/）
ffmpeg -i onepiece_demo.mp4 -qscale:v 1 -fps_mode cfr -r 23.98 tmp_frames/frame%08d.jpg

# 2. 放大每一帧（先创建 out_frames/）
./realesrgan-ncnn-vulkan.exe -i tmp_frames -o out_frames -n realesrgan-x4plus-anime -s 4 -f jpg

# 3. 合成视频（保留原音频）
ffmpeg -i out_frames/frame%08d.jpg -i onepiece_demo.mp4 -map 0:v:0 -map 1:a:0 -c:a copy -c:v libx264 -r 23.98 -pix_fmt yuv420p output_w_audio.mp4
```

## 可用模型

| 模型 | 适用场景 |
|------|---------|
| `realesrgan-x4plus-anime`（默认） | 动漫图片（推荐） |
| `realesrgan-x4plus` | 通用图片 |

> 所有模型固定 4x 输出。GUI 模型下拉框**自动检测** `tools/models/` 目录中的 .param 文件，支持用户自行添加新模型（v2.0 起 animevideov3 已从发行包移除，可自行放回）。

## 桌面 GUI（`server/ui/index.html`）

- 单 HTML + 原生 CSS/JS，**pywebview js_api 桥接**（无 HTTP、无 Flask）
- **4 个功能页**：单张图片、批量处理、目录批量、视频处理
- 放大设置：按比例（1-8x 滑条）或按目标尺寸，可选裁剪
- 可选第二模型混合（ffmpeg blend，mix_ratio 滑条）
- 结果画廊：打开 / 所在文件夹 / 另存为
- 模型下拉框动态从 `api.get_models()` 加载

## 架构要点

### 统一放大管线

**核心设计**：所有放大请求统一走两步管线，无论目标倍率多少。

```
输入图片 → 模型固定 4x 放大 → ffmpeg 缩放到目标 → 输出
```

| 用户选择 | 模型输出 | ffmpeg 缩放 | 最终 |
|---------|---------|------------|------|
| scale=2 | 4x | ×0.5 | 2x |
| scale=4 | 4x | ×1.0 | 4x |
| scale=6 | 4x | ×1.5 | 6x |
| 尺寸 800×600 | 4x | 缩放到 800×600 | 精确尺寸 |

> 模型（`realesrgan-ncnn-vulkan.exe`）固定 4x 输出，由 ffmpeg lanczos 缩放到目标，避免直接传 >4 的 scale 给引擎导致失败。

### 整体架构

```
pywebview 窗口 (server/ui/index.html)
        │  js_api 桥接（window.pywebview.api.*）
        ▼
GuiApi (server/gui_api.py) ──► UpscaleService (server/core.py)
                                      │
                          ┌───────────┼──────────────┐
                          ▼           ▼              ▼
                realesrgan-ncnn-   ffmpeg         TaskManager
                vulkan.exe          (resize/blend)  (后台线程任务)
                (模型 4x 放大)       (缩放/混合)
```

### 分层

1. **前端层**（`server/ui/index.html`）：单 HTML 文件，通过 `window.pywebview.api.*` 调用 Python（异步 Promise）
2. **桥接层**（`server/gui_api.py`）：pywebview js_api，文件对话框（`create_file_dialog`）、参数透传、任务提交、结果操作（`os.startfile` 打开/另存为/打包 zip）
3. **服务层**（`server/core.py`）：`UpscaleService` —— 参数校验（`parse_params`）、统一管线（`_run_upscale_pipeline`）、单图/多文件/目录/视频任务（后台线程 + `TaskManager` 轮询）
4. **引擎层**（`server/engine.py`）：封装 `realesrgan-ncnn-vulkan.exe` 子进程调用（全局 GPU 锁）
5. **缩放层**（`server/resizer.py`）：封装 `ffmpeg scale/crop` 滤镜
6. **混合层**（`server/mixer.py`）：利用 `ffmpeg blend` 滤镜实现双级放大器混合
7. **模型层**（`server/models.py`）：自动扫描 `tools/models/` 检测可用模型

### js_api 桥接方法（`window.pywebview.api.*`）

| 方法 | 说明 |
|------|------|
| `select_files(multiple)` / `select_video()` / `select_dir()` / `save_path(name)` | 原生文件对话框 |
| `get_models()` | 可用模型列表 |
| `image_preview(path)` | base64 预览（<512KB） |
| `submit_single(path, params)` / `submit_files(paths, params)` | 提交单图/多文件任务 → task_id |
| `submit_dir(input_dir, output_dir, params)` / `submit_video(path, params)` | 目录/视频任务 → task_id |
| `get_task(task_id)` | 轮询任务状态（status/progress/results/error） |
| `open_path(path)` / `open_folder(path)` | 系统打开文件/文件夹 |
| `copy_to(src, dest_dir)` / `zip_results(task_id, dest_zip)` | 另存为 / 打包 zip |

### 关键设计

- **引擎**（`realesrgan-ncnn-vulkan.exe`）：基于 [Tencent/ncnn](https://github.com/Tencent/ncnn) 和 [realsr-ncnn-vulkan](https://github.com/nihui/realsr-ncnn-vulkan)，纯 CPU/Vulkan 推理
- **分块处理**：引擎将图片切成多个 tile 分别处理再拼接，可能引入块间不一致
- **统一管线**：`_run_upscale_pipeline()` — 模型固定 4x → ffmpeg resize_by_scale(target/4)，适用于任意目标倍率
- **尺寸模式**：`_compute_dimension_upscale()` — 根据目标尺寸和裁剪选项计算有效倍率，支持 cover（裁剪）和 contain（适应）
- **视频处理**：提取帧 → 逐帧走统一管线 → ffprobe 检测 FPS → ffmpeg 合成（保留原音频），支持 mp4/avi/gif 输出
- **双级混合**：用 ffmpeg 的 `blend` 滤镜混合两个不同模型的放大结果
- **GPU 并发控制**：`threading.Lock` 确保一次只有一个引擎进程运行
- **路径感知**：开发模式（python app.py）和生产模式（PyInstaller exe）自动切换路径；frozen 时 exe 位于项目根目录（与 `tools/` 同级），dev 模式按 `app.py` 文件位置推导项目根（任何 cwd 都正确）
- **模型自动发现**：`get_available_models()` 扫描 `tools/models/*.param`，提取基名去重
- **任务模型**：所有处理（含单图）走 `TaskManager` 后台线程 + `task_id`，前端 500ms 轮询 `get_task`
- **无网络依赖**：GUI 本地处理文件路径，不上传、不校验 MIME（本地信任）；大小限制（50MB）仅保留在历史 Web 版，v2 无限制

## 开发指南

```bash
# 设置开发环境
python -m venv server\.venv
server\.venv\Scripts\pip install -r server\requirements-dev.txt

# 运行开发服务器（桌面窗口）
server\.venv\Scripts\python server\app.py

# 运行测试（真实引擎 + ffmpeg，无 mock）
server\.venv\Scripts\python -m pytest server\tests\ -v

# 打包构建
server\.venv\Scripts\pyinstaller server\build.spec --distpath . --workpath tools\build --clean
# 输出: 根目录 sd-enhance-server.exe + _internal/
# 然后 python package_release.py 2.0.0 打发行 zip
```

## 体积优化记录（v2.0）

| 项 | 大小 | 处理 |
|----|------|------|
| ffmpeg.exe + ffprobe.exe | 295M → **103M** | 全功能构建 → gyan.dev essentials 精简构建；ffprobe 完全删除（FPS 检测自动回退 ffmpeg -i） |
| models | 45M → 42M | 移除 animevideov3 系列（3.7M），保留 x4plus + x4plus-anime |
| vcomp140d.dll | 0.2M | 删除（调试版运行库） |
| sd-enhance-server | 45M → ~30M | 移除 Flask/Werkzeug/cryptography，改 pywebview |
| **tools/ 合计** | **390M → 190M** | |

## Git 状态

- 仓库已初始化，`.gitignore` 配置：排除 Python 缓存、venv、PyInstaller 产物、**全部 tools/ 二进制**、TMP/、release/
- **无远程仓库配置**
- 二进制文件需按 [README.md](README.md) 手动下载（AGENTS.md 旧版"二进制已追踪"描述已过时，已修正）
