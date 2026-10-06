# -*- coding: utf-8 -*-
"""读取飞影账号里已训练好的数字人和声音列表"""
import sys, io, os, json, requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "https://hfw-api.hifly.cc"
TOKEN = os.environ.get("FEIYING_TOKEN", "").strip()
if not TOKEN:
    print("错误：未设置 FEIYING_TOKEN 环境变量")
    sys.exit(1)

H = {"Authorization": f"Bearer {TOKEN}"}

def get(path, params=None):
    r = requests.get(BASE + path, headers=H, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

print("=" * 50)
print("【数字人列表】")
print("=" * 50)
try:
    for kind, label in [(1, "我自己训练的"), (2, "公版的")]:
        data = get("/api/v2/hifly/avatar/list", {"page": 1, "size": 50, "kind": kind})
        d = data.get("data", [])
        items = d if isinstance(d, list) else d.get("list", d.get("records", []))
        print(f"\n--- {label} (kind={kind}) ---")
        if not items:
            print("  (空，原始返回：%s)" % json.dumps(data, ensure_ascii=False)[:300])
        for a in items:
            print(f"  avatar={a.get('avatar')}  title={a.get('title')}  kind={a.get('kind')}")
except Exception as e:
    print("数字人列表读取失败：", e)

print("\n" + "=" * 50)
print("【声音列表】")
print("=" * 50)
try:
    for kind, label in [(1, "我自己克隆的"), (2, "公版的")]:
        data = get("/api/v2/hifly/voice/list", {"page": 1, "size": 50, "kind": kind})
        d = data.get("data", [])
        items = d if isinstance(d, list) else d.get("list", d.get("records", []))
        print(f"\n--- {label} (kind={kind}) ---")
        if not items:
            print("  (空，原始返回：%s)" % json.dumps(data, ensure_ascii=False)[:300])
        for v in items:
            print(f"  voice={v.get('voice')}  title={v.get('title')}  type={v.get('type')}")
except Exception as e:
    print("声音列表读取失败：", e)
