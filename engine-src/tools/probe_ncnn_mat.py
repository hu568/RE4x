import ncnn
import numpy as np

print("Mat methods:", [m for m in dir(ncnn.Mat) if not m.startswith("_")])
m = ncnn.Mat(4, 3, 2)  # w=4, h=3, c=2
print("w,h,c,elemsize,cstep:", m.w, m.h, m.c, m.elemsize, m.cstep)
print("has to_numpy:", hasattr(m, "to_numpy"), "has numpy:", hasattr(m, "numpy"))

a = np.arange(4 * 3 * 2, dtype=np.float32).reshape(3, 4, 2)  # (h=3, w=4, c=2)
try:
    m2 = ncnn.Mat(a)
    print("Mat(numpy hwc) ok:", m2.w, m2.h, m2.c, m2.cstep)
    out = m2.numpy() if hasattr(m2, "numpy") else np.array(m2)
    print("numpy view shape:", out.shape, out.dtype)
except Exception as e:
    print("Mat(numpy) failed:", e)
