# gpu_card_models

schema: aiinfra
table: gpu_card_models
aliases: 卡型号, 卡类型, GPU 型号, 显卡型号, A100, V100, H100, L40S, card model, GPU card
related_tables: aiinfra.resource_pools
join_keys: gpu_card_models.pool_type = resource_pools.pool_type

### 固定查询逻辑 ###
- 卡型号字典来自 `aiinfra.gpu_card_models`。
- `pool_type` 是卡型号表与资源池表的共同字段。
- 回答“某个卡型号有哪些资源池”“某资源池规格对应什么卡”“按卡型号看容量”时必须关联 `aiinfra.resource_pools`。
- 同一个 `pool_type` 只代表一个主卡型号；如果未来存在多型号混部，需要新增记录并在回答中展示全部匹配行。
- 如果查询没有匹配行，必须明确回答数据库中没有匹配数据，不能猜测卡型号。

### 业务逻辑 ###

## 型号字典
keywords: 卡型号字典, GPU 型号, card model dictionary, 型号列表
- 展示 `pool_type`、`card_model`、`vendor`、`memory_gb`、`architecture`、`compute_capability`。
- 默认按 `pool_type` 排序。

## 按型号查资源池
keywords: A100 有哪些资源池, V100 有哪些资源池, H100 有哪些资源池, L40S 有哪些资源池, 哪些资源池用, pools by card
- 必须通过 `pool_type` 关联资源池表。
- 对 `A100`、`V100`、`H100`、`L40S` 等型号使用 `card_model ILIKE` 匹配。
- 输出应包含 `card_model`、`pool_name`、`pool_type`、`region`、`environment`、`total_cards`、`available_cards`、`status`。

## 按型号统计容量
keywords: 按卡型号统计, 每种卡多少, 型号容量, capacity by model, cards by model
- 必须关联资源池表并按 `card_model` 聚合。
- 总卡数 = `SUM(resource_pools.total_cards)`。
- 可用卡数 = `SUM(resource_pools.available_cards)`。
- 可用率 = `SUM(available_cards) / NULLIF(SUM(total_cards), 0)`。
