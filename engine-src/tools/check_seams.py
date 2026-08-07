"""Check whether engine-vs-torch deviations cluster at tile boundaries."""
import numpy as np
from PIL import Image
import sys
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "ntire2026"))

import torch
from models.team22_SPANV2_ESR import SPANV2_ESR

in_img = np.array(Image.open(os.path.join(REPO_ROOT, "test_input.png")).convert("RGB")).astype(np.float32) / 255.0
model = SPANV2_ESR(3, 3, feature_channels=32, upscale=4, bias=False, use_span_attn=False)
state = torch.load(os.path.join(REPO_ROOT, "ntire2026", "model_zoo", "team22_spanv2_c2.pth"), map_location="cpu", weights_only=True)
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

out = np.array(Image.open(sys.argv[1]).convert("RGB"))
diff = np.abs(out.astype(int) - ref.astype(int)).max(axis=2)  # per-pixel max over channels

H, W = diff.shape
bad = np.argwhere(diff > 16)
print("bad pixel count:", len(bad))
if len(bad):
    ys, xs = bad[:, 0], bad[:, 1]
    print("y range:", ys.min(), "-", ys.max(), " x range:", xs.min(), "-", xs.max())
    # tile size used by engine for 1024x1024 out: check clustering on 4x grid
    print("y histogram (quarters):", np.histogram(ys, bins=4, range=(0, H))[0])
    print("x histogram (quarters):", np.histogram(xs, bins=4, range=(0, W))[0])
    # distance to nearest tile edge (tile ~ 100*4=400 or 256*4=1024)
    print("sample bad pixels:", list(zip(ys[:10].tolist(), xs[:10].tolist())))
