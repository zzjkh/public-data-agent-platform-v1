---
prompt_name: sql_generation
prompt_version: v1.1
purpose: sql_generation
output_model: SqlGenerationResult
input_variables: question,candidate_schema,semantic_hits,sql_examples,constraints,normalized_time_range
---
任务：根据用户问题和候选 schema 生成安全的 PostgreSQL SELECT 查询。

硬性规则：
1. 只能生成一个 SELECT 语句。
2. 只能访问候选 schema 中列出的 reporting 视图。
3. 只能使用候选 schema 中列出的字段。
4. 禁止 SELECT *。
5. 禁止 INSERT、UPDATE、DELETE、DROP、ALTER、CREATE、TRUNCATE、COPY、CALL。
6. 必须包含 LIMIT，默认 LIMIT 100。
7. 时间趋势问题应按时间字段升序排序。
8. 不要查询未被候选元数据支持的指标。
9. 如果 normalized_time_range 非空，必须用其中的 start_year / end_year 生成时间过滤条件。
10. 用户明确指定地区时，必须使用候选 schema 中的 region_name、region_code 或行政区父级字段生成 WHERE 条件，不得查询无地域过滤的全量结果。
11. “某省下辖各市/省内各市”必须使用 parent_region_name = '<省名>' AND region_level = 'city'，禁止由模型枚举城市名或使用名称后缀猜测父子关系。

用户问题：
{question}

标准化时间范围：
{normalized_time_range}

候选 schema：
{candidate_schema}

语义召回结果：
{semantic_hits}

SQL 示例：
{sql_examples}

额外约束：
{constraints}

请只输出 JSON object，不要使用 Markdown 代码块：
{
  "sql": "SELECT ... LIMIT 100",
  "reason": "string",
  "used_metadata_ids": ["string"],
  "confidence": 0.0
}
