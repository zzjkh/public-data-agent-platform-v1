import { Card, Divider, Empty, Space, Tag, Typography } from 'antd';

import type { QaCitation } from '../../api/qa';

interface CitationListProps {
  citations: QaCitation[];
}

export function CitationList({ citations }: CitationListProps) {
  if (citations.length === 0) {
    return (
      <Card title="引用依据">
        <Empty description="暂无引用" />
      </Card>
    );
  }

  return (
    <Card title="引用依据">
      <Space
        orientation="vertical"
        size="middle"
        separator={<Divider />}
        style={{ width: '100%' }}
      >
        {citations.map((citation, index) => (
          <div key={`${citation.type}-${citation.source_title}-${index}`}>
            <Space orientation="vertical" size={4} style={{ width: '100%' }}>
              <Space wrap>
                <Tag color={citation.type === 'policy' ? 'blue' : 'purple'}>{citation.type}</Tag>
                <Typography.Text strong>{citation.source_title}</Typography.Text>
              </Space>
              {citation.section_path ? (
                <Typography.Text type="secondary">{citation.section_path}</Typography.Text>
              ) : null}
              {citation.quote ? <Typography.Paragraph>{citation.quote}</Typography.Paragraph> : null}
              {citation.source_url ? (
                <Typography.Link href={citation.source_url} target="_blank" rel="noreferrer">
                  查看来源
                </Typography.Link>
              ) : null}
            </Space>
          </div>
        ))}
      </Space>
    </Card>
  );
}
