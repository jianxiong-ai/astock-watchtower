import { ChangeEvent, useEffect, useState } from 'react';
import Link from 'next/link';
import { apiDelete, apiGet, apiUrl, uploadFile } from '../lib/api';

type ProviderFileStatus = {
  key: string;
  title: string;
  description: string;
  filename: string;
  example_filename: string;
  required_columns: string[];
  recommended_columns: string[];
  path: string;
  exists: boolean;
  size_bytes: number;
  updated_at: string;
  columns: string[];
  total_rows: number;
  preview_rows: Record<string, string>[];
  errors: string[];
  error_truncated: boolean;
  example_available: boolean;
};

export default function ProvidersPage() {
  const [files, setFiles] = useState<ProviderFileStatus[]>([]);
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);
  const [busyKey, setBusyKey] = useState('');

  async function loadFiles() {
    setLoading(true);
    setMessage('');
    try {
      setFiles(await apiGet<ProviderFileStatus[]>('/api/providers/industry-files'));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadFiles();
  }, []);

  async function handleUpload(key: string, event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.csv')) {
      setMessage('只支持上传 .csv 文件。');
      return;
    }
    setBusyKey(key);
    setMessage('');
    try {
      const updated = await uploadFile<ProviderFileStatus>(`/api/providers/industry-files/${key}/upload`, file);
      setFiles((items) => items.map((item) => (item.key === key ? updated : item)));
      setMessage(`已更新 ${updated.filename}，当前 ${updated.total_rows} 行。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusyKey('');
    }
  }

  async function handleDelete(file: ProviderFileStatus) {
    if (!file.exists) return;
    if (!window.confirm(`确认删除当前 ${file.filename}？示例文件不会删除。`)) return;
    setBusyKey(file.key);
    setMessage('');
    try {
      const updated = await apiDeleteAndReturn(file.key);
      setFiles((items) => items.map((item) => (item.key === file.key ? updated : item)));
      setMessage(`已删除 ${file.filename}。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusyKey('');
    }
  }

  async function apiDeleteAndReturn(key: string): Promise<ProviderFileStatus> {
    await apiDelete(`/api/providers/industry-files/${key}`);
    return apiGet<ProviderFileStatus>(`/api/providers/industry-files/${key}`);
  }

  return (
    <main className="container">
      <Link href="/">← 返回首页</Link>
      <h1>行业数据源</h1>
      <p className="muted">
        管理行业 provider v1 的本地 CSV 数据。这里上传的是你自托管实例自己的数据源，不会提交到开源仓库。
      </p>

      <section className="card">
        <h2>使用方式</h2>
        <p className="muted">
          下载示例 CSV，按同一列名维护数据后上传替换。分析报告会优先读取这些文件，补齐内置行情和公告抽取暂时覆盖不到的行业证据。
        </p>
        <button type="button" onClick={loadFiles} disabled={loading}>
          {loading ? '刷新中...' : '刷新状态'}
        </button>
      </section>

      {message && <p className="notice">{message}</p>}

      <section className="grid two">
        {files.map((file) => (
          <article className="card provider-card" key={file.key}>
            <p className="eyebrow">{file.filename}</p>
            <h2>{file.title}</h2>
            <p className="muted">{file.description}</p>

            <div className="provider-status">
              <span className={file.exists && !file.errors.length ? 'badge ok' : file.exists ? 'badge warning' : 'badge muted-badge'}>
                {file.exists ? (file.errors.length ? '需修正' : '已配置') : '未配置'}
              </span>
              <span>{file.exists ? `${file.total_rows} 行` : '等待上传'}</span>
              {file.updated_at && <span>{file.updated_at}</span>}
            </div>

            <div className="provider-columns">
              <strong>必要列：</strong>
              {file.required_columns.join(', ')}
              <br />
              <strong>推荐列：</strong>
              {file.recommended_columns.join(', ')}
            </div>

            {file.errors.length > 0 && (
              <div className="warning">
                <strong>校验问题</strong>
                <ul>
                  {file.errors.slice(0, 8).map((item) => <li key={item}>{item}</li>)}
                </ul>
                {file.error_truncated && <p>还有更多问题未展示。</p>}
              </div>
            )}

            <div className="button-row">
              <label className={`button file-button ${busyKey === file.key ? 'disabled' : ''}`}>
                {busyKey === file.key ? '处理中...' : '上传/替换 CSV'}
                <input type="file" accept=".csv,text/csv" onChange={(event) => handleUpload(file.key, event)} disabled={busyKey === file.key} />
              </label>
              <a className="button secondary" href={apiUrl(`/api/providers/industry-files/${file.key}/example`)}>
                下载示例
              </a>
              {file.exists && (
                <a className="button secondary" href={apiUrl(`/api/providers/industry-files/${file.key}/download`)}>
                  下载当前
                </a>
              )}
              {file.exists && (
                <button type="button" className="danger" onClick={() => handleDelete(file)} disabled={busyKey === file.key}>
                  删除当前
                </button>
              )}
            </div>

            {file.preview_rows.length > 0 ? (
              <div className="table-wrap compact-table">
                <table>
                  <thead>
                    <tr>
                      {file.columns.slice(0, 8).map((column) => <th key={column}>{column}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {file.preview_rows.slice(0, 8).map((row, index) => (
                      <tr key={`${file.key}-${index}`}>
                        {file.columns.slice(0, 8).map((column) => <td key={column}>{row[column] || '—'}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="muted">暂无当前 CSV 预览。可先下载示例文件。</p>
            )}
          </article>
        ))}
      </section>
    </main>
  );
}
