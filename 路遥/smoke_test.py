"""蝉镜 API 三步冒烟测试。放在 路遥/ 文件夹里运行。

  第1步 获取 token          （免费）
  第2步 查询公共数字人列表   （免费）
  第3步 提交 5 秒文生视频    （花少量蝉豆，必须加 --spend 才会执行）

用法（PowerShell，先设置好 CHANJING_APP_ID / CHANJING_SECRET_KEY）：
  python smoke_test.py            # 只跑免费的第1、2步
  python smoke_test.py --spend    # 三步全跑

每一步都会打印接口的原始返回（token 已打码），把输出截图发给 Claude 即可对字段。
"""
import argparse
import json
import os
import sys
import time

import requests

BASE = os.getenv("CHANJING_BASE_URL", "https://open-api.chanjing.cc").rstrip("/")
APP_ID = os.getenv("CHANJING_APP_ID", "")
SECRET = os.getenv("CHANJING_SECRET_KEY", "")


def show(title, body):
    text = json.dumps(body, ensure_ascii=False, indent=2)
    if len(text) > 2500:
        text = text[:2500] + "\n...（已截断）"
    print(f"\n===== {title} =====\n{text}")


def mask(token):
    return token[:4] + "****" + token[-4:] if token and len(token) > 8 else "****"


def step1_token():
    r = requests.post(f"{BASE}/open/v1/access_token",
                      json={"app_id": APP_ID, "secret_key": SECRET}, timeout=30)
    print(f"HTTP {r.status_code}")
    body = r.json()
    data = body.get("data") or {}
    token = data.get("access_token") if isinstance(data, dict) else None
    safe = json.loads(json.dumps(body))
    if token:
        safe["data"]["access_token"] = mask(token)
    show("第1步 获取 token", safe)
    if not token:
        sys.exit("❌ 第1步失败：检查 APP_ID / SECRET_KEY 是否正确，或接口地址是否需要改成 https://www.chanjing.cc/api")
    print("✅ 第1步通过")
    return token


def step2_list(token):
    r = requests.get(f"{BASE}/open/v1/list_common_dp", headers={"access_token": token},
                     params={"page": 1, "size": 3}, timeout=30)
    print(f"HTTP {r.status_code}")
    body = r.json()
    show("第2步 公共数字人列表（前3个）", body)
    print("✅ 第2步通过" if body.get("code") == 0 else "❌ 第2步失败：看上面的 code 和 msg")


def step3_t2v(token):
    payload = {
        "creation_type": 4,
        "model_code": os.getenv("CHANJING_T2V_MODEL", "happyhorse-1.0-t2v"),
        "ref_prompt": "白色桌面上一盒绿色包装的羽衣甘蓝粉，旁边有绿植，镜头缓慢推近，自然光，真实质感",
        "aspect_ratio": "9:16",
        "clarity": 1080,
        "video_duration": 5,
    }
    headers = {"access_token": token, "Content-Type": "application/json"}
    r = requests.post(f"{BASE}/open/v1/ai_creation/task/submit", headers=headers, json=payload, timeout=30)
    print(f"HTTP {r.status_code}")
    body = r.json()
    show("第3步 提交文生视频", body)
    data = body.get("data")
    uid = data if isinstance(data, str) else (data or {}).get("unique_id")
    if not uid:
        sys.exit("❌ 第3步提交失败：看上面的 code 和 msg（可能是 model_code 不可用或余额不足）")

    print(f"已提交 unique_id={uid}，每 15 秒查询一次，最多 10 分钟……")
    for _ in range(40):
        time.sleep(15)
        q = requests.get(f"{BASE}/open/v1/ai_creation/task", headers={"access_token": token},
                         params={"unique_id": uid}, timeout=30).json()
        task = q.get("data") or {}
        out = task.get("output_url")
        print(f"  status={task.get('status')} progress={task.get('progress_desc')} err={task.get('err_msg')}")
        if out:
            show("第3步 任务完成（原始返回）", q)
            url = out[0] if isinstance(out, list) else out
            with open("smoke_test_output.mp4", "wb") as f:
                f.write(requests.get(url, timeout=300).content)
            print("✅ 第3步通过，视频已保存为 smoke_test_output.mp4")
            return
        if task.get("err_msg"):
            show("第3步 任务失败（原始返回）", q)
            sys.exit("❌ 第3步失败")
    print("⚠️ 10 分钟内没完成，把上面的输出发给 Claude 看看")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--spend", action="store_true", help="执行第3步（会消耗蝉豆）")
    args = ap.parse_args()
    if not APP_ID or not SECRET:
        sys.exit("❌ 没读到环境变量：请先在同一个 PowerShell 窗口里设置 CHANJING_APP_ID 和 CHANJING_SECRET_KEY")
    print(f"接口地址：{BASE}")
    tok = step1_token()
    step2_list(tok)
    if args.spend:
        step3_t2v(tok)
    else:
        print("\n（未执行第3步。确认前两步都通过后，用 python smoke_test.py --spend 再跑）")
