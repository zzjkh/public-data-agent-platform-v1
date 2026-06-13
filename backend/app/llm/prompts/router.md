---
prompt_name: router
prompt_version: v1.1
purpose: question_router
output_model: QuestionRoute
input_variables: question,available_capabilities,current_date
---
任务：判断用户问题应走哪条处理链路。

当前日期：
{current_date}

可用能力：
{available_capabilities}

用户问题：
{question}

规则：
1. POLICY_QA：政策文本、政策依据、制度解释类问题。
2. DATA_QA：GDP、常住人口、开放数据目录统计等结构化数据问题。
3. HYBRID_QA：同时需要政策依据和结构化数据分析的问题。
4. OTHER：超出范围、资料不足、危险操作或无法判断的问题。
5. 当问题包含“近五年”“去年”“最近一年”等相对时间，必须结合当前日期输出 normalized_time_range。
6. policy_topics 必须是适合政策检索的名词短语，不要复制完整问题。
7. HYBRID_QA 的 policy_topics 不要包含地区、年份和统计指标；这些实体由数据链路处理。
8. 对“注意事项、条件、风险、合规”类问题，应把隐含的规范维度展开到 policy_topics，例如个人信息保护、个人隐私、数据安全、分类分级、授权边界。

请只输出 JSON object，不要使用 Markdown 代码块：
{
  "route_type": "POLICY_QA | DATA_QA | HYBRID_QA | OTHER",
  "needs_policy_evidence": true,
  "needs_data_analysis": false,
  "confidence": 0.0,
  "reason": "string",
  "extracted_entities": {
    "region": "string | null",
    "time_range": "string | null",
    "normalized_time_range": {
      "start_year": "number | null",
      "end_year": "number | null",
      "grain": "year | month | day | null",
      "source_text": "string | null",
      "confidence": 0.0
    },
    "metrics": ["string"],
    "policy_topics": ["string"]
  }
}
