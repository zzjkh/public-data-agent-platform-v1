import { apiClient } from './client';

export interface OpenDataset {
  id: string;
  name: string;
  description: string | null;
  category: string | null;
  department: string | null;
  owner: string | null;
  source_platform: string | null;
  source_url: string | null;
  open_type: string | null;
  update_frequency: string | null;
  update_date: string | null;
  time_range: string | null;
  region_level: string | null;
  sensitivity_level: string | null;
  download_count: number;
  api_count: number;
  status: string;
  last_synced_at: string | null;
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface OpenDatasetListResponse {
  items: OpenDataset[];
  page: number;
  page_size: number;
  total: number;
  request_id: string;
}

export async function listDatasets() {
  const response = await apiClient.get<OpenDatasetListResponse>('/api/datasets', {
    params: { page: 1, page_size: 20 },
  });
  return response.data;
}
