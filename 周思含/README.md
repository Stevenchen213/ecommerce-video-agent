# 脚本驱动双平台视频组装 · 架构说明

> 目录：`D:\电商视频剪辑AI\脚本驱动双平台视频组装\`  
> 一句话：输入结构化脚本 → **两步分类**（平台分流 + 产品连续段）→ 飞影数字人 / 蝉镜生成必用镜头 → 按顺序组装成片。

---

## 1. 目标与边界

| 要做 | 不做（当前） |
|------|----------------|
| 脚本驱动分流与组装 | 智能精剪 / 从杂库挑选 |
| 双平台生成接口位 | 改飞影 / 蝉镜 API 协议 |
| 本地 FFmpeg 拼接 | 复杂时间线 UI |
| 简单对接台前端 | 多用户权限体系 |

**与旧素材库区别：** 旧库是候选池（选用）；本框架是按脚本严格生成，**每镜默认都要用**。

---

## 2. 总体架构

```text
                    ┌─────────────────────┐
                    │  结构化脚本 YAML     │
                    │  shots[] 顺序 = 成片 │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │  Schema 校验         │
                    │  Planner 两步分类    │
                    │  1) 飞影 / 蝉镜      │
                    │  2) 产品连续段聚合   │
                    └──────────┬──────────┘
               ┌───────────────┴───────────────┐
               ▼                               ▼
    ┌────────────────────┐          ┌────────────────────┐
    │ 飞影数字人 Provider │          │ 蝉镜 Provider       │
    │ 单镜口播            │          │ 按产品段连贯生成    │
    └─────────┬──────────┘          └─────────┬──────────┘
              │                               │
              ▼                               ▼
    library/feiying/<id>.mp4         library/chanjing/<id>.mp4
              │                               │
              └───────────────┬───────────────┘
                              ▼
                   ┌────────────────────┐
                   │ Assembler          │
                   │ 缺镜检查 → 统一规格 │
                   │ 顺序拼接 → 品牌叠加 │
                   └─────────┬──────────┘
                             ▼
                      output/final.mp4
```

---

## 3. 目录结构

```text
脚本驱动双平台视频组装/
├── README.md                 ← 本文件（架构 + 用法）
├── 任务说明.md               ← 需求说明
├── 启动组装台.bat            ← 一键起前端+API
└── video_pipeline/           ← Python 包
    ├── cli.py                ← 命令行入口
    ├── api.py                ← FastAPI（含静态前端）
    ├── pipeline.py           ← 编排总控
    ├── config.py             ← 环境配置
    ├── schema/               ← 脚本模型与校验
    ├── planner/              ← 两步分类（平台 + 产品连续段）
    ├── providers/            ← 飞影 / 蝉镜 / mock
    ├── compose/              ← concat + brand
    ├── library_check.py      ← 缺镜检查
    ├── jobs/                 ← 任务状态 JSON
    ├── storage/              ← 本地存储（预留云）
    ├── web/                  ← 对接台前端
    ├── examples/             ← 示例脚本
    ├── library/              ← 必用镜头库（运行时）
    ├── output/               ← 成片
    ├── assets/brand/         ← logo / bgm / endcard
    └── tests/                ← 单测
