"""Convert SPANV2_ESR (NTIRE2026 team22) PyTorch weights to ncnn param/bin format.

Numerical domain note:
- Official inference (test_demo_team22.py) uses data_range=1.0, i.e. input is
  uint/255 (0..1), output is clamped to 0..1 then *255 back to uint.
- The engine (Real-ESRGAN-ncnn-vulkan) preproc does /255 and postproc *255,
  so the exported model must accept 0..1 input and emit 0..1 output.
  The original model already behaves exactly like that (no internal
  normalization), so NO extra scaling layers are needed.
- use_span_attn=False makes SPABV2.forward use plain PyTorch ops
  (guidance = conv1x1(f3); guided = (x + f3) * guidance), which is
  numerically identical to the fused CUDA span_attention op.
"""

import os
import sys

import torch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NTIRE_DIR = os.path.join(REPO_ROOT, "ntire2026")
CKPT = os.path.join(NTIRE_DIR, "model_zoo", "team22_spanv2_c2.pth")
OUT_DIR = os.path.join(REPO_ROOT, "engine", "models")
OUT_NAME = "spanv2"

sys.path.insert(0, NTIRE_DIR)

from models.team22_SPANV2_ESR import SPANV2_ESR  # noqa: E402


def load_model():
    model = SPANV2_ESR(3, 3, feature_channels=32, upscale=4, bias=False, use_span_attn=False)
    state = torch.load(CKPT, map_location="cpu", weights_only=True)
    for key in ["model", "state_dict", "params", "params_ema"]:
        if isinstance(state, dict) and key in state:
            state = state[key]
            break
    model.load_state_dict(state, strict=True)
    model.eval()
    return model


def main():
    model = load_model()

    # sanity: fixed near-neighbour conv weight should be a fixed upsample kernel
    w = model.conv_near.weight
    print("conv_near nonzero:", int((w != 0).sum()), "ones:", int((w == 1).sum()), "unique sample:", w.flatten()[:12].tolist())

    # reference output on 0..1 input
    x = torch.rand(1, 3, 64, 64)
    with torch.no_grad():
        y = model(x)
    print("reference output:", tuple(y.shape), "min=%.4f max=%.4f" % (y.min().item(), y.max().item()))

    os.makedirs(OUT_DIR, exist_ok=True)

    import pnnx

    print("pnnx version:", pnnx.__version__ if hasattr(pnnx, "__version__") else "?")
    params = pnnx.export(
        model,
        os.path.join(OUT_DIR, OUT_NAME + ".torchscript.pt"),
        inputs=[x],
        input_shapes=[[1, 3, 64, 64]],
        input_types=["torch.float32"],
        device="cpu",
        ncnnparam=os.path.join(OUT_DIR, OUT_NAME + ".ncnn.param"),
        ncnnbin=os.path.join(OUT_DIR, OUT_NAME + ".ncnn.bin"),
        fp16=False,
    )

    # pnnx.export emits <name>.ncnn.param / <name>.ncnn.bin alongside onnx etc.
    ncnn_param = os.path.join(OUT_DIR, OUT_NAME + ".ncnn.param")
    ncnn_bin = os.path.join(OUT_DIR, OUT_NAME + ".ncnn.bin")
    for p in [ncnn_param, ncnn_bin]:
        print(("OK  " if os.path.exists(p) else "miss") + "  " + p + ("  (%d bytes)" % os.path.getsize(p) if os.path.exists(p) else ""))

    # The engine's realesrgan.cpp uses blob names "data" (input) and "output"
    # (output).  pnnx emits "in0"/"out0" — rename them in the param text.
    with open(ncnn_param, "r", encoding="utf-8") as f:
        text = f.read()
    import re

    # sanity: input/output blobs must exist before rename, or the replace
    # silently no-ops and the engine fails at runtime with "not exists"
    assert re.search(r"\bin0\b", text), "expected pnnx input blob 'in0' not found"
    assert re.search(r"\bout0\b", text), "expected pnnx output blob 'out0' not found"

    text = re.sub(r"\bin0\b", "data", text)
    text = re.sub(r"\bout0\b", "output", text)

    final_param = os.path.join(OUT_DIR, OUT_NAME + ".param")
    final_bin = os.path.join(OUT_DIR, OUT_NAME + ".bin")
    with open(final_param, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(ncnn_bin, final_bin)
    print("engine files: %s (%d bytes), %s (%d bytes)" % (final_param, os.path.getsize(final_param), final_bin, os.path.getsize(final_bin)))
    # drop the leftover ncnn.* artifacts we no longer need
    for leftover in [ncnn_param]:
        if os.path.exists(leftover):
            os.remove(leftover)


if __name__ == "__main__":
    main()
