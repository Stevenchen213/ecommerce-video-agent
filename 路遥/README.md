# 蝉镜调用架构（分镜脚本 → 成片）

```
分镜 JSON ──► ① 三道闸 checks.py ──► ② 分流 orchestrator.py ──► ③ 并发调用蝉镜 ──► ④ 时间轴 timeline.py ──► ⑤ 合成 composer.py
             结构/合规/授权            avatar / product          create_video           按口播字数切分          ffmpeg 拼接+统一音轨+AI标识
             任一不过即停止，不花蝉豆                              ai_creation(图生视频)
```

## 目录
| 文件 | 作用 |
|---|---|
| `config.py` | 环境变量配置（密钥、地址、画布、AI 标识字体） |
| `chanjing/client.py` | 鉴权（token 缓存+自动刷新）、统一请求、错误码、重试、通用轮询 |
| `chanjing/avatar.py` | 查数字人真实形态 → 组装 create_video → 轮询 `/open/v1/video` |
| `chanjing/ai_creation.py` | 图生视频提交与轮询（只有图片素材的产品镜头用） |
| `chanjing/files.py` | 素材上传（create_upload_url → PUT → file_detail） |
| `pipeline/checks.py` | 占位符填充、结构校验、禁用词检查、数字人授权校验 |
| `pipeline/timeline.py` | 以数字人音轨真实时长分配各镜头时间 |
| `pipeline/composer.py` | ffmpeg：数字人片段/产品片段/叠加产品图/拼接/加标识 |
| `pipeline/orchestrator.py` | 主流程编排 |
| `authorized_avatars.json` | 授权形象库（真人需授权编号、品牌范围、有效期） |

## 关键设计
- **一次数字人调用**：`voiceover_full` 整条送给数字人，声音统一、口型准确；avatar 镜头从中按时间轴切画面，product 镜头盖在同一条音轨上。
- **实拍优先**：product 镜头有 `clips` 就本地剪辑，不花蝉豆；只有图片时才调图生视频。
- **先检查后花钱**：占位符、禁用词、授权任一不过，直接返回错误，不调任何付费接口。

## 运行
```bash
pip install -r requirements.txt   # 另需 ffmpeg
# 1. 只检查 + 输出调用计划 work/plan.json
python run.py scripts/babao_qiegao.shots.json --person-id C-PLATFORM-DEMO-001 --voice-id <voice_id> \
  --brand 疆小娃 --fill ingredients_spoken=核桃、红枣、葡萄干 --dry-run
# 2. 本地联调（用任意视频冒充数字人，验证剪辑合成）
python run.py ... --mock-avatar-video mock.mp4
# 3. 真实调用
export CHANJING_APP_ID=... CHANJING_SECRET_KEY=...
python run.py ... 
```

## 接入前需要按合作文档核对的地方（均已集中在 chanjing/ 下）
1. `access_token` 返回字段名与过期字段；token 失效错误码 `TOKEN_INVALID_CODES`
2. `create_video` 请求体结构（person / audio.tts / 字幕开关字段）
3. `list_common_dp` 分页参数与 `figures` 字段
4. AI 创作的任务状态字段、图生视频 `model_code`
5. `file_detail` 的成功/失败状态值
