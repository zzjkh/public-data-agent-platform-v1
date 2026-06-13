---
prompt_name: chart_recommendation
prompt_version: v1.0
purpose: chart_recommendation
output_model: ChartSpec
input_variables: question,columns,rows,field_types
---
任务：为 SQL 查询结果推荐一个前端可渲染的图表。

允许的 chart_type：
- line：时间趋势。
- bar：分类对比。
- pie：构成占比。
- table：无法可靠绘图时使用。

规则：
1. chart_type 必须是 line、bar、pie、table 之一。
2. x_field 必须来自 columns。
3. y_field 必须来自 columns，且应是数值字段。
4. 如果没有合适的数值字段，使用 table。
5. 不要生成前端配置之外的字段。

用户问题：
{question}

字段：
{columns}

字段类型：
{field_types}

结果行预览：
{rows}

请只输出 JSON object，不要使用 Markdown 代码块：
{
  "chart_type": "line | bar | pie | table",
  "x_field": "string | null",
  "y_field": "string | null",
  "series_field": "string | null",
  "title": "string",
  "reason": "string"
}
