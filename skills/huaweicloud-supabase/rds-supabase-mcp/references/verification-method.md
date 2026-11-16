# 验证方法

## init.sql 部署验证（五步）

1. **预检**：部署前用 `list_tables`/`list_indexes`/`get_rls_status` 记录现状，识别已存在的对象
2. **事务回滚**：一批 `execute_sql` 里故意放一条会报错的语句测试 → 事后查询确认什么都没留下；成功批 → `success, rows_affected`
3. **API 暴露验证**：`GRANT` + `NOTIFY pgrst, 'reload schema'` 后，`GET /rest/v1/<表名>`（anon key）应返回 200；未授权的表不应出现
4. **查询确认**：`list_table_columns`/`list_constraints`/`list_rls_policies` 与脚本定义逐项一致；`get_rls_status` 确认已启用（必要时加 FORCE）
5. **安全检查**：`get_advisors(type=security)` 无新增 issue（重点 0013 未启用 RLS / 0007 有策略未启用 / 0008 已启用但无策略）

## 清理脚本验证（cleanup.sql，按需）

- **产出即验证**：init.sql 成稿时同步产出 cleanup.sql（init-sql-guide 第 7 节）；核对两点——与 init.sql 对象清单一一对应（不漏不越界）、逆序拆除且全部 `IF EXISTS`（可重复执行）
- **执行验证（删除场景、用户指定时机）**：执行前先 `list_tables`/`get_rls_status` 核对现状 → `execute_sql` 整批执行（同事务、失败自动回滚）→ `list_tables` 确认对象已消失、`get_advisors` 无新增 issue
- **红线**：只清理项目自建对象，严禁触碰 `public` schema 平台内置对象与 auth/storage 等系统 schema

## 只读模式验证

`HUAWEICLOUD_MCP_READ_ONLY=true` 时调用任一 WRITE 工具，会收到 `MCP_READ_ONLY` 错误（统一错误格式）；READ 工具不受影响。

## 安全策略验证

- 审计：stderr 或审计文件中出现每次工具调用的 JSONL 事件
- confirm 规则：为 `execute_sql` 配置 confirm 规则后，未带确认的首调用返回 `confirmation_required`
- 保护名单：受保护对象上的操作被 `MCP_GUARDRAIL_BLOCKED` 拒绝

## 冒烟

`scripts/smoke.py --skip-cloud -- <服务器命令>`：握手、38 工具顺序、只读拦截。
