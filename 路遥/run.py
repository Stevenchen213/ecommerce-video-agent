"""命令行入口。

  # 只做检查 + 生成调用计划，不花蝉豆
  python run.py scripts/babao_qiegao.shots.json --person-id C-xxx --voice-id C-yyy \
      --brand 疆小娃 --fill ingredients_spoken=核桃、红枣、葡萄干 --dry-run

  # 真实调用
  export CHANJING_APP_ID=... CHANJING_SECRET_KEY=...
  python run.py scripts/babao_qiegao.shots.json --person-id C-xxx --voice-id C-yyy --brand 疆小娃 ...
"""
import argparse
import json
import logging

from pipeline.orchestrator import JobConfig, run


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("--person-id", required=True)
    ap.add_argument("--voice-id", required=True)
    ap.add_argument("--brand")
    ap.add_argument("--source", default="common", choices=["common", "customised"])
    ap.add_argument("--figure-type")
    ap.add_argument("--fill", action="append", default=[], help="占位符 key=value，可多次")
    ap.add_argument("--assets-dir", default="assets")
    ap.add_argument("--asset-library")
    ap.add_argument("--registry", default="authorized_avatars.json")
    ap.add_argument("--workdir", default="work")
    ap.add_argument("--output", default="renders/output.mp4")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--mock-avatar-video", help="本地联调用，跳过数字人接口")
    a = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    fills = dict(kv.split("=", 1) for kv in a.fill)
    result = run(JobConfig(
        script_path=a.script, person_id=a.person_id, voice_id=a.voice_id, brand=a.brand,
        source=a.source, figure_type=a.figure_type, fills=fills, assets_dir=a.assets_dir,
        asset_library=a.asset_library, registry=a.registry, workdir=a.workdir,
        output=a.output, dry_run=a.dry_run, mock_avatar_video=a.mock_avatar_video))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
