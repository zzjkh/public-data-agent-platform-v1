import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { TraceSpan } from '../../api/traces';
import { TraceTimeline } from './TraceTimeline';

const spans: TraceSpan[] = [
  {
    id: 'span-1',
    trace_id: 'trace-1',
    parent_span_id: null,
    span_order: 1,
    span_type: 'router',
    input_json: { question: '近五年北京人口变化？' },
    output_json: { route_type: 'DATA_QA' },
    latency_ms: 11,
    status: 'success',
    error_message: null,
    started_at: null,
    ended_at: null,
    model_name: null,
    prompt_name: null,
    prompt_version: null,
    token_usage_json: {},
    cost_json: {},
    retry_count: 0,
    created_at: '2026-06-05T10:00:00Z',
  },
  {
    id: 'span-2',
    trace_id: 'trace-1',
    parent_span_id: null,
    span_order: 2,
    span_type: 'answer_generation',
    input_json: { context: 'evidence blocks' },
    output_json: { answer: '人口总体稳定。' },
    latency_ms: 35,
    status: 'success',
    error_message: null,
    started_at: null,
    ended_at: null,
    model_name: 'deepseek-v4-pro',
    prompt_name: 'rag_answer',
    prompt_version: 'v1',
    token_usage_json: {},
    cost_json: {},
    retry_count: 0,
    created_at: '2026-06-05T10:00:01Z',
  },
];

describe('TraceTimeline', () => {
  it('renders spans with order, latency and prompt metadata', () => {
    render(<TraceTimeline spans={spans} />);

    expect(screen.getByText('#1 问题分类')).toBeInTheDocument();
    expect(screen.getByText('#2 答案生成')).toBeInTheDocument();
    expect(screen.getByText('35 ms')).toBeInTheDocument();
    expect(screen.getByText('Version v1')).toBeInTheDocument();
    expect(screen.getByText(/人口总体稳定/)).toBeInTheDocument();
  });
});
