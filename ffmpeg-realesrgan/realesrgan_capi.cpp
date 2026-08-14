// C API around the RealESRGAN (ncnn) engine, for use from the FFmpeg filter.
// Part of RE4x ffmpeg-realesrgan (adopted from GitHub issue #3).

#include "realesrgan_capi.h"

#include "realesrgan.h"
#include "gpu.h"

#include <stdio.h>
#include <string.h>
#include <string>
#include <vector>

#ifdef _WIN32
#include <windows.h>
#endif

struct realesrgan_ctx
{
    RealESRGAN* esrgan;
    std::vector<unsigned char> outbuf;
    int w;
    int h;
    int scale;
};

static int g_gpu_instance_refs = 0;

#ifdef _WIN32
static std::wstring utf8_to_wide(const char* s)
{
    std::string str(s ? s : "");
    if (str.empty())
        return std::wstring();
    int n = MultiByteToWideChar(CP_UTF8, 0, str.c_str(), (int)str.size(), NULL, 0);
    std::wstring ws(n, L'\0');
    if (n > 0)
        MultiByteToWideChar(CP_UTF8, 0, str.c_str(), (int)str.size(), &ws[0], n);
    return ws;
}
#endif

static void release_gpu_instance()
{
    if (g_gpu_instance_refs > 0)
    {
        g_gpu_instance_refs--;
        if (g_gpu_instance_refs == 0)
            ncnn::destroy_gpu_instance();
    }
}

extern "C" {

realesrgan_ctx* realesrgan_create(const char* model_path, const char* model_name,
                                  int gpuid, int tilesize, int tta_mode,
                                  int* out_scale, char* errbuf, int errbuf_size)
{
    try
    {
        if (g_gpu_instance_refs == 0)
            ncnn::create_gpu_instance();
        g_gpu_instance_refs++;

        int gpu = gpuid;
        if (gpu < 0)
            gpu = ncnn::get_default_gpu_index();
        if (gpu < 0 || gpu >= ncnn::get_gpu_count())
        {
            release_gpu_instance();
            if (errbuf && errbuf_size > 0)
                snprintf(errbuf, errbuf_size, "no vulkan gpu available");
            return NULL;
        }

        RealESRGAN* esrgan = new RealESRGAN(gpu, tta_mode != 0);

#ifdef _WIN32
        std::wstring wpath = utf8_to_wide(model_path);
        std::wstring wname = utf8_to_wide(model_name);
        std::wstring parampath = wpath + L"/" + wname + L".param";
        std::wstring modelpath = wpath + L"/" + wname + L".bin";
#else
        std::string wpath(model_path ? model_path : "");
        std::string wname(model_name ? model_name : "");
        std::string parampath = wpath + "/" + wname + ".param";
        std::string modelpath = wpath + "/" + wname + ".bin";
#endif

        esrgan->load(parampath, modelpath);

        esrgan->scale = 4;

        if (tilesize == 0)
        {
            // auto tilesize policy, mirrors the engine main.cpp
            uint32_t heap_budget = ncnn::get_gpu_device(gpu)->get_heap_budget();
            if (heap_budget > 1900)
                tilesize = 200;
            else if (heap_budget > 550)
                tilesize = 100;
            else if (heap_budget > 190)
                tilesize = 64;
            else
                tilesize = 32;
        }
        esrgan->tilesize = tilesize;

        int prepadding = 10;
        {
            std::string mname(model_name ? model_name : "");
            if (mname.find("spanv2") != std::string::npos)
                prepadding = 16; // spanv2 receptive field 33 -> (33-1)/2
        }
        esrgan->prepadding = prepadding;

        realesrgan_ctx* rc = new realesrgan_ctx();
        rc->esrgan = esrgan;
        rc->w = 0;
        rc->h = 0;
        rc->scale = 4;
        if (out_scale)
            *out_scale = 4;
        return rc;
    }
    catch (const std::exception& e)
    {
        if (errbuf && errbuf_size > 0)
            snprintf(errbuf, errbuf_size, "%s", e.what());
    }
    catch (...)
    {
        if (errbuf && errbuf_size > 0)
            snprintf(errbuf, errbuf_size, "unknown ncnn error");
    }
    release_gpu_instance();
    return NULL;
}

int realesrgan_process(realesrgan_ctx* rc,
                       const unsigned char* in_bgr, int w, int h,
                       unsigned char* out_bgr)
{
    if (!rc || !rc->esrgan || !in_bgr || !out_bgr || w <= 0 || h <= 0)
        return -1;
    try
    {
        const int scale = rc->scale;
        if (rc->w != w || rc->h != h)
        {
            rc->outbuf.resize((size_t)w * scale * h * scale * 3);
            rc->w = w;
            rc->h = h;
        }

        ncnn::Mat inimage = ncnn::Mat(w, h, (void*)in_bgr, (size_t)3, 3);
        ncnn::Mat outimage = ncnn::Mat(w * scale, h * scale, rc->outbuf.data(), (size_t)3, 3);

        rc->esrgan->process(inimage, outimage);

        memcpy(out_bgr, rc->outbuf.data(), rc->outbuf.size());
        return 0;
    }
    catch (...)
    {
        return -1;
    }
}

void realesrgan_destroy(realesrgan_ctx* rc)
{
    if (!rc)
        return;
    delete rc->esrgan;
    delete rc;
    release_gpu_instance();
}

} // extern "C"
