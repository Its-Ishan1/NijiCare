// Run against the production build with a local Playwright package and Chromium.
import assert from 'node:assert/strict';
import { spawn, execFileSync } from 'node:child_process';
import { once } from 'node:events';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const { chromium } = createRequire(import.meta.url)(process.argv[2] || 'playwright');
const serverDir = fileURLToPath(new URL('../server/', import.meta.url));
const scratch = await mkdtemp(path.join(os.tmpdir(), 'wards-ui-'));
const app = spawn(process.env.PYTHON || 'python', ['-B', '-u', '-c',
  "from server import *; s=ThreadingHTTPServer(('127.0.0.1',0),make_handler(load_config())); print(s.server_port); s.serve_forever()"],
  { cwd: serverDir, env: { ...process.env, OUTPUT_DIR: path.join(scratch, 'web'), RAKSHA_SECRET: 'test-upload-parity' }, windowsHide: true });
let browser;
try {
  const [port] = await once(app.stdout, 'data');
  const origin = 'http://127.0.0.1:' + String(port).trim();
  browser = await chromium.launch({ executablePath: process.argv[3], headless: true });
  const page = await browser.newPage({ viewport: { width: 1360, height: 900 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (/^https?:/.test(request.url()) && new URL(request.url()).origin !== origin) errors.push('External request');
  });
  await page.goto(origin);
  const folder = path.join(scratch, 'input');
  const first = path.join(folder, 'ward-a', 'intake.csv');
  const second = path.join(folder, 'ward-b', 'intake.csv');
  await mkdir(path.dirname(first), { recursive: true });
  await mkdir(path.dirname(second), { recursive: true });
  await writeFile(first, 'Patient name,UHID,Dose\nRavi Sharma,TX-45891,2.5 mg\n');
  await writeFile(second, Buffer.from('\ufeffPatient name,UHID,Dose\r\nमीरा वर्मा,TX-67083,125 mg\r\n', 'utf16le'));
  await writeFile(path.join(folder, 'scan.pdf'), Buffer.from([37, 80, 68, 70, 0, 255]));
  const runButton = page.getByRole('button', { name: 'Run Privacy Pipeline' });
  await runButton.waitFor();
  assert.ok(await runButton.isDisabled());
  assert.equal(await page.getByRole('textbox').count(), 0);
  const choose = async (name, paths) => {
    const waiting = page.waitForEvent('filechooser');
    await page.getByRole('button', { name, exact: true }).click();
    await (await waiting).setFiles(paths);
  };
  async function verifyRun(input, tag, count) {
    const posted = page.waitForResponse(r => r.url() === origin + '/api/runs' && r.request().method() === 'POST');
    await runButton.click();
    const response = await posted;
    assert.equal(response.status(), 202);
    const { run_id } = await response.json();
    await page.getByRole('heading', { name: 'Results dashboard' }).waitFor();
    const web = path.join(scratch, 'web', run_id);
    const cli = path.join(scratch, 'cli-' + tag);
    execFileSync(process.env.PYTHON || 'python', ['-B', path.resolve(serverDir, '../../main.py'), '--input', input, '--output', cli],
      { env: { ...process.env, RAKSHA_SECRET: 'test-upload-parity' }, windowsHide: true });
    const report = JSON.parse(await readFile(path.join(web, 'report.json'), 'utf8'));
    const expected = JSON.parse(await readFile(path.join(cli, 'report.json'), 'utf8'));
    assert.equal(report.counts.files_total, count);
    for (const key of ['files', 'counts', 'entities']) assert.deepEqual(report[key], expected[key]);
    for (const rel of ['records.jsonl', ...report.files.filter(f => f.output).map(f => f.output)]) {
      assert.deepEqual(await readFile(path.join(web, rel)), await readFile(path.join(cli, rel)));
    }
    const exportZip = await page.request.get(origin + '/api/runs/' + run_id + '/export');
    assert.equal((await exportZip.body()).subarray(0, 2).toString(), 'PK');
    return { run_id, report, web };
  }
  await choose('Choose files', first);
  await page.getByText('1 file selected', { exact: true }).waitFor();
  const one = await verifyRun(first, 'file', 1);
  const sanitized = await readFile(path.join(one.web, one.report.files[0].output), 'utf8');
  assert.match(sanitized, /2\.5 mg/);
  assert.doesNotMatch(sanitized, /Ravi Sharma|TX-45891/);
  await page.getByRole('button', { name: 'Workbench', exact: true }).click();
  await choose('Choose files', [first, path.join(folder, 'scan.pdf')]);
  await page.getByText('2 files selected', { exact: true }).waitFor();
  await page.getByRole('button', { name: 'Clear all' }).click();
  await choose('Choose folder', folder);
  await page.getByText('3 files selected', { exact: true }).waitFor();
  const batch = await verifyRun(folder, 'folder', 3);
  assert.equal(batch.report.counts.files_sanitized, 2);
  assert.equal(batch.report.counts.files_quarantined, 1);
  const secondFile = batch.report.files.find(f => f.output === 'sanitized/ward-b/intake.csv');
  assert.ok(secondFile);
  const preview = await page.request.get(origin + '/api/runs/' + batch.run_id + '/before?sha256=' + secondFile.input_sha256);
  assert.match(await preview.text(), /मीरा वर्मा/);
  await page.getByRole('button', { name: 'Privacy & Audit' }).click();
  await page.getByText('100.0% of checked values', { exact: true }).waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Workbench', exact: true }).click();
  await runButton.waitFor();
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));

  const submit = async payload => {
    const response = await page.request.post(origin + '/api/runs', { data: payload });
    assert.equal(response.status(), 202);
    const { run_id: id } = await response.json();
    for (let i = 0; i < 100; i++) {
      const result = await (await page.request.get(origin + '/api/runs/' + id)).json();
      if (result.status === 'completed') return result;
      assert.equal(result.status, 'running');
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    throw Error('Run timed out');
  };
  const sample = { source: 'preset', preset_id: 'ward_transfer', seed: 778 };
  const replay = await submit(sample);
  assert.deepEqual((await submit(sample)).records, replay.records);
  assert.notDeepEqual((await submit({ ...sample, secret_mode: 'rotate' })).records, replay.records);
  const custom = await submit({ source: 'custom', policy: { extra_redact_fields: ['Badge'] }, files: [
    { name: 'intake.csv', content: 'UHID,Badge,Dose\nWX-30781,PrivateTag,2.5 mg\n' },
    { name: 'scan.pdf', content: 'UERG', encoding: 'base64' }] });
  assert.equal(custom.counts.files_quarantined, 1);
  const base = origin + '/api/runs/' + custom.run_id;
  const { files } = await (await page.request.get(base + '/files')).json();
  const file = files.find(f => f.status === 'sanitized');
  assert.match((await (await page.request.get(base + '/before?sha256=' + file.input_sha256)).text()), /PrivateTag/);
  const download = await (await page.request.get(base + '/file?download=1&path=' + encodeURIComponent(file.output))).text();
  assert.match(download, /2.5 mg/);
  assert.doesNotMatch(download, /PrivateTag/);
  assert.deepEqual(errors, []);
  console.log('PASS: file and folder pickers, nested duplicate basenames, UTF-16, CLI parity, mobile layout, replay, rotation, audit, quarantine, preview and ZIP export.');
} finally {
  await browser?.close();
  const closed = once(app, 'close');
  app.kill();
  await closed;
  if (path.dirname(scratch) === os.tmpdir() && path.basename(scratch).startsWith('wards-ui-')) {
    await rm(scratch, { recursive: true, force: true });
  }
}
