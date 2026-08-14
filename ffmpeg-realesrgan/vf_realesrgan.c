/*
 * FFmpeg filter: realesrgan — Real-ESRGAN 4x super-resolution via ncnn (Vulkan)
 *
 * In-process implementation of GitHub issue #3 of RE4x: instead of the
 * extract-frames -> external engine -> merge pipeline, one single ffmpeg
 * command upscales video (or images) with zero intermediate files:
 *
 *   ffmpeg -i input.mp4 -vf "realesrgan=model=realesrgan-x4plus-anime:model_path=tools/models,scale=..." out.mp4
 *
 * The Real-ESRGAN engine (realesrgan.cpp/h from the RE+SPANV2 fork of
 * Real-ESRGAN-ncnn-vulkan) is linked into libavfilter as a static C++
 * object; frames flow through the filter graph as AVFrame pointers.
 *
 * Part of RE4x (SD Enhance). See ffmpeg-realesrgan/README.md.
 */

#include "libavutil/imgutils.h"
#include "libavutil/mem.h"
#include "libavutil/opt.h"
#include "libavutil/pixdesc.h"

#include "avfilter.h"
#include "formats.h"
#include "video.h"

#include "libswscale/swscale.h"

#include "realesrgan_capi.h"

typedef struct RealesrganContext {
    const AVClass *class;

    char *model_path;
    char *model_name;
    int gpuid;
    int tilesize;
    int tta_mode;

    int scale;          /* model fixed output scale (4), from the engine */

    realesrgan_ctx *rc;

    /* bgr24 intermediate frames (model input/output domain) */
    AVFrame *rgb;       /* w x h, align=1 so stride == w*3 */
    uint8_t *up_data;   /* (w*scale) x (h*scale) contiguous bgr24 */
    int up_size;

    struct SwsContext *sws_in;   /* inlink format -> bgr24 */
    struct SwsContext *sws_out;  /* bgr24 -> inlink format */

    int in_w, in_h;
} RealesrganContext;

#define OFFSET(x) offsetof(RealesrganContext, x)
#define FLAGS AV_OPT_FLAG_FILTERING_PARAM | AV_OPT_FLAG_VIDEO_PARAM

static const AVOption realesrgan_options[] = {
    { "model_path", "directory containing the model files", OFFSET(model_path), AV_OPT_TYPE_STRING, {.str = "models"}, .flags = FLAGS },
    { "model",      "model base name (without .param/.bin)", OFFSET(model_name), AV_OPT_TYPE_STRING, {.str = "realesrgan-x4plus-anime"}, .flags = FLAGS },
    { "gpuid",      "vulkan gpu device index (-1 = auto)",   OFFSET(gpuid), AV_OPT_TYPE_INT, {.i64 = -1}, -1, 31, FLAGS },
    { "tilesize",   "tile size in pixels (0 = auto)",       OFFSET(tilesize), AV_OPT_TYPE_INT, {.i64 = 0}, 0, 4096, FLAGS },
    { "tta",        "enable test-time augmentation",        OFFSET(tta_mode), AV_OPT_TYPE_BOOL, {.i64 = 0}, 0, 1, FLAGS },
    { NULL }
};

AVFILTER_DEFINE_CLASS(realesrgan);

static av_cold int init(AVFilterContext *ctx)
{
    RealesrganContext *s = ctx->priv;
    char errbuf[512] = "";

    s->rc = realesrgan_create(s->model_path, s->model_name, s->gpuid,
                              s->tilesize, s->tta_mode, &s->scale,
                              errbuf, sizeof(errbuf));
    if (!s->rc) {
        av_log(ctx, AV_LOG_ERROR, "realesrgan init failed: %s\n",
               errbuf[0] ? errbuf : "unknown error");
        return AVERROR(EINVAL);
    }

    av_log(ctx, AV_LOG_INFO,
           "realesrgan: model '%s' loaded from '%s', output scale %dx, gpuid=%d\n",
           s->model_name, s->model_path, s->scale, s->gpuid);
    return 0;
}

static av_cold void uninit(AVFilterContext *ctx)
{
    RealesrganContext *s = ctx->priv;

    if (s->rc)
        realesrgan_destroy(s->rc);
    sws_free_context(&s->sws_in);
    sws_free_context(&s->sws_out);
    av_frame_free(&s->rgb);
    av_freep(&s->up_data);
}

static const int pix_fmts[] = {
    AV_PIX_FMT_YUV420P, AV_PIX_FMT_YUV422P, AV_PIX_FMT_YUV444P,
    AV_PIX_FMT_YUVA420P, AV_PIX_FMT_YUVA422P, AV_PIX_FMT_YUVA444P,
    AV_PIX_FMT_NV12, AV_PIX_FMT_NV21,
    AV_PIX_FMT_GRAY8,
    AV_PIX_FMT_RGB24, AV_PIX_FMT_BGR24, AV_PIX_FMT_ARGB, AV_PIX_FMT_ABGR,
    AV_PIX_FMT_RGBA, AV_PIX_FMT_BGRA,
    AV_PIX_FMT_NONE
};

