import type { EChartsOption } from 'echarts';
import ReactECharts from 'echarts-for-react';

interface EChartCanvasProps {
  option: EChartsOption;
  ariaLabel: string;
}

export default function EChartCanvas({ option, ariaLabel }: EChartCanvasProps) {
  return (
    <div aria-label={ariaLabel} role="img">
      <ReactECharts
        option={option}
        notMerge
        lazyUpdate
        style={{ width: '100%', height: 340 }}
      />
    </div>
  );
}
