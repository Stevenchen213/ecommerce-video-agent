"""剪映草稿导出（pyJianYingDraft）。

时间线结构：
  视频轨 main       每个镜头一段，按脚本顺序首尾相接
  音频轨 narration  产品镜头的旁白（数字人镜头自带声音，不重复铺）
  音频轨 bgm        assets/brand/ 里有 bgm.* 才加
  文本轨 subtitle   每镜头的 text 作为字幕，可在剪映里直接改

每个镜头的时长：
  数字人镜头 → 视频本身时长（音频驱动生成，口型和声音已对齐）
  产品镜头   → 旁白时长；没有旁白就用素材时长
  素材比旁白短时会自动放慢（剪映里显示为变速），低于 0.7 倍会打印提醒

注意：草稿里引用的是素材的绝对路径，导出后不要移动 / 删除 library/ 和 assets/。
兼容两种 pyJianYingDraft 写法（自动识别，不用改代码）：
  A. append_track(TrackSpec(...)) + add_segment(seg, track=轨道)  ← 你们本机实测可用的写法
  B. add_track(TrackType, 名字)   + add_segment(seg, 名字)
音量 / 字幕样式这些可选参数，若装的版本不支持会自动退回基础写法，并打印提示。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from video_pipeline.compose.concat import probe
from video_pipeline.schema import Platform, Script, Shot

SEC = 1_000_000          # pyJianYingDraft 时间单位：微秒
_EPS = SEC // 30         # 留一帧余量，防止 source 区间超出素材实际长度而报错


def _us(sec: float) -> int:
    return int(round(sec * SEC))


def _dur(path: Path) -> float:
    d = probe(path).duration
    if not d:
        raise RuntimeError(f"读不出时长: {path}")
    return float(d)


def _find_bgm(brand_dir: Path | None, bgm_file: str | None) -> Path | None:
    if not brand_dir:
        return None
    if bgm_file:
        p = Path(bgm_file)
        p = p if p.is_absolute() else brand_dir / p
        return p if p.exists() else None
    for ext in ("mp3", "wav", "m4a", "aac"):
        p = brand_dir / f"bgm.{ext}"
        if p.exists():
            return p
    return None


class _Draft:
    """屏蔽 pyJianYingDraft 版本差异的薄封装。"""

    def __init__(self, lib, sf):
        self.lib, self.sf = lib, sf
        self.tracks: dict[str, object] = {}
        self.use_spec = hasattr(lib, "TrackSpec") and hasattr(sf, "append_track")

    def track(self, kind: str, name: str) -> None:
        ttype = getattr(self.lib.TrackType, kind)
        if self.use_spec:
            self.tracks[name] = self.sf.append_track(self.lib.TrackSpec(ttype, name=name))
        else:
            self.sf.add_track(ttype, name)
            self.tracks[name] = name

    def add(self, seg, name: str) -> None:
        if self.use_spec:
            self.sf.add_segment(seg, track=self.tracks[name])
        else:
            self.sf.add_segment(seg, self.tracks[name])

    def media(self, cls_name: str, path: str, target, source=None, volume: float | None = None):
        cls = getattr(self.lib, cls_name)
        kw = {"material": path, "target_timerange": target}
        if source is not None:
            kw["source_timerange"] = source
        if volume is not None:
            try:
                return cls(**kw, volume=volume)
            except TypeError:
                print(f"  [剪映] 当前版本 {cls_name} 不支持 volume，跳过静音设置（可在剪映里手动静音）")
        return cls(**kw)

    def text(self, content: str, timerange):
        lib = self.lib
        try:
            return lib.TextSegment(
                text=content, timerange=timerange,
                style=lib.TextStyle(size=8.0, align=1, auto_wrapping=True),
                clip_settings=lib.ClipSettings(transform_y=-0.72),
            )
        except (TypeError, AttributeError):
            return lib.TextSegment(text=content, timerange=timerange)


def export_jianying_draft(
    script: Script,
    library_paths: dict[str, Path],
    *,
    draft_root: Path,
    draft_name: str,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    narration_for: Callable[[Shot], Path | None] = lambda s: None,
    brand_dir: Path | None = None,
    subtitles: bool = True,
    allow_replace: bool = True,
) -> Path:
    import pyJianYingDraft as draft

    draft_root.mkdir(parents=True, exist_ok=True)
    folder = draft.DraftFolder(str(draft_root))
    try:
        sf = folder.create_draft(draft_name, width, height, fps=fps, allow_replace=allow_replace)
    except TypeError:  # 部分版本没有 allow_replace：同名草稿请先在剪映里删掉
        sf = folder.create_draft(draft_name, width, height, fps=fps)
    d = _Draft(draft, sf)

    d.track("video", "视频轨")
    d.track("audio", "配音轨")
    if subtitles:
        d.track("text", "字幕轨")

    cursor = 0  # 微秒
    for shot in script.shots:
        clip = library_paths.get(shot.id)
        if clip is None or not Path(clip).exists():
            raise FileNotFoundError(f"剪映导出：缺少镜头 {shot.id}（{clip}）")
        clip = Path(clip).resolve()
        clip_us = _us(_dur(clip)) - _EPS

        is_avatar = shot.platform == Platform.FEIYING
        narr = None if is_avatar else narration_for(shot)

        if is_avatar or narr is None:
            target_us = clip_us
            source_us = clip_us
        else:
            narr = Path(narr).resolve()
            target_us = _us(_dur(narr)) - SEC // 100  # 留 10ms，防止超出音频实际长度
            source_us = min(clip_us, target_us)
            speed = source_us / target_us
            if speed < 0.7:
                print(f"  [剪映] {shot.id} 素材比旁白短很多，放慢到 {speed:.2f}x，建议补素材或改文案",
                      flush=True)

        seg = d.media(
            "VideoSegment", str(clip),
            draft.Timerange(cursor, target_us),
            source=draft.Timerange(0, source_us),
            # 产品素材的现场声（风扇声、拆包声）静音，声音以旁白为准
            volume=None if is_avatar or narr is None else 0.0,
        )
        d.add(seg, "视频轨")

        if narr is not None:
            d.add(d.media("AudioSegment", str(narr), draft.Timerange(cursor, target_us),
                          source=draft.Timerange(0, target_us)), "配音轨")

        if subtitles and shot.text.strip():
            d.add(d.text(shot.text.strip(), draft.Timerange(cursor, target_us)), "字幕轨")

        print(f"  [剪映] {shot.id:<16} {cursor / SEC:6.2f}s → {(cursor + target_us) / SEC:6.2f}s"
              f"  {'数字人' if is_avatar else '产品'}  {clip.name}", flush=True)
        cursor += target_us

    bgm = _find_bgm(brand_dir, script.brand.bgm_file) if script.brand.mix_bgm else None
    if bgm is not None:
        d.track("audio", "BGM轨")
        bgm_us = min(_us(_dur(bgm)) - _EPS, cursor)
        d.add(d.media("AudioSegment", str(bgm.resolve()), draft.Timerange(0, bgm_us),
                      source=draft.Timerange(0, bgm_us), volume=script.brand.bgm_volume), "BGM轨")

    sf.save()
    out = draft_root / draft_name
    print(f"\n✅ 剪映草稿已生成：{draft_name}（{cursor / SEC:.1f}s，{len(script.shots)} 个镜头）\n"
          f"   打开剪映 → 草稿列表里就能看到", flush=True)
    return out
