import { useEffect, useState } from 'react';
import Link from 'next/link';
import { apiGet } from '../lib/api';

type HealthResponse = {
  ok: boolean;
  status: string;
  service: string;
  checked_at: string;
  timezone: string;
  checks: Record<string, string>;
  database: { ok: boolean; url_kind?: string; tables?: Record<string, number>; error?: string };
  scheduler: { enabled: boolean; running: boolean; cron: string; timezone: string; next_run_time?: string | null };
  trading_day: { is_trading_day: boolean; date: string; source: string; warning?: string };
  configuration: Record<string, unknown>;
  data_sources: Array<{ name: string; type: string }>;
};

export default function HealthPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [message, setMessage] = useState('');

  useEffect(() => {
    apiGet<HealthResponse>('/api/system/health')
      .then(setHealth)
      .catch((error) => setMessage(error instanceof Error ? error.message : String(error)));
  }, []);

  return (
    <main className="container">
      <Link href="/">← 返回首页</Link>
      <h1>系统健康检查</h1>
      <p className="muted">检查数据库、调度器、交易日历、关键配置和数据源类型。</p>

      {message && <p className="notice">{message}</p>}
      {!health && !message && <p className="muted">正在读取健康状态...</p>}

      {health && (
        <section className="grid two">
          <div className="card">
            <p className="eyebrow dark">overall</p>
            <h2>{health.status.toUpperCase()}</h2>
            <p>{health.service}</p>
            <p className="muted">{health.checked_at} · {health.timezone}</p>
          </div>

          <div className="card">
            <h2>检查项</h2>
            <ul>
              {Object.entries(health.checks).map(([key, value]) => (
                <li key={key}>{key}：<strong>{value}</strong></li>
              ))}
            </ul>
          </div>

          <div className="card">
            <h2>数据库</h2>
            <p>{health.database.ok ? '可连接' : '异常'} · {health.database.url_kind || 'unknown'}</p>
            {health.database.error && <p className="warning">{health.database.error}</p>}
            <ul>
              {Object.entries(health.database.tables || {}).map(([key, value]) => (
                <li key={key}>{key}：{value}</li>
              ))}
            </ul>
          </div>

          <div className="card">
            <h2>调度器</h2>
            <p>{health.scheduler.running ? '运行中' : '未运行'} · {health.scheduler.enabled ? '已启用' : '未启用'}</p>
            <p>排程：{health.scheduler.cron} · {health.scheduler.timezone}</p>
            <p>下一次：{health.scheduler.next_run_time || '暂无'}</p>
          </div>

          <div className="card wide">
            <h2>交易日历</h2>
            <p>{health.trading_day.date}：{health.trading_day.is_trading_day ? 'A股交易日' : '非A股交易日'}</p>
            <p className="muted">{health.trading_day.source}</p>
            {health.trading_day.warning && <p className="warning">{health.trading_day.warning}</p>}
          </div>

          <div className="card">
            <h2>关键配置</h2>
            <ul>
              {Object.entries(health.configuration).map(([key, value]) => (
                <li key={key}>{key}：{Array.isArray(value) ? value.join('、') : String(value)}</li>
              ))}
            </ul>
          </div>

          <div className="card">
            <h2>数据源</h2>
            <ul>
              {health.data_sources.map((source) => (
                <li key={source.name}>{source.name}：{source.type}</li>
              ))}
            </ul>
          </div>
        </section>
      )}
    </main>
  );
}
