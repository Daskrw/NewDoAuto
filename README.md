# NewDoAuto

**NewDoAuto** is an independent, personal desktop automation application for Windows 10/11 designed to automate real desktop and web workflows without boilerplate code.

Inspired by reverse-engineering investigations of Microsoft Power Automate for desktop, NewDoAuto delivers a lightweight, reliable, and decoupled automation architecture built upon native **Windows UI Automation (UIA 3.0)**.

---

## Key Capabilities (Phase A Proven)

- **Native Windows UI Automation**: Locates and controls real Windows application elements by identity (`AutomationId`, `Name`, `ClassName`, `ControlTypeName`) rather than fragile screen coordinates.
- **Bi-directional UIA Data Flow**: Programmatically sets values via `ValuePattern` or simulated input, and reads back observed runtime state.
- **Declarative, Versioned Workflow Model**: Workflows are structured, versioned JSON definitions (`schema_version: "1.0.0"`) supporting actions, nested branching, parameters, and variable ledgers.
- **Real Conditional Logic (IF/ELSE)**: Dynamic condition evaluation engine supporting equality, inequality, numeric comparisons, and string predicates (`contains`, `startswith`, `endswith`) against live observed application state.
- **Execution Safety & Process Containment**:
  - Cooperative cancellation tokens.
  - Action timeouts with configurable retry and failure policies (`stop`, `continue`, `retry`).
  - Global emergency stop hotkey (`Ctrl+F12` / Win32 `RegisterHotKey`).
  - Automatic tracked cleanup of spawned child processes on workflow exit or abort.
- **Self-Contained Executable Packaging**: Bundles into a standalone Windows binary (`dist/newdoauto.exe`) with zero user Python dependency.

---

## Architecture

NewDoAuto strictly decouples workflow design, state management, and execution:

```
┌────────────────────────────────────────────────────────┐
│               NewDoAuto Workflow JSON                  │
│       (Declarative IR: Metadata, Variables, Actions)   │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│                   AutomationEngine                     │
│  - Schema Validation (validate_workflow)               │
│  - ExecutionContext & Variable Ledger                  │
│  - Action Dispatcher & Retry Policy Enforcement        │
└───────────────┬──────────────────────────┬─────────────┘
                │                          │
                ▼                          ▼
┌───────────────────────────────┐ ┌──────────────────────┐
│       UIA 3.0 Handlers        │ │ Flow & Logic Handlers│
│ - uia.find                    │ │ - flow.wait          │
│ - uia.get_text                │ │ - flow.set_variable  │
│ - uia.set_text                │ │ - flow.if_else       │
│ - uia.click                   │ │ - log.write          │
│ - app.launch / app.close      │ │                      │
└───────────────┬───────────────┘ └──────────────────────┘
                │
                ▼
┌────────────────────────────────────────────────────────┐
│     Target Windows Applications (e.g. Notepad.exe)     │
│   Communicates via Windows COM IUIAutomation3 Interfaces│
└────────────────────────────────────────────────────────┘
```

---

## Supported Actions (Phase A)

| Action Type | Description | Required Parameters |
| :--- | :--- | :--- |
| `app.launch` | Launches a Windows executable and tracks process | `command` |
| `app.close` | Terminates an application by PID or process name | `pid` or `process_name` |
| `uia.find` | Resolves control handle and returns metadata | `selector` |
| `uia.get_text` | Reads text via ValuePattern, TextPattern, or Name | `selector` |
| `uia.set_text` | Writes text via ValuePattern or simulated keystrokes | `selector`, `text` |
| `uia.click` | Triggers button/element click via InvokePattern | `selector` |
| `flow.wait` | Pauses execution with cooperative cancellation | `seconds` |
| `flow.set_variable` | Assigns or updates a variable in the execution context | `name`, `value` |
| `flow.if_else` | Evaluates condition and executes `then` or `else` branch | `condition` |
| `log.write` | Outputs structured log message with variable interpolation | `message` |

---

## Quickstart

### 1. Launch the Windows Desktop Application (Phase C GUI)
```powershell
# Launch via standalone desktop executable (No Python required)
.\dist\NewDoAuto-Desktop.exe

# Or launch via the CLI runner
.\dist\newdoauto.exe ui
```

### 2. Run Workflows via Standalone CLI (No Python Required)
```powershell
# Validate workflow
.\dist\newdoauto.exe validate workflows\notepad_poc.json

# Execute workflow
.\dist\newdoauto.exe run workflows\notepad_poc.json
```

