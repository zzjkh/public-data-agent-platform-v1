import { useQuery } from '@tanstack/react-query';
import { Alert, Card, Space, Table, Tag, Typography } from 'antd';
import { Link } from 'react-router-dom';

import { listTraces, type TraceSummary } from '../api/traces';

const STATUS_COLORS: Record<string, string> = {
  running: 'blue',
  success: 'green',
  failed: 'red',
  refused: 'orange',
};

function formatTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

export function TracesPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['traces', { page: 1, page_size: 20 }],
    queryFn: () => listTraces({ page: 1, page_size: 20 }),
  });

  return (
    <Card>
      <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
        <div>
          <Typography.Title level={3} style={{ marginBottom: 4 }}>
            Trace 追踪
          </Typography.Title>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            查看问答链路中的路由、检索、SQL、模型回答等执行步骤。
          </Typography.Paragraph>
        </div>

        {isError ? <Alert type="error" message="Trace 列表加载失败" showIcon /> : null}

        <Table<TraceSummary>
          rowKey="id"
          loading={isLoading}
          dataSource={data?.items ?? []}
          pagination={false}
          columns={[
            {
              title: '问题',
              dataIndex: 'user_question',
              render: (text: string, record) => <Link to={`/traces/${record.id}`}>{text}</Link>,
            },
            {
              title: '路由',
              dataIndex: 'route_type',
              width: 120,
              render: (value: string | null) => value ?? '-',
            },
            {
              title: '状态',
              dataIndex: 'status',
              width: 100,
              render: (value: string) => <Tag color={STATUS_COLORS[value] ?? 'default'}>{value}</Tag>,
            },
            {
              title: '耗时',
              dataIndex: 'latency_ms',
              width: 100,
              render: (value: number | null) => (value === null ? '-' : `${value} ms`),
            },
            {
              title: '创建时间',
              dataIndex: 'created_at',
              width: 180,
              render: (value: string) => formatTime(value),
            },
          ]}
        />
      </Space>
    </Card>
  );
}
