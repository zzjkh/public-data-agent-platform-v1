import { Card, Empty, Space, Table, Tag, Typography } from 'antd';

import type { QaSqlPayload } from '../../api/qa';

interface SqlPanelProps {
  sql: QaSqlPayload | null;
}

export function SqlPanel({ sql }: SqlPanelProps) {
  if (!sql) {
    return (
      <Card title="SQL 与数据结果">
        <Empty description="暂无 SQL 查询" />
      </Card>
    );
  }

  const columns = sql.columns.map((column) => ({
    title: column,
    dataIndex: column,
    key: column,
    render: (value: unknown) => formatCell(value),
  }));
  const dataSource = sql.result_preview.map((row, index) => ({
    ...row,
    __rowKey: stableRowKey(row, index),
  }));

  return (
    <Card title="SQL 与数据结果">
      <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
        <Space wrap>
          <Tag color="green">row_count {sql.row_count}</Tag>
          <Tag>{sql.columns.length} columns</Tag>
        </Space>
        <div>
          <Typography.Text strong>validated_sql</Typography.Text>
          <pre
            style={{
              marginTop: 8,
              background: '#f6f8fa',
              borderRadius: 6,
              padding: 12,
              overflow: 'auto',
            }}
          >
            {sql.validated_sql}
          </pre>
        </div>
        <Table
          size="small"
          rowKey="__rowKey"
          dataSource={dataSource}
          columns={columns}
          pagination={false}
          scroll={{ x: true }}
        />
      </Space>
    </Card>
  );
}

function stableRowKey(row: Record<string, unknown>, index: number) {
  const values = Object.values(row)
    .slice(0, 3)
    .map((value) => String(value ?? ''))
    .join('|');
  return `${values}|${index}`;
}

function formatCell(value: unknown) {
  if (value === null || value === undefined) {
    return '-';
  }
  if (typeof value === 'object') {
    return JSON.stringify(value);
  }
  return String(value);
}