```

---

## 4. 分层说明

### 4.1 脚本层 `schema/`
- 定义 `Script` / `Shot`（Pydantic）
- 关键字段：`id, role, platform, text, duration_sec, prompt, person_id, voice_id, transition_in, …`
- `platform`：`feiying`（数字人）| `chanjing`（产品）

### 4.2 分流层 `planner/`（两步分类）
1. **平台分类**：`feiying`（数字人）/ `chanjing`（产品）
2. **产品连续段**：数字人切开脚本后，相邻产品镜聚成一段（如 `p2→p3→p4`），同段带 `coherent_brief` 连贯生成；仍按 `shot_id` 落库
3. **不改变成片顺序**；顺序只在组装时使用 `Script.shots`

例：`产品1→数字人→产品2→3→4→数字人2→产品5→6`  
→ 产品段 `[p1]`、`[p2,p3,p4]`、`[p5,p6]`；飞影 `数字人`、`数字人2`

### 4.2b 路遥适配 `adapters/`（只读引用）
- YAML/Script → 路遥分镜 JSON
- `run --mode a`：整段口播切轨成片（调她的 orchestrator，**不改她的目录**）
- `run --mode b`：主架构各镜落库再拼接
- 上传远程仓库时**只改 `周思含/`**，见 `上传约定.md`


### 4.3 生成层 `providers/`
| 类 | 作用 |
|----|------|
| `MockFeiyingProvider` / `MockChanjingProvider` | 本地色卡 mock，用于联调 |
| `FeiyingProvider` | 飞影数字人真实 API **占位** |
| `ChanjingProvider` | 蝉镜真实 API **占位** |

产出约定：`library/<platform>/<shot_id>.mp4`（文件名 = 脚本 id）

### 4.4 组装层 `compose/`
1. **缺镜检查** `library_check.py`：少一镜则失败  
2. **normalize**：统一分辨率 / 帧率 / 音轨  
3. **concat**：硬切或 `fade` 转场  
4. **brand**（可选）：有资产才叠 logo / BGM / 片尾  

### 4.5 编排层 `pipeline.py`
- `run`：生成全部镜头 + 组装  
- `assemble_only`：跳过生成，只拼已有库  
- `retry_shot` / `status`  

### 4.6 接口层
- **CLI**：`python -m video_pipeline.cli …`  
- **HTTP**：`serve` → FastAPI + 静态前端 `web/`  

---

## 5. 数据流（对接同伴）

```text
同伴 A（飞影）生成数字人镜
  → 放入 library/feiying/<shot_id>.mp4

同伴 B（蝉镜）生成产品镜
  → 放入 library/chanjing/<shot_id>.mp4

任一方：
  → 打开组装台 / 执行 assemble
  → 系统按脚本顺序检查「全齐」后出片
```

缺任一 `shot_id` → 明确报缺镜，不瞎选替代素材。

---

## 6. 快速启动

```powershell
cd "D:\电商视频剪辑AI\脚本驱动双平台视频组装"

# 方式一：双击
启动组装台.bat

# 方式二：命令行
pip install -r video_pipeline\requirements.txt
python -m video_pipeline.cli serve --port 8787
```

浏览器：**http://127.0.0.1:8787/**

常用 CLI：

```powershell
python -m video_pipeline.cli validate video_pipeline\examples\sample_script.yaml
python -m video_pipeline.cli run video_pipeline\examples\sample_script.yaml
python -m video_pipeline.cli assemble video_pipeline\examples\sample_script.yaml
python -m video_pipeline.cli status video_pipeline\examples\sample_script.yaml
```

---

## 7. HTTP API 一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 对接台前端 |
| GET | `/health` | 健康检查 |
| GET | `/api/scripts` | 示例脚本列表 |
| GET | `/api/script?path=` | 脚本详情 + 缺镜 |
| POST | `/run` | 生成并组装 |
| POST | `/assemble` | 仅组装 |
| POST | `/retry` | 重跑单镜 |
| POST | `/status` | 任务 / 库状态 |
| GET | `/media/output/...` | 成片预览 |

---

## 8. 配置

见 `video_pipeline/config.example.env`：

- `VIDEO_PIPELINE_USE_MOCK=1`：用 mock 生成（默认）  
- `FEIYING_*` / `CHANJING_*`：真实 API（待填）  
- 画幅默认 `1080x1920` @ 30fps  

---

## 9. 当前进度 / 待办

| 状态 | 项 |
|------|----|
| 已完成 | 脚本校验、两步分类（平台+产品段）、mock、拼接、缺镜检查、品牌位、fade、CLI、HTTP、对接台前端 |
| 待队友 / 待接入 | 飞影数字人真实 API、蝉镜真实 API、真实素材库验收 |

---

## 10. 设计风格（前端）

对接台参考 [Swiss Minimalist](https://www.designprompts.dev/swiss-minimalist)：白底、黑线、橙色强调；**字号已收束**（标题约 28px），适合工具台而非超大营销字。
