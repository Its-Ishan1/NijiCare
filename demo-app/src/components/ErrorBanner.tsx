import './components.css';

interface ErrorBannerProps {
  message: string;
  requestId?: string;
  onRetry?: () => void;
  retryLabel?: string;
}

export function ErrorBanner({
  message,
  requestId,
  onRetry,
  retryLabel = 'Retry demo run',
}: ErrorBannerProps) {
  return (
    <div className="error-banner" role="alert">
      <div>
        <strong>Unable to complete sanitization run</strong>
        <p>{message}</p>
        {requestId && (
          <div className="error-request-id">Reference ID: {requestId}</div>
        )}
      </div>
      {onRetry && (
        <button type="button" className="btn btn-secondary" onClick={onRetry}>
          {retryLabel}
        </button>
      )}
    </div>
  );
}
