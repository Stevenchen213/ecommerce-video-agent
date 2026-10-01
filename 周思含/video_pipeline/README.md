# video_pipeline

> 所属目录：`D:\电商视频剪辑AI\脚本驱动双平台视频组装\`

脚本驱动的双平台视频组装框架：

- **飞影数字人** → 数字人 / 主播镜头（必用素材库）
- **蝉镜** → 产品镜头（必用素材库）；相邻产品镜会聚成连续段连贯生成
- **Assembler** → 按脚本顺序 FFmpeg 拼接成片

## 快速开始

在**上一级中文目录**下执行：

```powershell
cd "D:\电商视频剪辑AI\脚本驱动双平台视频组装"
pip install -r video_pipeline\requirements.txt
python -m video_pipeline.cli validate video_pipeline\examples\sample_script.yaml
python -m video_pipeline.cli run video_pipeline\examples\sample_script.yaml
```

成片默认：`video_pipeline\output\final.mp4`

更完整说明见同级 `任务说明.md` 与 `README.md`。
