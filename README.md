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

### 1. Run via Standalone Executable (No Python Required)
```powershell
# Validate workflow
.\dist\newdoauto.exe validate workflows\notepad_poc.json

# Execute workflow
.\dist\newdoauto.exe run workflows\notepad_poc.json
```

### 2. Development Setup
```powershell
# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install package in editable mode with development dependencies
pip install -e ".[dev]"

# Run test suite
pytest -v -s
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

### Building the Standalone Binary
```powershell
python packaging/build_standalone.py
```
This produces `dist/newdoauto.exe` (approx 7.6 MB) containing the embedded runtime and all required dependencies.

### Per-User Installation
```powershell
.\packaging\install.ps1
```
Installs `newdoauto.exe` into `%LOCALAPPDATA%\Programs\NewDoAuto\bin` and adds it to the user's `PATH`.

---

## Cloud Roadmap: Supabase Integration (Phase B)

In Phase B, saved workflows will synchronize across PCs using Supabase:
- **Supabase Auth**: User authentication.
- **Supabase PostgreSQL**: Authoritative cloud store for versioned workflow JSON documents.
- **Row Level Security (RLS)**: Enforces strict per-user ownership and isolation.
- **Security Rule**: No service role keys or database credentials are ever embedded in the client application. Client uses solely the public publishable anon key with authenticated JWTs.
- See [`.env.example`](.env.example) for template configuration.
