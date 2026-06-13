import { beforeEach, describe, expect, it, vi } from 'vitest';

import { apiClient } from './client';
import { askQuestion, QA_REQUEST_TIMEOUT_MS } from './qa';

vi.mock('./client', () => ({
  apiClient: {
    post: vi.fn(),
  },
}));

describe('askQuestion', () => {
  beforeEach(() => {
    vi.mocked(apiClient.post).mockReset();
  });

  it('uses the dedicated long-running QA timeout', async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ data: { answer: 'ok' } });

    await askQuestion({ question: '测试问题' });

    expect(QA_REQUEST_TIMEOUT_MS).toBe(120_000);
    expect(apiClient.post).toHaveBeenCalledWith(
      '/api/qa/ask',
      { question: '测试问题' },
      { timeout: 120_000 },
    );
  });
});
