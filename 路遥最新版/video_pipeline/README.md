# video_pipeline — AI 带货短视频自动剪辑

输入产品卖点和素材，自动产出「数字人口播 + 产品画面」交替、逻辑清楚的带货视频（mp4 成片 + 可精修的剪映草稿）。

**分工原则：豆包大模型决定「剪什么」，代码负责「怎么剪」。** 模型只输出结构化分镜，裁剪、生成、拼接、写草稿都由确定性代码完成，结果稳定、可批量、可排查。

## 流程

```
产品简报（卖点 / 价格 / 目标人群）+ 素材库
        │
        ▼  ① 豆包 doubao-seed 规划（planner/llm.py）
  分镜脚本：每句话 → 数字人 or 产品画面（素材编号 / Seedance 提示词）
        │  ② 代码校验：素材是否存在、违禁词、结构、AI 镜头数量、总时长
        │  ③ 豆包审核：每句旁白和画面是否对得上、衔接是否顺
        │     有问题 → 把问题发回豆包重写（最多 DOUBAO_LLM_MAX_ROUNDS 轮）
        ▼
  scripts/xxx_script.yaml（可人工修改）
        │
        ▼  ④ 生成镜头（pipeline.py）
  数字人镜头 → 飞影 API（整条配音一次 TTS，按句切开驱动口型）
  产品镜头   → 素材库裁剪 ─没有→ AI 缓存 ─没有→ Seedance 图生视频（有次数上限）
        │
        ▼  ⑤ 出片
  output/*.mp4（FFmpeg 拼接 + logo / BGM / 片尾）  +  剪映草稿（--jianying）
```

### 成片结构（写在豆包的提示词里）

钩子（前 3 秒）→ 痛点 / 场景 → 产品出场 → 卖点 ×2~4（**每个卖点紧跟一个能证明它的产品画面**）→ 信任背书 → 数字人下单引导

## 快速开始

```bash
pip install -r video_pipeline/requirements.txt
cp video_pipeline/config.example.env video_pipeline/.env   # 填 ARK_API_KEY / DOUBAO_LLM_MODEL / 飞影 Key

# 0. 素材库：视频放进 video_pipeline/assets/，参照 asset_index.example.json 写 asset_index.json
#    （可选）让豆包看截帧自动补画面描述，选镜会准很多：
python -m video_pipeline.cli describe-assets --product 秋梨糕

# 1. 只出脚本，先人工看一眼
python -m video_pipeline.cli plan video_pipeline/examples/brief_qiulisgao.yaml

# 2. 按脚本生成并出片（可加 --jianying 同时出剪映草稿）
python -m video_pipeline.cli run video_pipeline/scripts/brief_qiulisgao_script.yaml --jianying

# 或者一条龙：规划 + 出片
python -m video_pipeline.cli auto video_pipeline/examples/brief_qiulisgao.yaml --jianying
```

命令都在仓库根目录（`video_pipeline/` 的上一级）执行。不联网调试：`.env` 里设 `VIDEO_PIPELINE_USE_MOCK=1`，镜头会用纯色占位视频。

## 常用命令

| 命令 | 作用 |
|---|---|
| `plan <brief>` | 豆包规划：简报 → 脚本 YAML（`--no-review` 跳过审核） |
| `auto <brief>` | 规划 + 生成 + 出片 |
| `describe-assets --product X` | 豆包看素材截帧，补 `desc` / `tags`（原文件备份为 `.bak`） |
| `validate <script>` | 校验脚本，打印数字人 / 产品段分组 |
| `run <script>` | 生成全部镜头并出片（数字人内容没变不会重复扣费） |
| `retry <script> <shot_id>` | 强制重跑单个镜头 |
| `assemble <script>` | 只拼接（library 里已有全部镜头） |
| `export-jianying <script>` | 用已有镜头写剪映草稿，不调 API |
| `status [script]` | 查看各镜头状态 / 缺镜 |
| `serve` | 启动 HTTP API + 网页（含 `POST /plan`） |

## 目录

```
planner/llm.py        豆包规划 / 审核 / 素材打标签
planner/compliance.py 广告法违禁词（本地硬拦截）
planner/__init__.py   数字人 / 产品段分组
providers/doubao.py   产品镜头：素材库 → AI 缓存 → Seedance
providers/seedance.py Seedance 图生视频（火山方舟）
providers/feiying.py  飞影数字人 + TTS
voiceover.py          整条配音一次生成并按句切分
compose/              FFmpeg 拼接、叠图、品牌包装
export/jianying.py    剪映草稿（pyJianYingDraft）
jobs.py               镜头生成状态（jobs/state.json）
examples/             简报和脚本示例
```

## 素材库格式（assets/asset_index.json）

```json
[{"file": "秋梨糕/8.3-3.mp4", "tags": ["秋梨糕", "掰开特写"], "start": 0, "end": 4,
  "desc": "手把秋梨糕从中间掰开，酥皮掉渣，露出梨馅"}]
```

- `file` 相对 `assets/`，也可写绝对路径；`start` / `end` 为可用区间（秒）。
- `desc` 会发给豆包做选镜依据，越具体越好。
- 手写脚本用 `asset_tags` 时，**每个标签都要命中**才算匹配，否则走 Seedance。

## 注意

- **不要提交** `.env`、`assets/` 下的素材和真实 `asset_index.json`（已在 `.gitignore`）。用网页拖拽上传时 `.gitignore` 不生效，要手动避开。
- Seedance 按条计费，`SEEDANCE_MAX_CALLS_PER_RUN` 限制单次运行的调用次数；生成过的镜头缓存在 `assets/ai_generated/`，同样的提示词不会再次计费。
- 剪映草稿引用素材的绝对路径，导出后不要移动 `library/` 和 `assets/`；新版剪映对草稿有加密，请用团队实际安装的版本先测一遍。
