# AI Infra Demo Rules

## GPU Inventory

- 中文口径：总卡数、GPU 数量、显卡库存都从 `aiinfra.gpu_nodes.gpu_count` 汇总。
- Total card count is calculated from `SUM(aiinfra.gpu_nodes.gpu_count)`.
- Available production cards should include only nodes where `status = 'active'`.
- Offline and maintenance nodes must be reported separately from available capacity.

## Card-Hours And Utilization

- 中文口径：卡时、GPU-hour、card-hour 都指 GPU 卡运行小时。
- 中文口径：卡时使用率 = 已分配卡时 / (已分配卡时 + 空闲卡时)。
- Card-hours are stored as `aiinfra.daily_gpu_metrics.allocated_gpu_hours`.
- Idle card-hours are stored as `aiinfra.daily_gpu_metrics.idle_gpu_hours`.
- Card-hour utilization rate is `allocated_gpu_hours / (allocated_gpu_hours + idle_gpu_hours)`.
- GPU core utilization uses `avg_gpu_utilization_pct`; it is not the same as card-hour utilization.

## Capacity Pressure

- 中文口径：排队等待、容量压力、资源紧张都优先看 `queue_wait_minutes` 和未解决容量事件。
- Queue wait should be analyzed with `queue_wait_minutes`.
- `queue_wait_minutes >= 30` is a capacity pressure signal.
- Open capacity issues are rows in `aiinfra.capacity_events` where `resolved_at IS NULL`.
- Critical or warning capacity events should be surfaced before informational events.

## Cost

- 中文口径：成本、费用、单卡时成本都从 `cost_usd` 和 `allocated_gpu_hours` 计算。
- Daily infrastructure cost is stored in `aiinfra.daily_gpu_metrics.cost_usd`.
- Cost per used card-hour is `cost_usd / allocated_gpu_hours`.
- Avoid dividing by zero when allocated GPU-hours are zero.
