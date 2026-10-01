from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from video_pipeline.adapters.luyao_bridge import dump_converted_script, resolve_luyao_root
from video_pipeline.adapters.luyao_script import script_to_luyao_dict
from video_pipeline.pipeline import Pipeline
from video_pipeline.planner import plan_script
from video_pipeline.schema import load_script


def _print_result(result) -> None:
    payload = {
        "title": result.script_title,
        "mode": getattr(result, "mode", "b"),
        "output": str(result.output_path),
        "duration_sec": result.duration_sec,
        "library": {k: str(v) for k, v in result.library_paths.items()},
        "jobs": str(result.jobs_path),
    }
    if getattr(result, "extra", None):
        payload["extra"] = result.extra
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_validate(args: argparse.Namespace) -> int:
    script = load_script(args.script)
    plan = plan_script(script)
    print(f"OK title={script.title!r} shots={len(script.shots)}")
    print(f"  description={script.description!r}")
    print(f"  default_transition={script.default_transition}")
    print(f"  brand.enable={script.brand.enable}")
    print(f"  [1] feiying(数字人): {[s.id for s in plan.feiying_shots]}")
    print(f"  [1] chanjing(产品): {[s.id for s in plan.chanjing_shots]}")
    print(f"  [2] product_segments ({len(plan.product_segments)}):")
    for seg in plan.product_segments:
        print(f"      - {seg.id}: {seg.shot_ids}")
    print("  timeline:")
    for unit in plan.timeline:
        if unit.kind == "feiying":
            print(f"      · feiying {unit.shot.id if unit.shot else '?'}")
        else:
            seg = unit.segment
            print(f"      · product_segment {seg.id if seg else '?'}: {seg.shot_ids if seg else []}")
    if args.export_luyao:
        payload, id_map = script_to_luyao_dict(script)
        out = Path(args.export_luyao)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  exported luyao script → {out}")
        print(f"  id_map: {id_map.to_int}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    mode = args.mode
    output = args.output
    if mode in {"a", "cut", "切轨"} and output == "final.mp4":
        output = "mode_a_cut.mp4"
    if mode in {"b", "concat", "拼镜"} and output == "final.mp4":
        output = "mode_b_concat.mp4"
    _print_result(
        Pipeline().run(
            args.script,
            output_name=output,
            mode=mode,
            person_id=args.person_id,
            voice_id=args.voice_id,
            brand=args.brand,
            dry_run=args.dry_run,
            mock_avatar_video=args.mock_avatar_video,
        )
    )
    return 0


def cmd_export_luyao(args: argparse.Namespace) -> int:
    script = load_script(args.script)
    info = dump_converted_script(script, args.output)
    try:
        root = resolve_luyao_root()
        info["luyao_root"] = str(root)
    except Exception as e:
        info["luyao_root_error"] = str(e)
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


def cmd_assemble(args: argparse.Namespace) -> int:
    _print_result(Pipeline().assemble_only(args.script, output_name=args.output))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    print(json.dumps(Pipeline().status(args.script), ensure_ascii=False, indent=2))
    return 0


def cmd_retry(args: argparse.Namespace) -> int:
    path = Pipeline().retry_shot(args.script, args.shot_id)
    print(json.dumps({"shot_id": args.shot_id, "path": str(path)}, ensure_ascii=False, indent=2))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "video_pipeline.api:app",
        host=args.host,
        port=args.port,
        reload=False,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="video_pipeline", description="脚本驱动双平台视频组装")
    sub = p.add_subparsers(dest="command", required=True)

    v = sub.add_parser("validate", help="校验脚本并打印两步分类结果")
    v.add_argument("script", type=Path)
    v.add_argument(
        "--export-luyao",
        type=Path,
        default=None,
        help="同时导出路遥分镜 JSON（不调用 API）",
    )
    v.set_defaults(func=cmd_validate)

    r = sub.add_parser("run", help="生成并出片：mode=a 切轨 / mode=b 拼镜")
    r.add_argument("script", type=Path)
    r.add_argument("-o", "--output", default="final.mp4")
    r.add_argument(
        "--mode",
        default="b",
        choices=["a", "b", "cut", "concat", "切轨", "拼镜"],
        help="a=路遥切轨成片，b=主架构拼镜成片",
    )
    r.add_argument("--person-id", default=None, help="模式 A 数字人 ID")
    r.add_argument("--voice-id", default=None, help="模式 A 音色 ID")
    r.add_argument("--brand", default=None, help="模式 A 品牌（授权校验）")
    r.add_argument("--dry-run", action="store_true", help="模式 A：只检查+出 plan，不花钱")
    r.add_argument("--mock-avatar-video", default=None, help="模式 A：本地假数字人视频")
    r.set_defaults(func=cmd_run)

    e = sub.add_parser("export-luyao", help="仅导出路遥 JSON（对接联调）")
    e.add_argument("script", type=Path)
    e.add_argument("-o", "--output", type=Path, default=Path("tmp/luyao_script.json"))
    e.set_defaults(func=cmd_export_luyao)

    a = sub.add_parser("assemble", help="仅组装：要求 library 已有全部镜头")
    a.add_argument("script", type=Path)
    a.add_argument("-o", "--output", default="final.mp4")
    a.set_defaults(func=cmd_assemble)

    s = sub.add_parser("status", help="查看任务状态 / 缺镜情况")
    s.add_argument("script", type=Path, nargs="?", default=None)
    s.set_defaults(func=cmd_status)

    t = sub.add_parser("retry", help="重跑单个 shot 的生成")
    t.add_argument("script", type=Path)
    t.add_argument("shot_id")
    t.set_defaults(func=cmd_retry)

    srv = sub.add_parser("serve", help="启动 HTTP API")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8787)
    srv.set_defaults(func=cmd_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
