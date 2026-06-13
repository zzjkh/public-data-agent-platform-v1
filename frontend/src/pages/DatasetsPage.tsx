import { useQuery } from '@tanstack/react-query';
import { Alert, Card, Space, Table, Tag, Typography } from 'antd';

import { listDatasets, type OpenDataset } from '../api/datasets';

export const DATASET_TABLE_SCROLL_X = 1340;

export function DatasetsPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['datasets'],
    queryFn: listDatasets,
  });

  return (
    <Card>
      <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
        <div>
          <Typography.Title level={3} style={{ marginBottom: 4 }}>
            数据集管理
          </Typography.Title>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            查看开放数据目录、发布部门、开放类型和更新时间。
          </Typography.Paragraph>
        </div>
        {isError ? <Alert type="error" message="数据集列表加载失败" showIcon /> : null}
        <Table<OpenDataset>
          rowKey="id"
          loading={isLoading}
          dataSource={data?.items ?? []}
          pagination={false}
          scroll={{ x: DATASET_TABLE_SCROLL_X }}
          columns={[
            { title: '名称', dataIndex: 'name', key: 'name', width: 280, ellipsis: true },
            { title: '类别', dataIndex: 'category', key: 'category', width: 120, ellipsis: true },
            {
              title: '发布部门',
              dataIndex: 'department',
              key: 'department',
              width: 160,
              ellipsis: true,
            },
            {
              title: '更新频率',
              dataIndex: 'update_frequency',
              key: 'update_frequency',
              width: 110,
              ellipsis: true,
            },
            { title: '时间范围', dataIndex: 'time_range', key: 'time_range', width: 140, ellipsis: true },
            {
              title: '开放类型',
              dataIndex: 'open_type',
              key: 'open_type',
              width: 110,
              render: (value: string | null) => (value ? <Tag>{value}</Tag> : '-'),
            },
            {
              title: '更新时间',
              dataIndex: 'update_date',
              key: 'update_date',
              width: 120,
              render: (value: string | null) => value ?? '-',
            },
            {
              title: '来源',
              dataIndex: 'source_url',
              key: 'source_url',
              width: 300,
              ellipsis: true,
              render: (value: string | null) => value ?? '-',
            },
          ]}
        />
      </Space>
    </Card>
  );
}
