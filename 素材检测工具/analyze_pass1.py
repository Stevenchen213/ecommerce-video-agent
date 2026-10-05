# -*- coding: utf-8 -*-
"""素材检测第一遍：元数据 + 抽帧拼联系表（低 token 分类用）"""
import sys, io, os, re, json, subprocess
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
SRC = r"F:\AI项目\AI剪辑\素材视频"
OUT = r"E:\实习\AI项目\AI剪辑\_素材检测"
FRAMES = os.path.join(OUT, "frames")
os.makedirs(FRAMES, exist_ok=True)

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".MP4", ".MOV"}


def metadata(path):
    """用 ffmpeg -i 的 stderr 解析时长/分辨率/fps（免 ffprobe）"""
    p = subprocess.run([FFMPEG, "-i", path], capture_output=True, text=True, encoding="utf-8", errors="replace")
    info = p.stderr or ""
    dur = None
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", info)
    if m:
        dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    res = re.search(r"(\d{3,4})x(\d{3,4})", info)
    w, h = (int(res.group(1)), int(res.group(2))) if res else (None, None)
    fps_m = re.search(r"([\d.]+) fps", info)
    fps = float(fps_m.group(1)) if fps_m else None
    # 旋转标记（手机竖拍常见）
    rot = 90 if ("rotate" in info and "90" in info) else 0
    return dur, w, h, fps, rot


def grab_frame(path, t, out_jpg, height=240):
    subprocess.run([
        FFMPEG, "-y", "-ss", f"{t:.2f}", "-i", path,
        "-frames:v", "1", "-vf", f"scale=-2:{height}", "-q:v", "4", out_jpg,
    ], capture_output=True)


def main():
    files = sorted(f for f in os.listdir(SRC) if os.path.splitext(f)[1] in VIDEO_EXT)
    print(f"共 {len(files)} 条视频")
    records = []
    for i, fn in enumerate(files, 1):
        path = os.path.join(SRC, fn)
        size_mb = os.path.getsize(path) / 1048576
        dur, w, h, fps, rot = metadata(path)
        dur = dur or 0
        # 抽 3 帧：10% / 50% / 90%
        frame_paths = []
        for j, pct in enumerate([0.1, 0.5, 0.9]):
            fj = os.path.join(FRAMES, f"{i:02d}_{j}.jpg")
            if dur > 1:
                grab_frame(path, max(0.1, dur * pct - 0.5), fj)
            frame_paths.append(fj if os.path.exists(fj) else None)
        records.append({
            "idx": i, "file": fn, "size_mb": round(size_mb, 1),
            "duration_sec": round(dur, 1), "width": w, "height": h,
            "fps": fps, "rotate": rot, "frames": frame_paths,
        })
        print(f"[{i:02d}] {fn}  {size_mb:.0f}MB  {dur:.0f}s  {w}x{h}  rot={rot}")

    # 拼联系表：每张 8 条视频，每条一行（编号+文件名+3帧）
    font_path = r"C:\Windows\Fonts\msyh.ttc"
    font = ImageFont.truetype(font_path, 20)
    PER_SHEET = 8
    for sheet_i in range(0, len(records), PER_SHEET):
        batch = records[sheet_i:sheet_i + PER_SHEET]
        rows = []
        for r in batch:
            imgs = [Image.open(f) for f in r["frames"] if f]
            if not imgs:
                continue
            strip_w = sum(im.width for im in imgs) + 20 * len(imgs)
            label_w = 340
            row = Image.new("RGB", (label_w + strip_w, 260), (24, 24, 24))
            d = ImageDraw.Draw(row)
            d.text((8, 8), f"[{r['idx']:02d}] {r['file']}", font=font, fill=(255, 255, 120))
            d.text((8, 40), f"{r['duration_sec']}s {r['width']}x{r['height']}", font=font, fill=(160, 160, 160))
            x = label_w
            for im in imgs:
                row.paste(im, (x, 10))
                x += im.width + 20
            rows.append(row)
        if not rows:
            continue
        sheet_w = max(r.width for r in rows)
        sheet = Image.new("RGB", (sheet_w, len(rows) * 270 + 10), (0, 0, 0))
        y = 5
        for r in rows:
            sheet.paste(r, (0, y))
            y += 270
        out = os.path.join(OUT, f"sheet_{sheet_i // PER_SHEET + 1}.jpg")
        sheet.save(out, quality=82)
        print("联系表:", out)

    json.dump(records, open(os.path.join(OUT, "metadata.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("元数据已存:", os.path.join(OUT, "metadata.json"))


if __name__ == "__main__":
    main()
