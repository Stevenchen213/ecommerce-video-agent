# 蝉镜侧模块（产品画面）

> 分工（2026-10 起）：**数字人走飞影，蝉镜只做产品画面**。本模块不再调用蝉镜数字人接口。

```
分镜 JSON ──► ① 三道闸 checks.py ──► ② 产品镜头 ──────────────► ③ 时间轴 timeline.py ──► ④ 合成 composer.py
             结构/合规/授权          实拍 clips：本地剪辑          以飞影整条口播的          ffmpeg 拼接
             任一不过即停止           只有图片：蝉镜图生视频         真实时长切分              统一音轨 + AI 标识
                                    (chanjing/product.py)
                      飞影侧：按 plan.json 里 avatar.text 生成整条口播数字人视频 → 传入 --avatar-video
```

## 对外接口（给周思含的 ChanjingProvider 用）

```python
from chanjing.product import gen_product
info = gen_product(["images/box_front.jpg"], "包装盒静置在木桌上，镜头缓慢推近",
                   "library/chanjing/p2.mp4", target_duration=3.2)
# info: path / model_code / unique_id / requested_duration / elapsed_sec ...（同名 .json 留档）
```

- 本地图片自动上传到蝉镜换 URL（同一张图只传一次）；也可以直接传 URL
- 蝉镜最短生成 5 秒，镜头不足 5 秒时也请求 5 秒，拼接时截取开头
- 产出是**无声**视频，音轨由拼接层统一铺
- 提示词只写画面和运镜，不写产品名、价格、促销文字（文字由拼接层叠加）

## 目录
| 文件 | 作用 |
|---|---|
| `config.py` | 环境变量配置（密钥、地址、画布、图生视频模型、AI 标识字体） |
| `chanjing/client.py` | 鉴权（token 缓存+自动刷新）、统一请求、错误码、轮询；提交任务不做网络重试 |
| `chanjing/product.py` | **产品镜头生成入口** `gen_product()` |
| `chanjing/ai_creation.py` | 图生视频提交与轮询 |
| `chanjing/files.py` | 素材上传（create_upload_url → PUT → file_detail） |
| `pipeline/checks.py` | 占位符填充、结构校验、禁用词检查、数字人授权校验 |
| `pipeline/timeline.py` | 以数字人音轨真实时长分配各镜头时间 |
| `pipeline/composer.py` | ffmpeg：数字人片段/产品片段/叠加产品图/拼接/加标识 |
| `pipeline/orchestrator.py` | 主流程编排 |
| `authorized_avatars.json` | 授权形象库（飞影 avatar_id；真人需授权编号、品牌范围、有效期） |

## 运行
```bash
pip install -r requirements.txt   # 另需 ffmpeg

# 只测一个产品镜头（花蝉豆）
python run.py --product-only images/box_front.jpg --prompt "包装盒静置在木桌上，镜头缓慢推近" \
    --model tx_kling-v3-0-image2video

# 整条：1. 检查 + 输出调用计划 work/plan.json（不花钱）
python run.py scripts/babao_qiegao.shots.json --person-id <飞影avatar_id> --voice-id <声音ID> \
    --brand 疆小娃 --fill ingredients_spoken=核桃、红枣、葡萄干 --dry-run
# 2. 飞影侧生成整条口播视频后合成
python run.py scripts/babao_qiegao.shots.json --person-id <飞影avatar_id> --brand 疆小娃 \
    --fill ingredients_spoken=核桃、红枣、葡萄干 --avatar-video work/feiying_full.mp4
```

## 2026-10 改动说明
1. 删除 `chanjing/avatar.py`：数字人改由飞影生成，orchestrator 接收 `avatar_video`（旧参数 `mock_avatar_video` 仍兼容）
2. 新增 `chanjing/product.py` 的 `gen_product()`，作为模式 B 蝉镜 Provider 的接入点
3. 提交付费任务不再自动重试：超时/5xx 时任务可能已创建，重试会重复扣蝉豆
4. 默认图生视频模型改为文档已核对的 `tx_kling-v3-0-image2video`，可用 `CHANJING_I2V_MODEL` 覆盖
5. 产品镜头时长对齐：不再整段变速，素材偏长直接截取，变速限制在 0.8~1.25 倍，不足用定格补
6. AI 标识：Windows 默认微软雅黑；找不到字体直接报错，不再静默出无标识成片
7. `authorized_avatars.json` 登记了两个李亚鹏飞影形象，**需补授权合同编号、品牌、有效期后才能通过授权校验**
