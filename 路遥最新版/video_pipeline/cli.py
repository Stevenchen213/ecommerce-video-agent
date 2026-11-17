from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from video_pipeline.pipeline import Pipeline
from video_pipeline.planner import plan_script
from video_pipeline.schema import load_script


def _print_result(result) -> None:
    payload = {
        "title": result.script_title,
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
    print(f"  [1] doubao(产品): {[s.id for s in plan.doubao_shots]}")
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
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    _print_result(Pipeline().run(args.script, output_name=args.output, jianying=args.jianying))
    return 0


def _llm_chat():
    from video_pipeline.config import load_settings
    from video_pipeline.planner.llm import DoubaoChat

    st = load_settings()
    return st, DoubaoChat(st.ark_api_key, st.doubao_llm_model, st.ark_base_url)


def _plan(args: argparse.Namespace) -> Path:
    from video_pipeline.planner.llm import dump_script_yaml, load_brief, plan_with_llm

    st, chat = _llm_chat()
    brief = load_brief(args.brief)
    script, report = plan_with_llm(
        brief, chat,
        assets_dir=st.root / "assets",
        max_rounds=st.doubao_llm_max_rounds,
        max_seedance=st.seedance_max_calls,
        review=not args.no_review,
    )
    out = args.output or (st.root / "scripts" / f"{Path(args.brief).stem}_script.yaml")
    dump_script_yaml(script, Path(out), report)
    print(json.dumps({"script": str(out), **report.to_dict()}, ensure_ascii=False, indent=2))
    return Path(out)


def cmd_plan(args: argparse.Namespace) -> int:
    _plan(args)
    return 0


def cmd_auto(args: argparse.Namespace) -> int:
    script_path = _plan(args)
    print(f"\n[自动] 脚本已生成 → {script_path}，开始生成镜头并出片…\n")
    _print_result(Pipeline().run(script_path, output_name=f"{script_path.stem}.mp4",
                                 jianying=args.jianying))
    return 0


def cmd_describe_assets(args: argparse.Namespace) -> int:
    from video_pipeline.planner.llm import describe_assets

    st, chat = _llm_chat()
    n = describe_assets(chat, st.root / "assets", args.product, overwrite=args.overwrite)
    print(f"已更新 {n} 条素材描述 → {st.root / 'assets' / 'asset_index.json'}（原文件备份为 .bak）")
    return 0


def cmd_export_jianying(args: argparse.Namespace) -> int:
    draft = Pipeline().export_jianying(args.script, draft_name=args.name)
    print(json.dumps({"jianying_draft": str(draft)}, ensure_ascii=False, indent=2))
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
    p = argparse.ArgumentParser(prog="video_pipeline", description="AI 带货视频自动剪辑：豆包规划 + 素材库 / Seedance + 数字人 + 剪映草稿")
    sub = p.add_subparsers(dest="command", required=True)

    v = sub.add_parser("validate", help="校验脚本并打印两步分类结果")
    v.add_argument("script", type=Path)
    v.set_defaults(func=cmd_validate)

    r = sub.add_parser("run", help="按脚本生成全部镜头并拼接成片")
    r.add_argument("script", type=Path)
    r.add_argument("-o", "--output", default="final.mp4")
    r.add_argument("--jianying", action="store_true", help="同时生成剪映草稿")
    r.set_defaults(func=cmd_run)

    pl = sub.add_parser("plan", help="豆包规划：产品简报 → 带货脚本 YAML（可先人工检查）")
    pl.add_argument("brief", type=Path, help="产品简报 YAML，见 examples/brief_qiulisgao.yaml")
    pl.add_argument("-o", "--output", type=Path, default=None, help="默认 scripts/<简报名>_script.yaml")
    pl.add_argument("--no-review", action="store_true", help="跳过豆包审核（省一次调用）")
    pl.set_defaults(func=cmd_plan)

    au = sub.add_parser("auto", help="一条龙：豆包规划 → 素材库/Seedance/数字人 → 成片")
    au.add_argument("brief", type=Path)
    au.add_argument("-o", "--output", type=Path, default=None, help="规划出的脚本保存位置")
    au.add_argument("--no-review", action="store_true")
    au.add_argument("--jianying", action="store_true", help="同时生成剪映草稿")
    au.set_defaults(func=cmd_auto)

    da = sub.add_parser("describe-assets", help="豆包看素材截帧，自动补画面描述和标签")
    da.add_argument("--product", required=True, help="产品名，如 秋梨糕")
    da.add_argument("--overwrite", action="store_true", help="已有描述的也重写")
    da.set_defaults(func=cmd_describe_assets)

    j = sub.add_parser("export-jianying", help="把 library 里已有镜头写成剪映草稿（不调 API）")
    j.add_argument("script", type=Path)
    j.add_argument("--name", default=None, help="草稿名，默认用脚本 title")
    j.set_defaults(func=cmd_export_jianying)


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
    try:
        return args.func(args)
    except (ValueError, FileNotFoundError, RuntimeError, KeyError) as e:
        if os.getenv("VIDEO_PIPELINE_DEBUG"):
            raise
        print(f"\n❌ {type(e).__name__}: {e}\n（设置 VIDEO_PIPELINE_DEBUG=1 可看完整报错）", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
