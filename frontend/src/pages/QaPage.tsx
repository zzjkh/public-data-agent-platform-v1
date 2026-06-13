import { useMutation } from '@tanstack/react-query';
import { Alert, Button, Card, Col, Form, Input, Row, Space, Tag, Typography } from 'antd';
import axios from 'axios';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { getCurrentUser } from '../api/auth';
import { askQuestion, type QaResponse } from '../api/qa';
import { ChartRenderer } from '../components/ChartRenderer';
import { CitationList } from '../components/CitationList';
import { SqlPanel } from '../components/SqlPanel';
import {
  clearQaPageSession,
  loadQaPageSession,
  saveQaPageSession,
} from '../utils/qaSession';

const { TextArea } = Input;

const ROUTE_COLORS: Record<string, string> = {
  POLICY_QA: 'blue',
  DATA_QA: 'green',
  HYBRID_QA: 'purple',
  OTHER: 'orange',
};

export function getQaErrorMessage(error: unknown): string {
  if (!axios.isAxiosError(error)) {
    return '问答请求失败，请稍后重试';
  }
  if (error.code === 'ECONNABORTED') {
    return '问答处理超时，请缩小问题范围后重试';
  }
  const apiMessage = error.response?.data?.error?.message;
  if (typeof apiMessage === 'string' && apiMessage.trim()) {
    return apiMessage;
  }
  if (!error.response) {
    return '无法连接后端服务，请检查服务状态后重试';
  }
  return '问答请求失败，请稍后重试';
}

export function QaPage() {
  const username = getCurrentUser()?.username ?? 'anonymous';
  const [initialSession] = useState(() => loadQaPageSession(username));
  const [persistedResponse, setPersistedResponse] = useState<QaResponse | null>(
    initialSession?.response ?? null,
  );
  const [form] = Form.useForm<{ question: string }>();
  const currentQuestion = Form.useWatch('question', form) ?? initialSession?.question ?? '';
  const mutation = useMutation({
    mutationFn: (question: string) => askQuestion({ question, options: { return_trace: true } }),
    onSuccess: (data, question) => {
      setPersistedResponse(data);
      saveQaPageSession(username, question, data);
    },
  });

  const response = mutation.data ?? persistedResponse;

  const submitQuestion = ({ question }: { question: string }) => {
    mutation.mutate(question.trim());
  };

  const clearCurrentQuestion = () => {
    mutation.reset();
    setPersistedResponse(null);
    clearQaPageSession(username);
    form.setFieldsValue({ question: '' });
  };

  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={15}>
        <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
          <Card>
            <Typography.Title level={3}>智能问答</Typography.Title>
            <Typography.Paragraph type="secondary">
              支持政策问答、数据问答和政策 + 数据混合问答。每次回答都会生成 Trace，方便回看执行链路。
            </Typography.Paragraph>
            <Form
              form={form}
              layout="vertical"
              initialValues={{ question: initialSession?.question ?? '' }}
              onValuesChange={(_, values) => {
                saveQaPageSession(username, values.question ?? '', response ?? null);
              }}
              onFinish={submitQuestion}
            >
              <Form.Item
                label="请输入问题"
                name="question"
                rules={[
                  { required: true, message: '请输入问题' },
                  { min: 2, message: '问题太短了' },
                ]}
              >
                <TextArea
                  rows={4}
                  placeholder="例如：结合公共数据开放政策，说明开放人口数据时需要注意什么，并给出北京市 2024 年常住人口数据。"
                />
              </Form.Item>
              <Space>
                <Button type="primary" htmlType="submit" loading={mutation.isPending}>
                  开始分析
                </Button>
                <Button onClick={clearCurrentQuestion} disabled={!response && !currentQuestion.trim()}>
                  清除本次问答
                </Button>
              </Space>
            </Form>
          </Card>

          {mutation.isError ? (
            <Alert type="error" message={getQaErrorMessage(mutation.error)} showIcon />
          ) : null}

          {response ? <AnswerCard response={response} /> : null}
        </Space>
      </Col>
      <Col xs={24} lg={9}>
        <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
          <CitationList citations={response?.citations ?? []} />
          <SqlPanel sql={response?.sql ?? null} />
          <ChartRenderer chart={response?.chart ?? null} rows={response?.sql?.result_preview ?? []} />
        </Space>
      </Col>
    </Row>
  );
}

function AnswerCard({ response }: { response: QaResponse }) {
  return (
    <Card>
      <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
        <Space wrap>
          <Tag color={ROUTE_COLORS[response.route_type] ?? 'default'}>{response.route_type}</Tag>
          <Tag>request_id {response.request_id}</Tag>
          <Link to={`/traces/${response.trace_id}`}>查看 Trace</Link>
        </Space>
        <Typography.Title level={4}>回答</Typography.Title>
        <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>{response.answer}</Typography.Paragraph>
      </Space>
    </Card>
  );
}
