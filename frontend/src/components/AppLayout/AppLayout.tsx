import {
  BarChartOutlined,
  ClockCircleOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  MessageOutlined,
  ProfileOutlined,
  ReadOutlined,
} from '@ant-design/icons';
import { Layout, Menu, Typography } from 'antd';
import type { PropsWithChildren } from 'react';
import { Link, useLocation } from 'react-router-dom';

const { Header, Content, Sider } = Layout;

export function AppLayout({ children }: PropsWithChildren) {
  const location = useLocation();
  const selectedKey = selectedMenuKey(location.pathname);

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header style={{ display: 'flex', alignItems: 'center' }}>
        <Typography.Title level={4} style={{ color: '#fff', margin: 0 }}>
          公共数据开放智能平台
        </Typography.Title>
      </Header>
      <Layout>
        <Sider width={224} theme="light">
          <Menu
            mode="inline"
            selectedKeys={[selectedKey]}
            style={{ height: '100%', borderRight: 0 }}
            items={[
              {
                key: '/qa',
                icon: <MessageOutlined />,
                label: <Link to="/qa">智能问答</Link>,
              },
              {
                key: '/documents',
                icon: <FileTextOutlined />,
                label: <Link to="/documents">文档管理</Link>,
              },
              {
                key: '/datasets',
                icon: <DatabaseOutlined />,
                label: <Link to="/datasets">数据集管理</Link>,
              },
              {
                key: '/metrics',
                icon: <BarChartOutlined />,
                label: <Link to="/metrics">指标管理</Link>,
              },
              {
                key: '/jobs',
                icon: <ClockCircleOutlined />,
                label: <Link to="/jobs">任务管理</Link>,
              },
              {
                key: '/evaluation/cases',
                icon: <ReadOutlined />,
                label: <Link to="/evaluation/cases">评测用例</Link>,
              },
              {
                key: '/evaluation/runs',
                icon: <ReadOutlined />,
                label: <Link to="/evaluation/runs">评测运行</Link>,
              },
              {
                key: '/traces',
                icon: <ProfileOutlined />,
                label: <Link to="/traces">Trace 追踪</Link>,
              },
            ]}
          />
        </Sider>
        <Content style={{ padding: 24 }}>{children}</Content>
      </Layout>
    </Layout>
  );
}

function selectedMenuKey(pathname: string) {
  if (pathname.startsWith('/traces')) return '/traces';
  if (pathname.startsWith('/evaluation/cases')) return '/evaluation/cases';
  if (pathname.startsWith('/evaluation/runs')) return '/evaluation/runs';
  return pathname;
}
