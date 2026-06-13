import { apiClient } from './client';

export type TraceStatus = 'running' | 'success' | 'failed' | 'refused';
export type TraceSpanStatus = 'success' | 'failed' | 'skipped';

export interface TraceSummary {
  id: string;
  user_id: string | null;
  user_question: string;
  route_type: string | null;
  final_answer: string | null;
  status: TraceStatus;
  latency_ms: number | null;
  created_at: string;
}

export interface TraceSpan {
  id: string;
  trace_id: string;
  parent_span_id: string | null;
  span_order: number;
  span_type: string;
  input_json: Record<string, unknown>;
  output_json: Record<string, unknown> | null;
  latency_ms: number;
  status: TraceSpanStatus;
  error_message: string | null;
  started_at: string | null;
  ended_at: string | null;
  model_name: string | null;
  prompt_name: string | null;
  prompt_version: string | null;
  token_usage_json: Record<string, unknown>;
  cost_json: Record<string, unknown>;
  retry_count: number;
  created_at: string;
}

export interface TraceListResponse {
  items: TraceSummary[];
  page: number;
  page_size: number;
  total: number;
  request_id: string;
}

export interface TraceDetailResponse extends TraceSummary {
  spans: TraceSpan[];
  request_id: string;
}

export interface TraceListParams {
  page?: number;
  page_size?: number;
  status?: TraceStatus;
  route_type?: string;
}

export async function listTraces(params: TraceListParams = {}) {
  const response = await apiClient.get<TraceListResponse>('/api/traces', { params });
  return response.data;
}

export async function getTrace(traceId: string) {
  const response = await apiClient.get<TraceDetailResponse>(`/api/traces/${traceId}`);
  return response.data;
}
