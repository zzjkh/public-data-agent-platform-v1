import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { getLoginErrorMessage, LoginPage } from './LoginPage';

describe('LoginPage', () => {
  it('renders the login form', () => {
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole('heading', { name: '登录' })).toBeInTheDocument();
    expect(screen.getByLabelText('用户名')).toBeInTheDocument();
    expect(screen.getByLabelText('密码')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /登\s*录/ })).toBeInTheDocument();
  });

  it('distinguishes invalid credentials from connection failures', () => {
    expect(
      getLoginErrorMessage({
        isAxiosError: true,
        response: { status: 401 },
      }),
    ).toBe('用户名或密码错误');
    expect(getLoginErrorMessage(new Error('network failed'))).toBe(
      '无法连接后端服务，请检查服务地址或稍后重试',
    );
  });
});
