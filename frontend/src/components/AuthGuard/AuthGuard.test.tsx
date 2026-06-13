import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';

import { AuthGuard } from './AuthGuard';

describe('AuthGuard', () => {
  afterEach(() => {
    localStorage.clear();
  });

  it('redirects unauthenticated users to login', () => {
    render(
      <MemoryRouter initialEntries={['/documents']}>
        <Routes>
          <Route
            path="/documents"
            element={
              <AuthGuard>
                <div>文档管理</div>
              </AuthGuard>
            }
          />
          <Route path="/login" element={<div>登录页面</div>} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText('登录页面')).toBeInTheDocument();
  });

  it('blocks non-admin users from admin pages', () => {
    localStorage.setItem('access_token', 'token');
    localStorage.setItem(
      'current_user',
      JSON.stringify({ id: 'u1', username: 'demo', role: 'user', is_active: true, created_at: '' }),
    );

    render(
      <MemoryRouter>
        <AuthGuard requiredRole="admin">
          <div>管理后台</div>
        </AuthGuard>
      </MemoryRouter>,
    );

    expect(screen.getByRole('alert')).toHaveTextContent('403');
    expect(screen.queryByText('管理后台')).not.toBeInTheDocument();
  });
});
