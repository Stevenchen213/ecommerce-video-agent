"""命令行入口（数字人走飞影，蝉镜只做产品画面）。

  # 1. 只检查 + 生成调用计划 work/plan.json，不花蝉豆
  python run.py scripts/babao_qiegao.shots.json --person-id <飞影avatar_id> --voice-id <飞影声音ID> \\
      --brand 疆小娃 --fill ingredients_spoken=核桃、红枣、葡萄干 --dry-run

  # 2. 飞影侧按 plan.json 里 avatar.text 生成整条口播视频后，传入合成
  python run.py scripts/babao_qiegao.shots.json --person-id <飞影avatar_id> --brand 疆小娃 \\
      --avatar-video work/feiying_full.mp4

  # 只测蝉镜单个产品镜头（不需要数字人）
  python run.py --product-only images/box_front.jpg --prompt "包装盒静置在木桌上，镜头缓慢推近"
"""
import argparse
import json
import logging


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("script", nargs="?")
    ap.add_argument("--person-id", help="飞影 avatar_id，用于授权校验")
    ap.add_argument("--voice-id", default="", help="飞影克隆声音 ID，仅写入 plan")
    ap.add_argument("--brand")
    ap.add_argument("--fill", action="append", default=[], help="占位符 key=value，可多次")
    ap.add_argument("--assets-dir", default="assets")
    ap.add_argument("--asset-library")
    ap.add_argument("--registry", default="authorized_avatars.json")
    ap.add_argument("--workdir", default="work")
    ap.add_argument("--output", default="renders/output.mp4")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--avatar-video", help="飞影生成的整条口播数字人视频")
    ap.add_argument("--mock-avatar-video", help="同 --avatar-video（旧参数，保留兼容）")
    # 单镜头测试
    ap.add_argument("--product-only", nargs="+", metavar="IMAGE", help="只生成一个产品镜头")
    ap.add_argument("--prompt")
    ap.add_argument("--model")
    ap.add_argument("--duration", type=float)
    a = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    if a.product_only:
        from chanjing.product import gen_product
        if not a.prompt:
            ap.error("--product-only 需要同时给 --prompt")
        info = gen_product(a.product_only, a.prompt, f"{a.workdir}/product_test.mp4",
                           target_duration=a.duration, model_code=a.model)
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return

    if not a.script or not a.person_id:
        ap.error("整条成片需要 script 和 --person-id")
    from pipeline.orchestrator import JobConfig, run
    fills = dict(kv.split("=", 1) for kv in a.fill)
    result = run(JobConfig(
        script_path=a.script, person_id=a.person_id, voice_id=a.voice_id, brand=a.brand,
        fills=fills, assets_dir=a.assets_dir, asset_library=a.asset_library,
        registry=a.registry, workdir=a.workdir, output=a.output, dry_run=a.dry_run,
        avatar_video=a.avatar_video or a.mock_avatar_video))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
