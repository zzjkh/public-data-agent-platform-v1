import { useQuery } from '@tanstack/react-query';
import { Alert, Card, Space, Table, Tag, Typography } from 'antd';

import { listFiles, type SourceFile } from '../api/files';

export function DocumentsPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['source-files'],
    queryFn: listFiles,
  });

  return (
    <Card>
      <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
        <div>
          <Typography.Title level={3} style={{ marginBottom: 4 }}>
            文档管理
          </Typography.Title>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            当前展示已上传的原始文件。政策文档详情列表后续在补齐 `/api/documents` 后接入。
          </Typography.Paragraph>
        </div>
        {isError ? <Alert type="error" message="文档文件列表加载失败" showIcon /> : null}
        <Table<SourceFile>
          rowKey="id"
          loading={isLoading}
          dataSource={data?.items ?? []}
          pagination={false}
          scroll={{ x: true }}
          columns={[
            { title: '文件名', dataIndex: 'file_name', key: 'file_name' },
            { title: '类型', dataIndex: 'file_type', key: 'file_type', width: 90 },
            {
              title: '解析状态',
              dataIndex: 'parse_status',
              key: 'parse_status',
              width: 110,
              render: (value: string) => <Tag color={statusColor(value)}>{value}</Tag>,
            },
            { title: '版本', dataIndex: 'file_version', key: 'file_version', width: 90 },
            {
              title: '来源',
              dataIndex: 'source_url',
              key: 'source_url',
              render: (value: string | null) => value ?? '-',
            },
            {
              title: '上传时间',
              dataIndex: 'uploaded_at',
              key: 'uploaded_at',
              width: 180,
              render: formatTime,
            },
          ]}
        />
      </Space>
    </Card>
  );
}

function statusColor(status: string) {
  if (status === 'parsed') return 'green';
  if (status === 'failed') return 'red';
  if (status === 'partial') return 'orange';
  if (status === 'running' || status === 'pending') return 'blue';
  return 'default';
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}
