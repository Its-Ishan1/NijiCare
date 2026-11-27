export interface ApiError {
  message: string;
  requestId?: string;
}

async function parseErrorResponse(res: Response): Promise<ApiError> {
  try {
    const data = (await res.json()) as { error?: string; request_id?: string };
    return {
      message: data.error || `Request failed with status ${res.status}`,
      requestId: data.request_id,
    };
  } catch {
    return { message: `Request failed with status ${res.status}` };
  }
}

export async function apiGet<T>(url: string): Promise<T> {
  const res = await fetch(url, {
    method: 'GET',
    headers: { Accept: 'application/json' },
  });
  if (!res.ok) {
    throw await parseErrorResponse(res);
  }
  return (await res.json()) as T;
}

export async function apiPost<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw await parseErrorResponse(res);
  }
  return (await res.json()) as T;
}
