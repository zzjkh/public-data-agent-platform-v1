import { apiClient } from './client';

export interface Job {
  id: string;
  job_type: string;
  target_type: string;
  target_id: string | null;
  status: string;
  priority: number;
  payload_json: Record<string, unknown>;
  result_json: Record<string, unknown> | null;
  error_message: string | null;
  retry_count: number;
  max_retries: number;
  locked_by: string | null;
  locked_at: string | null;
  heartbeat_at: string | null;
  progress_percent: number;
  created_by: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface JobListResponse {
  items: Job[];
  page: number;
  page_size: number;
  total: number;
  request_id: string;
}

export async function listJobs() {
  const response = await apiClient.get<JobListResponse>('/api/jobs', {
    params: { page: 1, page_size: 20 },
  });
  return response.data;
}
