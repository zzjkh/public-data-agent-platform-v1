import { createBrowserRouter, Navigate } from 'react-router-dom';

import { AppLayout } from '../components/AppLayout';
import { AuthGuard } from '../components/AuthGuard';
import { DatasetsPage } from '../pages/DatasetsPage';
import { DocumentsPage } from '../pages/DocumentsPage';
import { EvalCasesPage } from '../pages/EvalCasesPage';
import { EvalRunsPage } from '../pages/EvalRunsPage';
import { JobsPage } from '../pages/JobsPage';
import { LoginPage } from '../pages/LoginPage';
import { MetricsPage } from '../pages/MetricsPage';
import { QaPage } from '../pages/QaPage';
import { TraceDetailPage } from '../pages/TraceDetailPage';
import { TracesPage } from '../pages/TracesPage';
import type { User } from '../api/auth';

function ProtectedPage({
  children,
  requiredRole,
}: {
  children: React.ReactNode;
  requiredRole?: User['role'];
}) {
  return (
    <AuthGuard requiredRole={requiredRole}>
      <AppLayout>{children}</AppLayout>
    </AuthGuard>
  );
}

export const router = createBrowserRouter([
  {
    path: '/',
    element: <Navigate to="/qa" replace />,
  },
  {
    path: '/login',
    element: <LoginPage />,
  },
  {
    path: '/qa',
    element: (
      <ProtectedPage>
        <QaPage />
      </ProtectedPage>
    ),
  },
  {
    path: '/documents',
    element: (
      <ProtectedPage requiredRole="admin">
        <DocumentsPage />
      </ProtectedPage>
    ),
  },
  {
    path: '/datasets',
    element: (
      <ProtectedPage requiredRole="admin">
        <DatasetsPage />
      </ProtectedPage>
    ),
  },
  {
    path: '/metrics',
    element: (
      <ProtectedPage requiredRole="admin">
        <MetricsPage />
      </ProtectedPage>
    ),
  },
  {
    path: '/jobs',
    element: (
      <ProtectedPage requiredRole="admin">
        <JobsPage />
      </ProtectedPage>
    ),
  },
  {
    path: '/evaluation/cases',
    element: (
      <ProtectedPage requiredRole="admin">
        <EvalCasesPage />
      </ProtectedPage>
    ),
  },
  {
    path: '/evaluation/runs',
    element: (
      <ProtectedPage requiredRole="admin">
        <EvalRunsPage />
      </ProtectedPage>
    ),
  },
  {
    path: '/traces',
    element: (
      <ProtectedPage>
        <TracesPage />
      </ProtectedPage>
    ),
  },
  {
    path: '/traces/:traceId',
    element: (
      <ProtectedPage>
        <TraceDetailPage />
      </ProtectedPage>
    ),
  },
]);
