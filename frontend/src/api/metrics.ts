import { apiClient } from './client';

export interface Metric {
  id: string;
  indicator_code: string;
  indicator_name: string;
  domain: string;
  unit: string | null;
  description: string | null;
  aliases_json: string[];
  source_dataset_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface MetricListResponse {
  items: Metric[];
  page: number;
  page_size: number;
  total: number;
  request_id: string;
}

export async function listMetrics() {
  const response = await apiClient.get<MetricListResponse>('/api/metrics', {
    params: { page: 1, page_size: 20 },
  });
  return response.data;
}
