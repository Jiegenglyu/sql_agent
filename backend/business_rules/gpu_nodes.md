# gpu_nodes

schema: aiinfra
table: gpu_nodes
aliases: 总卡数, GPU 数量, 显卡库存, 节点, 机器, 卡库存
related_tables: aiinfra.clusters

### 固定查询逻辑 ###
- 查询可用生产卡数时，只统计 `status = 'active'` 的节点。
- 维护中和离线节点不能算入可用容量，但可以单独展示。
- 按集群展示时，通过 `cluster_id` 关联 `aiinfra.clusters.id` 获取 `cluster_name`。

### 业务逻辑 ###

## 总卡数
keywords: 总卡数, GPU 数量, 显卡库存, 有多少卡
- 总卡数、GPU 数量、显卡库存都从 `SUM(gpu_count)` 汇总。
- 如果用户问“当前可用”，需要加上 `status = 'active'`。

## 节点状态
keywords: 节点状态, offline, maintenance, 维护, 离线
- 节点状态来自 `status`，取值包括 `active`、`maintenance`、`offline`。
- 汇总异常节点时，优先展示 `maintenance` 和 `offline`。
