// C API around the RealESRGAN (ncnn) engine, for use from the FFmpeg filter.
// Keeps all C++/ncnn types out of the C filter translation unit.
//
// Part of RE4x ffmpeg-realesrgan (adopted from GitHub issue #3).
// Engine sources (realesrgan.cpp/h) are from the RE+SPANV2 fork of
// Real-ESRGAN-ncnn-vulkan, see ffmpeg-realesrgan/README.md.

#ifndef RE4X_REALESRGAN_CAPI_H
#define RE4X_REALESRGAN_CAPI_H

#ifdef __cplusplus
extern "C" {
#endif

typedef struct realesrgan_ctx realesrgan_ctx;

/* Create an engine instance and load <model_path>/<model_name>.{param,bin}.
 *
 * - model_path: directory containing the models (utf-8, may be relative)
 * - model_name: model base name, e.g. "realesrgan-x4plus-anime" or "spanv2"
 * - gpuid:      vulkan device index, or -1 for auto
 * - tilesize:   tile size, or 0 for auto (picked from gpu heap budget)
 * - tta_mode:   non-zero enables test-time augmentation
 * - out_scale:  receives the model's fixed output scale (4)
 * - errbuf/errbuf_size: receives a human readable error on failure
 *
 * Returns NULL on failure. Destroy with realesrgan_destroy().
 */
realesrgan_ctx* realesrgan_create(const char* model_path,
                                  const char* model_name,
                                  int gpuid, int tilesize, int tta_mode,
                                  int* out_scale,
                                  char* errbuf, int errbuf_size);

/* Upscale one BGR24 image (contiguous, stride w*3) to out_bgr
 * (w*scale x h*scale, stride w*scale*3). Returns 0 on success.
 */
int realesrgan_process(realesrgan_ctx* ctx,
                       const unsigned char* in_bgr, int w, int h,
                       unsigned char* out_bgr);

void realesrgan_destroy(realesrgan_ctx* ctx);

#ifdef __cplusplus
}
#endif

#endif /* RE4X_REALESRGAN_CAPI_H */
