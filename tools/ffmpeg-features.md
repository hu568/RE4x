# ffmpeg 定制需求文档（ffmpeg-features.md）

RE4x（SD Enhance 便携工具包）使用**自构建最小化 ffmpeg**。本文档记录：
项目全部 ffmpeg 调用点、组件需求矩阵、configure 白名单、构建步骤、验证清单
与实际体积记录，是 `tools/ffmpeg.exe` 的可复现构建依据。

## 1. 为什么定制

| 项 | 现状 |
|----|------|
| 原方案 | gyan.dev `ffmpeg-release-essentials.zip`（ffmpeg 9.0） |
| 原体积 | `tools/ffmpeg.exe` = **102.8 MB** |
| 问题 | essentials 挂载大量本项目用不到的库：gnutls / srt / ssh / zmq / x265 / xvid / aom / vpx / avisynth / sdl2 / cuda / nvenc / dxva2 等 |
| 目标 | 静态单文件 `ffmpeg.exe`，仅含本项目所需组件，体积实测 **7.53 MB**（-92.7%） |

## 2. 全部 ffmpeg 调用点（源代码，v2.0 实测）

| # | 位置 | 用途 | 命令 / 滤镜 | 所需组件 |
|---|------|------|------------|---------|
| 1 | `server/resizer.py:100-106` | 图片精确缩放 | `-i IN -vf scale=W:H:flags=lanczos -y OUT` | filter `scale`；图片 demuxer/decoder、图片 muxer/encoder 按输入输出扩展名 |
| 2 | `server/resizer.py:215-221` | 居中裁剪 | `-i IN -vf crop=W:H -y OUT` | filter `crop` |
| 3 | `server/mixer.py:142-152` | 双模型混合 | 同尺寸：`-filter_complex "[0:v][1:v]blend=all_mode=overlay:all_opacity=X"`；异尺寸：`[1:v]scale=W:H:force_original_aspect_ratio=decrease,pad=W:H:(ow-iw)/2:(oh-ih)/2[1s];[0:v][1s]blend=...` | filter `scale` / `pad` / `blend` |
| 4 | `server/core.py:290-306` | FPS 探测回退 | `ffmpeg -i VIDEO`（解析 stderr 中 `fps` / `tbr` 文本） | 视频 demuxer + 流信息探测；**不需要 ffprobe** |
| 5 | `server/core.py:676-682` | 提取帧 | `-i VIDEO -qscale:v 1 -fps_mode cfr -r FPS -start_number 1 -y frame%08d.jpg` | 视频 demuxer/decoder、encoder `mjpeg`、muxer `image2`、`-fps_mode`（需 ≥ 6.0） |
| 6 | `server/core.py:825-834` | 合成 mp4 | `-start_number 1 -framerate FPS -i frame%08d.jpg -i VIDEO -map 0:v:0 -map 1:a:0? -c:a copy -c:v libx264 -r FPS -pix_fmt yuv420p -shortest -y OUT.mp4` | demuxer `image2`、encoder `libx264`（GPL）、muxer `mp4`、音频 parser（aac/mp3，`copy` 模式不转码） |
| 7 | `server/core.py:816-823` | 合成 gif | `-start_number 1 -framerate FPS -i frame%08d.jpg -vf "fps=10,scale=iw:ih:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" -y OUT.gif` | filter `fps`/`scale`/`split`/`palettegen`/`paletteuse`、encoder `gif`、muxer `gif` |
| 8 | `server/tests/test_core.py:282-285` | 抽单帧验证尺寸 | `-y -i OUT -frames:v 1 frame.jpg` | decoder `h264`、encoder `mjpeg`、muxer `image2` |

> **格式边界**：视频输入（`server/core.py:28`）= `.mp4 .webm .avi .mov .mkv`；
> 图片输入（`server/core.py:27`）= `.jpg .jpeg .png .webp .bmp .tiff`。
> 视频输出名义支持 `mp4/avi/gif`，但 `core.py:810` 把非 gif 一律输出为 mp4
> （`out_ext = 'gif' if output_format == 'gif' else 'mp4'`）→ **不需要 avi muxer**。

