# 周思含_短片编排

> 新主线（v2）。旧架构 `周思含/` / `脚本驱动双平台视频组装` **保留不动**。

## 一句话

路遥产出**产品 AI 短片** + 陈铭嵩产出**数字人短片** → 本系统按脚本顺序编排拼接 → 成片。  
本仓库目录同时提供 **后端 API + 前端工作台**。

## 角色边界

| 角色 | 产出 | 落盘约定 |
|------|------|----------|
| 路遥（蝉镜） | 产品短片（一小段一段，不生成长片） | `library/chanjing/<shot_id>.mp4` |
| 陈铭嵩（飞影） | 数字人短片 | `library/feiying/<shot_id>.mp4` |
| 周思含（本系统） | 脚本校验、缺镜检查、按序拼接、前后端工作台 | `output/*.mp4` |

## 目录

```text
周思含_短片编排/
├── README.md
├── 启动工作台.bat
├── requirements.txt
├── app/                 # 后端
│   ├── api.py
│   ├── pipeline.py
│   ├── schema.py
│   ├── config.py
│   ├── library_check.py
│   └── compose/
├── web/                 # 前端
├── examples/            # 示例脚本
├── library/feiying|chanjing/
├── output/
└── tmp/
```

## 快速启动

```powershell
cd "D:\电商视频剪辑AI\周思含_短片编排"
pip install -r requirements.txt
.\启动工作台.bat
```

浏览器：http://127.0.0.1:8790/

## 脚本约定

- `platform: feiying` → 数字人短片  
- `platform: chanjing` → 产品短片  
- 文件名必须 = `shot.id`  
- 成片顺序 = YAML 里 `shots` 顺序  

## 与旧架构关系

| | 旧 `周思含/` | 本目录 |
|--|-------------|--------|
| 主路径 | 双模式 A/B 探索 | **短片入库 → 按脚本拼** |
| 路遥 | 整段切轨也可 | 只收她的**短片** |
| 前端 | 对接台 8787 | 工作台 **8790**（避免端口冲突） |
