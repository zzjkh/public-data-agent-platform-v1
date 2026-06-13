import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { ChartSpec } from '../../api/qa';
import { buildChartOption, canRenderChart, ChartRenderer } from './ChartRenderer';

vi.mock('./EChartCanvas', () => ({
  default: ({ ariaLabel }: { ariaLabel: string }) => <div aria-label={ariaLabel} role="img" />,
}));

const rows = [
  { stat_year: 2023, value_numeric: 2185.8 },
  { stat_year: 2024, value_numeric: 2183.2 },
];

describe('ChartRenderer', () => {
  it('renders a real chart container when fields are valid', async () => {
    const chart: ChartSpec = {
      chart_type: 'bar',
      x_field: 'stat_year',
      y_field: 'value_numeric',
      series_field: null,
      title: '常住人口变化',
      reason: '年份和数值字段适合柱状图。',
    };

    render(<ChartRenderer chart={chart} rows={rows} />);

    expect(screen.getByText('常住人口变化')).toBeInTheDocument();
    expect(await screen.findByRole('img', { name: 'bar chart' })).toBeInTheDocument();
    expect(canRenderChart(chart, rows)).toBe(true);
  });

  it('builds a line option with axes and numeric data', () => {
    const chart: ChartSpec = {
      chart_type: 'line',
      x_field: 'stat_year',
      y_field: 'value_numeric',
      series_field: null,
      title: '常住人口趋势',
      reason: '趋势数据使用折线图。',
    };

    const option = buildChartOption(chart, rows);

    expect(option?.xAxis).toMatchObject({ type: 'category', data: ['2023', '2024'] });
    expect(option?.series).toMatchObject([{ type: 'line', data: [2185.8, 2183.2] }]);
  });

  it('falls back to a table when chart fields are missing', () => {
    const chart: ChartSpec = {
      chart_type: 'line',
      x_field: 'missing_year',
      y_field: 'value_numeric',
      series_field: null,
      title: '字段错误的图表',
      reason: '缺少 x 字段。',
    };

    render(<ChartRenderer chart={chart} rows={rows} />);

    expect(screen.getByText(/已降级为表格展示/)).toBeInTheDocument();
    expect(screen.getByText('stat_year')).toBeInTheDocument();
    expect(canRenderChart(chart, rows)).toBe(false);
  });
});
