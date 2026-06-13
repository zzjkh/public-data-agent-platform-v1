import type { PropsWithChildren } from 'react';
import { Navigate } from 'react-router-dom';

import { getCurrentUser, type User } from '../../api/auth';

interface AuthGuardProps extends PropsWithChildren {
  requiredRole?: User['role'];
}

export function AuthGuard({ children, requiredRole }: AuthGuardProps) {
  const token = localStorage.getItem('access_token');

  if (!token) {
    return <Navigate to="/login" replace />;
  }

  const user = getCurrentUser();
  if (requiredRole && user?.role !== requiredRole) {
    return (
      <div role="alert" style={{ padding: 24 }}>
        403：当前账号没有访问该页面的权限。
      </div>
    );
  }

  return children;
}
