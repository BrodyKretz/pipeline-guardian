# File Viewer UI Implementation Plan (Phase 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. **Verification is via Playwright screenshots** (no JS test harness in this repo) — that is the feedback loop for every UI task.

**Goal:** A "Files" screen in the dashboard where you watch the raw contents of every agent-touched file change live — damage in red, heals in the healing agent's color, unhealed damage staying red.

**Architecture:** A view toggle in the top bar switches the stage between the existing agent-graph and a new full-screen Files view. The Files view subscribes to the same `/ws` stream, keeps per-file content state, and on each `FILE_CHANGED` event diffs `before`→`after` by line and colors the changed lines by `kind`/agent. Colors are a browser-only overlay (the backend already keeps the AI blind to them — Phase 1).

**Tech Stack:** Vanilla JS + CSS in `dashboard/index.html` (matches existing style). Depends on Phase 1's `FILE_CHANGED` events.

**Prerequisite:** Phase 1 complete and merged (FILE_CHANGED events flow in both mock and AI mode).

---

## File Structure

- `dashboard/index.html` (modify) — add: view-toggle buttons in `#top`; a `#files` full-screen panel; per-file state + line-diff render in the `<script>`; hook `FILE_CHANGED` in the existing `handle(ev)` / `connect()` path.

All work is in this one file (matches the project's single-file dashboard pattern).

---

### Task 1: View toggle + Files screen scaffold

**Files:** Modify `dashboard/index.html`

- [ ] **Step 1: Add a view toggle to the top bar**

After the mode `<div class="seg" id="modeSeg">…</div>` block, add a second segmented control:

```html
    <div class="seg" id="viewSeg">
      <button id="vGraph" class="sel">GRAPH</button>
      <button id="vFiles">FILES</button>
    </div>
```

- [ ] **Step 2: Add the Files panel markup**

After the `#stage` div, add:

```html
  <div id="files" style="display:none">
    <div id="fileTabs"></div>
    <pre id="fileView"></pre>
  </div>
```

- [ ] **Step 3: Add CSS** (inside `<style>`)

```css
  #files{position:fixed;inset:56px 0 0 0;display:flex;flex-direction:column;
    padding:16px 24px;gap:12px;z-index:10}
  #fileTabs{display:flex;gap:8px}
  #fileTabs button{background:rgba(255,255,255,.05);border:1px solid var(--border);
    color:var(--dim);font:700 11px ui-monospace,monospace;padding:8px 14px;
    border-radius:8px;cursor:pointer;letter-spacing:.5px}
  #fileTabs button.sel{color:var(--txt);border-color:var(--patch)}
  #fileView{flex:1;overflow:auto;background:rgba(0,0,0,.35);
    border:1px solid var(--border);border-radius:12px;padding:16px 18px;
    font:13px/1.55 ui-monospace,monospace;white-space:pre;color:var(--dim)}
  .ln{display:block;border-radius:3px;padding:0 4px}
  .ln.damage{color:#ff5b73;background:rgba(255,45,85,.12)}
  .ln.heal{background:rgba(255,255,255,.04)}
```

- [ ] **Step 4: Wire the toggle** (in `<script>`, near the other control handlers)

```javascript
const stageEl=document.getElementById('stage');
const filesEl=document.getElementById('files');
function showView(v){
  const files=v==='files';
  filesEl.style.display=files?'flex':'none';
  stageEl.style.display=files?'none':'block';
  document.getElementById('vFiles').classList.toggle('sel',files);
  document.getElementById('vGraph').classList.toggle('sel',!files);
}
document.getElementById('vGraph').onclick=()=>showView('graph');
document.getElementById('vFiles').onclick=()=>showView('files');
```

- [ ] **Step 5: Verify with Playwright**

Start the app (`PG_DISABLE_SCHEDULER=1 python -m uvicorn main:app` in background), navigate to `http://localhost:8000`, click the FILES button, screenshot. Expected: empty Files screen with tabs area + dark code box, GRAPH/FILES toggle visible and switching. Then commit.

```bash
git add dashboard/index.html
git commit -m "feat(ui): Files view toggle + screen scaffold"
```

---

### Task 2: Per-file state + live render of FILE_CHANGED

**Files:** Modify `dashboard/index.html`

- [ ] **Step 1: Add file-state store + render**

```javascript
const fileState={};      // path -> {lines:[{text,cls}], }
let activeFile=null;

function ensureTab(path){
  if(fileState[path])return;
  fileState[path]={lines:[]};
  const b=el('button',null,path);
  b.onclick=()=>{activeFile=path;renderFile();
    [...document.getElementById('fileTabs').children]
      .forEach(c=>c.classList.toggle('sel',c.textContent===path));};
  document.getElementById('fileTabs').appendChild(b);
  if(!activeFile){activeFile=path;b.classList.add('sel');}
}

function renderFile(){
  const view=document.getElementById('fileView');
  view.replaceChildren();
  const st=fileState[activeFile];
  if(!st)return;
  st.lines.forEach(l=>{
    const span=el('span','ln'+(l.cls?(' '+l.cls):''),l.text+'\n');
    if(l.color)span.style.color=l.color;
    view.appendChild(span);
  });
}
```

- [ ] **Step 2: Diff before→after by line, color changed lines**

```javascript
function applyFileChange(d){
  ensureTab(d.path);
  const before=(d.before==null?'':d.before).split('\n');
  const after=(d.after==null?'':d.after).split('\n');
  const cls=d.kind==='damage'?'damage':(d.kind==='restore'?'':'heal');
  const color=d.kind==='heal'?(COLORS[fileChangeAgent]||null):null;
  const lines=after.map((text,i)=>{
    const changed=before[i]!==text;
    return changed?{text,cls,color}:{text,cls:'',color:null};
  });
  fileState[d.path].lines=lines;
  if(activeFile===d.path||activeFile==null){activeFile=d.path;renderFile();}
}
```

Note: capture the emitting agent for heal color. In `handle(ev)` set a module var before calling: `fileChangeAgent=ev.from_agent;`. (Damage is always red via the `.damage` class; heal uses the healing agent's color so different healers are visually distinct.)

- [ ] **Step 3: Hook into the websocket handler**

In `handle(ev)`, add near the top (after `logEvent(ev)` is fine, but before the wire/graph logic so FILE_CHANGED doesn't try to draw graph wires):

```javascript
  if(ev.type==='FILE_CHANGED'){
    fileChangeAgent=ev.from_agent;
    applyFileChange(ev.data);
    return;   // file events don't animate the agent graph
  }
```

Declare `let fileChangeAgent='chaos';` with the other top-level lets.

- [ ] **Step 4: Reset file view on SYSTEM_RESET**

In `resetUI()`, add:

```javascript
  Object.keys(fileState).forEach(k=>delete fileState[k]);
  activeFile=null;
  document.getElementById('fileTabs').replaceChildren();
  document.getElementById('fileView').replaceChildren();
```

- [ ] **Step 5: Verify live with Playwright (mock mode, free)**

Run the full app with the scheduler ON and fast timings so chaos fires quickly:

```bash
DEMO_FAST=1 python -m uvicorn main:app --port 8000   # background
```

Navigate to the dashboard, switch to FILES, wait for a chaos burst, screenshot. Expected: `weather_source.json` tab appears, damaged lines render in red; after the heal chain runs, repaired lines render in the patch color; on incident close the restore repaints to neutral. Capture screenshots at damage and at heal to confirm both colors. Iterate until both states are visibly correct.

- [ ] **Step 6: Commit**

```bash
git add dashboard/index.html
git commit -m "feat(ui): live per-file diff coloring from FILE_CHANGED stream"
```

---

### Task 3: Polish — multi-file tabs, pipeline.py, unhealed persistence

**Files:** Modify `dashboard/index.html`

- [ ] **Step 1: Confirm pipeline.py changes also surface**

When AI chaos edits `pipeline.py`, a second tab must appear automatically (handled by `ensureTab`). Verify in AI mode OR by manually emitting a FILE_CHANGED for `pipeline.py` via the browser console:

```javascript
applyFileChange({path:'pipeline.py',kind:'damage',before:'def run():\n  pass',after:'def run(:\n  pass'});
```

Screenshot: a `pipeline.py` tab appears, the broken line is red.

- [ ] **Step 2: Confirm unhealed damage persists**

Simulate an escalation: emit a damage change, then an INCIDENT_CLOSED with `resolved:false` and NO heal/restore. The red line must remain on screen (it only clears on a `restore` or a new `damage`/`heal` overwriting it). Verify via console + screenshot.

- [ ] **Step 3: Final pass**

Run the app in DEMO_FAST mock mode, watch several full incidents in the Files view, screenshot a damage frame and a healed frame. Confirm: tabs for both files, red on damage, agent-color on heal, neutral after restore, no console errors (`browser_console_messages`).

- [ ] **Step 4: Commit**

```bash
git add dashboard/index.html
git commit -m "feat(ui): multi-file tabs, pipeline.py viewer, persistent unhealed damage"
```

---

## Self-Review Notes

- **Spec coverage:** dedicated sub-tab/screen (T1), live raw-text render (T2), damage=red / heal=agent-color / restore=neutral (T2), any changed file visualizable incl. pipeline.py (T3), unhealed red persists (T3). Colors stay browser-only (consume Phase 1 events; backend never sends color).
- **Diff is line-positional** (simple, good enough for these mutations). If a future dataset shifts every line, revisit with a real LCS diff — deferred (YAGNI).
- **Verification** is screenshot-based per task; the mock path emitting FILE_CHANGED (Phase 1) makes this testable without API spend.