## 3. 组件需求矩阵（configure 白名单依据）

- **demuxer**：`image2`（图片/帧序列）、`mov`（mp4/mov）、`matroska`（mkv/webm）、`avi`
- **decoder**：`mjpeg, png, bmp, webp, tiff`（图片输入）+ `h264, hevc, mpeg4, vp8, vp9`（视频输入）
- **muxer**：`image2`（图片输出）、`mp4`、`gif`
- **encoder**：`libx264`（GPL，mp4 核心）、`mjpeg`（jpg）、`png`、`gif`
- **filter**：`scale, crop, blend, pad, split, fps, palettegen, paletteuse`
- **parser**：`h264, hevc, mpeg4, vp8, vp9, aac, mp3`（音频 `-c:a copy` 仅需 parser）
- **protocol**：`file`
- **其他**：`-fps_mode cfr` 需 ffmpeg ≥ 6.0（本项目锁定 9.0 分支，`-vsync` 已被移除）

**明确不需要**：ffprobe / ffplay 程序、全部网络协议（http/rtmp/rtsp/udp/srt/ssh…）、
音频编解码器（无转码需求）、字幕、设备输入（dshow/gdigrab）、硬件加速
（cuda/nvenc/dxva2/vaapi…）、libx264 之外的一切外部库（x265/aom/vpx/openjpeg/
gnutls/srt/zmq/avisynth/sdl2…）。

## 4. configure 白名单（可复现命令）

```bash
# 在 MSYS2 ucrt64 环境中执行（ffmpeg 9.0 源码根目录）
./configure --prefix=/usr/local \
  --disable-everything --disable-network --disable-autodetect \
  --disable-doc --disable-debug --disable-ffplay --disable-ffprobe \
  --enable-ffmpeg --enable-static --disable-shared --enable-small \
  --enable-gpl --enable-libx264 --enable-zlib \
  --pkg-config-flags=--static --extra-ldflags=-static \
  --enable-protocol=file \
  --enable-demuxer=image2,mov,matroska,avi \
  --enable-muxer=image2,mp4,gif \
  --enable-decoder=mjpeg,png,bmp,webp,tiff,h264,hevc,mpeg4,vp8,vp9 \
  --enable-encoder=libx264,mjpeg,png,gif \
  --enable-filter=scale,crop,blend,pad,split,fps,palettegen,paletteuse \
  --enable-parser=h264,hevc,mpeg4,vp8,vp9,aac,mp3
make -j"$(nproc)"
```

> **构建要点（实测踩坑）**
> - `--disable-everything` 会连带禁用 zlib 封装 → **png 解码/编码被禁**（png 依赖
>   inflate/deflate），必须显式加 `--enable-zlib`
> - MSYS2 的 x264/zlib 包默认是共享库（`libx264-165.dll`、`zlib1.dll`），必须加
>   `--pkg-config-flags=--static --extra-ldflags=-static` 强制全静态链接
>   （libx264.a / libz.a / libwinpthread.a / libgcc.a），产物仅依赖 Windows 系统库
>   （KERNEL32 / api-ms-win-crt-* / bcrypt）

## 5. 构建步骤（Windows / MSYS2）

1. 安装 MSYS2（本机已装于 `C:\msys64`），打开 **ucrt64** 终端
2. 安装工具链与依赖：
   ```bash
   pacman -S --needed base-devel mingw-w64-ucrt-x86_64-toolchain \
     mingw-w64-ucrt-x86_64-x264 mingw-w64-ucrt-x86_64-nasm \
     mingw-w64-ucrt-x86_64-pkgconf
   ```
