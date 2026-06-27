import { FormEvent, useEffect, useState } from 'react';
import Link from 'next/link';
import { apiDelete, apiGet, apiPost, apiPut, uploadFile } from '../lib/api';

type Subscription = {
  id: number;
  symbol: string;
  name: string;
  exchange: string;
  feishu_webhook: string;
  feishu_secret?: string;
  is_active: boolean;
};

type Position = {
  symbol: string;
  shares: number;
  average_cost: number;
  cost_basis: number;
  realized_pnl: number;
  latest_price: number | null;
  latest_price_time: string | null;
  market_value: number | null;
  unrealized_pnl: number | null;
  unrealized_pnl_pct: number | null;
  total_pnl: number | null;
  warnings: string[];
};

type Trade = {
  id: number;
  symbol: string;
  trade_date: string;
  side: 'buy' | 'sell';
  price: number;
  quantity: number;
  fee: number;
  note: string;
  created_at: string;
  updated_at: string;
};

type TradeForm = {
  symbol: string;
  trade_date: string;
  side: 'buy' | 'sell';
  price: string;
  quantity: string;
  fee: string;
  note: string;
};

type TradeImportError = {
  row_number: number;
  reason: string;
  raw: Record<string, unknown>;
};

type TradeImportResult = {
  ok: boolean;
  total_rows: number;
  imported: number;
  failed: number;
  skipped_blank_rows: number;
  columns: string[];
  symbol_counts: Record<string, number>;
  side_counts: Record<string, number>;
  date_range: { min: string; max: string };
  errors: TradeImportError[];
  error_preview_truncated: boolean;
};

type SubscriptionForm = {
  name: string;
  feishu_webhook: string;
  feishu_secret: string;
  is_active: boolean;
};

type ManualAnalysisPushResponse = {
  ok: boolean;
  status: string;
  symbol: string;
  message_preview: string;
};

type PushMessageBrief = {
  title?: string;
  conclusion?: string;
  market_line?: string;
  top_three?: string[];
  action_line?: string;
  data_boundary?: string;
  has_morning_brief?: boolean;
};

type PushLog = {
  id: number;
  subscription_id: number | null;
  symbol: string;
  status: string;
  trigger_summary: string;
  message: string;
  message_brief: PushMessageBrief;
  error: string;
  created_at: string;
};

