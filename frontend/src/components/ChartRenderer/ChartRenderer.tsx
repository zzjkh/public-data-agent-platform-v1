import type { EChartsOption, SeriesOption } from 'echarts';
import { Card, Empty, Spin, Table, Typography } from 'antd';
import { lazy, Suspense } from 'react';

import type { ChartSpec } from '../../api/qa';

const EChartCanvas = lazy(() => import('./EChartCanvas'));

interface ChartRendererProps {
  chart: ChartSpec | null;
  rows: Record<string, unknown>[];
}

export function ChartRenderer({ chart, rows }: ChartRendererProps) {
  if (!chart) {
    return (
      <Card title="图表">
        <Empty description="暂无图表推荐" />
      </Card>
    );
  }

  if (!canRenderChart(chart, rows)) {
    return (
      <Card title={chart.title}>
        <Typography.Paragraph type="secondary">
          图表字段不足，已降级为表格展示。{chart.reason}
        </Typography.Paragraph>
        <FallbackTable rows={rows} />
      </Card>
    );
  }

  if (chart.chart_type === 'table') {
    return (
      <Card title={chart.title}>
        <Typography.Paragraph type="secondary">{chart.reason}</Typography.Paragraph>
        <FallbackTable rows={rows} />
      </Card>
    );
  }

  const option = buildChartOption(chart, rows);
  if (!option) {
    return (
      <Card title={chart.title}>
        <Typography.Paragraph type="secondary">
          图表配置无效，已降级为表格展示。{chart.reason}
        </Typography.Paragraph>
        <FallbackTable rows={rows} />
      </Card>
    );
  }

  return (
    <Card title={chart.title}>
      <Typography.Paragraph type="secondary">{chart.reason}</Typography.Paragraph>
      <Suspense fallback={<Spin description="图表加载中" />}>
        <EChartCanvas option={option} ariaLabel={`${chart.chart_type} chart`} />
      </Suspense>
    </Card>
  );
}

export function canRenderChart(chart: ChartSpec, rows: Record<string, unknown>[]) {
  if (chart.chart_type === 'table') {
    return rows.length > 0;
  }
  const xField = chart.x_field;
  const yField = chart.y_field;
  if (!xField || !yField || rows.length === 0) {
    return false;
  }
  return rows.every(
    (row) => xField in row && yField in row && Number.isFinite(toNumber(row[yField])),
  );
}

export function buildChartOption(
  chart: ChartSpec,
  rows: Record<string, unknown>[],
): EChartsOption | null {
  if (!canRenderChart(chart, rows) || chart.chart_type === 'table') {
    return null;
  }
  const xField = chart.x_field as string;
  const yField = chart.y_field as string;
  const unit = inferUnit(rows);

  if (chart.chart_type === 'pie') {
    return {
      aria: { enabled: true, description: chart.title },
      tooltip: { trigger: 'item' },
      legend: { type: 'scroll', bottom: 0 },
      series: [
        {
          type: 'pie',
          radius: ['35%', '68%'],
          center: ['50%', '45%'],
          label: { formatter: `{b}: {c}${unit}` },
          data: rows.map((row) => ({
            name: pieLabel(row, xField, chart.series_field),
            value: toNumber(row[yField]),
          })),
        },
      ],
    };
  }

  const categories = uniqueValues(rows.map((row) => String(row[xField] ?? '-')));
  const series = buildCartesianSeries(chart, rows, categories, xField, yField);
  return {
    aria: { enabled: true, description: chart.title },
    tooltip: { trigger: 'axis', valueFormatter: (value) => `${String(value)}${unit}` },
    legend: series.length > 1 ? { type: 'scroll', top: 0 } : undefined,
    grid: { left: 56, right: 24, top: series.length > 1 ? 48 : 24, bottom: 48 },
    xAxis: {
      type: 'category',
      data: categories,
      name: xField,
      nameLocation: 'middle',
      nameGap: 30,
      axisLabel: { hideOverlap: true },
    },
    yAxis: {
      type: 'value',
      name: unit || yField,
      scale: chart.chart_type === 'line',
    },
    series,
  };
}

function buildCartesianSeries(
  chart: ChartSpec,
  rows: Record<string, unknown>[],
  categories: string[],
  xField: string,
  yField: string,
): SeriesOption[] {
  const chartType = chart.chart_type === 'line' ? 'line' : 'bar';
  const seriesField = chart.series_field;
  if (!seriesField || !rows.every((row) => seriesField in row)) {
    return [
      {
        type: chartType,
        name: chart.title,
        data: categories.map((category) => {
          const row = rows.find((item) => String(item[xField] ?? '-') === category);
          return row ? toNumber(row[yField]) : null;
        }),
        smooth: chartType === 'line',
        showSymbol: true,
      },
    ];
  }

  const seriesNames = uniqueValues(rows.map((row) => String(row[seriesField] ?? '-')));
  return seriesNames.map((seriesName) => ({
    type: chartType,
    name: seriesName,
    data: categories.map((category) => {
      const row = rows.find(
        (item) =>
          String(item[xField] ?? '-') === category &&
          String(item[seriesField] ?? '-') === seriesName,
      );
      return row ? toNumber(row[yField]) : null;
    }),
    smooth: chartType === 'line',
    showSymbol: true,
  }));
}

function FallbackTable({ rows }: { rows: Record<string, unknown>[] }) {
  const columns = Object.keys(rows[0] ?? {}).map((column) => ({
    title: column,
    dataIndex: column,
    key: column,
    render: (value: unknown) =>
      typeof value === 'object' ? JSON.stringify(value) : String(value ?? '-'),
  }));
  const dataSource = rows.map((row, index) => ({
    ...row,
    __rowKey: stableRowKey(row, index),
  }));

  return (
    <Table
      size="small"
      rowKey="__rowKey"
      dataSource={dataSource}
      columns={columns}
      pagination={false}
    />
  );
}

function stableRowKey(row: Record<string, unknown>, index: number) {
  const values = Object.values(row)
    .slice(0, 3)
    .map((value) => String(value ?? ''))
    .join('|');
  return `${values}|${index}`;
}

function pieLabel(row: Record<string, unknown>, xField: string, seriesField: string | null) {
  const category = String(row[xField] ?? '-');
  if (!seriesField || !(seriesField in row)) {
    return category;
  }
  return `${category} · ${String(row[seriesField] ?? '-')}`;
}

function inferUnit(rows: Record<string, unknown>[]) {
  const units = uniqueValues(
    rows.map((row) => String(row.unit ?? '')).filter((unit) => unit.length > 0),
  );
  return units.length === 1 ? units[0] : '';
}

function uniqueValues(values: string[]) {
  return [...new Set(values)];
}

function toNumber(value: unknown) {
  if (typeof value === 'number') {
    return value;
  }
  if (typeof value === 'string' && value.trim()) {
    return Number(value);
  }
  return Number.NaN;
}
