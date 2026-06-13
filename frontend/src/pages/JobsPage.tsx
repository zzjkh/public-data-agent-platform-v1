import { useQuery } from '@tanstack/react-query';
import { Alert, Card, Progress, Space, Table, Tag, Typography } from 'antd';

import { listJobs, type Job } from '../api/jobs';

export function JobsPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['jobs'],
    queryFn: listJobs,
  });

  return (
    <Card>
      <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
        <div>
          <Typography.Title level={3} style={{ marginBottom: 4 }}>
            任务管理
          </Typography.Title>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            查看文件解析、数据导入、embedding 构建等异步任务状态。
          </Typography.Paragraph>
        </div>
        {isError ? <Alert type="error" message="任务列表加载失败" showIcon /> : null}
        <Table<Job>
          rowKey="id"
          loading={isLoading}
          dataSource={data?.items ?? []}
          pagination={false}
          scroll={{ x: true }}
          columns={[
            { title: 'job_id', dataIndex: 'id', key: 'id', width: 260 },
            { title: '类型', dataIndex: 'job_type', key: 'job_type', width: 170 },
            { title: '目标', dataIndex: 'target_type', key: 'target_type', width: 140 },
            {
              title: '状态',
              dataIndex: 'status',
              key: 'status',
              width: 110,
              render: (value: string) => <Tag color={statusColor(value)}>{value}</Tag>,
            },
            {
              title: '进度',
              dataIndex: 'progress_percent',
              key: 'progress_percent',
              width: 150,
              render: (value: number) => <Progress percent={value} size="small" />,
            },
            { title: '重试', dataIndex: 'retry_count', key: 'retry_count', width: 80 },
            {
              title: '错误',
              dataIndex: 'error_message',
              key: 'error_message',
              render: (value: string | null) => value ?? '-',
            },
          ]}
        />
      </Space>
    </Card>
  );
}

function statusColor(status: string) {
  if (status === 'success') return 'green';
  if (status === 'failed') return 'red';
  if (status === 'partial') return 'orange';
  if (status === 'running') return 'blue';
  if (status === 'cancelled') return 'default';
  return 'processing';
}
