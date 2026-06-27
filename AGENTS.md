# RE4x — SD Enhance 图片后期处理工具链

## 项目性质

这是一个 **便携式图片/视频放大工具包**，非标准代码项目。无需安装、无需 CUDA/PyTorch，开箱即用。

> **注意**：Git 仓库仅包含 Python 源码。大型二进制文件（模型、引擎、ffmpeg）需自行下载，详见 [README.md](README.md)。

## 目录结构

```
RE4x/
├── tools/                       # 可执行工具（gitignored，需下载）
│   ├── realesrgan-ncnn-vulkan.exe   # AI 图片放大引擎
│   ├── ffmpeg.exe / ffprobe.exe     # 视频处理
│   ├── vcomp140.dll / vcomp140d.dll # VC++ 运行库
│   ├── sd-enhance-server/           # PyInstaller 打包的后端
│   └── models/                      # ESRGAN 模型（.param + .bin）
├── server/                      # Python Flask 后端源码（git 追踪）
│   ├── main.py                  # Flask 应用入口
│   ├── engine.py                # realesrgan-ncnn-vulkan.exe 封装
│   ├── mixer.py                 # 双级放大器混合（ffmpeg blend）
│   ├── resizer.py               # ffmpeg 缩放/裁剪（统一管线第二步）
│   ├── models.py                # 模型自动探测
│   ├── routes.py                # API 路由 + 统一放大管线
│   ├── templates/               # Web UI
│   ├── tests/                   # pytest 测试套件
│   ├── requirements*.txt        # Python 依赖
│   └── build.spec               # PyInstaller 构建配置
├── test-data/                   # 测试素材
├── start.bat                    # 一键启动脚本
├── README.md                    # 面向用户的说明
└── AGENTS.md                    # 本文件（开发文档）
```

## 快速启动

```bash
# 方式一：双击 start.bat（生产模式）
# 自动检测打包版 exe 或 dev 环境，启动服务并打开浏览器

# 方式二：开发模式
cd server
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python main.py
# 然后访问 http://localhost:5000

# 方式三：打包构建
cd server
.venv\Scripts\pyinstaller build.spec
# 输出到 tools/sd-enhance-server/
```

## 核心命令（引擎原始 CLI）

### 单张图片放大

```bash
# 默认模型（realesr-animevideov3，2x 放大）
tools/realesrgan-ncnn-vulkan.exe -i test-data/input.jpg -o output.png

# 指定模型和放大倍数
tools/realesrgan-ncnn-vulkan.exe -i input.jpg -o output.png -n realesrgan-x4plus -s 4

# 批量处理目录
tools/realesrgan-ncnn-vulkan.exe -i input_folder -o output_folder -n realesr-animevideov3 -s 2 -f jpg
```

### 动漫视频放大（三步走）

```bash
# 1. 提取帧（先创建 tmp_frames/）
ffmpeg -i onepiece_demo.mp4 -qscale:v 1 -qmin 1 -qmax 1 -vsync 0 tmp_frames/frame%08d.jpg

# 2. 放大每一帧（先创建 out_frames/）
./realesrgan-ncnn-vulkan.exe -i tmp_frames -o out_frames -n realesr-animevideov3 -s 2 -f jpg

# 3. 合成视频（保留原音频）
ffmpeg -i out_frames/frame%08d.jpg -i onepiece_demo.mp4 -map 0:v:0 -map 1:a:0 -c:a copy -c:v libx264 -r 23.98 -pix_fmt yuv420p output_w_audio.mp4
```

## 可用模型

| 模型 | 适用场景 |
|------|---------|
| `realesr-animevideov3`（默认） | 动漫视频（推荐，2x/3x/4x） |
| `realesrgan-x4plus` | 通用图片（4x） |
| `realesrgan-x4plus-anime` | 动漫图片（4x） |

> 所有模型最大 4x 放大。Web UI 中的模型下拉框**自动检测** `tools/models/` 目录中的 .param 文件，支持用户自行添加新模型。

## SD Enhance Web UI（`server/templates/index.html`）

- UI 基于原本的 HTML 参考设计，**真实 API 驱动**
- **4 个页面标签页**：单张图片、批量处理、目录批量、视频处理
- 放大设置（折叠面板）：
  - 按比例（1-8x）或按目标尺寸
  - 可选裁剪到目标尺寸
  - 单个放大器选择
- 结果画廊 + 灯箱预览
- 模型下拉框动态从 `/api/models` 实时加载

## 前端 UI

- ``server/templates/index.html`` 为真实前端实现，通过后端 API 调用引擎
- 历史上用过静态 HTML mock 作为 UI 设计参考，现已删除

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

