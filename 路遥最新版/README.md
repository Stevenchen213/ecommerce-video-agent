# 路遥最新版 — AI 带货视频自动剪辑

豆包（doubao-seed）规划带货脚本 → 素材库优先、Seedance 图生视频兜底 → 飞影数字人 → FFmpeg 成片 + 剪映草稿。

在本目录下执行：

```bash
pip install -r video_pipeline/requirements.txt
cp video_pipeline/config.example.env video_pipeline/.env   # 填 ARK_API_KEY、DOUBAO_LLM_MODEL 等
python -m video_pipeline.cli plan video_pipeline/examples/brief_qiulisgao.yaml
python -m video_pipeline.cli auto video_pipeline/examples/brief_qiulisgao.yaml --jianying
```

完整说明见 [video_pipeline/README.md](video_pipeline/README.md)。
