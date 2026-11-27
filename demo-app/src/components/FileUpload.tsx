import { useRef, useState, type DragEvent } from 'react';
import type { CustomFileInput, RunRequestPayload } from '../types';

type Selection = { path: string; file: File };
const maxFiles = 250;
const maxBodyBytes = 25 * 1024 * 1024;

function fromPicker(files: FileList | null): Selection[] {
  return Array.from(files ?? [], file => ({
    path: file.webkitRelativePath.split('/').slice(1).join('/') || file.name,
    file,
  }));
}

async function fromDrop(event: DragEvent): Promise<Selection[]> {
  const items = Array.from(event.dataTransfer.items).filter(item => item.kind === 'file');
  const entries = items.map(item => item.webkitGetAsEntry?.());
  if (!entries.length || entries.some(entry => !entry)) return fromPicker(event.dataTransfer.files);
  const selected: Selection[] = [];
  async function visit(entry: FileSystemEntry, path: string) {
    if (entry.isFile) {
      if (selected.length >= maxFiles) throw Error('Select up to 250 files per run.');
      const file = await new Promise<File>((ok, fail) => (entry as FileSystemFileEntry).file(ok, fail));
      selected.push({ path, file });
    } else {
      const reader = (entry as FileSystemDirectoryEntry).createReader();
      while (true) {
        const batch = await new Promise<FileSystemEntry[]>((ok, fail) => reader.readEntries(ok, fail));
        if (!batch.length) break;
        for (const child of batch) await visit(child, path ? path + '/' + child.name : child.name);
      }
    }
  }
  for (const entry of entries) {
    if (entry) await visit(entry, entry.isDirectory && entries.length === 1 ? '' : entry.name);
  }
  return selected;
}

function encode({ path, file }: Selection): Promise<CustomFileInput> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(Error('Could not read ' + path + '. Select it again.'));
    reader.onload = () => {
      const url = String(reader.result);
      resolve({ name: path, encoding: 'base64', content: url.slice(url.indexOf(',') + 1) });
    };
    reader.readAsDataURL(file);
  });
}

interface Props {
  busy: boolean;
  onRun: (files: NonNullable<RunRequestPayload['files']>) => Promise<boolean>;
}

export function FileUpload({ busy, onRun }: Props) {
  const [selected, setSelected] = useState<Selection[]>([]);
  const [error, setError] = useState('');
  const [reading, setReading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const filesInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  const locked = busy || reading;

  async function add(selection: Promise<Selection[]> | Selection[]) {
    if (locked) return;
    setReading(true);
    setError('');
    try {
      const additions = await selection;
      if (!additions.length) throw Error('The selection contains no files.');
      const next = [...selected, ...additions];
      if (next.length > maxFiles) throw Error('Select up to 250 files per run.');
      if (next.reduce((n, item) => n + 4 * Math.ceil(item.file.size / 3), 0) >= maxBodyBytes) {
        throw Error('This batch exceeds the 25 MiB upload limit after encoding. Use a smaller batch or the CLI.');
      }
      const paths = new Set<string>();
      for (const item of next) {
        const key = item.path.toLowerCase();
        if (paths.has(key)) throw Error('Duplicate path: ' + item.path + '. Select its parent folder or remove the earlier file.');
        paths.add(key);
      }
      setSelected(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not read the selection. Try Choose folder.');
    } finally {
      setReading(false);
    }
  }

  async function run() {
    if (locked || !selected.length) return;
    setError('');
    setReading(true);
    try {
      await onRun(await Promise.all(selected.map(encode)));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not read the files.');
    } finally {
      setReading(false);
    }
  }

  return <section className="card wb-card wb-pane" aria-label="Upload input">
    <div className={'dropzone' + (dragging ? ' is-dragging' : '')}
      onDragOver={event => { event.preventDefault(); if (!locked) setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={event => {
        event.preventDefault();
        setDragging(false);
        if (!locked) void add(fromDrop(event));
      }}>
      <h3>Drop files or a folder here</h3>
      <p>CSV, TSV, JSON and TXT files are processed. Other formats appear in Quarantine.</p>
      <div className="upload-actions">
        <button className="btn btn-secondary" disabled={locked} onClick={() => filesInput.current?.click()}>Choose files</button>
        <button className="btn btn-secondary" disabled={locked} onClick={() => folderInput.current?.click()}>Choose folder</button>
      </div>
      <input ref={filesInput} type="file" multiple hidden aria-label="Files to upload"
        onChange={e => { const files = fromPicker(e.currentTarget.files); e.currentTarget.value = ''; void add(files); }} />
      <input ref={folderInput} type="file" multiple webkitdirectory="" hidden aria-label="Folder to upload"
        onChange={e => { const files = fromPicker(e.currentTarget.files); e.currentTarget.value = ''; void add(files); }} />
    </div>
    {error && <p className="error-banner" role="alert">{error}</p>}
    {selected.length > 0 && <div className="staged-list">
      <div className="staged-list-head">
        <strong>{selected.length} {selected.length === 1 ? 'file' : 'files'} selected</strong>
        <button className="btn-link" disabled={locked} onClick={() => { setSelected([]); setError(''); }}>Clear all</button>
      </div>
      <ul>{selected.map(item => <li className="staged-item" key={item.path}>
        <span className="mono">{item.path}</span>
        <button className="btn-link" disabled={locked} aria-label={'Remove ' + item.path}
          onClick={() => { setSelected(selected.filter(f => f.path !== item.path)); setError(''); }}>Remove</button>
      </li>)}</ul>
    </div>}
    <div><button type="button" className="btn btn-primary wb-run-btn" disabled={locked || !selected.length}
      onClick={() => void run()}>{busy ? 'Running offline pipeline…' : reading ? 'Reading files…' : 'Run Privacy Pipeline'}</button></div>
  </section>;
}