3. 下载源码（入 `tools/ffmpeg-src/`，gitignored）：
   ```bash
   git clone --depth 1 --branch n9.0 https://git.ffmpeg.org/ffmpeg.git
   # 或下载 n9.0 tag tarball 解压
   ```
4. 按第 4 节 `configure` + `make`，产出 `ffmpeg.exe`
5. 备份旧 `tools/ffmpeg.exe` 为 `.bak` 后替换

## 6. 验证清单（冒烟测试，逐调用点复现）

```bash
# 1. scale (lanczos)  2. crop
tools/ffmpeg.exe -y -i test-data/input.jpg -vf scale=220:220:flags=lanczos /tmp/smoke_scale.png
tools/ffmpeg.exe -y -i test-data/input.jpg -vf crop=50:50 /tmp/smoke_crop.png
# 3. blend（同尺寸）  3b. blend（异尺寸 → scale+pad）
tools/ffmpeg.exe -y -i test-data/input.jpg -i test-data/input2.jpg \
  -filter_complex "[0:v][1:v]blend=all_mode=overlay:all_opacity=0.5" /tmp/smoke_blend.png
# 4. FPS 探测（解析 stderr 的 fps/tbr）
tools/ffmpeg.exe -i test-data/onepiece_demo.mp4 2>&1 | grep -E 'fps|tbr'
# 5. 提取帧（-qscale:v 1 -fps_mode cfr）
mkdir -p /tmp/smoke_frames
tools/ffmpeg.exe -y -i test-data/onepiece_demo.mp4 -qscale:v 1 -fps_mode cfr \
  -r 23.98 -start_number 1 /tmp/smoke_frames/frame%08d.jpg
# 6. 合成 mp4（libx264 + 音频 copy + yuv420p）
tools/ffmpeg.exe -y -start_number 1 -framerate 23.98 \
  -i /tmp/smoke_frames/frame%08d.jpg -i test-data/onepiece_demo.mp4 \
  -map 0:v:0 -map 1:a:0? -c:a copy -c:v libx264 -r 23.98 -pix_fmt yuv420p \
  -shortest /tmp/smoke_out.mp4
# 7. 合成 gif（palettegen/paletteuse）
tools/ffmpeg.exe -y -start_number 1 -framerate 23.98 \
  -i /tmp/smoke_frames/frame%08d.jpg \
  -vf "fps=10,scale=iw:ih:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" \
  /tmp/smoke_out.gif
# 8. 抽单帧（-frames:v 1）
tools/ffmpeg.exe -y -i /tmp/smoke_out.mp4 -frames:v 1 /tmp/smoke_frame1.jpg
```

全部通过后运行测试套件（真实引擎 + ffmpeg，无 mock）：

```bash
server\.venv\Scripts\python -m pytest server\tests\ -v
```

## 7. 构建假设与注意事项

- **GPL**：`libx264` 是 mp4 输出的唯一合理编码器（与现用 gyan essentials 一致），
  故接受 GPL 构建（`--enable-gpl`）
- **静态单文件**：`--enable-static --disable-shared`，便携分发无需额外 DLL
- **版本锁定 9.0 分支**：与项目当前二进制及代码注释（`-fps_mode` 替代 `-vsync`）保持一致；
  `-fps_mode` 语法要求 ffmpeg ≥ 6.0
- **不带 ffprobe/ffplay**：`server/core.py` 的 `_detect_fps` 已实现 ffprobe 缺失回退
- 旧 exe 保留 `.bak` 便于回滚

## 8. 体积记录

| 项 | 大小 |
|----|------|
| gyan essentials `ffmpeg.exe`（9.0，102.8 MB 配置） | 102.8 MB |
| 定制 `ffmpeg.exe`（9.0，白名单 + `--enable-small` + 全静态） | **7.53 MB（7,900,672 B，-92.7%）** |
| `tools/` 发行载荷合计（引擎 5.9M + models 41M + ffmpeg 7.6M + vcomp140 180K） | **约 55 MB** |
