# Business Rules

Place business rule documents in this directory.

Supported file types:

- `.md`
- `.txt`
- `.yaml`
- `.yml`
- `.json`

The rule search and read tools are intentionally limited to this directory. The Agent can list files, search across files for candidate rules, then read a selected file or line range for the final SQL prompt. Rule reads reject absolute paths, parent-directory escapes, symlinks that resolve outside the directory, oversized files, and unsupported extensions.

For Agent query routing, prefer one structured rule file per business table:

```text
resource_pools.md
gpu_card_models.md
```

Use this shape:

```md
# resource_pools

schema: aiinfra
table: resource_pools
aliases: 资源池, resource pool, Xlarge
related_tables: aiinfra.gpu_card_models
join_keys: resource_pools.pool_type = gpu_card_models.pool_type

### 固定查询逻辑 ###
- Rules in this block are always included when the table is selected.

### 业务逻辑 ###

## 资源池卡型号
keywords: Xlarge 是什么卡, 资源池是什么卡, 卡型号
- Rules in this section are included only when the user question matches it.
```

The resolver first chooses candidate rule files and matched sections. If confidence is low or the question is ambiguous, the Agent asks a clarification question instead of generating SQL. If confidence is sufficient, only selected table metadata is loaded with `pg_describe_table`; the full schema overview is used only as a legacy fallback when no structured rule files exist.
