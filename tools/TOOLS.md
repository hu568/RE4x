# TOOLS.md — tools/ 工具目录说明

本目录包含 RE4x（SD Enhance）便携工具包的全部可执行工具与模型。
**无需安装、无需 CUDA/PyTorch**，GUI 通过 Python 子进程调用这些二进制完成放大管线。

## 1. 目录内容总览

| 文件/目录 | 体积 | 用途 |
|-----------|------|------|
| `realesrgan-ncnn-vulkan.exe` | 5.9 MB | AI 图片放大引擎（CPU/Vulkan 推理） |
| `ffmpeg.exe` | 7.5 MB | 视频处理 + 图片缩放/裁剪/混合（自构建最小版，见下文） |
| `vcomp140.dll` | 178 KB | VC++ 运行库（引擎依赖，需与 exe 同目录） |
| `models/` | 41 MB | ESRGAN 模型（`.param` + `.bin`），GUI 自动探测 |
| `ffmpeg-src/` | — | ffmpeg 自构建源码（非发行内容，可删） |
| `ffmpeg.exe.bak` | 103 MB | 替换前的旧版 ffmpeg（非发行内容，可删） |

发行载荷合计约 **55 MB**。

## 2. AI 放大引擎 `realesrgan-ncnn-vulkan.exe`

