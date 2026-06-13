---
prompt_name: hybrid_answer
prompt_version: v1.0
purpose: hybrid_answer
output_model: HybridAnswer
input_variables: question,policy_answer,policy_citations,sql_explanation,sql_result,chart_spec
---
任务：综合政策依据和结构化数据结果，回答用户的复合问题。

规则：
1. 必须区分政策依据和数据分析结果。
2. 政策结论必须来自 policy_answer 和 citations。
3. 数据结论必须来自 sql_result 和 sql_explanation。
4. 不要把数据趋势说成政策要求。
5. 不要给出正式行政办理结论。
6. 如果政策依据或数据结果缺失，应在 caveat 中说明。

用户问题：
{question}

政策回答：
{policy_answer}

政策引用：
{policy_citations}

数据分析：
{sql_explanation}

SQL 结果：
{sql_result}

图表：
{chart_spec}

请只输出 JSON object，不要使用 Markdown 代码块：
{
  "answer": "string",
  "policy_citations": [
    {
      "source_title": "string",
      "source_url": "string | null",
      "section_path": "string | null",
      "quote": "string"
    }
  ],
  "data_sources": [
    {
      "title": "string",
      "source_url": "string | null"
    }
  ],
  "used_sql": true,
  "used_policy_evidence": true,
  "caveat": "string | null"
}
