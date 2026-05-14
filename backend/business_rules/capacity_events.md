# capacity_events

schema: aiinfra
table: capacity_events
aliases: 容量告警, 容量事件, 未解决告警, 故障, 容量短缺
related_tables: aiinfra.clusters

### 固定查询逻辑 ###
- 查询当前未解决事件时，必须使用 `resolved_at IS NULL`。
- 告警严重度按 `critical`、`warning`、`info` 的业务优先级展示。
- 按集群展示时，通过 `cluster_id` 关联 `aiinfra.clusters.id` 获取 `cluster_name`。

### 业务逻辑 ###

## 未解决容量告警
keywords: 未解决, 当前告警, open capacity issue, unresolved capacity alert
- 未解决容量告警是 `resolved_at IS NULL` 的行。
- `severity IN ('critical', 'warning')` 的事件应优先展示。

## 容量短缺事件
keywords: 容量短缺, capacity shortage, quota limit, 资源紧张
- 容量短缺相关事件优先看 `event_type IN ('capacity_shortage', 'quota_limit')`。
- 需要展示 `event_time`、`severity`、`event_type`、`message` 和 `affected_gpus`。
