# 数字人素材 · 第一次测试

> 日期：2026-10-01
> 用途：飞影数字人 API 首批生成测试，供拼接流程联调与效果评估

## 本批清单

| 文件 | 对应脚本镜头 | 文案 | 时长 |
|---|---|---|---|
| onlytree_kale_shot1.mp4 | onlytree_kale 镜1（hook） | 最近到处都在卖羽衣甘蓝粉，到底值不值得买？ | 4s |
| onlytree_kale_shot2.mp4 | onlytree_kale 镜2（pain_point） | 天天外卖，蔬菜总是吃不够，我找到一个省事的办法。 | 5s |
| onlytree_kale_shot6.mp4 | onlytree_kale 镜6（cta） | 独立小条装，上班带着走。想试试的，点击下方看看。 | 5s |
| babao_qiegao_shot2.mp4 | babao_qiegao 镜2（pain_point） | 下午嘴馋，又想吃点有嚼劲的？试试疆小娃八宝手工切糕。 | 8s |
| babao_qiegao_shot5.mp4 | babao_qiegao 镜5（texture） | 坚果香，果干甜，一盒两百克，放在办公室正好。 | 6s |

## 生成参数（第一次测试用）

| 产品 | avatar（形象） | voice（声音） |
|---|---|---|
| onlytree 羽衣甘蓝粉 | `GzcsOucmue291Eiq0-gAWg`（羽衣甘蓝李亚鹏） | `b0c66f97-4b39-46c3-81ff-33df16d8ac41`（李亚鹏1） |
| 疆小娃切糕 | `JtbIs57CkRcHze4ambSJCg`（桀桀桀-鹏哥-工厂1） | `27fa2bfa-3f13-42b2-923d-342a39c2a6ac`（鹏哥-工厂1 配套） |

- 接口：飞影 `POST /api/v2/hifly/video/create_by_tts`
- 字幕：**未烧入**（st_show=0），字幕由拼接层统一添加
- 本次消耗：266 积分（约 9.5 积分/秒）
