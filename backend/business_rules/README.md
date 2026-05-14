# Business Rules

Place business rule documents in this directory.

Supported file types:

- `.md`
- `.txt`
- `.yaml`
- `.yml`
- `.json`

The rule search and read tools are intentionally limited to this directory. The Agent can list files, search across files for candidate rules, then read a selected file or line range for the final SQL prompt. Rule reads reject absolute paths, parent-directory escapes, symlinks that resolve outside the directory, oversized files, and unsupported extensions.

For Agent query routing, prefer one structured rule file per table:

```text
daily_gpu_metrics.md
gpu_nodes.md
capacity_events.md
```

Use this shape:

```md
# daily_gpu_metrics

schema: aiinfra
table: daily_gpu_metrics
aliases: 卡时, 使用率, 单卡时成本
related_tables: aiinfra.clusters, aiinfra.teams

### 固定查询逻辑 ###
- Rules in this block are always included when the table is selected.

### 业务逻辑 ###

## 单卡时成本
keywords: 单卡时成本, cost per GPU-hour
- Rules in this section are included only when the user question matches it.
```

The resolver first chooses candidate rule files and matched sections. If confidence is low or the question is ambiguous, the Agent asks a clarification question instead of generating SQL. If confidence is sufficient, only selected table metadata is loaded with `pg_describe_table`; the full schema overview is used only as a legacy fallback when no structured rule files exist.