> 模型（`realesrgan-ncnn-vulkan.exe`）最大只能 4x，统一先用模型跑 4x 发挥 AI 放大能力，再用 ffmpeg lanczos 缩放到目标。避免直接传 >4 的 scale 给引擎导致失败。

### 整体架构

```
浏览器 (Web UI) ──HTTP──> Flask 后端 (server/)
                               │
                    ┌──────────┼──────────────┐
                    ▼          ▼              ▼
          realesrgan-ncnn-   ffmpeg         Task Manager
          vulkan.exe          (resize/blend)  (单 GPU 锁)
          (模型 4x 放大)       (缩放/混合)
```

### 分层

1. **前端层**（`server/templates/index.html`）：单 HTML 文件，通过 `fetch()` 调用后端 API
2. **API 层**（`server/routes.py`）：Flask Blueprint，处理上传、参数校验、任务调度、统一放大管线
3. **引擎层**（`server/engine.py`）：封装 `realesrgan-ncnn-vulkan.exe` 子进程调用
4. **缩放层**（`server/resizer.py`）：封装 `ffmpeg scale/crop` 滤镜，实现管线第二步
5. **混合层**（`server/mixer.py`）：利用 `ffmpeg blend` 滤镜实现双级放大器混合
6. **模型层**（`server/models.py`）：自动扫描 `tools/models/` 检测可用模型

### API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 前端页面 |
| `/api/models` | GET | 获取可用模型列表 |
| `/api/upscale` | POST | 单张图片上传 + 处理（同步返回，统一管线） |
| `/api/upscale/batch` | POST | 批量上传 + 处理（异步，返回 task_id） |
| `/api/upscale/dir` | POST | 按目录路径批量处理（异步，返回 task_id） |
| `/api/upscale/video` | POST | 视频上传 + 逐帧放大合成（异步，返回 task_id） |
| `/api/status/<id>` | GET | 查询异步任务状态和结果 |
| `/api/results/<id>/<filename>` | GET | 获取异步任务的结果文件 |

### 关键设计

- **引擎**（`realesrgan-ncnn-vulkan.exe`）：基于 [Tencent/ncnn](https://github.com/Tencent/ncnn) 和 [realsr-ncnn-vulkan](https://github.com/nihui/realsr-ncnn-vulkan)，纯 CPU/Vulkan 推理
- **分块处理**：引擎将图片切成多个 tile 分别处理再拼接，可能引入块间不一致
- **统一管线**：`_run_upscale_pipeline()` — 模型固定 4x → ffmpeg resize_by_scale(target/4)，适用于任意目标倍率
- **尺寸模式**：`_compute_dimension_upscale()` — 根据目标尺寸和裁剪选项计算有效倍率，支持 cover（裁剪）和 contain（适应）
- **视频处理**：提取帧 → 逐帧走统一管线 → ffprobe 检测 FPS → ffmpeg 合成（保留原音频），支持 mp4/avi/gif 输出
- **双级混合**（可选，API 支持）：用 ffmpeg 的 `blend` 滤镜混合两个不同模型的放大结果
- **GPU 并发控制**：`threading.Lock` 确保一次只有一个引擎进程运行
- **路径感知**：开发模式（python main.py）和生产模式（PyInstaller exe）自动切换路径
- **模型自动发现**：`get_available_models()` 扫描 `tools/models/*.param`，提取基名去重
- 引擎、模型、运行库全部打包在 `tools/` 下，**全部可执行文件均已提交到 git**

## 开发指南

```bash
# 设置开发环境
python -m venv server\.venv
server\.venv\Scripts\pip install -r server\requirements-dev.txt

# 运行开发服务器
server\.venv\Scripts\python server\main.py

# 运行测试
server\.venv\Scripts\python -m pytest server\tests\ -v

# 打包构建
server\.venv\Scripts\pyinstaller server\build.spec
# 输出: tools/sd-enhance-server/sd-enhance-server/
# 手动将 exe 和 _internal/ 移到 tools/sd-enhance-server/ 根目录
```

## Git 状态

- 仓库已初始化
- `.gitignore` 已配置：排除 Python 缓存、PyInstaller 构建产物、虚拟环境
- 所有二进制文件（引擎、ffmpeg、VC++ 运行库、模型）已追踪
- 无远程仓库配置

## 计划参考

当前开发工作依据 `.sisyphus/plans/sd-enhance-tool.md` 执行，包含：

- **10 个开发任务**，分 4 个波次并行执行
- **4 路最终验证**：Oracle 合规审计 + Code Review + 手动 QA + 范围检查
- **6 次原子提交**，清晰的文件分组
- **每个任务包含**：具体实现说明、验收标准、QA 场景（curl/Python 命令）
- **安全防护**：文件类型校验、大小限制（50MB）、路径穿越防护、GPU 并发锁
