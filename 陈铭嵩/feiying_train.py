# -*- coding: utf-8 -*-
"""飞影数字人训练：上传本地视频 -> create_by_video -> 轮询任务 -> 记录 avatar ID

用法:  python feiying_train.py <视频路径> <形象名称>
需要先设置环境变量 FEIYING_TOKEN
"""
import sys, io, os, json, time, requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "https://hfw-api.hifly.cc"
TOKEN = os.environ.get("FEIYING_TOKEN", "").strip()
if not TOKEN:
    print("错误：未设置 FEIYING_TOKEN 环境变量")
    sys.exit(1)
H = {"Authorization": f"Bearer {TOKEN}"}
RECORD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_avatars.json")


def post(path, payload):
    r = requests.post(BASE + path, headers=H, json=payload, timeout=60)
    r.raise_for_status()
    d = r.json()
    if "code" in d and d["code"] != 0:
        raise RuntimeError(f"{path} 失败: {json.dumps(d, ensure_ascii=False)}")
    return d.get("data", d)


def upload(local_path):
    ext = os.path.splitext(local_path)[1].lstrip(".")
    d = post("/api/v2/hifly/tool/create_upload_url", {"file_extension": ext})
    with open(local_path, "rb") as f:
        r = requests.put(d["upload_url"], data=f,
                         headers={"Content-Type": d["content_type"]}, timeout=600)
        r.raise_for_status()
    print(f"  上传完成 file_id={d['file_id']}")
    return d["file_id"]


def train(title, file_id):
    d = post("/api/v2/hifly/avatar/create_by_video", {"title": title, "file_id": file_id})
    task_id = d.get("task_id") or d.get("data", {}).get("task_id")
    print(f"  训练任务已提交 task_id={task_id}")
    return task_id


def wait_task(task_id, timeout_min=40):
    t0 = time.time()
    while time.time() - t0 < timeout_min * 60:
        r = requests.get(BASE + "/api/v2/hifly/avatar/task",
                         headers=H, params={"task_id": task_id}, timeout=30)
        d = r.json()
        d = d.get("data", d) if isinstance(d, dict) else {}
        status = d.get("status")
        if status == 3:
            return d.get("avatar")
        if status == 4:
            raise RuntimeError(f"训练失败: {json.dumps(d, ensure_ascii=False)}")
        print(f"  训练中 status={status} 已等 {int(time.time()-t0)}s", flush=True)
        time.sleep(30)
    raise TimeoutError("训练超时")


def credit():
    r = requests.get(BASE + "/api/v2/hifly/account/credit", headers=H, timeout=30)
    return r.json().get("data", {}).get("left")


def record(title, avatar, src):
    recs = json.load(open(RECORD, encoding="utf-8")) if os.path.exists(RECORD) else []
    recs.append({"title": title, "avatar": avatar, "src": src,
                 "created": time.strftime("%Y-%m-%d %H:%M:%S")})
    json.dump(recs, open(RECORD, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    video, title = sys.argv[1], sys.argv[2]
    print(f"[1/3] 上传 {os.path.basename(video)} ({os.path.getsize(video)//1048576}MB)")
    fid = upload(video)
    print(f"[2/3] 提交训练「{title}」")
    tid = train(title, fid)
    print(f"[3/3] 等待训练完成（最长40分钟）")
    avatar = wait_task(tid)
    print(f"训练成功 avatar={avatar}")
    record(title, avatar, video)
    print(f"当前积分: {credit()}")
