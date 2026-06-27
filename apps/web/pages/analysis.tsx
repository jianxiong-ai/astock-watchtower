import React, { FormEvent, useState } from 'react';
import Link from 'next/link';
import { ReportSections, type ReportSection } from '../components/ReportSections';
import { apiPost } from '../lib/api';

type AnalyzeResponse = {
  symbol: string;
  name: string;
  industry: string;
  data_mode: string;
  decision: string;
  market_weather: {
    classification: string;
    as_of?: string;
    indices?: Array<{ name: string; change_pct: number }>;
    breadth?: { up?: number; down?: number; rising_ratio?: number; timestamp?: string };
  };
  snapshot: { price: number; change_pct: number; timestamp: string; source: string; market_cap?: number | null; pe_dynamic?: number | null; pb?: number | null };
  universal_indicators: {
    valuation?: {
      status: string;
      market_cap?: number | null;
      float_market_cap?: number | null;
      pe_dynamic?: number | null;
      pb?: number | null;
      turnover_pct?: number | null;
      timestamp?: string;
      source?: string;
      warning?: string;
    };
    technicals?: {
      status: string;
      as_of?: string;
      ma?: Record<string, number | null>;
      rsi14?: number | null;
      high_low?: Record<string, number | null>;
      recent_peak_drawdown_pct?: number | null;
      volume_ratio_to_ma20?: number | null;
      signals?: string[];
      reason?: string;
    };
    financials?: {
      status: string;
      latest_fact_date?: string;
      evidence_lines?: string[];
      recent_facts?: Array<{
        label: string;
        value: string;
        fact_type: string;
        announcement_title: string;
        published_at: string;
        source_url: string;
      }>;
    };
  };
  sector_indicators: {
    core_metrics: string[];
    current_status: string;
    official_fact_evidence?: string[];
    mapped_summary?: string[];
    mapped_coverage?: Record<string, unknown>;
    mapped_metrics?: Array<{
      metric: string;
      status: string;
      latest_reading: string;
      as_of: string;
      source: string;
      source_url: string;
      relevance: string;
      next_evidence: string;
    }>;
  };
  events?: Array<{ title: string; type: string; importance: string; published_at: string; url: string; pdf_extract_status?: string; pdf_table_count?: number }>;
  missing_inputs: Array<{ metric: string; impact: string }>;
  stale_sources?: Array<{ metric: string; impact?: string }>;
  research_posture: { position_basis: string; posture: string; rationale: string };
  position?: {
    symbol: string;
    shares: number;
    average_cost: number;
    market_value?: number | null;
    unrealized_pnl?: number | null;
    unrealized_pnl_pct?: number | null;
  } | null;
  action_advice?: {
    posture?: string;
    severity?: string;
    position_summary?: string;
    trigger_condition?: string;
    invalidation_condition?: string;
    rationale?: string;
    main_risk?: string;
    next_decision_point?: string;
    lot_quantity_range?: string;
    position_pct?: number | null;
    summary_line?: string;
    urgency?: string;
    action_steps?: string[];
    risk_controls?: string[];
    decision_checklist?: string[];
    do_not?: string[];
  };
  report_sections?: ReportSection[];
};

function fmtLargeMoney(value?: number | null) {
  if (value === null || value === undefined) return '不可靠可得';
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return '不可靠可得';
  if (Math.abs(numeric) >= 100000000) return `¥${(numeric / 100000000).toFixed(2)}亿`;
  return `¥${numeric.toLocaleString()}`;
}

function fmtNumber(value?: number | string | null, digits = 1) {
  if (value === null || value === undefined || value === '') return '';
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return '';
  return numeric.toFixed(digits);
}

function safeArray<T>(value: T[] | null | undefined): T[] {
  return Array.isArray(value) ? value : [];
}

function safeTextArray(value: string[] | null | undefined): string[] {
  return Array.isArray(value) ? value.filter(Boolean) : [];
}