static int query_formats(const AVFilterContext *ctx,
                         AVFilterFormatsConfig **cfg_in,
                         AVFilterFormatsConfig **cfg_out)
{
    return ff_set_common_formats_from_list2(ctx, cfg_in, cfg_out, pix_fmts);
}

static int config_output(AVFilterLink *outlink)
{
    AVFilterContext *ctx = outlink->src;
    RealesrganContext *s = ctx->priv;
    AVFilterLink *inlink = ctx->inputs[0];

    outlink->w = inlink->w * s->scale;
    outlink->h = inlink->h * s->scale;
    outlink->sample_aspect_ratio = inlink->sample_aspect_ratio;
    return 0;
}

static int ensure_buffers(AVFilterContext *ctx, AVFrame *in)
{
    RealesrganContext *s = ctx->priv;
    int ret;

    if (s->rgb && s->in_w == in->width && s->in_h == in->height)
        return 0;

    s->in_w = in->width;
    s->in_h = in->height;

    av_frame_free(&s->rgb);
    av_freep(&s->up_data);

    s->rgb = av_frame_alloc();
    if (!s->rgb)
        return AVERROR(ENOMEM);
    s->rgb->format = AV_PIX_FMT_BGR24;
    s->rgb->width = in->width;
    s->rgb->height = in->height;
    /* align=1: the model reads contiguous bgr rows without padding */
    ret = av_frame_get_buffer(s->rgb, 1);
    if (ret < 0)
        return ret;

    s->up_size = in->width * s->scale * in->height * s->scale * 3;
    s->up_data = av_malloc(s->up_size);
    if (!s->up_data)
        return AVERROR(ENOMEM);

    sws_free_context(&s->sws_in);
    sws_free_context(&s->sws_out);
    s->sws_in = sws_getContext(in->width, in->height, in->format,
                               in->width, in->height, AV_PIX_FMT_BGR24,
                               SWS_BILINEAR, NULL, NULL, NULL);
    s->sws_out = sws_getContext(in->width * s->scale, in->height * s->scale, AV_PIX_FMT_BGR24,
                                in->width * s->scale, in->height * s->scale, in->format,
                                SWS_BILINEAR, NULL, NULL, NULL);
    if (!s->sws_in || !s->sws_out)
        return AVERROR(EINVAL);

    return 0;
}

static int filter_frame(AVFilterLink *inlink, AVFrame *in)
{
    AVFilterContext *ctx = inlink->dst;
    RealesrganContext *s = ctx->priv;
    AVFilterLink *outlink = ctx->outputs[0];
    AVFrame *out;
    const uint8_t *up_src[4] = { NULL };
    int up_stride[4] = { 0 };
    int ret;

    ret = ensure_buffers(ctx, in);
    if (ret < 0) {
        av_frame_free(&in);
        return ret;
    }

    /* input frame -> bgr24 */
    sws_scale(s->sws_in, (const uint8_t *const *)in->data, in->linesize,
              0, in->height, s->rgb->data, s->rgb->linesize);

    /* run the model (4x) */
    ret = realesrgan_process(s->rc, s->rgb->data[0], in->width, in->height, s->up_data);
    if (ret != 0) {
        av_log(ctx, AV_LOG_ERROR, "realesrgan model inference failed\n");
        av_frame_free(&in);
        return AVERROR(EIO);
    }

    out = ff_get_video_buffer(outlink, outlink->w, outlink->h);
    if (!out) {
        av_frame_free(&in);
        return AVERROR(ENOMEM);
    }
    av_frame_copy_props(out, in);

    up_src[0] = s->up_data;
    up_stride[0] = in->width * s->scale * 3;
    sws_scale(s->sws_out, up_src, up_stride,
              0, in->height * s->scale, out->data, out->linesize);

    av_frame_free(&in);
    return ff_filter_frame(outlink, out);
}

static const AVFilterPad avfilter_vf_realesrgan_inputs[] = {
    {
        .name         = "default",
        .type         = AVMEDIA_TYPE_VIDEO,
        .filter_frame = filter_frame,
    },
};

static const AVFilterPad avfilter_vf_realesrgan_outputs[] = {
    {
        .name         = "default",
        .type         = AVMEDIA_TYPE_VIDEO,
        .config_props = config_output,
    },
};

const FFFilter ff_vf_realesrgan = {
    .p.name          = "realesrgan",
    .p.description   = NULL_IF_CONFIG_SMALL("Real-ESRGAN 4x super-resolution via ncnn (Vulkan)"),
    .p.priv_class    = &realesrgan_class,
    .init            = init,
    .uninit          = uninit,
    .priv_size       = sizeof(RealesrganContext),
    FILTER_INPUTS(avfilter_vf_realesrgan_inputs),
    FILTER_OUTPUTS(avfilter_vf_realesrgan_outputs),
    FILTER_QUERY_FUNC2(query_formats),
};
