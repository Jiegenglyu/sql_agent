# daily_gpu_metrics

schema: aiinfra
table: daily_gpu_metrics
aliases: 卡时, GPU-hour, 使用率, 利用率, 成本, 单卡时成本, 队列等待, 容量压力
related_tables: aiinfra.clusters, aiinfra.teams

### 固定查询逻辑 ###
- 查询该表时，除非用户明确指定日期范围，否则默认使用最新 `metric_date`。
- 涉及“上周”“本周”“昨天”“今天”等相对日期时，使用当前日期上下文解析日期范围。
- 计算比率或单价时必须使用 `NULLIF(..., 0)` 避免除以零。
- 按团队展示时，通过 `team_id` 关联 `aiinfra.teams.id` 获取 `team_name`。
- 按集群展示时，通过 `cluster_id` 关联 `aiinfra.clusters.id` 获取 `cluster_name`。

### 业务逻辑 ###

## 卡时使用率
keywords: 卡时使用率, GPU-hour utilization, card-hour utilization, 使用率, 使用情况
- 卡时、GPU-hour、card-hour 都指 GPU 卡运行小时。
- 卡时使用率 = `SUM(allocated_gpu_hours) / NULLIF(SUM(allocated_gpu_hours + idle_gpu_hours), 0)`。
- `avg_gpu_utilization_pct` 是 GPU 核心利用率，不等于卡时使用率。

## GPU/NPU 核心利用率
keywords: 核心利用率, GPU 利用率, NPU 利用率, avg_gpu_utilization_pct, 使用情况
- GPU/NPU 核心利用率优先使用 `avg_gpu_utilization_pct`。
- 聚合多行时用 `AVG(avg_gpu_utilization_pct)`，除非用户要求按卡时加权。

## 单卡时成本
keywords: 单卡时成本, 每卡时成本, cost per GPU-hour, 成本
- 单卡时成本 = `SUM(cost_usd) / NULLIF(SUM(allocated_gpu_hours), 0)`。
- 每团队、每集群、每型号成本都需要按对应维度分组后再计算。

## 容量压力
keywords: 容量压力, 资源紧张, 排队等待, queue wait
- 容量压力优先看 `queue_wait_minutes`。
- `queue_wait_minutes >= 30` 是容量压力信号。
