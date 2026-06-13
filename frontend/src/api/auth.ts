import { apiClient } from './client';

export type User = {
  id: string;
  username: string;
  role: 'admin' | 'user';
  is_active: boolean;
  created_at: string;
};

export type LoginResponse = {
  access_token: string;
  token_type: 'bearer';
  user: User;
};

export function getCurrentUser(): User | null {
  const raw = localStorage.getItem('current_user');
  if (!raw) {
    return null;
  }
  try {
    return JSON.parse(raw) as User;
  } catch {
    localStorage.removeItem('current_user');
    return null;
  }
}

export async function login(username: string, password: string): Promise<LoginResponse> {
  const response = await apiClient.post<LoginResponse>('/api/auth/login', {
    username,
    password,
  });
  return response.data;
}
