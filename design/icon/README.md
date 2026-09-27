# RE4x 软件图标设计

Windows 11 Fluent 风格应用图标，配色与应用内 WinUI 主题（蓝青系）呼应。
打开 [preview.png](preview.png) 查看三方案在浅色/深色背景与 64/48/32/16px 下的对比。

## 三个概念方案

| 方案 | 概念 | 特点 |
|------|------|------|
| [A · 放大镜 + 山景](concept-a-magnifier/icon.svg) | 经典"查看/增强"隐喻：白色放大镜内嵌山景照片，右上 AI 光斑 | 语义最直白，气质接近系统相册类应用 |
| [B · 像素重生](concept-b-pixels/icon.svg) | 低分辨率像素块沿 45° 对角线逐级放大，汇入高清照片卡片 | 最贴合"AI 超分"业务概念，独特性最强 |
| [C · 4× 徽标](concept-c-4x/icon.svg) | 粗壮白色"4×"字标（path 绘制，非字体）+ 光斑 | 最简洁，16px 下辨识度最高，品牌感强 |

三个方案共享同一套底板：蓝青对角渐变（`#6FC9F8 → #3D93EC → #1B5DC4`）+
顶部高光 + 内缘亮边 + 12px 透明安全边距，圆角 54/256（≈ Win11 应用图标比例）。

## 目录结构

```
design/icon/
├── preview.png                    # 三方案对比图（浅/深背景 + 小尺寸阶梯）
├── concept-*/icon.svg             # 矢量源文件（viewBox 256×256，可任意缩放）
├── concept-*/<concept>.ico        # 多尺寸 .ico（256/128/64/48/32/16）
├── concept-*/png/*_N.png          # 各尺寸透明 PNG（含 1024 主图）
├── concept-*/design_brief.json    # 设计简报（svg-maker 脚手架生成）
├── render_transparent.py          # SVG → 透明 PNG（playwright，逐尺寸矢量直渲染）
└── build_assets.py                # 组装 .ico + 拼接预览图
```

## 重新生成

```bash
python design/icon/render_transparent.py   # 改 SVG 后重渲染（透明背景）
python design/icon/build_assets.py         # 重建 .ico 与 preview.png
```

依赖：`playwright`（Chromium）、`Pillow`。

> 注意：svg-maker 技能自带的 `svg_to_png.py` 会把白色页面背景烘焙进 PNG，
> 应用图标需要真透明，因此使用本目录的 `render_transparent.py`（`omit_background=True`）。

## 接入应用

已选定 **方案 B（像素重生）** 并接入：

- **exe 图标**：`server/build.spec` 的 `EXE(icon=...)` 直接引用本目录的 `concept-b-pixels.ico`
- **窗口图标**：`server/app.py` 的 `_window_icon()` 在开发模式传给 `webview.start(icon=...)`（pywebview WinForms 后端支持，文档标注 GTK/QT-only 已过时）；打包模式无需传——pywebview 会自动从 exe 提取内嵌图标

如需换用其他方案，改 `build.spec` 与 `app.py` 中指向的概念目录即可。
