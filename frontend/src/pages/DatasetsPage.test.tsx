import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { DATASET_TABLE_SCROLL_X, DatasetsPage } from './DatasetsPage';

vi.mock('../api/datasets', () => ({
  listDatasets: vi.fn().mockResolvedValue({
    items: [
      {
        id: 'dataset-1',
        name: '京津冀协同开放数据专题',
        category: '区域协同',
        department: '北京市相关部门',
        owner: null,
        description: null,
        source_platform: null,
        source_url: 'https://example.com/datasets/1',
        open_type: '政府公开',
        update_frequency: '年度',
        update_date: '2026-01-01',
        time_range: '2020-2025',
        region_level: 'province',
        sensitivity_level: 'public',
        download_count: 0,
        api_count: 0,
        status: 'active',
        last_synced_at: null,
        metadata_json: {},
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
    ],
    page: 1,
    page_size: 20,
    total: 1,
    request_id: 'request-1',
  }),
}));

describe('DatasetsPage', () => {
  it('keeps a fixed minimum table width instead of squeezing Chinese columns vertically', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <DatasetsPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByText('京津冀协同开放数据专题')).toBeInTheDocument();
    await waitFor(() => {
      const table = container.querySelector('.ant-table-content table');
      expect(table).toHaveStyle({ width: `${DATASET_TABLE_SCROLL_X}px` });
      expect(table).toHaveStyle({ minWidth: '100%' });
    });
  });
});
