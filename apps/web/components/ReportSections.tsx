export type ReportSection = {
  key: string;
  title: string;
  summary: string;
  items?: Array<{ label: string; value: unknown; level?: string; source?: string }>;
  table?: Array<Record<string, unknown>>;
  events?: Array<Record<string, unknown>>;
};

export function renderValue(value: unknown) {
  if (value === null || value === undefined || value === '') return '不可靠可得';
  if (Array.isArray(value)) return value.map((item) => String(item)).join('、') || '不可靠可得';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

const COLUMN_LABELS: Record<string, string> = {
  metric: '指标',
  status: '状态',
  latest_reading: '最新读数/状态',
  as_of: '截止时间/报告期',
  source: '来源',
  relevance: '为什么重要',
  next_evidence: '下一证据',
};

function renderSectionTable(section: ReportSection) {
  const rows = section.table || [];
  if (!rows.length) return null;
  const preferredColumns = ['metric', 'status', 'latest_reading', 'as_of', 'source', 'relevance', 'next_evidence'];
  const columns = preferredColumns.filter((column) => rows.some((row) => row[column] !== undefined));
  const hiddenColumns = new Set(['raw', 'source_url', 'company', 'symbol']);
  const fallbackColumns = Object.keys(rows[0] || {}).filter((column) => !columns.includes(column) && !hiddenColumns.has(column));
  const finalColumns = [...columns, ...fallbackColumns].slice(0, 8);
  return (
    <div className="table-wrap mini">
      <table>
        <thead>
          <tr>
            {finalColumns.map((column) => <th key={column}>{COLUMN_LABELS[column] || column}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 12).map((row, rowIndex) => (
            <tr key={`${section.key}-table-${rowIndex}`}>
              {finalColumns.map((column) => {
                const value = row[column];
                const url = row.source_url;
                return (
                  <td key={`${section.key}-${rowIndex}-${column}`}>
                    {column === 'source' && typeof url === 'string' && url ? (
                      <a href={url} target="_blank" rel="noreferrer">{renderValue(value)}</a>
                    ) : renderValue(value)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > 12 && <p className="muted">已展示前 12 行，共 {rows.length} 行。</p>}
    </div>
  );
}

function renderSectionEvents(section: ReportSection) {
  const events = section.events || [];
  if (!events.length) return null;
  return (
    <div className="event-list">
      {events.slice(0, 8).map((event, index) => {
        const title = renderValue(event.title || event.announcement_title || `事件 ${index + 1}`);
        const url = typeof event.url === 'string' ? event.url : typeof event.source_url === 'string' ? event.source_url : '';
        return (
          <p key={`${section.key}-event-${index}`}>
            {url ? <a href={url} target="_blank" rel="noreferrer">{title}</a> : title}
            <span className="muted"> · {renderValue(event.importance || event.type || event.announcement_type)} · {renderValue(event.published_at)}</span>
          </p>
        );
      })}
    </div>
  );
}

export function ReportSections({ sections }: { sections: ReportSection[] }) {
  if (!sections.length) {
    return <p className="muted">暂无结构化报告。</p>;
  }
  return (
    <>
      {sections.map((section) => (
        <details key={section.key} className="run-result" open={section.key === 'summary' || section.key === 'market_snapshot'}>
          <summary>{section.title}</summary>
          <p>{section.summary}</p>
          {!!(section.items || []).length && (
            <ul className="section-items">
              {(section.items || []).map((item, index) => (
                <li key={`${section.key}-${item.label}-${index}`} className={item.level ? `level-${item.level}` : ''}>
                  <span>{item.label}：</span>{renderValue(item.value)}
                  {item.source && <span className="muted"> · {item.source}</span>}
                </li>
              ))}
            </ul>
          )}
          {renderSectionTable(section)}
          {renderSectionEvents(section)}
        </details>
      ))}
    </>
  );
}