function fmtCoverage(value?: Record<string, unknown>) {
  if (!value) return '';
  const directAvailable = Number(value.available);
  const directMissing = Number(value.missing);
  const directTotal = Number(value.total);
  if (Number.isFinite(directAvailable) || Number.isFinite(directMissing) || Number.isFinite(directTotal)) {
    return `Available ${Number.isFinite(directAvailable) ? directAvailable : '—'} / Missing ${Number.isFinite(directMissing) ? directMissing : '—'} / Total ${Number.isFinite(directTotal) ? directTotal : '—'}`;
  }
  const total = value.total as Record<string, unknown> | undefined;
  const filing = value.filing as Record<string, unknown> | undefined;
  const provider = value.provider as Record<string, unknown> | undefined;
  const parts = [];
  if (total) parts.push(`合计 Available ${total.available ?? '—'} / Missing ${total.missing ?? '—'} / Total ${total.total ?? '—'}`);
  if (filing) parts.push(`公告/财报 ${filing.available ?? '—'} 可用`);
  if (provider) parts.push(`Provider ${provider.available ?? '—'} 可用`);
  return parts.join('；') || JSON.stringify(value);
}

class AnalysisRenderBoundary extends React.Component<{ children: React.ReactNode }, { error: string }> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { error: '' };
  }

  static getDerivedStateFromError(error: Error) {
    return { error: error.message || '未知渲染错误' };
  }

  render() {
    if (this.state.error) {
      return (
        <div className="card wide">
          <h2>报告渲染异常</h2>
          <p className="notice">分析数据已返回，但页面渲染某个字段时出错：{this.state.error}</p>
          <p className="muted">请保留当前股票和时间点，后续可以继续定位字段口径；页面不会再整体崩溃。</p>
        </div>
      );
    }
    return this.props.children;
  }
}

