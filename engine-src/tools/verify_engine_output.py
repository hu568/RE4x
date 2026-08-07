"""Compare the engine's end-to-end output image against PyTorch reference.

The engine (realesrgan-ncnn-vulkan) preprocs uint8 RGB -> float [0,1], runs the
SPANV2 model, postprocs *255+0.5.  PyTorch reference: same uint8 input, model on
[0,1], output *255 rounded.  Both should match to within fp16 tolerance
(engine default fp16 storage) plus tile-boundary handling.

Usage: python tools/verify_engine_output.py <engine_out.png> [--strict]
"""

import sys
import os

import numpy as np
from PIL import Image


def main():
    assert len(sys.argv) >= 2, "need engine output png path"
    out_path = sys.argv[1]
    strict = "--strict" in sys.argv

    # reference: run PyTorch SPANV2 on the same input image
    REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    NTIRE_DIR = os.path.join(REPO_ROOT, "ntire2026")
    sys.path.insert(0, NTIRE_DIR)
    import torch
    from models.team22_SPANV2_ESR import SPANV2_ESR

    in_img = np.array(Image.open(os.path.join(REPO_ROOT, "test_input.png")).convert("RGB")).astype(np.float32) / 255.0
    model = SPANV2_ESR(3, 3, feature_channels=32, upscale=4, bias=False, use_span_attn=False)
    state = torch.load(os.path.join(NTIRE_DIR, "model_zoo", "team22_spanv2_c2.pth"), map_location="cpu", weights_only=True)
    for key in ["model", "state_dict", "params", "params_ema"]:
        if isinstance(state, dict) and key in state:
            state = state[key]
            break
    model.load_state_dict(state, strict=True)
    model.eval()
    x = torch.from_numpy(in_img.transpose(2, 0, 1)[None]).float()
    with torch.no_grad():
        y = model(x)[0].clamp(0, 1).permute(1, 2, 0).numpy()
    ref = np.uint8(np.round(y * 255.0))

    out = np.array(Image.open(out_path).convert("RGB"))
    print("engine out:", out.shape, "ref:", ref.shape)
    assert out.shape == ref.shape, "shape mismatch"

    diff = np.abs(out.astype(int) - ref.astype(int))
    print("max abs diff (uint8):", diff.max())
    print("mean abs diff (uint8): %.4f" % diff.mean())
    bad = (diff > 16).sum()
    total = diff.size
    print("pixels >16 off: %d / %d (%.4f%%)" % (bad, total, 100.0 * bad / total))
    ok = (diff.mean() < 2.0) if strict else (diff.max() <= 64)
    print("VERDICT:", "PASS" if ok else "CHECK")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
