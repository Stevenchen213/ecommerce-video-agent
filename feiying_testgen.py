# -*- coding: utf-8 -*-
"""飞影测试片生成：create_by_tts -> 轮询 -> 下载成片 -> 抽帧验证无幽灵字幕"""
import sys, io, os, json, time, requests, subprocess, shutil
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "https://hfw-api.hifly.cc"
TOKEN = os.environ.get("FEIYING_TOKEN", "").strip()
if not TOKEN:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
        TOKEN = winreg.QueryValueEx(k, "FEIYING_TOKEN")[0].strip()
H = {"Authorization": f"Bearer {TOKEN}"}

OUT = r"F:\AI项目\AI剪辑\_验证片"
os.makedirs(OUT, exist_ok=True)

TEST_TEXT = "大家好，今天给大家推荐一款好东西。这是我们精心挑选的，品质有保证，喜欢的朋友可以试试看。"
VOICE = "b0c66f97-4b39-46c3-81ff-33df16d8ac41"

AVATARS = {
    "书法背景干净版": "qbK4XQ1bdH0Of_vcczaSRA",
    "手持展示空手": "nnDAnInYNyK5YjsBs_VpWw",
}


def post(path, payload):
    r = requests.post(BASE + path, headers=H, json=payload, timeout=60)
    d = r.json()
    return d.get("data", d) if isinstance(d, dict) else d


def submit(name, avatar):
    d = post("/api/v2/hifly/video/create_by_tts", {
        "title": f"验证_{name}", "avatar": avatar, "voice": VOICE,
        "text": TEST_TEXT, "st_show": 0,
    })
    tid = d.get("task_id")
    print(f"[{name}] 已提交 task_id={tid}", flush=True)
    return tid


def wait_video(task_id, name, timeout_min=30):
    t0 = time.time()
    while time.time() - t0 < timeout_min * 60:
        r = requests.get(BASE + "/api/v2/hifly/video/task",
                         headers=H, params={"task_id": task_id}, timeout=30)
        d = r.json()
        d = d.get("data", d) if isinstance(d, dict) else {}
        status = d.get("status")
        if status == 3:
            return d.get("video_Url") or d.get("video_url")
        if status == 4:
            raise RuntimeError(f"[{name}] 生成失败: {json.dumps(d, ensure_ascii=False)}")
        print(f"[{name}] 生成中 status={status} {int(time.time()-t0)}s", flush=True)
        time.sleep(20)
    raise TimeoutError(name)


tasks = {name: submit(name, av) for name, av in AVATARS.items()}
for name, tid in tasks.items():
    url = wait_video(tid, name)
    fp = os.path.join(OUT, f"验证_{name}.mp4")
    r = requests.get(url, timeout=300)
    open(fp, "wb").write(r.content)
    print(f"[{name}] 成片已下载 {fp} ({len(r.content)//1048576}MB)", flush=True)

# 积分
r = requests.get(BASE + "/api/v2/hifly/account/credit", headers=H, timeout=30)
print("积分返回:", r.text[:200])
