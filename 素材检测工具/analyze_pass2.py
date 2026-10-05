# -*- coding: utf-8 -*-
"""素材检测第二遍：卡顿(freezedetect) + 音量(volumedetect) + 长静音(silencedetect) + 烧录字幕检测"""
import sys, io, os, re, json, subprocess, shutil
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import imageio_ffmpeg
import numpy as np
from PIL import Image

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
SRC = r"F:\AI项目\AI剪辑\素材视频"
OUT = r"E:\实习\AI项目\AI剪辑\_素材检测"
SUBPROOF = os.path.join(OUT, "_字幕证据")

VIDEO_EXT = {".mp4", ".mov", ".m4v"}
SHORTLIST = sorted(f for f in os.listdir(SRC) if os.path.splitext(f)[1].lower() in VIDEO_EXT)


def run_filter(path, vf=None, af=None):
    cmd = [FFMPEG, "-hide_banner", "-i", path]
    if vf:
        cmd += ["-vf", vf]
    if af:
        cmd += ["-af", af]
    cmd += ["-f", "null", "-"]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.stderr or ""


def analyze_freeze(path):
    err = run_filter(path, vf="freezedetect=n=0.001:d=0.5", af=None)
    freezes = []
    cur = {}
    for line in err.splitlines():
        m = re.search(r"freeze_start: ([\d.]+)", line)
        if m:
            cur = {"start": float(m.group(1))}
        m = re.search(r"freeze_end: ([\d.]+)", line)
        if m:
            cur["end"] = float(m.group(1))
        m = re.search(r"freeze_duration: ([\d.]+)", line)
        if m:
            cur["duration"] = float(m.group(1))
            freezes.append(cur)
            cur = {}
    return freezes


def analyze_volume(path):
    err = run_filter(path, af="volumedetect")
    mean = re.search(r"mean_volume: ([-\d.]+) dB", err)
    mx = re.search(r"max_volume: ([-\d.]+) dB", err)
    return (float(mean.group(1)) if mean else None, float(mx.group(1)) if mx else None)


def analyze_silence(path):
    err = run_filter(path, af="silencedetect=n=-35dB:d=3")
    sils = []
    for m in re.finditer(r"silence_start: ([\d.]+)", err):
        sils.append({"start": float(m.group(1))})
    for i, m in enumerate(re.finditer(r"silence_end: ([\d.]+) \| silence_duration: ([\d.]+)", err)):
        if i < len(sils):
            sils[i]["end"] = float(m.group(1))
            sils[i]["duration"] = float(m.group(2))
    return sils


def analyze_subtitles(path, fn):
    """烧录字幕启发式：底部 30% 区域内「亮像素(>190)且 3px 邻域有暗像素(<100)」
    即亮字+深色描边的占比。阈值 0.012 由已知样本校准：有字幕 ≥0.018，无字幕 ≤0.009。
    命中帧占比 >20% 判有字幕；命中时把最多 3 张底部条带存到 _字幕证据/ 供人工抽查。"""
    tmp = os.path.join(OUT, "_sub_tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-i", path,
                    "-vf", "fps=1/3,scale=320:-2", "-frames:v", "50",
                    os.path.join(tmp, "f%03d.jpg")], capture_output=True)
    flagged, total = 0, 0
    proof = []
    for f in sorted(os.listdir(tmp)):
        a = np.asarray(Image.open(os.path.join(tmp, f)).convert("L"), dtype=np.float32)
        h = a.shape[0]
        band = a[int(h * 0.70):]
        bright = band > 190
        dark = band < 100
        d_up = np.zeros_like(dark); d_up[3:] = dark[:-3]
        d_dn = np.zeros_like(dark); d_dn[:-3] = dark[3:]
        stroke = (bright & (d_up | d_dn)).sum() / band.size
        total += 1
        if stroke > 0.012:
            flagged += 1
            if len(proof) < 3:
                os.makedirs(SUBPROOF, exist_ok=True)
                dst = os.path.join(SUBPROOF, f"{os.path.splitext(fn)[0]}_{f}")
                Image.open(os.path.join(tmp, f)).crop(
                    (0, int(h * 0.70), a.shape[1], h)).save(dst, quality=80)
                proof.append(dst)
    shutil.rmtree(tmp, ignore_errors=True)
    ratio = flagged / total if total else 0
    return {"has_subtitles": ratio > 0.20, "flagged_ratio": round(ratio, 2),
            "sampled": total, "proof": proof}


results = {}
for fn in SHORTLIST:
    path = os.path.join(SRC, fn)
    print(f"=== {fn} ===")
    freezes = analyze_freeze(path)
    mean_v, max_v = analyze_volume(path)
    sils = analyze_silence(path)
    total_freeze = sum(f.get("duration", 0) for f in freezes)
    total_sil = sum(s.get("duration", 0) for s in sils)
    sub = analyze_subtitles(path, fn)
    print(f"  卡顿: {len(freezes)} 次, 共 {total_freeze:.1f}s", freezes[:5] if freezes else "")
    print(f"  音量: mean={mean_v} dB  max={max_v} dB")
    print(f"  长静音(>3s): {len(sils)} 段, 共 {total_sil:.1f}s", sils[:5] if sils else "")
    print(f"  烧录字幕: {'⚠️ 有' if sub['has_subtitles'] else '无'} (命中帧占比 {sub['flagged_ratio']}, 抽样 {sub['sampled']} 帧)")
    results[fn] = {
        "freezes": freezes, "total_freeze_sec": round(total_freeze, 1),
        "mean_volume_db": mean_v, "max_volume_db": max_v,
        "silences": sils, "total_silence_sec": round(total_sil, 1),
        "has_subtitles": sub["has_subtitles"], "subtitle_flagged_ratio": sub["flagged_ratio"],
    }

json.dump(results, open(os.path.join(OUT, "quality.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\n质检报告已存:", os.path.join(OUT, "quality.json"))
