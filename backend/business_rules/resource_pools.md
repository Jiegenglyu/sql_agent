# resource_pools

schema: aiinfra
table: resource_pools
aliases: 资源池, 支援资源池, resource pool, pool, Xlarge, Large, Medium, Small, 推理池, 训练池, 容量, 可用卡
related_tables: aiinfra.gpu_card_models
join_keys: resource_pools.pool_type = gpu_card_models.pool_type

### 固定查询逻辑 ###
- 资源池基础信息来自 `aiinfra.resource_pools`。
- `pool_type` 是资源池与卡型号表的共同字段，回答“资源池是什么卡”“某卡型号有哪些资源池”“按卡型号统计容量”等问题时必须关联 `aiinfra.gpu_card_models`。
- 只查询当前可服务资源池时使用 `status = 'active'`；如果用户问全部资源池，需要保留 `status` 字段并展示非 active 状态。
- 容量口径：总卡数使用 `total_cards`，可用卡数使用 `available_cards`，已占用卡数使用 `total_cards - available_cards`。
- 如果查询没有匹配行，必须明确回答数据库中没有匹配数据，不能编造资源池或卡型号。

### 业务逻辑 ###

## 资源池列表
keywords: 资源池列表, 有哪些资源池, 所有资源池, pool list, resource pools
- 展示 `pool_name`、`pool_type`、`region`、`environment`、`owner_team`、`status`、`total_cards`、`available_cards`。
- 默认按 `status`、`region`、`pool_name` 排序。

## 资源池卡型号
keywords: Xlarge 是什么卡, 资源池是什么卡, pool type card model, 卡型号, 显卡型号
- 必须通过 `resource_pools.pool_type = gpu_card_models.pool_type` 关联卡型号表。
- 对于 `Xlarge`、`Large`、`Medium`、`Small` 这类资源池规格，使用 `pool_type` 精确匹配。
- 输出应包含 `pool_type`、`pool_name`、`card_model`、`memory_gb`、`vendor`、`architecture`。

## 资源池容量
keywords: 容量, 可用卡, 总卡数, available cards, total cards, capacity
- 按资源池统计时直接读取 `total_cards` 和 `available_cards`。
- 按卡型号统计时必须关联卡型号表并按 `card_model` 聚合。
- 可用率 = `SUM(available_cards) / NULLIF(SUM(total_cards), 0)`。

## 归属和区域
keywords: 负责人, owner, 团队, 区域, region, environment
- 归属团队来自 `owner_team`。
- 区域来自 `region`，环境来自 `environment`。
