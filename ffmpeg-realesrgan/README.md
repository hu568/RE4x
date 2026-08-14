# ffmpeg-realesrgan — FFmpeg 滤镜链内嵌 Real-ESRGAN（issue #3）

把 Real-ESRGAN（ncnn-Vulkan）作为 **ffmpeg 进程内滤镜** 编入自构建 ffmpeg，
一条命令完成视频/图片超分，**消除中间帧**：

```bash
ffmpeg -i input.mp4 -vf "realesrgan=model=realesrgan-x4plus-anime:model_path=tools/models,scale=2560:1440" -c:v libx264 out.mp4
```

- 帧在滤镜链内以 AVFrame 指针传递：零中间文件、零磁盘 IO
- 单进程推理：不再反复拉起 realesrgan-ncnn-vulkan.exe 子进程
- 与 FFmpeg 滤镜生态无缝串联（scale/crop/fps/palettegen…）
- 滤镜缺失时 server/core.py 自动回退旧两步管线（向后兼容）

## 目录结构

| 文件 | 说明 |
|------|------|
| vf_realesrgan.c | FFmpeg 滤镜（C）：YUV↔BGR24 转换（swscale）+ 帧调度 |
| realesrgan_capi.h/.cpp | extern "C" 桥接层：模型加载 / 推理 / ncnn 全局生命周期 |
| realesrgan.h/.cpp | Real-ESRGAN 引擎实现（复制自 RE+SPANV2 的 Real-ESRGAN-ncnn-vulkan fork，删除了 tile 进度打印） |
| realesrgan_*.spv.hex.h | 预编译 SPIR-V 预处理/后处理 shader（引擎离线产物） |
| build_filter.sh | 一键构建脚本：复制源码 → 注册滤镜 → configure → make → 安装 tools/ffmpeg.exe |

## 滤镜参数

| 参数 | 默认 | 说明 |
|------|------|------|
| model | realesrgan-x4plus-anime | 模型基名（自动拼 .param/.bin） |
| model_path | models | 模型目录（相对 ffmpeg 进程 cwd 或绝对路径） |
| gpuid | -1 | Vulkan 设备索引，-1 = 自动 |
| tilesize | 0 | 分块尺寸，0 = 按 GPU 显存自动（200/100/64/32） |
| tta | 0 | 测试时增强（8 次推理，更稳但 8 倍计算） |

模型固定 4x 输出；目标倍率由后续 scale 滤镜完成（沿用项目统一两步管线语义）。
spanv2 模型自动使用 prepadding=16（感受野 33），其余 10。

## 构建

前置条件与工具链见 tools/ffmpeg-features.md
（MSYS2 ucrt64 + x264 + nasm + pkgconf + vulkan-loader/vulkan-headers + glslang），
另需 ncnn 源码与静态库：

```bash
# 1) 构建 ncnn 静态库（Vulkan 后端，MSYS2 ucrt64 MinGW）
bash tools/build_ncnn.sh            # 产出 tools/ncnn-build/src/libncnn.a

# 2) 构建带 realesrgan 滤镜的 ffmpeg
bash ffmpeg-realesrgan/build_filter.sh   # 产出 tools/ffmpeg.exe（旧版备份 .bak）
```

- ncnn 源码取自 RE+SPANV2 引擎 fork 的 engine/src/ncnn 子模块（复制到
  tools/ncnn-src/，排除 .git；tools/ 已 gitignore，不入库）
- ffmpeg 源码树为 tools/ffmpeg-src/（n9.0，gitignored）；本目录的滤镜源码
  是唯一需要版本控制的构建输入
- 链接要点：--extra-libs 含 -lstdc++ 会触发 ffmpeg 用 C++ 链接器
  （ffbuild/common.mak 的 LINK 规则）；-static 与 MinGW import lib 冲突，
  改用 -static-libgcc -static-libstdc++（vulkan-1.dll 为 Windows 系统库）

## 验证

```bash
tools/ffmpeg.exe -hide_banner -filters | grep realesrgan
# 图片单张（4x 原尺寸）
tools/ffmpeg.exe -y -i test-data/input.jpg -vf "realesrgan=model=realesrgan-x4plus-anime:model_path=tools/models" TMP/filter_4x.png
# 视频单命令（2x：滤镜 4x → lanczos 缩回 2x）
tools/ffmpeg.exe -y -i test-data/onepiece_demo.mp4 \
  -vf "realesrgan=model=realesrgan-x4plus-anime:model_path=tools/models,scale=trunc(iw*2/8)*2:trunc(ih*2/8)*2:flags=lanczos" \
  -map 0:v:0 -map 0:a:0? -c:a copy -c:v libx264 -pix_fmt yuv420p TMP/out_filter.mp4
```

## 许可

- vf_realesrgan.c / realesrgan_capi.*：随 RE4x 项目许可分发
- realesrgan.cpp/h：Real-ESRGAN-ncnn-vulkan（BSD-3-Clause，见文件头）
- ncnn / glslang：BSD 系许可，静态链接进 ffmpeg.exe（ffmpeg 本体仍为 GPLv2+，
  随包源码获取途径见 tools/ffmpeg-features.md 第 8 节）
