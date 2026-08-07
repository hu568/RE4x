# RE+SPANV2 — SPANV2 (NTIRE2026 Team22) on Real-ESRGAN-ncnn-vulkan

把 NTIRE2026 Efficient SR 的 **SPANV2_ESR** 模型移植到
[Real-ESRGAN-ncnn-vulkan](https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan) 引擎，
实现 Vulkan (GPU) 加速推理。

## 目录结构

```
RE+SPANV2/
├── engine/                  # Real-ESRGAN-ncnn-vulkan（已改造）
│   ├── src/main.cpp         # prepadding 10→16（spanv2 模型名时）
│   ├── src/CMakeLists.txt   # WITH_LAYER_convolutiondepthwise ON
│   ├── models/spanv2.param  # SPANV2 ncnn 模型（blob: data/output）
│   ├── models/spanv2.bin    # fp32 权重（556 KB）
│   └── build/Release/realesrgan-ncnn-vulkan.exe
├── ntire2026/               # NTIRE2026_ESR 上游（只读参考）
├── tools/
│   ├── convert_spanv2.py    # PyTorch → pnnx → ncnn 转换
│   ├── verify_spanv2.py     # ncnn CPU vs PyTorch 数值一致性
│   ├── verify_spanv2_vulkan.py  # ncnn Vulkan vs PyTorch
│   ├── verify_engine_output.py  # 引擎端到端输出 vs PyTorch
│   ├── build_engine.sh      # 引擎编译脚本
│   └── make_test_image.py   # 生成测试图
└── tests/test_spanv2.py     # unittest（CPU/Vulkan 一致性）
```

## 使用方法

```bash
# GPU 推理（RTX 5070 Ti 等；引擎为 Vulkan-only，-g 需 ≥0）
engine/build/Release/realesrgan-ncnn-vulkan.exe \
  -i input.png -o output.png -m engine/models -n spanv2 -s 4 -g 0
```

- `-m engine/models`：模型目录（main.cpp 要求路径含 `models`）
- `-n spanv2`：模型名（触发 prepadding=16）
- `-s 4`：4x 超分
- 数据域：引擎 preproc `/255` + postproc `*255+0.5`，与 SPANV2 官方推理
  （uint/255 → 0..1 → *255）天然一致

## 移植要点

1. **无自定义算子**：SPANV2 全部由标准算子构成（Convolution /
   ConvolutionDepthWise / BinaryOp / Concat / PixelShuffle）。官方 `use_span_attn=False`
   路径（`guided = (x+f3)*conv1x1(f3)`）与 CUDA 融合算子数值等价，直接导出即可。
2. **pnnx 导出**：`pnnx.export(..., fp16=False)` 生成 fp32 param/bin，
   并把 blob 名 `in0/out0` 重命名为引擎要求的 `data/output`。
3. **prepadding 10→16**：SPANV2 感受野 33（5 个 SPAB + 尾部 3x3 depthwise），
   引擎默认 10 会在 tile 边界留缝；模型名含 `spanv2` 时提升到 16。
4. **启用 depthwise 层**：引擎 CMakeLists 默认 `WITH_LAYER_convolutiondepthwise OFF`
   （Real-ESRGAN 原模型不用），SPANV2 需要，改为 ON 并重新编译。

## 数值验证结果

| 验证 | 最大绝对误差 | PSNR | 结论 |
|---|---|---|---|
| ncnn CPU fp32 vs PyTorch | 1.7e-4 (0..1) | 102.7 dB | PASS |
| ncnn Vulkan fp32 vs PyTorch | 5.0e-5 (0..1) | 114.5 dB | PASS |
| ncnn Vulkan fp16（引擎默认） | 0.058–0.116 (0..1) | 46–49 dB | PASS（fp16 固有精度，容差 0.2） |
| 引擎端到端 (uint8) | mean 0.216 / max 35 | — | PASS（>16 像素仅 93/314 万，均在图像外边缘） |

`python -m unittest discover -s tests` 可复跑前 3 项。

## 构建环境

- MSVC 14.44（Visual Studio 2022 Build Tools）
- Vulkan SDK：`C:\Users\Administrator\VulkanSDK\1.4.350.0\`
  （由 `vulkansdk-windows-X64-1.4.350.0.exe` 解压 + Khronos Vulkan-Headers v1.4.350 +
  系统 `vulkan-1.dll` 生成的导入库组装，非完整 SDK）
- CMake ≥ 3.5，`-DCMAKE_POLICY_VERSION_MINIMUM=3.5`（ncnn 兼容）
