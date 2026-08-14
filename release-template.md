<!--
RE4x GitHub Release 说明模板（与 v2.1.5 / v2.1.6 历史格式一致）

使用方法：
1. 复制本文件「模板正文」（HTML 注释之后的部分）到 release/v<版本>-notes.md
   （release/ 目录已 gitignore，notes 文件不进仓库）
2. 替换占位符：
   - {{TAG}}      新版本号（如 v2.1.7）
   - {{PREV_TAG}} 上一版本号（如 v2.1.6，用于「修复（自 …）」与 Full Changelog 对比链接）
   - {{FIXES}}    本次修复/变更条目，照 CHANGELOG 要点写：
     每条一行「- **加粗标题**（[issue #N](链接)）: 一句说明——问题现象、原因、现在的行为」
     没有 issue 时省略括号链接
3. 「✨ 新特性」「📦 使用方法」「⚖️ 许可」三个小节是固定段落，每次原样保留
4. 创建或更新 Release：

   gh release create {{TAG}} release/RE4x-SD-Enhance-{{TAG}}.zip \
     --repo hu568/RE4x --title "RE4x SD Enhance {{TAG}}" \
     --notes-file release/{{TAG}}-notes.md

   已发布的 Release 更新说明用：gh release edit {{TAG}} --notes-file ...
-->
便携式 AI 图片/视频放大工具包。无需安装、无需 CUDA/PyTorch、无需浏览器，双击 exe 即用。

## 🔧 修复（自 {{PREV_TAG}}）

{{FIXES}}

## ✨ 新特性（自 v1.0.1 起，v2.1 系列）

- **桌面 GUI（pywebview）**：单 HTML 界面 + Python 桥接，4 大功能页（单图 / 批量 / 目录 / 视频），无 Flask、无浏览器
- **SPANV2 引擎与模型**（NTIRE2026 高效超分）：新增 `spanv2` 模型
- **统一放大管线**：模型固定 4x → ffmpeg 缩放，任意目标倍率（1-8x / 目标尺寸）均可
- **视频尺寸模式**：新增 contain（适应）/ cover（裁剪）两种模式
- **双级放大器混合**：ffmpeg blend 混合两个不同模型的结果
- **磁盘运行日志**：自动写入 `logs/sd-enhance.log`（每日轮转，保留 7 天）
- **模型自动发现**：下拉框自动扫描 `tools/models/`，可自行添加新模型

## 📦 使用方法

1. 解压 zip（资源管理器直接解压即可）
2. 双击 `sd-enhance-server.exe`
3. 选择图片/视频，设置倍率，点「开始」

## ⚖️ 许可

GPL-3.0，免费开源，仅供学习参考，严禁商业倒卖。

**第三方组件**：Real-ESRGAN (BSD-3)、FFmpeg (GPL/LGPL)、ncnn (BSD-3)、pywebview (BSD-3)、RE+SPANV2 (NTIRE2026)

**Full Changelog**: https://github.com/hu568/RE4x/compare/{{PREV_TAG}}...{{TAG}}
