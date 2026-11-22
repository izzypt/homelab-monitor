import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import type { EChartsCoreOption } from 'echarts/core';
import { NgxEchartsDirective } from 'ngx-echarts';

export interface Series {
  name: string;
  /** [ISO time, value] pairs; null values leave a gap. */
  points: [string, number | null][];
}

/**
 * Theme colours come from the page's Material tokens, so charts follow light/dark mode.
 * The tokens can be `light-dark(...)` expressions, which canvas can't parse, so resolve them
 * to a plain rgb() through a probe element.
 */
function themeColor(name: string, fallback: string): string {
  const probe = document.createElement('span');
  probe.style.color = `var(${name}, ${fallback})`;
  document.body.appendChild(probe);
  const color = getComputedStyle(probe).color;
  probe.remove();
  return color || fallback;
}

/** Time-series line chart (ECharts) with a shared tooltip. */
@Component({
  selector: 'app-line-chart',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NgxEchartsDirective],
  template: `<div echarts [options]="options()" class="chart" [style.height.px]="height()"></div>`,
  styles: `
    .chart {
      width: 100%;
    }
  `,
})
export class LineChart {
  readonly series = input.required<Series[]>();
  readonly unit = input('');
  readonly max = input<number | undefined>(undefined);
  readonly height = input(260);

  protected readonly options = computed<EChartsCoreOption>(() => {
    const text = themeColor('--mat-sys-on-surface-variant', '#666');
    const grid = themeColor('--mat-sys-outline-variant', '#ddd');
    const unit = this.unit();
    return {
      animation: false,
      textStyle: { color: text },
      grid: { left: 48, right: 16, top: 32, bottom: 32 },
      legend: { top: 0, textStyle: { color: text } },
      tooltip: {
        trigger: 'axis',
        valueFormatter: (v: unknown) =>
          v == null ? '—' : `${Math.round(Number(v) * 10) / 10}${unit}`,
      },
      xAxis: { type: 'time', axisLine: { lineStyle: { color: grid } } },
      yAxis: {
        type: 'value',
        min: 0,
        max: this.max(),
        axisLabel: { formatter: `{value}${unit}` },
        splitLine: { lineStyle: { color: grid } },
      },
      series: this.series().map((s) => ({
        name: s.name,
        type: 'line',
        showSymbol: false,
        connectNulls: false,
        data: s.points,
      })),
    };
  });
}
