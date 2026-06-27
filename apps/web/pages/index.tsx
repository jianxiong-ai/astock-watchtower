import Link from 'next/link';
import { useEffect, useState } from 'react';
import { AnalysisWorkspace } from './analysis';
import { SubscriptionsWorkspace } from './subscriptions';

type MainPanel = 'subscriptions' | 'analysis';

export default function Home() {
  const [activePanel, setActivePanel] = useState<MainPanel>('subscriptions');
  const [showAdvanced, setShowAdvanced] = useState(false);

  useEffect(() => {
    setShowAdvanced(window.localStorage.getItem('astock-show-advanced') === 'true');
  }, []);

  function toggleAdvanced() {
    const nextValue = !showAdvanced;
    setShowAdvanced(nextValue);
    window.localStorage.setItem('astock-show-advanced', String(nextValue));
  }

  return (
    <main className="app-shell">
      <section className="terminal-bar">
        <div className="terminal-brand">
          <p>ASTOCK-WATCHTOWER</p>
        </div>
        <p className="terminal-summary">自托管 A 股研究工作台 · 订阅最多 3 只 · 手动分析任意 A 股 · 飞书触发提醒</p>
        <div className="terminal-actions">
          <button type="button" className={activePanel === 'subscriptions' ? 'active' : ''} onClick={() => setActivePanel('subscriptions')}>
            订阅
          </button>
          <button type="button" className={activePanel === 'analysis' ? 'active' : ''} onClick={() => setActivePanel('analysis')}>
            分析
          </button>
          <button type="button" className="ghost" onClick={toggleAdvanced}>
            {showAdvanced ? '隐藏高级' : '显示高级'}
          </button>
        </div>
      </section>

      {showAdvanced && (
        <section className="advanced-strip">
          <Link href="/quality">
            <a>数据质量</a>
          </Link>
          <Link href="/health">
            <a>健康检查</a>
          </Link>
          <span>高级入口默认隐藏；开关状态仅保存在当前浏览器。</span>
        </section>
      )}

      <section className="workspace-card">
        {activePanel === 'subscriptions' ? <SubscriptionsWorkspace embedded /> : <AnalysisWorkspace embedded />}
      </section>
    </main>
  );
}
