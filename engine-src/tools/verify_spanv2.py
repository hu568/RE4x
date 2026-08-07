"""Numerical consistency check: ncnn (CPU) inference of the exported SPANV2
model vs the original PyTorch model, on the same random 0..1 input.

Usage: python tools/verify_spanv2.py
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


def run_ncnn(net, x_chw):
    """x_chw: numpy (c, h, w) float32 in [0,1] (ncnn CHW layout)."""
    c, h, w = x_chw.shape
    mat_in = ncnn.Mat(x_chw)
    ex = net.create_extractor()
    ex.input("data", mat_in)
    mat_out = ncnn.Mat()
    ex.extract("output", mat_out)
    # ncnn python numpy view is (c, h, w)
    return np.array(mat_out, copy=True)


def main():
    torch.manual_seed(42)
    model = build_torch_model()

    net = ncnn.Net()
    net.opt.use_vulkan_compute = False
    net.opt.use_fp16_packed = False
    net.opt.use_fp16_storage = False
    net.opt.use_fp16_arithmetic = False
    ret1 = net.load_param(PARAM)
    ret2 = net.load_model(BIN)
    print("ncnn load_param=%d load_model=%d" % (ret1, ret2))
    assert ret1 == 0 and ret2 == 0, "ncnn model load failed"

    H, W = 96, 128
    x = torch.rand(1, 3, H, W)
    with torch.no_grad():
        y_torch = model(x)

    x_chw = x[0].numpy()  # (3, H, W)
    y_ncnn = run_ncnn(net, x_chw)  # (3, H*4, W*4)

    y_torch_chw = y_torch[0].numpy()  # (3, H*4, W*4)

    print("torch out:", y_torch_chw.shape, "ncnn out:", y_ncnn.shape)
    assert y_ncnn.shape == y_torch_chw.shape, "shape mismatch"

    diff = np.abs(y_ncnn - y_torch_chw)
    print("full-image  max abs diff = %.6f" % diff.max())

    # interior region (skip prepadding 16 * 4 = 64 px border, same as engine crop)
    b = 64
    diff_int = diff[:, b:-b, b:-b]
    mse = (diff_int ** 2).mean()
    psnr = 10 * np.log10(1.0 / max(mse, 1e-12))
    print("interior    max abs diff = %.6f   PSNR = %.3f dB" % (diff_int.max(), psnr))

    # per-channel mean abs diff
    for ci in range(3):
        print("  ch%d mean abs diff = %.6f" % (ci, diff_int[ci].mean()))

    ok = diff_int.max() < 1e-3
    print("VERDICT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
