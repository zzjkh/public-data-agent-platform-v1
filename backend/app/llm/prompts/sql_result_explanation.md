---
prompt_name: sql_result_explanation
prompt_version: v1.0
purpose: sql_result_explanation
output_model: SqlResultExplanation
input_variables: question,validated_sql,columns,rows,row_count,data_sources
---
任务：基于 SQL 查询结果回答用户的数据问题。

规则：
1. 只能解释 rows 中出现的数据。
2. 不要编造未返回的年份、地区或数值。
3. 必须说明单位。
4. 必须说明数据来源。
5. 如果 rows 为空，说明当前结构化数据中未找到结果。

用户问题：
{question}

执行 SQL：
{validated_sql}

字段：
{columns}

结果行数：
{row_count}

结果行：
{rows}

数据来源：
{data_sources}

请只输出 JSON object，不要使用 Markdown 代码块：
{
  "summary": "string",
  "key_findings": ["string"],
  "data_sources": [
    {
      "title": "string",
      "source_url": "string | null"
    }
  ],
  "caveat": "string | null"
}
