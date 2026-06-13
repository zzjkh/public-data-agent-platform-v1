import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { QaResponse } from '../api/qa';
import { loadQaPageSession, saveQaPageSession } from '../utils/qaSession';
import { getQaErrorMessage } from './QaPage';
import { QaPage } from './QaPage';

vi.mock('../api/qa', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/qa')>();
  return { ...actual, askQuestion: vi.fn() };
});

const restoredResponse: QaResponse = {
  trace_id: 'trace-1',
  route_type: 'DATA_QA',
  answer: '已恢复的问答结果',
  citations: [],
  sql: null,
  chart: null,
  request_id: 'request-1',
};

describe('getQaErrorMessage', () => {
  it('shows dependency, timeout, and network errors separately', () => {
    expect(
      getQaErrorMessage({
        isAxiosError: true,
        response: { status: 503, data: { error: { message: 'Embedding 服务暂不可用' } } },
      }),
    ).toBe('Embedding 服务暂不可用');
    expect(getQaErrorMessage({ isAxiosError: true, code: 'ECONNABORTED' })).toBe(
      '问答处理超时，请缩小问题范围后重试',
    );
    expect(getQaErrorMessage({ isAxiosError: true })).toBe(
      '无法连接后端服务，请检查服务状态后重试',
    );
  });
});

describe('QaPage session restoration', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    localStorage.setItem(
      'current_user',
      JSON.stringify({
        id: 'user-1',
        username: 'admin',
        role: 'admin',
        is_active: true,
        created_at: '2026-06-12T00:00:00Z',
      }),
    );
  });

  it('restores and clears the latest question and response', async () => {
    saveQaPageSession('admin', '恢复这个问题', restoredResponse);
    const user = userEvent.setup();
    renderQaPage();

    expect(screen.getByRole('textbox', { name: '请输入问题' })).toHaveValue('恢复这个问题');
    expect(screen.getByText('已恢复的问答结果')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '清除本次问答' }));

    expect(screen.queryByText('已恢复的问答结果')).not.toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: '请输入问题' })).toHaveValue('');
    expect(loadQaPageSession('admin')).toBeNull();
  });

  it('keeps an unsubmitted draft after navigating to another child page', async () => {
    const user = userEvent.setup();
    renderQaRouteHarness();

    await user.type(screen.getByRole('textbox', { name: '请输入问题' }), '跨页面保留的问题');
    await user.click(screen.getByRole('link', { name: '文档管理' }));
    expect(screen.getByText('文档子页面')).toBeInTheDocument();

    await user.click(screen.getByRole('link', { name: '智能问答' }));
    expect(screen.getByRole('textbox', { name: '请输入问题' })).toHaveValue(
      '跨页面保留的问题',
    );
  });

  it('keeps the latest response after navigating to another child page', async () => {
    saveQaPageSession('admin', '恢复这个问题', restoredResponse);
    const user = userEvent.setup();
    renderQaRouteHarness();

    await user.click(screen.getByRole('link', { name: '文档管理' }));
    await user.click(screen.getByRole('link', { name: '智能问答' }));

    expect(screen.getByText('已恢复的问答结果')).toBeInTheDocument();
  });
});

function renderQaPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <QaPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function renderQaRouteHarness() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/qa']}>
        <nav>
          <Link to="/qa">智能问答</Link>
          <Link to="/documents">文档管理</Link>
        </nav>
        <Routes>
          <Route path="/qa" element={<QaPage />} />
          <Route path="/documents" element={<div>文档子页面</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
