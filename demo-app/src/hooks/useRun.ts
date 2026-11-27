import { useCallback, useEffect, useRef, useState } from 'react';
import type {
  PipelineFileEntry,
  RunDetail,
  RunFilesResponse,
  RunHistoryItem,
  RunRequestPayload,
} from '../types';
import { apiGet, apiPost, type ApiError } from './useApi';

interface StartRunResponse {
  run_id: string;
  status: 'running';
}

export function useRun(onRunCompleted?: () => void) {
  const [runId, setRunId] = useState<string | null>(null);
  const [runDetail, setRunDetail] = useState<RunDetail | null>(null);
  const [files, setFiles] = useState<PipelineFileEntry[]>([]);
  const [history, setHistory] = useState<RunHistoryItem[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  const [isStarting, setIsStarting] = useState(false);

  const pollRef = useRef<number | null>(null);
  const generation = useRef(0);
  const onCompletedRef = useRef(onRunCompleted);
  onCompletedRef.current = onRunCompleted;

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearTimeout(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const refreshHistory = useCallback(async () => {
    try {
      const res = await apiGet<{ runs: RunHistoryItem[] }>('/api/runs');
      setHistory(res.runs || []);
    } catch {
      // Ignore if offline
    }
  }, []);

  const loadRunFiles = useCallback(async (id: string, token: number) => {
    const filesRes = await apiGet<RunFilesResponse>(`/api/runs/${encodeURIComponent(id)}/files`);
    if (generation.current === token) setFiles(filesRes.files);
  }, []);

  const pollStatus = useCallback(
    async function poll(id: string, token: number, navigate = true): Promise<void> {
      try {
        const detail = await apiGet<RunDetail>(`/api/runs/${encodeURIComponent(id)}`);
        if (token !== generation.current) return;
        setRunDetail(detail);
        if (detail.status === 'completed') {
          stopPolling();
          await loadRunFiles(id, token);
          await refreshHistory();
          if (navigate && token === generation.current) onCompletedRef.current?.();
          return;
        }
        if (detail.status === 'failed') {
          stopPolling();
          await refreshHistory();
          if (token !== generation.current) return;
          setError({
            message: detail.error_message || 'Pipeline execution failed.',
            requestId: detail.request_id || undefined,
          });
          return;
        }
        pollRef.current = window.setTimeout(() => void poll(id, token), 350);
      } catch (err) {
        if (token !== generation.current) return;
        stopPolling();
        const apiErr = err as ApiError;
        setError({
          message: apiErr?.message || 'Unable to reach local privacy server.',
          requestId: apiErr?.requestId,
        });
      }
    },
    [loadRunFiles, refreshHistory, stopPolling]
  );

  const startRun = useCallback(
    async (payload: RunRequestPayload): Promise<boolean> => {
      stopPolling();
      const token = ++generation.current;
      setError(null);
      setFiles([]);
      setRunDetail(null);
      setIsStarting(true);

      try {
        const created = await apiPost<StartRunResponse>('/api/runs', payload);
        if (token !== generation.current) return false;
        setRunId(created.run_id);
        setRunDetail({
          run_id: created.run_id,
          source: payload.label || payload.source,
          label: payload.label,
          status: 'running',
          started_at: new Date().toISOString(),
          finished_at: null,
          counts: null,
          entities: {},
          timing: null,
          resources: { peak_rss_mb: null },
          records: [],
          risk: null,
          policy_used: payload.policy ?? null,
          secret_mode: payload.secret_mode ?? 'default',
          error_message: null,
        });

        await pollStatus(created.run_id, token);
        return true;
      } catch (err) {
        if (generation.current !== token) return false;
        const apiErr = err as ApiError;
        setError({
          message: apiErr?.message || 'Unable to start sanitization run.',
          requestId: apiErr?.requestId,
        });
        return false;
      } finally {
        if (generation.current === token) setIsStarting(false);
      }
    },
    [pollStatus, stopPolling]
  );

  const selectRun = useCallback(
    async (id: string) => {
      stopPolling();
      const token = ++generation.current;
      setError(null);
      setIsStarting(false);
      setRunId(id);
      setRunDetail(null);
      setFiles([]);
      await pollStatus(id, token, false);
    },
    [pollStatus, stopPolling]
  );

  useEffect(() => {
    void refreshHistory();
    return () => { generation.current++; stopPolling(); };
  }, [refreshHistory, stopPolling]);

  return {
    runId,
    runDetail,
    files,
    history,
    error,
    isStarting,
    startRun,
    selectRun,
    refreshHistory,
  };
}