### 3. Development Setup
```powershell
# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install package in editable mode with development dependencies
pip install -e ".[dev]"

# Launch the desktop GUI from source
newdoauto ui
# or: python -m newdoauto.ui.app

# Run test suite
pytest -v -rs
```

---

## End-to-End Proof of Concept (Notepad Verification)

The included proof-of-concept workflows demonstrate live interaction with Microsoft Notepad:

1. **`workflows/notepad_poc.json` (THEN Branch Verification)**:
   - Launches `notepad.exe`.
   - Locates the text editor `DocumentControl` (`RichEditD2DPT`).
   - Writes `NewDoAuto_POC_2026` via UI Automation `ValuePattern`.
   - Reads back the actual text.
   - Evaluates condition: `${observed_text} == 'NewDoAuto_POC_2026'`.
   - Executes the `then` branch and logs the verified success.
   - Terminates Notepad cleanly on completion.

2. **`workflows/notepad_poc_else.json` (ELSE Branch Verification)**:
   - Evaluates condition against mismatched text: `${observed_text} == 'MISMATCHED_STRING_12345'`.
   - Proves that the `else` branch executes when the condition is false.

---

## Packaging & Installation

### Building the Standalone Executables
```powershell
python packaging/build_standalone.py
```
This produces two self-contained Windows binaries in `dist/` with no external Python requirement:
1. `dist/NewDoAuto-Desktop.exe`: Windowed PySide6 desktop application (Authentication, Cloud Dashboard, Visual Workflow Editor, and Live Execution Runner).
2. `dist/newdoauto.exe`: Command-line runner supporting `newdoauto run`, `newdoauto validate`, and `newdoauto ui`.

### Per-User Installation
```powershell
.\packaging\install.ps1
```
Installs `NewDoAuto-Desktop.exe` and `newdoauto.exe` into `%LOCALAPPDATA%\Programs\NewDoAuto\bin` and adds the directory to the user's `PATH`.

---

## Windows Desktop Application (Phase C)

Built with **PySide6 (Qt for Python)** in `src/newdoauto/ui/`, the desktop application wraps `AutomationEngine`, `SupabaseAuthService`, and `WorkflowCloudRepository` without duplicating business logic:

- **Account & Session Management**:
  - Sign In and Create Account screens with clear validation and sanitized error messages.
  - Automatic session restoration on startup (`restore_session()`) and one-click Sign Out that immediately clears user-scoped cloud state.
  - Full Local Mode support when working offline or without a Supabase connection.
- **Cloud Workflow Dashboard**:
  - Displays the authenticated user's workflows from Supabase (`list_workflows()`).
  - Create, Open, Rename, Refresh, and Delete (with confirmation dialog), plus Local JSON Import/Export.
- **Visual Step-by-Step Workflow Editor**:
  - Edit workflow name, description, and initial variables JSON.
  - Add any of the 10 supported action types from `ActionRegistry`, edit step parameters in a structured form (`StepParameterEditor`), reorder steps (Move Up / Move Down), duplicate steps, and delete steps.
  - Visual overview and validated JSON branch editor for `flow.if_else` (`then` and `else` branches), preserving nested actions and any unknown/extra schema fields on round-trip save.
  - Tracks unsaved changes (`● Unsaved Changes`) and prompts before discarding edits.
  - Handles optimistic concurrency conflicts (`WorkflowConflictError`) with options to **Reload Cloud Version**, **Save Local Edits as New Copy**, or **Cancel**—never silently overwriting newer cloud data.
- **Responsive Execution & Live Logs**:
  - Runs workflows in a background `QThread` (`WorkflowExecutionWorker`) so the UI never freezes.
  - Streams structured execution logs incrementally in real time.
  - Provides a **Stop** button alongside the `Ctrl+F12` global emergency stop hotkey, and displays distinct status badges (`IDLE`, `RUNNING`, `SUCCESS`, `FAILED`, `TIMEOUT`, `CANCELLED`).

---

## Cloud Persistence & Supabase Authentication (Phase B)

NewDoAuto uses **Supabase** (`Supabase Auth` + `Supabase PostgreSQL` + `Row Level Security`) as its sole cloud database platform. The cloud layer (`src/newdoauto/cloud/`) is strictly decoupled from the Windows UI Automation engine (`src/newdoauto/core/`), ensuring local JSON workflows continue to execute offline without requiring a cloud connection.

