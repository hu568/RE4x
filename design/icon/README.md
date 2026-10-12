# RE4x 软件图标设计

Windows 11 Fluent 风格应用图标，配色与应用内 WinUI 主题（蓝青系）呼应。
打开 [preview.png](preview.png) 查看图标在浅色/深色背景与 64/48/32/16px 下的效果。

## 设计方案：像素重生

低分辨率像素块沿 45° 对角线逐级放大，汇入高清照片卡片——最贴合「AI 超分」业务概念。
蓝青对角渐变底板（`#6FC9F8 → #3D93EC → #1B5DC4`）+ 顶部高光 + 内缘亮边 +
12px 透明安全边距，圆角 54/256（≈ Win11 应用图标比例）。

## 目录结构

```
design/icon/
├── preview.png                    # 预览图（浅/深背景 + 小尺寸阶梯）
├── concept-b-pixels/icon.svg      # 矢量源文件（viewBox 256×256，可任意缩放）
├── concept-b-pixels/concept-b-pixels.ico   # 多尺寸 .ico（256/128/64/48/32/16）
├── concept-b-pixels/png/*_N.png   # 各尺寸透明 PNG（含 1024 主图）
├── concept-b-pixels/design_brief.json      # 设计简报（svg-maker 脚手架生成）
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

已选定 **像素重生** 并接入：

- **exe 图标**：`server/build.spec` 的 `EXE(icon=...)` 直接引用本目录的 `concept-b-pixels.ico`
- **窗口图标**：`server/app.py` 的 `_window_icon()` 在开发模式传给 `webview.start(icon=...)`（pywebview WinForms 后端支持，文档标注 GTK/QT-only 已过时）；打包模式无需传——pywebview 会自动从 exe 提取内嵌图标