基于 [Tencent/ncnn](https://github.com/Tencent/ncnn) 与
[realsr-ncnn-vulkan](https://github.com/nihui/realsr-ncnn-vulkan) 的便携可执行文件，
已内置全部运行库与模型，无需 CUDA 或 PyTorch 环境。

### 可用模型

| 模型 | 适用场景 | 输出倍率 |
|------|---------|---------|
| `realesrgan-x4plus-anime`（默认） | 动漫图片（推荐） | 固定 4x |
| `realesrgan-x4plus` | 通用图片 | 固定 4x |

> v2.0 起 `animevideov3` 系列已从发行包移除，如需可自行放入 `models/`。

### 原始 CLI 命令

```bash
# 单张图片放大（默认模型 x4plus-anime，4x）
realesrgan-ncnn-vulkan.exe -i input.jpg -o output.png

# 指定模型
realesrgan-ncnn-vulkan.exe -i input.jpg -o output.png -n realesrgan-x4plus

# 批量处理目录（-f 指定输出格式）
realesrgan-ncnn-vulkan.exe -i input_folder -o output_folder \
  -n realesrgan-x4plus-anime -s 4 -f jpg
```

> **注意**：所有模型固定输出 4x。GUI 采用统一两步管线 ——
> 引擎 4x 放大 → ffmpeg 缩放到目标（1–8x 或精确尺寸），
> 因此不要直接向引擎传大于 4 的 `-s` 值。

### 分块处理说明

引擎先把图片切成多个 tile 分别推理再拼接，可能引入块间轻微不一致，
且结果与 PyTorch 版实现略有差异 —— 属正常现象。

### 模型自动探测

GUI 下拉框动态扫描 `models/` 目录中所有 `.param` 文件并提取基名去重。
自行添加新模型 = 把 `.param` + `.bin` 放入 `models/` 即可。

## 3. 视频处理 `ffmpeg.exe`（自构建最小版）

**ffmpeg 9.0**，白名单 + `--enable-small` 全静态编译，仅依赖 Windows 系统库
（KERNEL32 / api-ms-win-crt-* / bcrypt），**无需 ffprobe**（程序自动回退解析）。

### 功能白名单

- **demuxer**：`image2`（图片/帧序列）、`mov`（mp4/mov）、`matroska`（mkv/webm）、`avi`
- **decoder**：`mjpeg, png, bmp, webp, tiff`（图片）+ `h264, hevc, mpeg4, vp8, vp9`（视频）
- **muxer**：`image2`、`mp4`、`gif`
- **encoder**：`libx264`（mp4，GPL）、`mjpeg`（jpg）、`png`、`gif`
- **filter**：`scale, crop, blend, pad, split, fps, palettegen, paletteuse`
- **parser**：`h264, hevc, mpeg4, vp8, vp9, aac, mp3`（音频流拷贝）

### 项目内用途

| 模块 | 用途 |
|------|------|
| `server/resizer.py` | 图片缩放 `scale`（lanczos）、居中裁剪 `crop` |
| `server/mixer.py` | 双模型混合 `blend`（异尺寸时 `scale`+`pad`） |
| `server/core.py` | 视频：提取帧、合成 mp4（libx264+音频 copy）、合成 gif（palettegen/paletteuse）、FPS 探测 |

### 视频处理原始命令（三步走）

```bash
# 1. 提取帧（先建 tmp_frames/）
ffmpeg -i onepiece_demo.mp4 -qscale:v 1 -fps_mode cfr -r 23.98 tmp_frames/frame%08d.jpg

# 2. 引擎放大每帧（先建 out_frames/）
realesrgan-ncnn-vulkan.exe -i tmp_frames -o out_frames \
  -n realesrgan-x4plus-anime -s 4 -f jpg

# 3. 合成视频（保留原音频）
ffmpeg -i out_frames/frame%08d.jpg -i onepiece_demo.mp4 \
  -map 0:v:0 -map 1:a:0 -c:a copy -c:v libx264 -r 23.98 -pix_fmt yuv420p output_w_audio.mp4
```

> `-fps_mode cfr` 是 ffmpeg 9.0 语法（替代旧版 `-vsync cfr` / `-vsync 0`），
> 本项目锁定 9.0 分支。GUI 已集成上述流程，无需手动执行。

### 重新构建

完整构建依据（需求矩阵、configure 白名单、踩坑记录）见 **`ffmpeg-features.md`**（与本文档同目录）。快速要点：

```bash
# MSYS2 ucrt64 环境
pacman -S --needed base-devel mingw-w64-ucrt-x86_64-toolchain \
  mingw-w64-ucrt-x86_64-x264 mingw-w64-ucrt-x86_64-nasm \
  mingw-w64-ucrt-x86_64-pkgconf
# 克隆 n9.0 源码后执行 ffmpeg-features.md 第 4 节的 configure + make
```

## 4. 运行库 `vcomp140.dll`

引擎（`realesrgan-ncnn-vulkan.exe`）依赖的 VC++ 2015-2022 运行库组件，
必须与 exe 同目录。删除会导致引擎启动失败。

## 5. 非发行内容（可安全删除）

| 路径 | 说明 |
|------|------|
| `ffmpeg-src/` | ffmpeg 自构建源码（git 浅克隆，约 129 MB）；构建文档 [ffmpeg-features.md](ffmpeg-features.md) 在 tools/ 下已入 git，删除此目录不影响 |
| `ffmpeg.exe.bak` | 替换前的 gyan essentials 旧版 ffmpeg（103 MB，回滚备用） |

确认新版正常后可删除以节省磁盘；两者均已加入 `.gitignore`，不影响仓库。

## 6. 快速验证

```bash
# 引擎 + 模型
tools/realesrgan-ncnn-vulkan.exe -i test-data/input.jpg -o TMP/verify.png

# ffmpeg 关键能力
tools/ffmpeg.exe -version
tools/ffmpeg.exe -y -i test-data/input.jpg -vf scale=220:220:flags=lanczos TMP/verify_scale.png
```

全部通过后运行测试套件（真实引擎 + ffmpeg，无 mock）：

```bash
server\.venv\Scripts\python -m pytest server\tests\ -v
```

---

相关文档：仓库根 [README.md](../README.md)（用户手册）、[AGENTS.md](../AGENTS.md)（开发文档）、[ffmpeg-features.md](ffmpeg-features.md)（ffmpeg 构建依据）。
