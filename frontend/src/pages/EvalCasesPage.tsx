import { useQuery } from '@tanstack/react-query';
import { Alert, Card, Space, Table, Tag, Typography } from 'antd';

import { listEvalCases, type EvalCase } from '../api/evaluation';

export function EvalCasesPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['eval-cases'],
    queryFn: listEvalCases,
  });

  return (
    <Card>
      <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
        <div>
          <Typography.Title level={3} style={{ marginBottom: 4 }}>
            评测用例
          </Typography.Title>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            查看 RAG、SQL、Hybrid、Safety 四类 smoke eval 用例。
          </Typography.Paragraph>
        </div>
        {isError ? <Alert type="error" message="评测用例加载失败" showIcon /> : null}
        <Table<EvalCase>
          rowKey="id"
          loading={isLoading}
          dataSource={data?.items ?? []}
          pagination={false}
          scroll={{ x: true }}
          columns={[
            {
              title: '类型',
              dataIndex: 'case_type',
              key: 'case_type',
              width: 100,
              render: (value: string) => <Tag>{value}</Tag>,
            },
            { title: '问题', dataIndex: 'question', key: 'question', width: 360 },
            { title: '预期路由', dataIndex: 'expected_route_type', key: 'expected_route_type', width: 130 },
            { title: '预期视图', dataIndex: 'expected_view', key: 'expected_view', width: 220 },
            {
              title: '关键词',
              dataIndex: 'expected_keywords_json',
              key: 'expected_keywords_json',
              render: (keywords: string[]) =>
                keywords.length > 0 ? keywords.map((keyword) => <Tag key={keyword}>{keyword}</Tag>) : '-',
            },
            {
              title: '启用',
              dataIndex: 'enabled',
              key: 'enabled',
              width: 90,
              render: (value: boolean) => <Tag color={value ? 'green' : 'default'}>{value ? '启用' : '停用'}</Tag>,
            },
          ]}
        />
      </Space>
    </Card>
  );
}
