import { apiClient } from './client';

export interface EvalCase {
  id: string;
  case_type: string;
  question: string;
  expected_route_type: string | null;
  expected_behavior: string | null;
  expected_sources_json: string[];
  expected_view: string | null;
  expected_metric_codes_json: string[];
  expected_sql_pattern: string | null;
  expected_sql_result_json: Record<string, unknown>;
  expected_keywords_json: string[];
  judge_model: string | null;
  prompt_version: string | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface EvalRun {
  id: string;
  name: string;
  model_name: string;
  embedding_model: string;
  judge_model: string | null;
  prompt_versions_json: Record<string, unknown>;
  run_config_json: Record<string, unknown>;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export interface EvalCaseListResponse {
  items: EvalCase[];
  page: number;
  page_size: number;
  total: number;
  request_id: string;
}

export interface EvalRunListResponse {
  items: EvalRun[];
  page: number;
  page_size: number;
  total: number;
  request_id: string;
}

export async function listEvalCases() {
  const response = await apiClient.get<EvalCaseListResponse>('/api/eval/cases', {
    params: { page: 1, page_size: 20, enabled: true },
  });
  return response.data;
}

export async function listEvalRuns() {
  const response = await apiClient.get<EvalRunListResponse>('/api/eval/runs', {
    params: { page: 1, page_size: 20 },
  });
  return response.data;
}
