import { Card, Empty, Space, Tag, Timeline, Typography } from 'antd';

import type { TraceSpan } from '../../api/traces';

const SPAN_LABELS: Record<string, string> = {
  safety_guard: '问题安全检查',
  router: '问题分类',
  policy_retrieval: '政策检索',
  semantic_retrieval: '语义元数据检索',
  sql_generation: 'SQL 生成',
  sql_guard: 'SQL 安全校验',
  sql_execution: 'SQL 执行',
  answer_generation: '答案生成',
  chart_generation: '图表推荐',
};

const STATUS_COLORS: Record<string, string> = {
  success: 'green',
  failed: 'red',
  skipped: 'default',
};

interface TraceTimelineProps {
  spans: TraceSpan[];
}

function JsonBlock({ title, value }: { title: string; value: unknown }) {
  return (
    <div>
      <Typography.Text strong>{title}</Typography.Text>
      <pre
        style={{
          marginTop: 8,
          marginBottom: 0,
          maxHeight: 220,
          overflow: 'auto',
          background: '#f6f8fa',
          borderRadius: 6,
          padding: 12,
          fontSize: 12,
        }}
      >
        {JSON.stringify(value ?? {}, null, 2)}
      </pre>
    </div>
  );
}

export function TraceTimeline({ spans }: TraceTimelineProps) {
  if (spans.length === 0) {
    return <Empty description="暂无 Trace span" />;
  }

  return (
    <Timeline
      items={spans.map((span) => ({
        color: STATUS_COLORS[span.status] ?? 'blue',
        content: (
          <Card
            size="small"
            title={`#${span.span_order} ${SPAN_LABELS[span.span_type] ?? span.span_type}`}
            style={{ marginBottom: 16 }}
          >
            <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
              <Space wrap>
                <Tag>{span.span_type}</Tag>
                <Tag color={STATUS_COLORS[span.status] ?? 'blue'}>{span.status}</Tag>
                <Tag>{span.latency_ms} ms</Tag>
                {span.prompt_name ? <Tag>Prompt {span.prompt_name}</Tag> : null}
                {span.prompt_version ? <Tag>Version {span.prompt_version}</Tag> : null}
                {span.model_name ? <Tag>Model {span.model_name}</Tag> : null}
              </Space>
              {span.error_message ? (
                <Typography.Text type="danger">{span.error_message}</Typography.Text>
              ) : null}
              <JsonBlock title="输入 input_json" value={span.input_json} />
              <JsonBlock title="输出 output_json" value={span.output_json} />
            </Space>
          </Card>
        ),
      }))}
    />
  );
}
