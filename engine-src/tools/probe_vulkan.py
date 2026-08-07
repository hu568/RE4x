import ncnn

print("ncnn version:", ncnn.__version__)
print("gpu count:", ncnn.get_gpu_count())
if ncnn.get_gpu_count() > 0:
    for i in range(ncnn.get_gpu_count()):
        info = ncnn.get_gpu_info(i)
        print("gpu", i, ":", info.device_name())
