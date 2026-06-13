import { useQuery } from '@tanstack/react-query';
import { Alert, Card, Descriptions, Space, Spin, Tag, Typography } from 'antd';
import { Link, useParams } from 'react-router-dom';

import { getTrace } from '../api/traces';
import { TraceTimeline } from '../components/TraceTimeline';

const STATUS_COLORS: Record<string, string> = {
  running: 'blue',
  success: 'green',
  failed: 'red',
  refused: 'orange',
};

export function TraceDetailPage() {
  const { traceId } = useParams<{ traceId: string }>();
  const { data, isLoading, isError } = useQuery({
    queryKey: ['trace', traceId],
    queryFn: () => getTrace(traceId ?? ''),
    enabled: Boolean(traceId),
  });

  if (!traceId) {
    return <Alert type="error" message="Trace ID 缺失" showIcon />;
  }

  if (isLoading) {
    return <Spin />;
  }

  if (isError || !data) {
    return <Alert type="error" message="Trace 详情加载失败" showIcon />;
  }

  return (
    <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
      <Link to="/traces">返回 Trace 列表</Link>
      <Card>
        <Typography.Title level={3}>Trace 详情</Typography.Title>
        <Descriptions
          bordered
          column={2}
          items={[
            { key: 'id', label: 'Trace ID', children: data.id },
            { key: 'route_type', label: '路由', children: data.route_type ?? '-' },
            {
              key: 'status',
              label: '状态',
              children: (
                <Tag color={STATUS_COLORS[data.status] ?? 'default'}>{data.status}</Tag>
              ),
            },
            {
              key: 'latency_ms',
              label: '总耗时',
              children: data.latency_ms === null ? '-' : `${data.latency_ms} ms`,
            },
            { key: 'question', label: '用户问题', children: data.user_question, span: 2 },
            {
              key: 'answer',
              label: '最终回答',
              children: data.final_answer ?? '-',
              span: 2,
            },
          ]}
        />
      </Card>
      <Card title="执行时间线">
        <TraceTimeline spans={data.spans} />
      </Card>
    </Space>
  );
}
