import { apiClient } from './client';

export interface SourceFile {
  id: string;
  file_name: string;
  file_type: string;
  storage_uri: string;
  source_url: string | null;
  file_hash: string;
  file_version: string;
  parse_status: string;
  error_message: string | null;
  uploaded_by: string | null;
  uploaded_at: string;
}

export interface SourceFileListResponse {
  items: SourceFile[];
  page: number;
  page_size: number;
  total: number;
  request_id: string;
}

export async function listFiles() {
  const response = await apiClient.get<SourceFileListResponse>('/api/files', {
    params: { page: 1, page_size: 20 },
  });
  return response.data;
}
