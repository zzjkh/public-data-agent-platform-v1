import { apiClient } from './client';

export const QA_REQUEST_TIMEOUT_MS = Number(
  import.meta.env.VITE_QA_REQUEST_TIMEOUT_MS ?? 120_000,
);

export type RouteType = 'POLICY_QA' | 'DATA_QA' | 'HYBRID_QA' | 'OTHER';
export type ChartType = 'line' | 'bar' | 'pie' | 'table';

export interface QaCitation {
  type: 'policy' | 'data';
  source_title: string;
  source_url: string | null;
  section_path: string | null;
  quote: string | null;
}

export interface QaSqlPayload {
  validated_sql: string;
  row_count: number;
  columns: string[];
  result_preview: Record<string, unknown>[];
}

export interface ChartSpec {
  chart_type: ChartType;
  x_field: string | null;
  y_field: string | null;
  series_field: string | null;
  title: string;
  reason: string;
}

export interface QaResponse {
  trace_id: string;
  route_type: RouteType;
  answer: string;
  citations: QaCitation[];
  sql: QaSqlPayload | null;
  chart: ChartSpec | null;
  request_id: string;
}

export interface QaAskRequest {
  question: string;
  options?: {
    return_trace?: boolean;
  };
}

export async function askQuestion(request: QaAskRequest) {
  const response = await apiClient.post<QaResponse>('/api/qa/ask', request, {
    timeout: QA_REQUEST_TIMEOUT_MS,
  });
  return response.data;
}