export function SubscriptionsWorkspace({ embedded = false }: { embedded?: boolean }) {
  const [items, setItems] = useState<Subscription[]>([]);
  const [positions, setPositions] = useState<Record<string, Position>>({});
  const [trades, setTrades] = useState<Trade[]>([]);
  const [pushLogs, setPushLogs] = useState<PushLog[]>([]);
  const [importResult, setImportResult] = useState<TradeImportResult | null>(null);
  const [symbol, setSymbol] = useState('');
  const [name, setName] = useState('');
  const [webhook, setWebhook] = useState('');
  const [secret, setSecret] = useState('');
  const [tradeForm, setTradeForm] = useState<TradeForm>({
    symbol: '',
    trade_date: new Date().toISOString().slice(0, 16),
    side: 'buy',
    price: '',
    quantity: '100',
    fee: '0',
    note: '',
  });
  const [editingTradeId, setEditingTradeId] = useState<number | null>(null);
  const [editingTrade, setEditingTrade] = useState<TradeForm | null>(null);
  const [editingSubscriptionId, setEditingSubscriptionId] = useState<number | null>(null);
  const [editingSubscription, setEditingSubscription] = useState<SubscriptionForm | null>(null);
  const [tradeFilter, setTradeFilter] = useState('all');
  const [activeTab, setActiveTab] = useState<'config' | 'trades'>('config');
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);

  async function load() {
    const [subscriptionData, positionData, tradeData] = await Promise.all([
      apiGet<Subscription[]>('/api/subscriptions'),
      apiGet<Position[]>('/api/positions'),
      apiGet<Trade[]>('/api/trades'),
    ]);
    setItems(subscriptionData);
    setPositions(Object.fromEntries(positionData.map((position) => [position.symbol, position])));
    setTrades(tradeData);
  }

  async function loadPushLogs() {
    const data = await apiGet<PushLog[]>('/api/scheduler/logs?limit=12');
    setPushLogs(data);
  }

  useEffect(() => {
    Promise.all([load(), loadPushLogs()]).catch((error) => setMessage(error.message));
  }, []);

  function activeSubscriptionCount() {
    return items.filter((item) => item.is_active).length;
  }

  function portfolioSummary() {
    const positionList = Object.values(positions);
    const marketValue = positionList.reduce((sum, item) => sum + Number(item.market_value || 0), 0);
    const costBasis = positionList.reduce((sum, item) => sum + Number(item.cost_basis || 0), 0);
    const unrealizedPnl = positionList.reduce((sum, item) => sum + Number(item.unrealized_pnl || 0), 0);
    const realizedPnl = positionList.reduce((sum, item) => sum + Number(item.realized_pnl || 0), 0);
    const totalPnl = positionList.reduce((sum, item) => sum + Number(item.total_pnl || 0), 0);
    return { marketValue, costBasis, unrealizedPnl, realizedPnl, totalPnl };
  }

  function tradeStats(symbolValue?: string) {
    const scoped = symbolValue ? trades.filter((trade) => trade.symbol === symbolValue) : trades;
    const buyAmount = scoped.filter((trade) => trade.side === 'buy').reduce((sum, trade) => sum + trade.price * trade.quantity + Number(trade.fee || 0), 0);
    const sellAmount = scoped.filter((trade) => trade.side === 'sell').reduce((sum, trade) => sum + trade.price * trade.quantity - Number(trade.fee || 0), 0);
    const fees = scoped.reduce((sum, trade) => sum + Number(trade.fee || 0), 0);
    return {
      count: scoped.length,
      buyCount: scoped.filter((trade) => trade.side === 'buy').length,
      sellCount: scoped.filter((trade) => trade.side === 'sell').length,
      buyAmount,
      sellAmount,
      fees,
    };
  }

  function fmtMoney(value: number) {
    return `¥${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  }

  function filteredTrades() {
    if (tradeFilter === 'all') return trades;
    return trades.filter((trade) => trade.symbol === tradeFilter);
  }

  function validateWebhook(value: string) {
    const trimmed = value.trim();
    if (!trimmed) return '';
    try {
      const url = new URL(trimmed);
      if (url.protocol !== 'https:') return '飞书 webhook 必须使用 https。';
      if (!url.hostname.endsWith('feishu.cn') && !url.hostname.endsWith('larksuite.com')) {
        return '飞书 webhook 域名看起来不正确，应为 feishu.cn 或 larksuite.com。';
      }
      if (!url.pathname.includes('/open-apis/bot/')) {
        return '飞书 webhook 路径看起来不正确，应包含 /open-apis/bot/。';
      }
      return '';
    } catch {
      return '飞书 webhook 不是有效 URL。';
    }
  }

  function validateSubscriptionCreate() {
    if (!symbol.trim()) return '请输入股票代码或名称。';
    if (activeSubscriptionCount() >= 3) return '最多只能启用 3 个订阅；请先暂停或删除一个订阅。';
    return validateWebhook(webhook);
  }

  function validateSubscriptionEdit(item: Subscription, form: SubscriptionForm) {
    if (form.is_active && !item.is_active && activeSubscriptionCount() >= 3) {
      return '最多只能启用 3 个订阅；请先暂停或删除一个订阅。';
    }
    return validateWebhook(form.feishu_webhook);
  }

  function validateTradeForm(form: TradeForm) {
    if (!form.symbol.trim()) return '请选择股票。';
    const timestamp = new Date(form.trade_date).getTime();
    if (!form.trade_date || Number.isNaN(timestamp)) return '请输入有效成交时间。';
    const price = Number(form.price);
    if (!Number.isFinite(price) || price <= 0) return '成交价格必须大于 0。';
    const quantity = Number(form.quantity);
    if (!Number.isInteger(quantity) || quantity <= 0) return '成交数量必须是正整数。';
    const fee = Number(form.fee || 0);
    if (!Number.isFinite(fee) || fee < 0) return '交易费用不能为负数。';
    return '';
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    const validationError = validateSubscriptionCreate();
    if (validationError) {
      setMessage(validationError);
      return;
    }
    setLoading(true);
    setMessage('');
    try {
      await apiPost('/api/subscriptions', {
        symbol,
        name,
        feishu_webhook: webhook,
        feishu_secret: secret,
        is_active: true,
      });
      setSymbol('');
      setName('');
      setWebhook('');
      setSecret('');
      await load();
      setMessage('订阅已创建');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  }

  async function remove(id: number) {
    const confirmed = window.confirm('确认删除这个订阅？交易记录不会被删除，但该股票将不再参与定时推送。');
    if (!confirmed) return;
    setLoading(true);
    setMessage('');
    try {
      await apiDelete(`/api/subscriptions/${id}`);
      await load();
      setMessage('订阅已删除');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  }

  function startEditSubscription(item: Subscription) {
    setEditingSubscriptionId(item.id);
    setEditingSubscription({
      name: item.name || '',
      feishu_webhook: item.feishu_webhook || '',
      feishu_secret: '',
      is_active: item.is_active,
    });
  }

  function cancelEditSubscription() {
    setEditingSubscriptionId(null);
    setEditingSubscription(null);
  }

  async function saveSubscription(subscriptionId: number) {
    if (!editingSubscription) return;
    const item = items.find((subscription) => subscription.id === subscriptionId);
    if (!item) return;
    const validationError = validateSubscriptionEdit(item, editingSubscription);
    if (validationError) {
      setMessage(validationError);
      return;
    }
    setLoading(true);
    setMessage('');
    try {
      const payload: Record<string, unknown> = {
        name: editingSubscription.name,
        feishu_webhook: editingSubscription.feishu_webhook,
        is_active: editingSubscription.is_active,
      };
      if (editingSubscription.feishu_secret.trim()) {
        payload.feishu_secret = editingSubscription.feishu_secret;
      }
      await apiPut<Subscription>(`/api/subscriptions/${subscriptionId}`, payload);
      cancelEditSubscription();
      await load();
      setMessage('订阅配置已更新');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  }

  async function toggleSubscription(item: Subscription) {
    if (!item.is_active && activeSubscriptionCount() >= 3) {
      setMessage('最多只能启用 3 个订阅；请先暂停或删除一个订阅。');
      return;
    }
    setLoading(true);
    setMessage('');
    try {
      await apiPut<Subscription>(`/api/subscriptions/${item.id}`, { is_active: !item.is_active });
      await load();
      setMessage(item.is_active ? '订阅已暂停' : '订阅已启用');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  }

  async function sendAnalysisPush(id: number) {
    setLoading(true);
    setMessage('');
    try {
      const result = await apiPost<ManualAnalysisPushResponse>(`/api/subscriptions/${id}/send-analysis-push`, {});
      await loadPushLogs();
      setMessage(`分析推送已发送：${result.symbol}。本次不会改变正式定时任务或触发规则。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  }

  async function upload(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setImportResult(null);
    try {
      const result = await uploadFile<TradeImportResult>('/api/trades/upload-excel', file);
      await load();
      setImportResult(result);
      setMessage(`已导入 ${result.imported} 条交易记录；失败 ${result.failed} 条；跳过空行 ${result.skipped_blank_rows} 条。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }

  function tradeToForm(trade: Trade): TradeForm {
    return {
      symbol: trade.symbol,
      trade_date: trade.trade_date.slice(0, 16),
      side: trade.side,
      price: String(trade.price),
      quantity: String(trade.quantity),
      fee: String(trade.fee || 0),
      note: trade.note || '',
    };
  }

  function buildTradePayload(form: TradeForm) {
    return {
      symbol: form.symbol.trim(),
      trade_date: new Date(form.trade_date).toISOString(),
      side: form.side,
      price: Number(form.price),
      quantity: Number(form.quantity),
      fee: Number(form.fee || 0),
      note: form.note,
    };
  }

  async function createTrade(event: FormEvent) {
    event.preventDefault();
    const validationError = validateTradeForm(tradeForm);
    if (validationError) {
      setMessage(validationError);
      return;
    }
    setLoading(true);
    setMessage('');
    try {
      await apiPost<Trade>('/api/trades', buildTradePayload(tradeForm));
      setTradeForm({
        ...tradeForm,
        price: '',
        quantity: '100',
        fee: '0',
        note: '',
      });
      await load();
      setMessage('交易记录已新增，持仓已刷新');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  }

  function startTradeForSymbol(symbolValue: string) {
    setTradeForm({
      ...tradeForm,
      symbol: symbolValue,
      trade_date: new Date().toISOString().slice(0, 16),
    });
    setMessage(`已切换新增交易表单到 ${symbolValue}`);
  }

  function startEditTrade(trade: Trade) {
    setEditingTradeId(trade.id);
    setEditingTrade(tradeToForm(trade));
  }

  function cancelEditTrade() {
    setEditingTradeId(null);
    setEditingTrade(null);
  }

  async function saveTrade(tradeId: number) {
    if (!editingTrade) return;
    const validationError = validateTradeForm(editingTrade);
    if (validationError) {
      setMessage(validationError);
      return;
    }
    setLoading(true);
    setMessage('');
    try {
      await apiPut<Trade>(`/api/trades/${tradeId}`, buildTradePayload(editingTrade));
      cancelEditTrade();
      await load();
      setMessage('交易记录已更新，持仓已刷新');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  }

  async function removeTrade(tradeId: number) {
    const confirmed = window.confirm('确认删除这条交易记录？删除后持仓会重新计算。');
    if (!confirmed) return;
    setLoading(true);
    setMessage('');
    try {
      await apiDelete(`/api/trades/${tradeId}`);
      await load();
      setMessage('交易记录已删除，持仓已刷新');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  }

  function formatLogTime(value: string) {
    try {
      return new Date(value).toLocaleString('zh-CN', { hour12: false });
    } catch {
      return value;
    }
  }

  function latestLogsForSymbol(symbolValue: string) {
    return pushLogs.filter((log) => log.symbol === symbolValue).slice(0, 3);
  }

  function renderPushLogBrief(log: PushLog) {
    const brief = log.message_brief || {};
    const topThree = brief.top_three || [];
    return (
      <article className="push-log-card" key={log.id}>
        <div className="push-log-head">
          <div>
            <strong>{log.symbol || '未知股票'}</strong>
            <span>{log.status}</span>
          </div>
          <time>{formatLogTime(log.created_at)}</time>
        </div>
        {brief.has_morning_brief ? (
          <div className="push-brief">
            {brief.conclusion && <p className="brief-conclusion">{brief.conclusion.replace(/^结论：/, '')}</p>}
            {brief.market_line && <p className="muted">{brief.market_line}</p>}
            {topThree.length > 0 && (
              <>
                <p className="section-label">今日只看 3 件事</p>
                <ol className="brief-list">
                  {topThree.map((item) => <li key={item}>{item}</li>)}
                </ol>
              </>
            )}
            {brief.action_line && <p className="discipline-line">{brief.action_line}</p>}
            {brief.data_boundary && <p className="muted">{brief.data_boundary}</p>}
          </div>
        ) : (
          <p className="muted">{log.trigger_summary || log.error || '旧日志暂无结构化晨会摘要。'}</p>
        )}
        {log.message && (
          <details className="run-result nested">
            <summary>查看完整推送文本</summary>
            <pre>{log.message}</pre>
          </details>
        )}
        {log.error && <p className="warning">{log.error}</p>}
      </article>
    );
  }

  return (
    <main className={embedded ? 'workspace-panel' : 'container'}>
      {!embedded && <Link href="/">← 返回首页</Link>}
      <h1>订阅</h1>
      <p className="muted">最多启用 3 只 A 股。当前已启用 {activeSubscriptionCount()} / 3。飞书 webhook 只保存在你的自托管数据库里。</p>
      <section className="flow-hint">
        <div>
          <strong>1. 订阅配置</strong>
          <span>管理股票、飞书和启用状态。</span>
        </div>
        <div>
          <strong>2. 持仓交易</strong>
          <span>上传/维护交易记录，生成持仓基线。</span>
        </div>
      </section>

      <nav className="tabs">
        <button type="button" className={activeTab === 'config' ? 'active' : ''} onClick={() => setActiveTab('config')}>订阅配置</button>
        <button type="button" className={activeTab === 'trades' ? 'active' : ''} onClick={() => setActiveTab('trades')}>持仓交易</button>
      </nav>
      <p className="tab-note">
        {activeTab === 'config' && '当前页处理订阅和飞书配置；可手动发送一份当前分析报告，不改变正式定时任务。'}
        {activeTab === 'trades' && '当前页维护交易流水和持仓基线；删除交易前会二次确认，修改后会重新计算持仓。'}
      </p>

      {message && <p className="notice">{message}</p>}

      {activeTab === 'config' && (
      <form className="card form" onSubmit={create}>
        <label>
          股票代码或名称
          <input value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="请输入股票代码或名称" required />
        </label>
        <label>
          显示名称
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="可选显示名称" />
        </label>
        <label>
          飞书 webhook
          <input value={webhook} onChange={(e) => setWebhook(e.target.value)} placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/..." />
        </label>
        <label>
          飞书签名密钥（可选）
          <input value={secret} onChange={(e) => setSecret(e.target.value)} placeholder="可选" />
        </label>
        <button disabled={loading}>{loading ? '保存中...' : '新增订阅'}</button>
        {activeSubscriptionCount() >= 3 && <p className="warning">已达到 3 个启用订阅上限；新增前请先暂停或删除一个订阅。</p>}
      </form>
      )}

      {activeTab === 'config' && (
      <section className="card">
        <div className="section-header">
          <div>
            <h2>最近分析推送</h2>
            <p className="muted">网页端复用飞书推送的晨会摘要结构；完整原文默认折叠。</p>
          </div>
          <button type="button" onClick={() => loadPushLogs().catch((error) => setMessage(error.message))} disabled={loading}>刷新历史</button>
        </div>
        <div className="push-log-grid">
          {pushLogs.slice(0, 6).map(renderPushLogBrief)}
          {pushLogs.length === 0 && <p className="muted">暂无推送历史。点击订阅卡片里的“发送分析推送”后会在这里展示预览。</p>}
        </div>
      </section>
      )}

      {activeTab === 'trades' && (
      <>
      <section className="card">
        <h2>上传交易记录 Excel</h2>
        <input type="file" accept=".xlsx" onChange={upload} />
        <p className="muted">支持列：symbol / trade_date / side / price / quantity / fee / note，也兼容中文列名。</p>
        {importResult && (
          <div className="import-summary">
            <p>
              总行数：{importResult.total_rows} · 导入：{importResult.imported} · 失败：{importResult.failed} · 跳过空行：{importResult.skipped_blank_rows}
            </p>
            <p className="muted">
              日期范围：{importResult.date_range.min || '—'} → {importResult.date_range.max || '—'}
            </p>
            <p>股票分布：{Object.entries(importResult.symbol_counts).map(([key, value]) => `${key} ${value}条`).join('；') || '无'}</p>
            <p>方向分布：买入 {importResult.side_counts.buy || 0} 条；卖出 {importResult.side_counts.sell || 0} 条</p>
            {importResult.errors.length > 0 && (
              <details className="run-result" open>
                <summary>失败行预览（{importResult.failed}）</summary>
                <div className="table-wrap mini">
                  <table>
                    <thead>
                      <tr>
                        <th>Excel行</th>
                        <th>原因</th>
                        <th>原始内容</th>
                      </tr>
                    </thead>
                    <tbody>
                      {importResult.errors.map((item) => (
                        <tr key={`${item.row_number}-${item.reason}`}>
                          <td>{item.row_number}</td>
                          <td>{item.reason}</td>
                          <td>{JSON.stringify(item.raw)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {importResult.error_preview_truncated && <p className="muted">错误较多，仅展示前 20 条。</p>}
              </details>
            )}
          </div>
        )}
      </section>

      <section className="card">
        <h2>新增交易记录</h2>
        <form className="form trade-form" onSubmit={createTrade}>
          <label>
            股票
            <select value={tradeForm.symbol} onChange={(event) => setTradeForm({ ...tradeForm, symbol: event.target.value })} required>
              <option value="">选择订阅股票</option>
              {items.map((item) => <option key={item.symbol} value={item.symbol}>{item.name || item.symbol} · {item.symbol}</option>)}
            </select>
          </label>
          <label>
            成交时间
            <input type="datetime-local" value={tradeForm.trade_date} onChange={(event) => setTradeForm({ ...tradeForm, trade_date: event.target.value })} required />
          </label>
          <label>
            方向
            <select value={tradeForm.side} onChange={(event) => setTradeForm({ ...tradeForm, side: event.target.value as 'buy' | 'sell' })}>
              <option value="buy">买入</option>
              <option value="sell">卖出</option>
            </select>
          </label>
          <label>
            价格
            <input type="number" min="0" step="0.001" value={tradeForm.price} onChange={(event) => setTradeForm({ ...tradeForm, price: event.target.value })} required />
          </label>
          <label>
            数量
            <input type="number" min="1" step="1" value={tradeForm.quantity} onChange={(event) => setTradeForm({ ...tradeForm, quantity: event.target.value })} required />
          </label>
          <label>
            费用
            <input type="number" min="0" step="0.01" value={tradeForm.fee} onChange={(event) => setTradeForm({ ...tradeForm, fee: event.target.value })} />
          </label>
          <label className="wide-field">
            备注
            <input value={tradeForm.note} onChange={(event) => setTradeForm({ ...tradeForm, note: event.target.value })} placeholder="可选" />
          </label>
          <button disabled={loading}>{loading ? '保存中...' : '新增交易'}</button>
        </form>
      </section>
      </>
      )}

      {activeTab === 'trades' && (
      <section className="card">
        <h2>组合与交易总览</h2>
        <div className="summary-grid">
          <div>
            <p className="muted">订阅</p>
            <p className="big small">{activeSubscriptionCount()} / 3 启用</p>
          </div>
          <div>
            <p className="muted">持仓市值</p>
            <p className="big small">{fmtMoney(portfolioSummary().marketValue)}</p>
          </div>
          <div>
            <p className="muted">成本金额</p>
            <p className="big small">{fmtMoney(portfolioSummary().costBasis)}</p>
          </div>
          <div>
            <p className="muted">浮盈亏</p>
            <p className="big small">{fmtMoney(portfolioSummary().unrealizedPnl)}</p>
          </div>
          <div>
            <p className="muted">已实现盈亏</p>
            <p className="big small">{fmtMoney(portfolioSummary().realizedPnl)}</p>
          </div>
          <div>
            <p className="muted">合计盈亏</p>
            <p className="big small">{fmtMoney(portfolioSummary().totalPnl)}</p>
          </div>
        </div>
        <div className="table-wrap mini">
          <table>
            <thead>
              <tr>
                <th>股票</th>
                <th>交易数</th>
                <th>买入/卖出</th>
                <th>买入金额</th>
                <th>卖出金额</th>
                <th>费用</th>
                <th>快捷操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => {
                const stats = tradeStats(item.symbol);
                return (
                  <tr key={`stats-${item.symbol}`}>
                    <td>{item.name || item.symbol} · {item.symbol}</td>
                    <td>{stats.count}</td>
                    <td>{stats.buyCount} / {stats.sellCount}</td>
                    <td>{fmtMoney(stats.buyAmount)}</td>
                    <td>{fmtMoney(stats.sellAmount)}</td>
                    <td>{fmtMoney(stats.fees)}</td>
                    <td>
                      <div className="row-actions">
                        <button type="button" onClick={() => startTradeForSymbol(item.symbol)}>新增交易</button>
                        <button type="button" onClick={() => setTradeFilter(item.symbol)}>筛选</button>
                      </div>
                    </td>
                  </tr>
                );
              })}
              {items.length === 0 && (
                <tr>
                  <td colSpan={7} className="muted">暂无订阅。先新增订阅，再维护交易记录。</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
      )}

      {activeTab === 'trades' && (
      <section className="card">
        <h2>最近交易流水</h2>
        <div className="actions">
          <label>
            筛选股票
            <select value={tradeFilter} onChange={(event) => setTradeFilter(event.target.value)}>
              <option value="all">全部股票</option>
              {items.map((item) => <option key={`filter-${item.symbol}`} value={item.symbol}>{item.name || item.symbol} · {item.symbol}</option>)}
            </select>
          </label>
        </div>
        <p className="muted">
          当前筛选：{tradeFilter === 'all' ? '全部' : tradeFilter}；
          交易 {tradeStats(tradeFilter === 'all' ? undefined : tradeFilter).count} 条；
          买入金额 {fmtMoney(tradeStats(tradeFilter === 'all' ? undefined : tradeFilter).buyAmount)}；
          卖出金额 {fmtMoney(tradeStats(tradeFilter === 'all' ? undefined : tradeFilter).sellAmount)}；
          费用 {fmtMoney(tradeStats(tradeFilter === 'all' ? undefined : tradeFilter).fees)}
        </p>
        <div className="table-wrap mini">
          <table>
            <thead>
              <tr>
                <th>股票</th>
                <th>时间</th>
                <th>方向</th>
                <th>价格</th>
                <th>数量</th>
                <th>费用</th>
                <th>备注</th>
              </tr>
            </thead>
            <tbody>
              {filteredTrades().slice(0, 50).map((trade) => (
                <tr key={`recent-${trade.id}`}>
                  <td>{trade.symbol}</td>
                  <td>{trade.trade_date.replace('T', ' ').slice(0, 16)}</td>
                  <td>{trade.side === 'buy' ? '买入' : '卖出'}</td>
                  <td>{trade.price}</td>
                  <td>{trade.quantity}</td>
                  <td>{trade.fee}</td>
                  <td>{trade.note || '—'}</td>
                </tr>
              ))}
              {filteredTrades().length === 0 && (
                <tr>
                  <td colSpan={7} className="muted">暂无交易流水。</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {filteredTrades().length > 50 && <p className="muted">已展示最近 50 条交易流水。</p>}
      </section>
      )}

      <section className="grid">
        {items.map((item) => {
          const position = positions[item.symbol];
          return (
            <div className="card" key={item.id}>
              <h2>{item.name || item.symbol}</h2>
              <p>{item.symbol} · {item.exchange} · {item.is_active ? 'ACTIVE' : 'PAUSED'}</p>
              <p className="muted">{item.feishu_webhook ? '已配置飞书 webhook' : '未配置飞书 webhook'}</p>

              {activeTab === 'config' && (
              <>
              <details className="run-result">
                <summary>编辑订阅配置</summary>
                {editingSubscriptionId === item.id && editingSubscription ? (
                  <div className="form subscription-edit-form">
                    <label>
                      显示名称
                      <input value={editingSubscription.name} onChange={(event) => setEditingSubscription({ ...editingSubscription, name: event.target.value })} />
                    </label>
                    <label>
                      飞书 webhook
                      <input value={editingSubscription.feishu_webhook} onChange={(event) => setEditingSubscription({ ...editingSubscription, feishu_webhook: event.target.value })} placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/..." />
                    </label>
                    <label>
                      新签名密钥
                      <input value={editingSubscription.feishu_secret} onChange={(event) => setEditingSubscription({ ...editingSubscription, feishu_secret: event.target.value })} placeholder="留空表示不修改" />
                    </label>
                    <label className="checkbox-label">
                      <input type="checkbox" checked={editingSubscription.is_active} onChange={(event) => setEditingSubscription({ ...editingSubscription, is_active: event.target.checked })} />
                      启用定时推送
                    </label>
                    <div className="actions">
                      <button onClick={() => saveSubscription(item.id)} disabled={loading}>保存配置</button>
                      <button type="button" onClick={cancelEditSubscription}>取消</button>
                    </div>
                    <p className="muted">签名密钥不会回显；如需修改请输入新密钥，留空则保持原值。</p>
                  </div>
                ) : (
                  <div className="actions">
                    <button type="button" onClick={() => startEditSubscription(item)}>编辑配置</button>
                    <button type="button" onClick={() => toggleSubscription(item)} disabled={loading}>{item.is_active ? '暂停订阅' : '启用订阅'}</button>
                  </div>
                )}
              </details>
              <div className="actions">
                <button onClick={() => sendAnalysisPush(item.id)} disabled={loading}>{loading ? '生成中...' : '发送分析推送'}</button>
                <button className="danger" onClick={() => remove(item.id)}>删除</button>
              </div>
              {latestLogsForSymbol(item.symbol).length > 0 && (
                <details className="run-result" open>
                  <summary>该股票最近推送</summary>
                  <div className="push-log-stack">
                    {latestLogsForSymbol(item.symbol).map(renderPushLogBrief)}
                  </div>
                </details>
              )}
              </>
              )}

              {activeTab === 'trades' && (
              <>
              {position ? (
                <div className="position">
                  <p><strong>{position.shares}</strong> 股 · 成本 ¥{position.average_cost}</p>
                  <p>最新价：{position.latest_price ? `¥${position.latest_price}` : '暂无'} · 市值：{position.market_value ? `¥${position.market_value}` : '暂无'}</p>
                  <p>浮盈亏：{position.unrealized_pnl ?? '暂无'} ({position.unrealized_pnl_pct ?? '暂无'}%)</p>
                  <p>已实现盈亏：{position.realized_pnl} · 合计盈亏：{position.total_pnl ?? '暂无'}</p>
                  {position.warnings.length > 0 && <p className="warning">{position.warnings.join('；')}</p>}
                </div>
              ) : (
                <p className="muted">暂无交易记录/持仓基线</p>
              )}

              <details className="run-result">
                <summary>交易记录（{trades.filter((trade) => trade.symbol === item.symbol).length}）</summary>
                <div className="table-wrap mini">
                  <table>
                    <thead>
                      <tr>
                        <th>时间</th>
                        <th>方向</th>
                        <th>价格</th>
                        <th>数量</th>
                        <th>费用</th>
                        <th>备注</th>
                        <th>操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {trades.filter((trade) => trade.symbol === item.symbol).slice(0, 20).map((trade) => {
                        const isEditing = editingTradeId === trade.id && editingTrade;
                        return (
                          <tr key={trade.id}>
                            <td>
                              {isEditing ? (
                                <input type="datetime-local" value={editingTrade.trade_date} onChange={(event) => setEditingTrade({ ...editingTrade, trade_date: event.target.value })} />
                              ) : trade.trade_date.replace('T', ' ').slice(0, 16)}
                            </td>
                            <td>
                              {isEditing ? (
                                <select value={editingTrade.side} onChange={(event) => setEditingTrade({ ...editingTrade, side: event.target.value as 'buy' | 'sell' })}>
                                  <option value="buy">买入</option>
                                  <option value="sell">卖出</option>
                                </select>
                              ) : trade.side === 'buy' ? '买入' : '卖出'}
                            </td>
                            <td>{isEditing ? <input type="number" min="0" step="0.001" value={editingTrade.price} onChange={(event) => setEditingTrade({ ...editingTrade, price: event.target.value })} /> : trade.price}</td>
                            <td>{isEditing ? <input type="number" min="1" step="1" value={editingTrade.quantity} onChange={(event) => setEditingTrade({ ...editingTrade, quantity: event.target.value })} /> : trade.quantity}</td>
                            <td>{isEditing ? <input type="number" min="0" step="0.01" value={editingTrade.fee} onChange={(event) => setEditingTrade({ ...editingTrade, fee: event.target.value })} /> : trade.fee}</td>
                            <td>{isEditing ? <input value={editingTrade.note} onChange={(event) => setEditingTrade({ ...editingTrade, note: event.target.value })} /> : trade.note || '—'}</td>
                            <td>
                              {isEditing ? (
                                <div className="row-actions">
                                  <button onClick={() => saveTrade(trade.id)} disabled={loading}>保存</button>
                                  <button type="button" onClick={cancelEditTrade}>取消</button>
                                </div>
                              ) : (
                                <div className="row-actions">
                                  <button type="button" onClick={() => startEditTrade(trade)}>编辑</button>
                                  <button type="button" className="danger" onClick={() => removeTrade(trade.id)}>删除</button>
                                </div>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                {trades.filter((trade) => trade.symbol === item.symbol).length > 20 && <p className="muted">已展示最近 20 条交易记录。</p>}
              </details>
              </>
              )}
            </div>
          );
        })}
      </section>
    </main>
  );
}

export default function SubscriptionsPage() {
  return <SubscriptionsWorkspace />;
}
