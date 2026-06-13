import { useQuery } from '@tanstack/react-query';
import { Alert, Card, Space, Table, Tag, Typography } from 'antd';

import { listMetrics, type Metric } from '../api/metrics';

export function MetricsPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['metrics'],
    queryFn: listMetrics,
  });

  return (
    <Card>
      <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
        <div>
          <Typography.Title level={3} style={{ marginBottom: 4 }}>
            指标管理
          </Typography.Title>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            查看 GDP、常住人口等结构化指标定义。
          </Typography.Paragraph>
        </div>
        {isError ? <Alert type="error" message="指标列表加载失败" showIcon /> : null}
        <Table<Metric>
          rowKey="id"
          loading={isLoading}
          dataSource={data?.items ?? []}
          pagination={false}
          scroll={{ x: true }}
          columns={[
            { title: '指标编码', dataIndex: 'indicator_code', key: 'indicator_code', width: 150 },
            { title: '指标名称', dataIndex: 'indicator_name', key: 'indicator_name', width: 220 },
            { title: '领域', dataIndex: 'domain', key: 'domain', width: 120 },
            { title: '单位', dataIndex: 'unit', key: 'unit', width: 100 },
            {
              title: '别名',
              dataIndex: 'aliases_json',
              key: 'aliases_json',
              render: (aliases: string[]) =>
                aliases.length > 0 ? aliases.map((alias) => <Tag key={alias}>{alias}</Tag>) : '-',
            },
            { title: '描述', dataIndex: 'description', key: 'description' },
          ]}
        />
      </Space>
    </Card>
  );
}
