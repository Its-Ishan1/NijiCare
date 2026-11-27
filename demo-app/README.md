# Local workbench

The local server runs the Python engine in a separate process, serves the production frontend and provides before/after previews and exports for synthetic data.

## Start on macOS / Linux

From the repository root:

```bash
./start-web.sh
```

Or, from this directory, launch the standard-library adapter directly:

```bash
python3 -B server/server.py
```

Open **http://127.0.0.1:8081**. The root launcher uses a demo-only key if `RAKSHA_SECRET` is unset, and warns to use synthetic data with that key. Set `RAKSHA_SECRET` before launch to use a private test key. Set `PORT=8082` to select another local port.

## Start on Windows PowerShell

From this directory:

```powershell
python -B server/server.py
```

Open **http://127.0.0.1:8081**. The environment variable `PORT` overrides the port. The release includes `dist/`, so it can run offline without Node. To edit the frontend, install dependencies with `npm ci` and rebuild with `npm run build`.

## Uploading files

Use **Choose files** or **Choose folder** and click **Run Privacy Pipeline**. Folder selection retains nested relative paths. CSV, TSV, JSON, single-patient FHIR Bundles and TXT go through the sanitizer. A Bundle with multiple `Patient` resources is quarantined as `unsupported_fhir_patient_count` rather than partially released. The report gives a reason for each quarantined file. Select **Download ZIP** in Results to export the sanitized files, report and record index.

`OUTPUT_DIR` selects where releases are saved. Uploaded files are staged temporarily on the local machine. Before-previews live in the server process. The browser accepts up to 250 files per run and a 25 MiB encoded request body. The CLI accepts a single file or a directory directly.

## Browser verification

With the frontend built, run `node tools/check-ui.mjs <path-to-local-playwright-package> <path-to-Chromium>`. This starts an isolated local adapter with temporary storage, drives a desktop and mobile session, checks file and folder uploads against CLI output, replay and rotation, and closes both processes. Playwright and Chromium are development tools.

See the [user guide](../docs/USER_GUIDE.md) for uploads and policy settings, and the [architecture](../docs/ARCHITECTURE.md) for API details.
