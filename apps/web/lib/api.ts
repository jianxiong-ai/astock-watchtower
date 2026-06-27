const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

export function apiUrl(path: string): string {
  return `${API_BASE_URL}${path}`;
}

type ApiValidationError = {
  loc?: unknown[];
  msg?: string;
};

async function parseError(response: Response): Promise<Error> {
  const text = await response.text();
  if (!text) return new Error(`${response.status} ${response.statusText}`);
  try {
    const data = JSON.parse(text);
    if (typeof data.detail === 'string') {
      return new Error(data.detail);
    }
    if (Array.isArray(data.detail)) {
      const lines = data.detail.map((item: ApiValidationError) => {
        const loc = Array.isArray(item.loc) ? item.loc.filter((part: unknown) => part !== 'body').join('.') : '';
        return `${loc ? `${loc}: ` : ''}${item.msg || JSON.stringify(item)}`;
      });
      return new Error(lines.join('；'));
    }
    if (data.message) {
      return new Error(String(data.message));
    }
    return new Error(JSON.stringify(data));
  } catch {
    return new Error(text);
  }
}

function normalizeFetchError(error: unknown): Error {
  if (error instanceof Error) {
    if (error.name === 'TypeError' || error.message.toLowerCase().includes('failed to fetch')) {
      return new Error(`无法连接后端 API（${API_BASE_URL}）。请检查 API 是否启动、NEXT_PUBLIC_API_BASE_URL 是否正确，以及浏览器是否允许访问该地址。`);
    }
    return error;
  }
  return new Error(String(error));
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, init);
    if (!response.ok) throw await parseError(response);
    if (response.status === 204) return undefined as T;
    return response.json();
  } catch (error) {
    throw normalizeFetchError(error);
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  return request<T>(path);
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export async function apiDelete(path: string): Promise<void> {
  await request<void>(path, { method: 'DELETE' });
}

export async function uploadFile<T>(path: string, file: File): Promise<T> {
  const form = new FormData();
  form.append('file', file);
  return request<T>(path, { method: 'POST', body: form });
}