### 1. Security & Key Guardrails
- **Publishable Key Only**: The desktop client uses only `SUPABASE_URL` and the public `SUPABASE_ANON_KEY` (configured via environment variables or `.env`).
- **Active Secret Rejection**: `load_supabase_config()` inspects configured keys and actively rejects `service_role` JWTs and `sb_secret_...` keys so privileged credentials can never be used in the desktop client.
- **Zero Password Persistence**: `SupabaseAuthService` persists only non-password session tokens (`access_token`, `refresh_token`, `expires_at`) to `%LOCALAPPDATA%\NewDoAuto\session.json` and redacts tokens/passwords from all `repr()` strings and exception messages via `sanitize_error_message()`.

### 2. Database Schema & Migration
Apply the version-controlled migration in [`supabase/migrations/20261029000001_create_workflows_table.sql`](supabase/migrations/20261029000001_create_workflows_table.sql) via the Supabase SQL Editor or `supabase db push`:

- **Table**: `public.workflows`
  - `id` (`UUID PRIMARY KEY`)
  - `owner_id` (`UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE`)
  - `name` (`TEXT NOT NULL`, non-empty constraint)
  - `description` (`TEXT`)
  - `schema_version` (`TEXT NOT NULL DEFAULT '1.0.0'`)
  - `definition` (`JSONB NOT NULL`, checked to be a JSON object)
  - `version` (`INTEGER NOT NULL DEFAULT 1`, checked `>= 1` for optimistic concurrency control)
  - `created_at` / `updated_at` (`TIMESTAMPTZ NOT NULL DEFAULT now()`)
- **Row Level Security (RLS)**:
  - `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY` on `public.workflows`.
  - All privileges revoked from `PUBLIC` and `anon`.
  - Four per-operation policies (`workflows_select_own`, `workflows_insert_own`, `workflows_update_own`, `workflows_delete_own`) restricting `authenticated` users strictly to rows where `(SELECT auth.uid()) = owner_id`.
  - Database trigger `trg_workflows_before_update` prevents mutating `id` or `owner_id` and automatically updates `updated_at`.

### 3. Desktop UI Integration Interface
The future desktop UI layer interacts with the cloud module through two service classes:

```python
from newdoauto.cloud import (
    SupabaseAuthService,
    WorkflowCloudRepository,
    WorkflowConflictError,
)
from newdoauto.models.workflow import Workflow

# 1. Initialize Auth Service (loads SUPABASE_URL and SUPABASE_ANON_KEY from .env)
auth = SupabaseAuthService()

# Restore previous session on app launch, or sign in with email & password
session = auth.restore_session() or auth.sign_in("user@example.com", "StrongPassword123!")

# 2. Perform Authenticated Workflow CRUD
repo = WorkflowCloudRepository(auth_service=auth)

# Create workflow (saved at version=1)
wf = Workflow.from_json(open("workflows/notepad_poc.json", encoding="utf-8").read())
record = repo.create_workflow(wf)

# List and fetch user's workflows
my_workflows = repo.list_workflows()
loaded = repo.get_workflow(record.id)

# Update with optimistic concurrency protection
try:
    loaded.workflow.name = "Updated Notepad Flow"
    updated = repo.update_workflow(
        workflow_id=loaded.id,
        workflow=loaded.workflow,
        expected_version=loaded.version,
    )
except WorkflowConflictError as exc:
    # Handle concurrent edit from another PC without silent data loss
    print(f"Conflict: expected v{exc.expected_version}, cloud has v{exc.actual_version}")

# Delete workflow and sign out
repo.delete_workflow(record.id)
auth.sign_out()
```

### 4. Verifying Row Level Security (RLS) Live
1. Open your Supabase project dashboard -> **SQL Editor**, paste the contents of [`supabase/migrations/20261029000001_create_workflows_table.sql`](supabase/migrations/20261029000001_create_workflows_table.sql), and click **Run**.
2. Create two test users in **Authentication -> Users** (or enable immediate email sign-up) and set `NEWDOAUTO_TEST_USER_A_EMAIL`, `NEWDOAUTO_TEST_USER_A_PASSWORD`, `NEWDOAUTO_TEST_USER_B_EMAIL`, and `NEWDOAUTO_TEST_USER_B_PASSWORD` in your local `.env`.
3. Run the live verification suite:
   ```powershell
   pytest tests/test_supabase_live_rls.py -v -rs
   ```
   This verifies live Auth rejection of invalid credentials, anonymous table protection, and two-user RLS isolation (confirming User B cannot read, update, delete, or spoof `owner_id` for User A's workflows).
