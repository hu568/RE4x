"""Vulkan inference check: run the exported SPANV2 ncnn model on GPU with the
same ncnn option set the Real-ESRGAN-ncnn-vulkan engine uses, compare against
PyTorch reference on 0..1 input.

Usage: python tools/verify_spanv2_vulkan.py [gpuid]
"""

import os
import sys

import numpy as np
import torch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NTIRE_DIR = os.path.join(REPO_ROOT, "ntire2026")
MODEL_DIR = os.path.join(REPO_ROOT, "engine", "models")
PARAM = os.path.join(MODEL_DIR, "spanv2.param")
BIN = os.path.join(MODEL_DIR, "spanv2.bin")

sys.path.insert(0, NTIRE_DIR)

import ncnn  # noqa: E402

from models.team22_SPANV2_ESR import SPANV2_ESR  # noqa: E402


def build_torch_model():
    model = SPANV2_ESR(3, 3, feature_channels=32, upscale=4, bias=False, use_span_attn=False)
    state = torch.load(os.path.join(NTIRE_DIR, "model_zoo", "team22_spanv2_c2.pth"), map_location="cpu", weights_only=True)
    for key in ["model", "state_dict", "params", "params_ema"]:
        if isinstance(state, dict) and key in state:
            state = state[key]
            break
    model.load_state_dict(state, strict=True)
    model.eval()
    return model


def main():
    gpuid = int(sys.argv[1]) if len(sys.argv) > 1 else 0

    torch.manual_seed(7)
    model = build_torch_model()

    net = ncnn.Net()
    opt = net.opt
    opt.use_vulkan_compute = True
    # default: fp32 (PASS threshold 1e-2); set SPANV2_FP16=1 for the engine's
    # fp16+int8 storage config (use its looser 0.2 threshold)
    fp16 = os.environ.get("SPANV2_FP16", "0") == "1"
    if fp16:
        # engine defaults: fp16 packed+storage, fp32 arithmetic
        opt.use_fp16_packed = True
        opt.use_fp16_storage = True
        opt.use_fp16_arithmetic = False
        opt.use_int8_storage = True
        opt.use_int8_arithmetic = False
    else:
        opt.use_fp16_packed = False
        opt.use_fp16_storage = False
        opt.use_fp16_arithmetic = False
        opt.use_int8_storage = False
        opt.use_int8_arithmetic = False
    net.set_vulkan_device(gpuid)

    if ncnn.get_gpu_count() <= 0:
        print("ERROR: no Vulkan GPU available, cannot verify Vulkan path")
        return 1

    ret1 = net.load_param(PARAM)
    ret2 = net.load_model(BIN)
    print("gpuid=%d ncnn load_param=%d load_model=%d (gpu_count=%d)" % (gpuid, ret1, ret2, ncnn.get_gpu_count()))
    assert ret1 == 0 and ret2 == 0, "ncnn model load failed"

    H, W = 96, 128
    x = torch.rand(1, 3, H, W)
    with torch.no_grad():
        y_torch = model(x)

    x_chw = x[0].numpy()
    mat_in = ncnn.Mat(x_chw)
    ex = net.create_extractor()
    ex.input("data", mat_in)
    mat_out = ncnn.Mat()
    ex.extract("output", mat_out)
    y_ncnn = np.array(mat_out, copy=True)

    y_torch_chw = y_torch[0].numpy()
    print("torch out:", y_torch_chw.shape, "ncnn out:", y_ncnn.shape)
    assert y_ncnn.shape == y_torch_chw.shape

    diff = np.abs(y_ncnn - y_torch_chw)
    b = 64  # skip 16 px prepadding * 4 scale
    diff_int = diff[:, b:-b, b:-b]
    mse = (diff_int ** 2).mean()
    psnr = 10 * np.log10(1.0 / max(mse, 1e-12))
    print("full-image max abs diff = %.6f" % diff.max())
    print("interior   max abs diff = %.6f   PSNR = %.3f dB" % (diff_int.max(), psnr))
    for ci in range(3):
        print("  ch%d mean abs diff = %.6f" % (ci, diff_int[ci].mean()))
    threshold = 0.2 if fp16 else 1e-2
    ok = diff_int.max() < threshold
    print("VERDICT:", "PASS" if ok else "CHECK")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
