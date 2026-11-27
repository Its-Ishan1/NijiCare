import './components.css';

export const PIPELINE_STAGES = [
  {
    title: 'Read and parse files',
    detail: 'Inspect supported CSV, TSV, JSON/FHIR, and text files; route unsupported formats to quarantine.',
  },
  {
    title: 'Detect personal information',
    detail: 'Identify names, phone numbers, health IDs, dates of birth, and addresses across English, Hindi, and Hinglish.',
  },
  {
    title: 'Link records conservatively',
    detail: 'Assign deterministic HMAC pseudonyms across scripts while keeping distinct homonyms separated.',
  },
  {
    title: 'Generalize or shift risky details',
    detail: 'Apply adaptive k-anonymous age bands and consistent per-patient date shifts preserving clinical durations.',
  },
  {
    title: 'Write sanitized files and audit report',
    detail: 'Emit cleaned outputs, records.jsonl linkage map, and aggregate SHA-256 report.json.',
  },
];

interface PipelineStagesProps {
  activeStageIndex: number;
  isComplete: boolean;
}

export function PipelineStages({ activeStageIndex, isComplete }: PipelineStagesProps) {
  return (
    <ol className="stages-list">
      {PIPELINE_STAGES.map((stage, idx) => {
        const isDone = isComplete || idx < activeStageIndex;
        const isActive = !isComplete && idx === activeStageIndex;
        const stateClass = isDone ? 'is-done' : isActive ? 'is-active' : '';
        return (
          <li key={stage.title} className={`stage-item ${stateClass}`}>
            <span className="stage-badge" aria-hidden="true">
              {isDone ? '✓' : idx + 1}
            </span>
            <div className="stage-copy">
              <strong>{stage.title}</strong>
              <small>{stage.detail}</small>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
