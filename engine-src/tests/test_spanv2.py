"""Unittest wrapper for SPANV2 -> ncnn numerical consistency checks.

Run with: python -m unittest tests.test_spanv2 -v
(or: python -m unittest discover -s tests)
"""

import os
import sys
import unittest

import numpy as np
import torch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NTIRE_DIR = os.path.join(REPO_ROOT, "ntire2026")
MODEL_DIR = os.path.join(REPO_ROOT, "engine", "models")
PARAM = os.path.join(MODEL_DIR, "spanv2.param")
BIN = os.path.join(MODEL_DIR, "spanv2.bin")
CKPT = os.path.join(NTIRE_DIR, "model_zoo", "team22_spanv2_c2.pth")

sys.path.insert(0, NTIRE_DIR)

import ncnn  # noqa: E402

from models.team22_SPANV2_ESR import SPANV2_ESR  # noqa: E402

H, W = 96, 128
BORDER = 64  # 16 px prepadding * 4 scale


def build_torch_model():
    model = SPANV2_ESR(3, 3, feature_channels=32, upscale=4, bias=False, use_span_attn=False)
    state = torch.load(CKPT, map_location="cpu", weights_only=True)
    for key in ["model", "state_dict", "params", "params_ema"]:
        if isinstance(state, dict) and key in state:
            state = state[key]
            break
    model.load_state_dict(state, strict=True)
    model.eval()
    return model


def interior_diff(y_ncnn, y_torch):
    diff = np.abs(y_ncnn - y_torch)
    return diff[:, BORDER:-BORDER, BORDER:-BORDER]


class TestSpanV2Conversion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = build_torch_model()
        torch.manual_seed(42)
        cls.x = torch.rand(1, 3, H, W)
        with torch.no_grad():
            cls.y_torch = cls.model(cls.x)[0].numpy()  # (3, H*4, W*4)

    def _run_ncnn(self, use_vulkan, fp16=False, gpuid=0):
        net = ncnn.Net()
        opt = net.opt
        opt.use_vulkan_compute = use_vulkan
        opt.use_fp16_packed = fp16
        opt.use_fp16_storage = fp16
        opt.use_fp16_arithmetic = False
        opt.use_int8_storage = fp16
        opt.use_int8_arithmetic = False
        if use_vulkan:
            net.set_vulkan_device(gpuid)
        self.assertEqual(net.load_param(PARAM), 0)
        self.assertEqual(net.load_model(BIN), 0)
        ex = net.create_extractor()
        ex.input("data", ncnn.Mat(self.x[0].numpy()))
        mat_out = ncnn.Mat()
        ex.extract("output", mat_out)
        return np.array(mat_out, copy=True)

    def test_cpu_fp32_matches_torch(self):
        y = self._run_ncnn(use_vulkan=False, fp16=False)
        self.assertEqual(y.shape, self.y_torch.shape)
        d = interior_diff(y, self.y_torch)
        self.assertLess(d.max(), 1e-3, "CPU fp32 max abs diff too large: %.6f" % d.max())

    @unittest.skipUnless(ncnn.get_gpu_count() > 0, "no Vulkan GPU available")
    def test_vulkan_fp32_matches_torch(self):
        y = self._run_ncnn(use_vulkan=True, fp16=False)
        self.assertEqual(y.shape, self.y_torch.shape)
        d = interior_diff(y, self.y_torch)
        self.assertLess(d.max(), 1e-3, "Vulkan fp32 max abs diff too large: %.6f" % d.max())

    @unittest.skipUnless(ncnn.get_gpu_count() > 0, "no Vulkan GPU available")
    def test_vulkan_fp16_engine_defaults(self):
        # engine default option set: fp16 packed+storage, int8 storage, fp32 arithmetic
        y = self._run_ncnn(use_vulkan=True, fp16=True)
        self.assertEqual(y.shape, self.y_torch.shape)
        d = interior_diff(y, self.y_torch)
        self.assertLess(d.max(), 0.2, "Vulkan fp16 max abs diff too large: %.6f" % d.max())


if __name__ == "__main__":
    unittest.main(verbosity=2)
