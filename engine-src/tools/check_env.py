"""Check Python environment capabilities for the SPANV2 -> ncnn conversion pipeline."""
import importlib.util
import platform
import sys

print("python:", sys.version.split()[0], platform.platform())

mods = ["torch", "ncnn", "pnnx", "torchvision", "numpy", "onnx", "onnxruntime"]
for m in mods:
    spec = importlib.util.find_spec(m)
    if spec is None:
        print(f"{m}: NOT INSTALLED")
        continue
    mod = __import__(m)
    print(f"{m}: {getattr(mod, '__version__', '?')} @ {spec.origin}")
