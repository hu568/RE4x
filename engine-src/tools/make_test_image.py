"""Generate a small test input image (PNG) for end-to-end engine testing."""
import numpy as np
from PIL import Image
import os

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "test_input.png")
rng = np.random.default_rng(123)
# 256x256 RGB gradient + noise, realistic-ish content
yy, xx = np.mgrid[0:256, 0:256]
img = np.zeros((256, 256, 3), dtype=np.uint8)
img[..., 0] = (xx * 0.5 + yy * 0.3 + rng.normal(0, 8, (256, 256))).clip(0, 255)
img[..., 1] = (yy * 0.6 + xx * 0.2 + rng.normal(0, 8, (256, 256))).clip(0, 255)
img[..., 2] = (128 + 40 * np.sin(xx / 20) + rng.normal(0, 8, (256, 256))).clip(0, 255)
Image.fromarray(img, "RGB").save(out)
print("wrote", os.path.abspath(out), os.path.getsize(out), "bytes")
