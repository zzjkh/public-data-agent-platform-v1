import { useQuery } from '@tanstack/react-query';
import { Alert, Card, Space, Table, Tag, Typography } from 'antd';

import { listEvalRuns, type EvalRun } from '../api/evaluation';

export function EvalRunsPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['eval-runs'],
    queryFn: listEvalRuns,
  });

  return (
    <Card>
      <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
        <div>
          <Typography.Title level={3} style={{ marginBottom: 4 }}>
            评测运行
          </Typography.Title>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            查看 smoke eval 运行状态、模型信息和通过率。
          </Typography.Paragraph>
        </div>
        {isError ? <Alert type="error" message="评测运行加载失败" showIcon /> : null}
        <Table<EvalRun>
          rowKey="id"
          loading={isLoading}
          dataSource={data?.items ?? []}
          pagination={false}
          scroll={{ x: true }}
          columns={[
            { title: '名称', dataIndex: 'name', key: 'name', width: 180 },
            { title: '模型', dataIndex: 'model_name', key: 'model_name', width: 170 },
            { title: 'Embedding', dataIndex: 'embedding_model', key: 'embedding_model', width: 220 },
            {
              title: '状态',
              dataIndex: 'status',
              key: 'status',
              width: 100,
              render: (value: string) => <Tag color={value === 'success' ? 'green' : 'blue'}>{value}</Tag>,
            },
            {
              title: '通过率',
              dataIndex: 'run_config_json',
              key: 'pass_rate',
              width: 100,
              render: (value: Record<string, unknown>) =>
                typeof value.pass_rate === 'number' ? `${Math.round(value.pass_rate * 100)}%` : '-',
            },
            {
              title: '用例数',
              dataIndex: 'run_config_json',
              key: 'total_cases',
              width: 100,
              render: (value: Record<string, unknown>) => String(value.total_cases ?? '-'),
            },
            {
              title: '开始时间',
              dataIndex: 'started_at',
              key: 'started_at',
              width: 180,
              render: (value: string | null) => (value ? formatTime(value) : '-'),
            },
          ]}
        />
      </Space>
    </Card>
  );
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}
