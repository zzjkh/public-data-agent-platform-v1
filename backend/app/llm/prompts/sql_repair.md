---
prompt_name: sql_repair
prompt_version: v1.0
purpose: sql_repair
output_model: SqlGenerationResult
input_variables: question,previous_sql,violations,candidate_schema,semantic_hits,normalized_time_range
---
任务：修复上一条 SQL，使其满足安全规则并更可能返回正确结果。

用户问题：
{question}

上一条 SQL：
{previous_sql}

校验或执行问题：
{violations}

候选 schema：
{candidate_schema}

语义召回结果：
{semantic_hits}

标准化时间范围：
{normalized_time_range}

修复规则：
1. 只能输出一个 SELECT。
2. 只能访问 reporting 视图。
3. 禁止 SELECT *。
4. 必须 LIMIT。
5. 不要引入候选 schema 之外的字段。
6. 如果是空结果，可尝试使用召回到的别名或更宽松的等值条件。
7. 如果 normalized_time_range 非空，修复后 SQL 仍必须保留对应时间范围。

请只输出 JSON object，不要使用 Markdown 代码块：
{
  "sql": "SELECT ... LIMIT 100",
  "reason": "string",
  "used_metadata_ids": ["string"],
  "confidence": 0.0
}
