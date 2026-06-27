import { FormEvent, useState } from 'react';
import Link from 'next/link';
import { apiPost } from '../lib/api';

type QualityFact = {
  id: number;
  fact_type: string;
  field_name: string;
  label: string;
  value: string;
  unit: string;
  confidence: string;
  extractor: string;
  source_text: string;
};

type QualityAnnouncement = {
  id: number;
  title: string;
  announcement_type: string;
  importance: string;
  published_at: string;
  source: string;
  source_url: string;
  pdf_extract_status: string;
  pdf_extract_error: string;
  pdf_page_count: number;
  pdf_text_chars: number;
  pdf_table_count: number;
  fact_count: number;
  fact_type_counts: Record<string, number>;
  facts: QualityFact[];
  table_excerpt: string;
};

type SectorMetric = {
  metric: string;
  status: string;
  latest_reading: string;
  as_of: string;
  source: string;
  source_url: string;
  relevance: string;
  next_evidence: string;
};

type QualityResponse = {
  symbol: string;
  company_name: string;
  industry: string;
  synced: boolean;
  sync_source: string;
  sync_warning: string;
  announcement_count: number;
  fact_count: number;
  fact_type_counts: Record<string, number>;
  sector_mapping_coverage: { available: number; partial: number; missing: number; total: number };
  sector_missing_inputs: Array<{ metric: string; preferred_source: string; impact: string }>;
  sector_mapped_metrics: SectorMetric[];
  warnings: string[];
  announcements: QualityAnnouncement[];
};

export default function QualityPage() {
  const [symbol, setSymbol] = useState('000001.SZ');
  const [days, setDays] = useState(180);
  const [sync, setSync] = useState(true);
  const [result, setResult] = useState<QualityResponse | null>(null);
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);

  async function inspect(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setMessage('');
    setResult(null);
    try {
      const data = await apiPost<QualityResponse>('/api/announcements/quality', { symbol, days, sync });
      setResult(data);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="container">
      <Link href="/">← 返回首页</Link>
      <h1>抽取质量</h1>
      <p className="muted">检查官方公告 PDF、表格、结构化事实和行业映射覆盖率。这个页面用于调试抽取规则。</p>

      <form className="card form inline" onSubmit={inspect}>
        <label>
          股票
          <input value={symbol} onChange={(event) => setSymbol(event.target.value)} placeholder="000001.SZ / 平安银行" />
        </label>
        <label>
          回看天数
          <input type="number" value={days} min={1} max={365} onChange={(event) => setDays(Number(event.target.value))} />
        </label>
        <label>
          同步公告
          <select value={sync ? 'yes' : 'no'} onChange={(event) => setSync(event.target.value === 'yes')}>
            <option value="yes">是</option>
            <option value="no">否，只读本地库</option>
          </select>
        </label>
        <button disabled={loading}>{loading ? '检查中...' : '开始检查'}</button>
      </form>

      {message && <p className="notice">{message}</p>}

      {result && (
        <section className="grid two">
          <div className="card">
            <p className="eyebrow">{result.symbol} · {result.industry}</p>
            <h2>{result.company_name}</h2>
            <p>公告：{result.announcement_count} 条 · 结构化事实：{result.fact_count} 条</p>
            <p className="muted">同步：{result.synced ? '已执行' : '未执行'} · {result.sync_source || '本地库'}</p>
            {result.sync_warning && <p className="warning">{result.sync_warning}</p>}
          </div>

          <div className="card">
            <h2>事实类型</h2>
            <ul>
              {Object.entries(result.fact_type_counts).map(([key, value]) => <li key={key}>{key}：{value}</li>)}
            </ul>
          </div>

          <div className="card wide">
            <h2>行业映射覆盖</h2>
            <p>
              Available {result.sector_mapping_coverage.available} · Partial {result.sector_mapping_coverage.partial} ·
              Missing {result.sector_mapping_coverage.missing} · Total {result.sector_mapping_coverage.total}
            </p>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>指标</th>
                    <th>Status</th>
                    <th>读数</th>
                    <th>证据</th>
                    <th>下一证据</th>
                  </tr>
                </thead>
                <tbody>
                  {result.sector_mapped_metrics.map((row) => (
                    <tr key={row.metric}>
                      <td>{row.metric}</td>
                      <td>{row.status}</td>
                      <td>{row.latest_reading}</td>
                      <td>{row.source || '—'}<br /><span className="muted">{row.as_of || '—'}</span></td>
                      <td>{row.next_evidence}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {result.warnings.length > 0 && (
            <div className="card wide">
              <h2>质量警告</h2>
              <ul>
                {result.warnings.map((item) => <li key={item}>{item}</li>)}
              </ul>
            </div>
          )}

          <div className="card wide">
            <h2>公告与抽取字段</h2>
            {result.announcements.map((item) => (
              <details key={item.id} className="run-result">
                <summary>
                  {item.published_at} · {item.announcement_type} · {item.title} · Facts {item.fact_count} · PDF {item.pdf_extract_status} · 表格 {item.pdf_table_count}
                </summary>
                <p>
                  <a href={item.source_url} target="_blank" rel="noreferrer">打开官方公告</a>
                </p>
                {item.pdf_extract_error && <p className="warning">{item.pdf_extract_error}</p>}
                {item.facts.length ? (
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>字段</th>
                          <th>类型</th>
                          <th>值</th>
                          <th>置信度</th>
                          <th>来源片段</th>
                        </tr>
                      </thead>
                      <tbody>
                        {item.facts.map((fact) => (
                          <tr key={fact.id}>
                            <td>{fact.label}<br /><span className="muted">{fact.field_name}</span></td>
                            <td>{fact.fact_type}</td>
                            <td>{fact.value} {fact.unit}</td>
                            <td>{fact.confidence}<br /><span className="muted">{fact.extractor}</span></td>
                            <td>{fact.source_text || '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="muted">这份公告未抽出结构化事实。</p>
                )}
                {item.table_excerpt && (
                  <>
                    <h3>表格片段</h3>
                    <pre>{item.table_excerpt}</pre>
                  </>
                )}
              </details>
            ))}
          </div>
        </section>
      )}
    </main>
  );
}