export function AnalysisWorkspace({ embedded = false }: { embedded?: boolean }) {
  const [query, setQuery] = useState('');
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);

  async function analyze(event: FormEvent) {
    event.preventDefault();
    const normalizedQuery = query.trim();
    if (!normalizedQuery) {
      setMessage('请输入股票名称或代码。');
      return;
    }
    setLoading(true);
    setMessage('');
    setResult(null);
    try {
      const data = await apiPost<AnalyzeResponse>('/api/analyze', { query: normalizedQuery, include_intraday: true });
      setResult(data);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className={embedded ? 'workspace-panel' : 'container'}>
      {!embedded && <Link href="/">← 返回首页</Link>}
      <h1>{embedded ? '分析' : '手动分析'}</h1>
      <p className="muted">输入任意 A 股公司名或代码。临时分析不会加入订阅。</p>

      <form className="card form inline" onSubmit={analyze}>
        <label>
          股票
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="请输入股票名称或代码" />
        </label>
        <button disabled={loading}>{loading ? '分析中...' : '开始分析'}</button>
      </form>

      {message && <p className="notice">{message}</p>}

      {result && (
        <AnalysisRenderBoundary>
        <section className="analysis-brief">
          <div>
            <p className="eyebrow">{result.symbol} · {result.industry} · {result.data_mode}</p>
            <h2>{result.name}</h2>
            <p className="brief-conclusion">
              {result.name}｜{result.decision}｜市场 {result.market_weather.classification || 'Unknown'}｜
              价格 ¥{result.snapshot.price}，涨跌幅 {result.snapshot.change_pct}%。
            </p>
            <p className="muted">
              截止：{result.snapshot.timestamp || '不可靠可得'} · 来源：{result.snapshot.source || '不可靠可得'}
              {result.market_weather.as_of ? ` · 市场天气：${result.market_weather.as_of}` : ''}
            </p>
          </div>
          <div className="analysis-brief-metrics">
            <span>Missing {safeArray(result.missing_inputs).length}</span>
            <span>Stale {safeArray(result.stale_sources).length}</span>
            <span>{result.action_advice?.posture ? `操作：${result.action_advice.posture}` : '未接持仓建议'}</span>
          </div>
        </section>

        {result.action_advice?.posture ? (
          <section className="card wide advice-card">
            <div className="section-header">
              <div>
                <p className="eyebrow">POSITION DISCIPLINE</p>
                <h2>持仓操作纪律</h2>
              </div>
              <span className={`badge ${result.action_advice.severity === 'medium' ? 'warning' : 'ok'}`}>
                {result.action_advice.posture}
              </span>
            </div>
            <p className="brief-conclusion">{result.action_advice.summary_line || result.action_advice.rationale}</p>
            {result.position && (
              <p className="muted">
                持仓：{result.position.shares} 股 · 成本 ¥{result.position.average_cost}
                {fmtNumber(result.action_advice.position_pct) ? ` · 估算仓位 ${fmtNumber(result.action_advice.position_pct)}%` : ''}
              </p>
            )}
            <div className="advice-grid">
              <div>
                <h3>执行步骤</h3>
                <ol>
                  {safeTextArray(result.action_advice.action_steps).slice(0, 4).map((item) => <li key={item}>{item}</li>)}
                </ol>
                {!safeTextArray(result.action_advice.action_steps).length && <p className="muted">暂无执行步骤。</p>}
              </div>
              <div>
                <h3>风控线</h3>
                <ul>
                  {safeTextArray(result.action_advice.risk_controls).slice(0, 4).map((item) => <li key={item}>{item}</li>)}
                </ul>
                {!safeTextArray(result.action_advice.risk_controls).length && <p className="muted">暂无风控线。</p>}
              </div>
            </div>
            <p>触发条件：{result.action_advice.trigger_condition || '—'}</p>
            <p>失效条件：{result.action_advice.invalidation_condition || '—'}</p>
            <p>下一决策点：{result.action_advice.next_decision_point || '—'}</p>
            <p className="muted">本模块只在股票已加入订阅池且存在本地交易记录/持仓基线时接入；不会执行交易。</p>
          </section>
        ) : (
          <section className="card wide subtle-card">
            <p className="muted">该股票未匹配到订阅池持仓基线，因此仅展示研究分析；如需操盘纪律，请先加入订阅并维护交易记录。</p>
          </section>
        )}

        <section className="grid two">
          <div className="card wide">
            <h2>完整报告</h2>
            <ReportSections sections={result.report_sections || []} />
          </div>

          <div className="card">
            <p className="eyebrow">{result.symbol} · {result.industry}</p>
            <h2>{result.name}</h2>
            <p className="big">¥{result.snapshot.price} <span>{result.snapshot.change_pct}%</span></p>
            <p className="muted">{result.snapshot.timestamp} · {result.snapshot.source}</p>
            <p>市场天气：<strong>{result.market_weather.classification}</strong></p>
            <p>触发判断：<strong>{result.decision}</strong></p>
          </div>

          <div className="card">
            <h2>估值</h2>
            {result.universal_indicators.valuation?.status === 'Available' ? (
              <>
                <p>总市值：<strong>{fmtLargeMoney(result.universal_indicators.valuation.market_cap)}</strong></p>
                <p>流通市值：{fmtLargeMoney(result.universal_indicators.valuation.float_market_cap)}</p>
                <p>PE：{result.universal_indicators.valuation.pe_dynamic ?? '不可靠可得'} · PB：{result.universal_indicators.valuation.pb ?? '不可靠可得'}</p>
                <p>换手率：{result.universal_indicators.valuation.turnover_pct ?? '不可靠可得'}%</p>
                <p className="muted">{result.universal_indicators.valuation.timestamp} · {result.universal_indicators.valuation.source || 'secondary valuation'}</p>
              </>
            ) : (
              <p className="muted">{result.universal_indicators.valuation?.warning || '估值不可靠可得'}</p>
            )}
          </div>

          <div className="card wide">
            <h2>技术指标</h2>
            {result.universal_indicators.technicals?.status === 'Available' ? (
              <div className="grid">
                <div>
                  <p>MA5/10/20/60/120</p>
                  <p className="big small">
                    {result.universal_indicators.technicals.ma?.ma5 ?? '—'} / {result.universal_indicators.technicals.ma?.ma10 ?? '—'} / {result.universal_indicators.technicals.ma?.ma20 ?? '—'} / {result.universal_indicators.technicals.ma?.ma60 ?? '—'} / {result.universal_indicators.technicals.ma?.ma120 ?? '—'}
                  </p>
                </div>
                <div>
                  <p>RSI14：{result.universal_indicators.technicals.rsi14 ?? '—'}</p>
                  <p>20日高/低：{result.universal_indicators.technicals.high_low?.high_20 ?? '—'} / {result.universal_indicators.technicals.high_low?.low_20 ?? '—'}</p>
                  <p>60日高/低：{result.universal_indicators.technicals.high_low?.high_60 ?? '—'} / {result.universal_indicators.technicals.high_low?.low_60 ?? '—'}</p>
                  <p>回撤：{result.universal_indicators.technicals.recent_peak_drawdown_pct ?? '—'}% · 量比20日：{result.universal_indicators.technicals.volume_ratio_to_ma20 ?? '—'}</p>
                </div>
                <div>
                  <p>信号</p>
                  <ul>
                    {safeArray(result.universal_indicators.technicals.signals).map((item) => <li key={item}>{item}</li>)}
                  </ul>
                  {!safeArray(result.universal_indicators.technicals.signals).length && <p className="muted">暂无技术触发。</p>}
                </div>
              </div>
            ) : (
              <p className="muted">{result.universal_indicators.technicals?.reason || '技术指标不可靠可得'}</p>
            )}
          </div>

          <div className="card">
            <h2>研究姿态</h2>
            <p>{result.research_posture.position_basis}</p>
            <p><strong>{result.research_posture.posture}</strong></p>
            <p className="muted">{result.research_posture.rationale}</p>
          </div>

          <div className="card">
            <h2>行业特有指标</h2>
            <ul>
              {safeArray(result.sector_indicators.core_metrics).map((metric) => <li key={metric}>{metric}</li>)}
            </ul>
            <p className="muted">{result.sector_indicators.current_status}</p>
          </div>

          <div className="card wide">
            <h2>行业映射指标</h2>
            {result.sector_indicators.mapped_coverage && (
              <p className="muted">
                覆盖：{fmtCoverage(result.sector_indicators.mapped_coverage)}
              </p>
            )}
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>指标</th>
                    <th>Status</th>
                    <th>最新读数</th>
                    <th>证据期</th>
                    <th>下一证据</th>
                  </tr>
                </thead>
                <tbody>
                  {safeArray(result.sector_indicators.mapped_metrics).map((row) => (
                    <tr key={row.metric}>
                      <td>{row.metric}</td>
                      <td>{row.status}</td>
                      <td>{row.latest_reading}</td>
                      <td>{row.as_of || '—'}</td>
                      <td>{row.next_evidence}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card">
            <h2>官方结构化事实</h2>
            <p className="muted">
              状态：{result.universal_indicators.financials?.status || 'Missing'}
              {result.universal_indicators.financials?.latest_fact_date ? ` · 最新证据 ${result.universal_indicators.financials.latest_fact_date}` : ''}
            </p>
            <ul>
              {safeArray(result.universal_indicators.financials?.evidence_lines).slice(0, 8).map((line) => <li key={line}>{line}</li>)}
            </ul>
            {!safeArray(result.universal_indicators.financials?.evidence_lines).length && <p className="muted">暂无可展示的财报/分红/业绩预告字段。</p>}
          </div>

          <div className="card">
            <h2>官方公告</h2>
            <ul>
              {safeArray(result.events).slice(0, 6).map((item) => (
                <li key={`${item.published_at}-${item.title}`}>
                  <a href={item.url} target="_blank" rel="noreferrer">{item.importance}｜{item.type}｜{item.title}</a>
                  <span className="muted"> · {item.published_at} · PDF {item.pdf_extract_status || 'not_attempted'}{item.pdf_table_count ? ` · 表格${item.pdf_table_count}个` : ''}</span>
                </li>
              ))}
            </ul>
          </div>

          <div className="card">
            <h2>Missing Inputs</h2>
            <ul>
              {safeArray(result.missing_inputs).map((item) => <li key={item.metric}>{item.metric}：{item.impact}</li>)}
            </ul>
          </div>
        </section>
        </AnalysisRenderBoundary>
      )}
    </main>
  );
}

export default function AnalysisPage() {
  return <AnalysisWorkspace />;
}
