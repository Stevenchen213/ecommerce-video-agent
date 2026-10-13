from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from video_pipeline.compose import (
    apply_brand,
    apply_overlay,
    concat_segments,
    mux_narration,
    resolve_overlay_image,
    transitions_from_shots,
)
from video_pipeline.config import Settings, load_settings
from video_pipeline.jobs import JobRecord, JobStore
from video_pipeline.library_check import check_library, expected_library_path
from video_pipeline.planner import ProductSegment, plan_script
from video_pipeline.providers import (
    ChanjingProvider,
    FeiyingProvider,
    MockChanjingProvider,
    MockFeiyingProvider,
    VideoProvider,
)
from video_pipeline.schema import Platform, Script, Shot, load_script
from video_pipeline.storage import LocalStorage


@dataclass
class PipelineResult:
    script_title: str
    output_path: Path
    duration_sec: float | None
    library_paths: dict[str, Path]
    jobs_path: Path
    mode: str = "b"
    extra: dict | None = None


class Pipeline:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or load_settings()
        self.storage = LocalStorage()
        self.jobs = JobStore(self.settings.jobs_dir / "state.json")
        self.feiying: VideoProvider
        self.chanjing: VideoProvider
        if self.settings.use_mock:
            self.feiying = MockFeiyingProvider(
                self.settings.width, self.settings.height, self.settings.fps
            )
            self.chanjing = MockChanjingProvider(
                self.settings.width, self.settings.height, self.settings.fps
            )
        else:
            self.feiying = FeiyingProvider(
                self.settings.feiying_api_base, self.settings.feiying_api_key
            )
            self.chanjing = ChanjingProvider(
                self.settings.chanjing_api_base,
                self.settings.chanjing_api_key,
                app_id=self.settings.chanjing_app_id,
                secret_key=self.settings.chanjing_secret_key,
                luyao_root=self.settings.luyao_root,
            )

    def _provider_for(self, platform: Platform) -> VideoProvider:
        if platform == Platform.FEIYING:
            return self.feiying
        if platform == Platform.CHANJING:
            return self.chanjing
        raise ValueError(platform)

    def _library_path(self, shot: Shot) -> Path:
        return expected_library_path(self.settings.library_dir, shot)

    def _narration_path(self, shot: Shot) -> Path:
        """旁白音轨 sidecar：产品镜头（无 person_id）配李亚鹏克隆声音。"""
        return self.settings.library_dir / f"{shot.id}_narration.wav"

    def _needs_narration(self, shot: Shot) -> bool:
        return not shot.person_id and bool(shot.text.strip())

    def _generate_narration(self, shot: Shot) -> None:
        if getattr(self, "_skip_narration_tts", False):
            return  # 完整音轨模式：旁白直接从整条音轨里切，不再单独 TTS
        if not self._needs_narration(shot):
            return
        gen_audio = getattr(self.feiying, "generate_audio", None)
        if gen_audio is None:
            return  # mock 模式没有真 TTS，跳过
        try:
            gen_audio(shot.text, self._narration_path(shot), voice_id=shot.voice_id or "")
        except Exception as e:
            print(f"[旁白] shot={shot.id} 生成失败（不阻断主流程）: {e}")

    def _ensure_dirs(self) -> None:
        self.storage.ensure_dir(self.settings.library_dir)
        self.storage.ensure_dir(self.settings.output_dir)
        self.storage.ensure_dir(self.settings.brand_dir)
        self.storage.ensure_dir(self.settings.jobs_dir)
        self.storage.ensure_dir(self.settings.tmp_dir)

    def generate_shot(self, shot: Shot) -> Path:
        out = self._library_path(shot)
        self.jobs.upsert(
            JobRecord(shot_id=shot.id, platform=shot.platform.value, status="running")
        )
        try:
            provider = self._provider_for(shot.platform)
            result = provider.generate(shot, out)
            self.storage.put_file(result.local_path, out)
            self.jobs.upsert(
                JobRecord(
                    shot_id=shot.id,
                    platform=shot.platform.value,
                    status="done",
                    local_path=str(out),
                    task_id=result.task_id,
                )
            )
            return out
        except Exception as e:
            self.jobs.upsert(
                JobRecord(
                    shot_id=shot.id,
                    platform=shot.platform.value,
                    status="failed",
                    error=str(e),
                )
            )
            raise

    def generate_product_segment(self, segment: ProductSegment) -> dict[str, Path]:
        """第二步产物：同段产品镜带连贯上下文生成，仍按 shot_id 落库。"""
        paths: dict[str, Path] = {}
        for shot in segment.shots:
            self.jobs.upsert(
                JobRecord(
                    shot_id=shot.id,
                    platform=shot.platform.value,
                    status="running",
                )
            )
        try:
            results = self.chanjing.generate_segment(segment, self._library_path)
            for shot, result in zip(segment.shots, results, strict=True):
                out = self._library_path(shot)
                self.storage.put_file(result.local_path, out)
                self._generate_narration(shot)
                self.jobs.upsert(
                    JobRecord(
                        shot_id=shot.id,
                        platform=shot.platform.value,
                        status="done",
                        local_path=str(out),
                        task_id=result.task_id,
                    )
                )
                paths[shot.id] = out
            return paths
        except Exception as e:
            for shot in segment.shots:
                if shot.id not in paths:
                    self.jobs.upsert(
                        JobRecord(
                            shot_id=shot.id,
                            platform=shot.platform.value,
                            status="failed",
                            error=str(e),
                        )
                    )
            raise

    def generate_all_full_track(self, script: Script) -> dict[str, Path]:
        """完整音轨模式：整脚本一次 TTS → 切分 → 数字人镜头音频驱动、产品镜头铺音轨。

        开启方式：脚本 extra.voiceover = "full_track"。
        产物：tmp/voiceover/timeline.json（每镜头精确起止，供剪辑侧用）。
        """
        from video_pipeline.voiceover import build_voiceover

        plan = plan_script(script)
        self._skip_narration_tts = True
        track = build_voiceover(script, self.feiying, self.settings.tmp_dir / "voiceover")
        seg_by_id = {s.shot_id: s for s in track.segments}
        paths: dict[str, Path] = {}
        for unit in plan.timeline:
            if unit.kind == "feiying":
                shot = unit.shot
                assert shot is not None
                seg = seg_by_id.get(shot.id)
                if seg is None:
                    raise ValueError(f"镜头 {shot.id} 没有文案，无法走完整音轨模式")
                out = self._library_path(shot)
                self.jobs.upsert(JobRecord(shot_id=shot.id, platform=shot.platform.value, status="running"))
                try:
                    result = self.feiying.generate_by_audio(shot, seg.file, out)
                    self.jobs.upsert(JobRecord(shot_id=shot.id, platform=shot.platform.value,
                                               status="done", local_path=str(out), task_id=result.task_id))
                    paths[shot.id] = out
                except Exception as e:
                    self.jobs.upsert(JobRecord(shot_id=shot.id, platform=shot.platform.value,
                                               status="failed", error=str(e)))
                    raise
            else:
                assert unit.segment is not None
                existing = {s.id: self._library_path(s) for s in unit.segment.shots}
                if all(p.exists() for p in existing.values()):
                    print(f"[跳过] 产品段 {unit.segment.id} 全部镜头已在库中", flush=True)
                    paths.update(existing)
                else:
                    paths.update(self.generate_product_segment(unit.segment))
                # 产品镜头：直接铺完整音轨里对应的那段（不再单独 TTS）
                for shot in unit.segment.shots:
                    seg = seg_by_id.get(shot.id)
                    if seg is not None:
                        self._narration_path(shot).write_bytes(seg.file.read_bytes())

        missing = [s.id for s in script.shots if s.id not in paths or not paths[s.id].exists()]
        if missing:
            raise FileNotFoundError(f"以下必用镜头未生成: {missing}")
        return paths

    def generate_all(self, script: Script) -> dict[str, Path]:
        if script.extra.get("voiceover") == "full_track":
            return self.generate_all_full_track(script)
        plan = plan_script(script)
        planned_ids = {s.id for s in plan.all_shots}
        script_ids = {s.id for s in script.shots}
        if planned_ids != script_ids:
            raise RuntimeError("Planner 分流结果与脚本镜头不一致")

        paths: dict[str, Path] = {}
        for unit in plan.timeline:
            if unit.kind == "feiying":
                assert unit.shot is not None
                paths[unit.shot.id] = self.generate_shot(unit.shot)
            elif unit.kind == "product_segment":
                assert unit.segment is not None
                paths.update(self.generate_product_segment(unit.segment))
            else:
                raise ValueError(f"未知 timeline unit: {unit.kind}")

        missing = [s.id for s in script.shots if s.id not in paths or not paths[s.id].exists()]
        if missing:
            raise FileNotFoundError(f"以下必用镜头未生成: {missing}")
        return paths

    def resolve_library(self, script: Script) -> dict[str, Path]:
        check = check_library(script, self.settings.library_dir)
        check.raise_if_missing()
        return check.present

    def assemble(
        self,
        script: Script,
        library_paths: dict[str, Path] | None = None,
        output: Path | None = None,
    ) -> PipelineResult:
        self._ensure_dirs()
        paths = library_paths or self.resolve_library(script)
        output = output or (self.settings.output_dir / "final.mp4")
        work = self.settings.tmp_dir / "assemble"
        # 再次按脚本顺序缺镜检查；有旁白 sidecar 的镜头先铺上音轨；
        # 有 overlay_asset_refs 的镜头叠产品图（素材从 root/assets/ 解析）
        ordered: list[Path] = []
        assets_by_id = {a.asset_id: a for a in script.assets}
        assets_dir = self.settings.root / "assets"
        for i, shot in enumerate(script.shots):
            p = paths.get(shot.id) or self._library_path(shot)
            if not p.exists():
                raise FileNotFoundError(f"组装失败，缺少必用镜头 {shot.id}: {p}")
            narr = self._narration_path(shot)
            if self._needs_narration(shot) and narr.exists():
                p = mux_narration(p, narr, work / f"narr_{i:03d}_{p.stem}.mp4")
            if shot.overlay_asset_refs:
                img = resolve_overlay_image(
                    shot.overlay_asset_refs[0], assets_by_id, assets_dir, work, shot.id
                )
                if img:
                    p = apply_overlay(
                        p, img, work / f"ovr_{i:03d}_{shot.id}.mp4",
                        self.settings.width, self.settings.height,
                    )
                else:
                    print(f"[叠加] shot={shot.id} 素材 {shot.overlay_asset_refs[0]} 找不到，跳过")
            ordered.append(p)

        transitions, fades = transitions_from_shots(
            script.shots, default=script.default_transition
        )
        raw_out = work / "concat_raw.mp4"
        result = concat_segments(
            ordered,
            raw_out,
            work_dir=work,
            width=self.settings.width,
            height=self.settings.height,
            fps=self.settings.fps,
            transitions=transitions,
            fade_durations=fades,
        )

        branded = apply_brand(
            result.output_path,
            output,
            self.settings.brand_dir,
            script.brand,
            work_dir=self.settings.tmp_dir / "brand",
        )
        from video_pipeline.compose.concat import probe

        info = probe(branded)
        return PipelineResult(
            script_title=script.title,
            output_path=branded,
            duration_sec=info.duration,
            library_paths=paths,
            jobs_path=self.jobs.path,
        )

    def assemble_only(
        self,
        script_path: str | Path,
        output_name: str = "final.mp4",
    ) -> PipelineResult:
        """跳过生成：要求 library 已有全部必用镜头。"""
        script = load_script(script_path)
        self._ensure_dirs()
        paths = self.resolve_library(script)
        return self.assemble(script, paths, self.settings.output_dir / output_name)

    def run(
        self,
        script_path: str | Path,
        output_name: str = "final.mp4",
        mode: str = "b",
        *,
        person_id: str | None = None,
        voice_id: str | None = None,
        brand: str | None = None,
        dry_run: bool = False,
        mock_avatar_video: str | None = None,
    ) -> PipelineResult:
        """
        mode=b：主架构拼镜（各镜落库再拼接）
        mode=a：路遥切轨（整段口播一次生成再切开）；只读调用她的 orchestrator
        """
        mode = (mode or "b").lower()
        if mode in {"b", "concat", "拼镜"}:
            script = load_script(script_path)
            self._ensure_dirs()
            library_paths = self.generate_all(script)
            result = self.assemble(
                script, library_paths, self.settings.output_dir / output_name
            )
            result.mode = "b"
            return result
        if mode in {"a", "cut", "切轨"}:
            return self.run_mode_a(
                script_path,
                output_name=output_name,
                person_id=person_id,
                voice_id=voice_id,
                brand=brand,
                dry_run=dry_run,
                mock_avatar_video=mock_avatar_video,
            )
        raise ValueError(f"未知 mode={mode!r}，请用 a（切轨）或 b（拼镜）")

    def run_mode_a(
        self,
        script_path: str | Path,
        output_name: str = "mode_a_cut.mp4",
        *,
        person_id: str | None = None,
        voice_id: str | None = None,
        brand: str | None = None,
        dry_run: bool = False,
        mock_avatar_video: str | None = None,
    ) -> PipelineResult:
        from video_pipeline.adapters.luyao_bridge import run_mode_a

        script = load_script(script_path)
        self._ensure_dirs()
        pid = person_id or self.settings.default_person_id
        vid = voice_id or self.settings.default_voice_id
        if not pid or not vid:
            raise ValueError("模式 A 需要 person_id 与 voice_id（CLI 或 DEFAULT_* 环境变量）")

        out = self.settings.output_dir / output_name
        work = self.settings.tmp_dir / "mode_a"
        result = run_mode_a(
            script,
            workdir=work,
            output=out,
            person_id=pid,
            voice_id=vid,
            brand=brand or script.brand_name,
            dry_run=dry_run,
            mock_avatar_video=mock_avatar_video,
            luyao_root=self.settings.luyao_root or None,
        )
        if not result.ok and not dry_run:
            raise RuntimeError(f"模式 A 失败 stage={result.stage}: {result.raw}")

        out_path = result.output_path or result.plan_path or result.luyao_script_path
        return PipelineResult(
            script_title=script.title,
            output_path=out_path,
            duration_sec=(result.raw or {}).get("duration"),
            library_paths={},
            jobs_path=self.jobs.path,
            mode="a",
            extra={
                "stage": result.stage,
                "luyao_script": str(result.luyao_script_path),
                "plan": str(result.plan_path) if result.plan_path else None,
                "id_map": result.id_map.to_int,
                "raw": result.raw,
            },
        )

    def retry_shot(self, script_path: str | Path, shot_id: str) -> Path:
        script = load_script(script_path)
        shot = next((s for s in script.shots if s.id == shot_id), None)
        if not shot:
            raise KeyError(f"脚本中不存在 shot_id={shot_id}")
        self._ensure_dirs()
        return self.generate_shot(shot)

    def status(self, script_path: str | Path | None = None) -> dict:
        self.jobs.reload()
        jobs = [j.__dict__ for j in self.jobs.list_all()]
        payload: dict = {"jobs": jobs, "jobs_path": str(self.jobs.path)}
        if script_path:
            script = load_script(script_path)
            check = check_library(script, self.settings.library_dir)
            payload["library_ok"] = check.ok
            payload["missing"] = [
                {
                    "shot_id": m.shot_id,
                    "platform": m.platform,
                    "expected_path": str(m.expected_path),
                }
                for m in check.missing
            ]
            payload["present"] = {k: str(v) for k, v in check.present.items()}
        return payload
