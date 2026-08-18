"""Live output dashboard for run_benchmark trials.

Reads output/trials_<slug>/ directories, exposes them as JSON at /api/runs,
and serves a single-page dashboard at / that auto-refreshes every 3 seconds.

    python dashboard.py                # scans ./output on port 8080
    python dashboard.py --port 9090 --dir output_all
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

OUTPUT_DIR = Path("output")
_TRIALS_PREFIX = "trials_"


def _load(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _mtime(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def _iter_task_dirs(root: Path):
    # Documents/complex-mcp writes one trials_<slug>/ directly under output/.
    # Top-level pass_summary.json, report.md, summary.json are global rollups and skipped.
    for p in sorted(root.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.is_dir() and p.name.startswith(_TRIALS_PREFIX):
            yield p


def _collect_runs():
    if not OUTPUT_DIR.exists():
        return []
    out = []
    for run_root in _iter_task_dirs(OUTPUT_DIR):
        summary = _load(run_root / "summary.json") or {}
        metrics = summary.get("metrics", {}) if isinstance(summary, dict) else {}
        traj_dir = run_root / "trajectories"
        model = "?"
        run_dirs = []
        if traj_dir.exists():
            for model_dir in traj_dir.iterdir():
                if not model_dir.is_dir():
                    continue
                model = model_dir.name
                for r in sorted(model_dir.iterdir()):
                    if r.is_dir() and r.name.startswith("run_"):
                        run_dirs.append(r)
        latest_run = run_dirs[-1] if run_dirs else None
        reward_json = _load(latest_run / "verifier" / "reward.json") if latest_run else None
        top_reward = _load(latest_run / "reward.json") if latest_run else None
        report_json = _load(latest_run / "report.json") if latest_run else None
        # Reward preference: verifier/reward.json → top-level reward.json → report_json → summary avg
        reward = None
        for src in (reward_json, top_reward, report_json):
            if isinstance(src, dict) and src.get("reward") is not None:
                reward = src.get("reward"); break
        if reward is None:
            attempts = summary.get("attempts") or []
            rewards = [a.get("reward") for a in attempts if isinstance(a, dict) and a.get("reward") is not None]
            if rewards:
                reward = sum(rewards) / len(rewards)
        stem = run_root.name
        display = stem[len(_TRIALS_PREFIX):] if stem.startswith(_TRIALS_PREFIX) else stem
        task = summary.get("task") or (report_json or {}).get("task") or display
        first_fail = next((a for a in (summary.get("attempts") or []) if isinstance(a, dict) and not a.get("passed")), None)
        out.append({
            "id": stem,
            "task": task,
            "display": display,
            "model": summary.get("model") or (report_json or {}).get("model") or model,
            "started_at": _mtime(run_root),
            "finished_at": _mtime(latest_run) if latest_run else None,
            "n_attempts": metrics.get("n") or len(summary.get("attempts") or []) or len(run_dirs),
            "reward": reward,
            "passed": bool(reward == 1.0) if reward is not None else None,
            "grader": (reward_json or top_reward or {}).get("grader"),
            "quadrant": (report_json or {}).get("quadrant") or (reward_json or {}).get("quadrant"),
            "completion_rate": (report_json or {}).get("completion_rate") or (reward_json or {}).get("completion_rate"),
            "misbehaving_rate": (report_json or {}).get("misbehaving_rate") or (reward_json or {}).get("misbehaving_rate"),
            "pass_at_1": metrics.get("pass@1"),
            "pass_at_k": metrics.get("pass@k"),
            "failure_class": (first_fail or {}).get("failure_class"),
            "graph_f1": (reward_json or {}).get("graph_f1"),
            "rubric_score": (reward_json or {}).get("rubric_score") or (report_json or {}).get("rubric_weights_percentage"),
            "tests_percentage": (report_json or {}).get("test_weights_percentage"),
            "valid_tool_calls": (report_json or {}).get("tool_summary", {}).get("valid_tool_calls"),
            "invalid_tool_calls": (report_json or {}).get("tool_summary", {}).get("invalid_tool_calls"),
            "error_tool_calls": (report_json or {}).get("tool_summary", {}).get("error_tool_calls"),
            "prompt_tokens": (report_json or {}).get("tokens", {}).get("prompt"),
            "llm_tokens": (report_json or {}).get("tokens", {}).get("llm"),
            "tool_tokens": (report_json or {}).get("tokens", {}).get("tool"),
            "path": str(run_root),
        })
    return out


def _run_detail(run_id: str):
    run_root = OUTPUT_DIR / run_id
    if not run_root.exists():
        return None
    traj_dir = run_root / "trajectories"
    summary = _load(run_root / "summary.json") or {}
    failure_analysis = _load(run_root / "failure_analysis.json") or {}
    result = {
        "id": run_id,
        "path": str(run_root),
        "summary": summary,
        "failure_analysis": failure_analysis,
        "runs": [],
    }
    if traj_dir.exists():
        for model_dir in traj_dir.iterdir():
            if not model_dir.is_dir():
                continue
            for r in sorted(model_dir.iterdir()):
                if not (r.is_dir() and r.name.startswith("run_")):
                    continue
                traj = _load(r / "agent" / "trajectory.json") or {}
                steps = []
                if isinstance(traj, dict):
                    raw = traj.get("steps") or traj.get("trajectory") or []
                    for i, s in enumerate(raw[:100]):
                        if not isinstance(s, dict):
                            continue
                        steps.append({
                            "step": i + 1,
                            "tool": s.get("tool") or s.get("tool_name"),
                            "arguments": s.get("arguments") or s.get("args"),
                            "response": str(s.get("response") or s.get("result") or "")[:400],
                        })
                result["runs"].append({
                    "run": r.name,
                    "model": model_dir.name,
                    "reward": _load(r / "verifier" / "reward.json") or _load(r / "reward.json"),
                    "report": _load(r / "report.json"),
                    "diagnosis": _load(r / "diagnosis.json"),
                    "steps": steps,
                    "final_message": (traj or {}).get("final_message") if isinstance(traj, dict) else None,
                })
    return result


INDEX_HTML = r"""<!doctype html>
<html lang="en" class="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ComplexMCP · Dashboard</title>
<script src="https://cdn.tailwindcss.com"></script>
<script>tailwind.config={theme:{extend:{colors:{brand:'#7c3aed',ink:'#0b0f19',panel:'#0f172a',border:'#1e293b'}}}}</script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
  :root{color-scheme:dark}
  html,body{background:#050810;color:#e2e8f0;font-family:'Inter',ui-sans-serif,system-ui,-apple-system,sans-serif}
  .mono{font-family:'JetBrains Mono',ui-monospace,monospace}
  .glass{background:linear-gradient(180deg,rgba(15,23,42,.72),rgba(11,15,25,.72));backdrop-filter:blur(12px);border:1px solid rgba(148,163,184,.08)}
  .card-hover{transition:all .2s cubic-bezier(.4,0,.2,1)}
  .card-hover:hover{transform:translateY(-2px);border-color:rgba(124,58,237,.4);box-shadow:0 8px 24px -12px rgba(124,58,237,.3)}
  .card-hover.selected{border-color:#7c3aed;background:linear-gradient(180deg,rgba(124,58,237,.12),rgba(15,23,42,.72))}
  .pulse-dot{width:8px;height:8px;border-radius:50%;background:#10b981;box-shadow:0 0 0 0 rgba(16,185,129,.7);animation:pulse 2s infinite}
  @keyframes pulse{0%{box-shadow:0 0 0 0 rgba(16,185,129,.7)}70%{box-shadow:0 0 0 8px rgba(16,185,129,0)}100%{box-shadow:0 0 0 0 rgba(16,185,129,0)}}
  .fade-in{animation:fadeIn .3s ease-out}
  @keyframes fadeIn{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:translateY(0)}}
  .slide-in{animation:slideIn .35s cubic-bezier(.4,0,.2,1)}
  @keyframes slideIn{from{opacity:0;transform:translateX(16px)}to{opacity:1;transform:translateX(0)}}
  .grad-text{background:linear-gradient(135deg,#a78bfa 0%,#818cf8 50%,#38bdf8 100%);-webkit-background-clip:text;background-clip:text;color:transparent}
  .scrollbar::-webkit-scrollbar{width:8px;height:8px}
  .scrollbar::-webkit-scrollbar-thumb{background:#1e293b;border-radius:4px}
  .scrollbar::-webkit-scrollbar-thumb:hover{background:#334155}
  .scrollbar::-webkit-scrollbar-track{background:transparent}
  .tab-btn{padding:8px 14px;border-radius:8px;font-size:12px;font-weight:500;color:#64748b;transition:all .15s}
  .tab-btn:hover{color:#cbd5e1;background:rgba(30,41,59,.5)}
  .tab-btn.active{color:#a78bfa;background:rgba(124,58,237,.12)}
  .badge{display:inline-flex;align-items:center;gap:4px;padding:3px 8px;border-radius:6px;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.5px}
  .b-solved{background:rgba(16,185,129,.15);color:#34d399;border:1px solid rgba(16,185,129,.3)}
  .b-failed{background:rgba(239,68,68,.15);color:#f87171;border:1px solid rgba(239,68,68,.3)}
  .b-plan{background:rgba(245,158,11,.15);color:#fbbf24;border:1px solid rgba(245,158,11,.3)}
  .b-brute{background:rgba(59,130,246,.15);color:#60a5fa;border:1px solid rgba(59,130,246,.3)}
  .b-exec{background:rgba(236,72,153,.15);color:#f472b6;border:1px solid rgba(236,72,153,.3)}
  .prog{height:6px;background:#1e293b;border-radius:3px;overflow:hidden}
  .prog>div{height:100%;border-radius:3px;transition:width .4s cubic-bezier(.4,0,.2,1)}
  .bg-gradient-mesh{background:radial-gradient(at 20% 0%,rgba(124,58,237,.12) 0px,transparent 50%),radial-gradient(at 80% 100%,rgba(56,189,248,.08) 0px,transparent 50%)}
</style>
</head>
<body class="bg-gradient-mesh min-h-screen">

<header class="glass sticky top-0 z-40">
  <div class="max-w-[1600px] mx-auto px-6 py-3 flex items-center justify-between">
    <div class="flex items-center gap-6">
      <div class="flex items-center gap-2.5">
        <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-purple-500 to-blue-500 flex items-center justify-center text-white font-bold text-sm">C</div>
        <div>
          <h1 class="text-sm font-semibold grad-text">ComplexMCP</h1>
          <div class="text-[10px] text-slate-500 -mt-0.5">Live Trajectory Dashboard</div>
        </div>
      </div>
      <div class="hidden md:flex items-center gap-4 pl-6 border-l border-slate-800">
        <div class="flex items-center gap-2"><span class="pulse-dot"></span><span class="text-xs text-slate-400">Live</span></div>
        <div class="text-xs text-slate-500">refreshes in <span id="countdown" class="mono text-slate-300">3s</span></div>
      </div>
    </div>
    <div class="flex items-center gap-3">
      <input id="filter" type="search" placeholder="Filter tasks..." class="w-64 px-3 py-1.5 bg-panel/60 border border-border rounded-lg text-xs placeholder:text-slate-600 focus:outline-none focus:border-brand/60">
      <button id="refresh" class="px-3 py-1.5 bg-panel/60 border border-border rounded-lg text-xs text-slate-400 hover:text-slate-200 hover:border-brand/40">Refresh</button>
    </div>
  </div>
</header>

<div class="max-w-[1600px] mx-auto px-6 pt-5">
  <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
    <div class="glass rounded-xl p-4"><div class="text-[10px] text-slate-500 uppercase tracking-wider">Total Tasks</div><div class="text-2xl font-semibold mt-1 mono" id="m-total">—</div></div>
    <div class="glass rounded-xl p-4"><div class="text-[10px] text-slate-500 uppercase tracking-wider">Passed</div><div class="text-2xl font-semibold mt-1 mono text-emerald-400" id="m-passed">—</div></div>
    <div class="glass rounded-xl p-4"><div class="text-[10px] text-slate-500 uppercase tracking-wider">Avg Reward</div><div class="text-2xl font-semibold mt-1 mono grad-text" id="m-avg">—</div></div>
    <div class="glass rounded-xl p-4"><div class="text-[10px] text-slate-500 uppercase tracking-wider">Total Tokens</div><div class="text-2xl font-semibold mt-1 mono text-slate-300" id="m-tokens">—</div></div>
  </div>
</div>

<main class="max-w-[1600px] mx-auto px-6 py-5 grid grid-cols-1 lg:grid-cols-[440px_1fr] gap-4">
  <section class="glass rounded-xl overflow-hidden flex flex-col" style="min-height:calc(100vh - 190px)">
    <div class="px-4 py-3 border-b border-border/60 flex items-center justify-between">
      <h2 class="text-xs font-semibold text-slate-300 uppercase tracking-wider">Tasks</h2>
      <span id="run-count" class="text-xs text-slate-500 mono">0</span>
    </div>
    <div id="rows" class="flex-1 overflow-auto scrollbar p-3 space-y-2">
      <div class="text-center py-16 text-slate-600 text-sm">Loading…</div>
    </div>
  </section>

  <section class="glass rounded-xl overflow-hidden flex flex-col" style="min-height:calc(100vh - 190px)">
    <div class="px-5 py-3 border-b border-border/60 flex items-center justify-between gap-3">
      <div id="detail-title" class="min-w-0 flex-1">
        <div class="text-xs text-slate-500">No task selected</div>
        <div class="text-sm font-semibold text-slate-300 truncate mono">—</div>
      </div>
      <div class="flex gap-1" id="tabs">
        <button data-tab="overview" class="tab-btn active">Overview</button>
        <button data-tab="trajectory" class="tab-btn">Trajectory</button>
        <button data-tab="reward" class="tab-btn">Reward</button>
        <button data-tab="raw" class="tab-btn">Raw</button>
      </div>
    </div>
    <div id="detail" class="flex-1 overflow-auto scrollbar p-5">
      <div class="flex flex-col items-center justify-center h-full text-slate-600">
        <div class="w-16 h-16 rounded-2xl bg-panel/60 flex items-center justify-center mb-4"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M9 12h6M9 16h6M9 8h6M5 4h14a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V6a2 2 0 012-2z"/></svg></div>
        <div class="text-sm">Select a task to inspect its trajectory</div>
        <div class="text-xs text-slate-700 mt-1">Data auto-refreshes every 3 seconds</div>
      </div>
    </div>
  </section>
</main>

<script>
let runs=[],selected=null,activeTab='overview',filterText='',tickLeft=3;
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[<>&]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]));
const fmtAge=iso=>{if(!iso)return'';const d=(Date.now()-new Date(iso).getTime())/1000;if(d<60)return`${Math.floor(d)}s ago`;if(d<3600)return`${Math.floor(d/60)}m ago`;if(d<86400)return`${Math.floor(d/3600)}h ago`;return`${Math.floor(d/86400)}d ago`};
const fmtN=n=>n==null?'—':(typeof n==='number'?(Number.isInteger(n)?n.toLocaleString():n.toFixed(3)):n);
const fmtT=n=>n==null?'—':(n>=1e6?(n/1e6).toFixed(2)+'M':n>=1e3?(n/1e3).toFixed(1)+'k':Math.round(n));
const rewardCls=r=>r==null?'text-slate-500':(r>=0.8?'text-emerald-400':r>=0.3?'text-amber-400':'text-rose-400');
const rewardBg=r=>r==null?'#334155':(r>=0.8?'#10b981':r>=0.3?'#f59e0b':'#ef4444');
const qBadge=q=>{const cls={SOLVED:'b-solved',FAILED:'b-failed',PLAN_ONLY:'b-plan',BRUTE_FORCE:'b-brute',EXECUTION_FAIL:'b-exec'}[q]||'b-plan';return `<span class="badge ${cls}">${q}</span>`};

function renderMetrics(){
  const passed=runs.filter(r=>r.reward!=null&&r.reward>=0.8).length;
  const withReward=runs.filter(r=>r.reward!=null);
  const avg=withReward.length?withReward.reduce((a,r)=>a+r.reward,0)/withReward.length:null;
  const tot=runs.reduce((a,r)=>a+(r.prompt_tokens||0)+(r.llm_tokens||0)+(r.tool_tokens||0),0);
  $('m-total').textContent=runs.length;
  $('m-passed').textContent=`${passed} / ${runs.length}`;
  $('m-avg').textContent=avg==null?'—':avg.toFixed(3);
  $('m-tokens').textContent=fmtT(tot);
}

function renderRows(){
  const list=runs.filter(r=>!filterText||(r.task||'').toLowerCase().includes(filterText)||(r.model||'').toLowerCase().includes(filterText)||(r.display||'').toLowerCase().includes(filterText));
  $('run-count').textContent=`${list.length} of ${runs.length}`;
  const el=$('rows');
  if(!list.length){el.innerHTML=`<div class="text-center py-16 text-slate-600 text-sm">No tasks match. Try clearing the filter.</div>`;return}
  el.innerHTML=list.map(r=>{
    const rew=r.reward;
    const barW=rew==null?0:Math.min(100,Math.max(0,rew*100));
    const short=(r.task||r.display||'').split('/').pop();
    return `<div class="card-hover glass rounded-lg p-3 cursor-pointer ${r.id===selected?'selected':''}" data-id="${r.id}">
      <div class="flex items-start justify-between gap-2">
        <div class="min-w-0 flex-1">
          <div class="text-sm font-medium text-slate-200 truncate">${esc(short)}</div>
          <div class="text-[11px] text-slate-500 mono truncate mt-0.5">${esc(r.model||'—')}</div>
        </div>
        ${r.quadrant?qBadge(r.quadrant):(r.failure_class?`<span class="badge b-failed">${esc(r.failure_class)}</span>`:'')}
      </div>
      <div class="mt-3 flex items-center gap-3">
        <div class="flex-1 prog"><div style="width:${barW}%;background:${rewardBg(rew)}"></div></div>
        <div class="text-xs mono font-semibold ${rewardCls(rew)}">${fmtN(rew)}</div>
      </div>
      <div class="mt-2.5 flex items-center justify-between text-[11px] text-slate-500 mono">
        <span>${r.valid_tool_calls!=null?r.valid_tool_calls+' tools':'—'}</span>
        <span>${r.n_attempts||1}× · ${fmtAge(r.finished_at||r.started_at)}</span>
      </div>
    </div>`}).join('');
  el.querySelectorAll('[data-id]').forEach(node=>node.onclick=()=>{selected=node.dataset.id;renderRows();loadDetail(selected)});
}

function renderDetailHeader(id){
  const r=runs.find(x=>x.id===id);if(!r)return;
  $('detail-title').innerHTML=`<div class="text-[10px] text-slate-500 uppercase tracking-wider">Task · <button class="hover:text-slate-300 mono" onclick="navigator.clipboard.writeText('${esc(r.path)}')">${esc(r.path)}</button></div><div class="text-sm font-semibold text-slate-100 truncate mono">${esc(r.task)}</div>`;
}

function tabOverview(d,r){
  const rewards=d.runs.map(x=>(x.reward||{}).reward).filter(x=>x!=null);
  const avgR=rewards.length?rewards.reduce((a,b)=>a+b,0)/rewards.length:null;
  return `<div class="grid grid-cols-1 md:grid-cols-2 gap-4">
    <div class="glass rounded-xl p-5">
      <h3 class="text-[10px] uppercase tracking-wider text-slate-500 mb-3">Summary</h3>
      <div class="space-y-3">
        <div class="flex justify-between"><span class="text-xs text-slate-400">Task</span><span class="text-xs mono text-slate-200 truncate ml-4">${esc(r.task)}</span></div>
        <div class="flex justify-between"><span class="text-xs text-slate-400">Model</span><span class="text-xs mono text-slate-200">${esc(r.model||'—')}</span></div>
        <div class="flex justify-between"><span class="text-xs text-slate-400">Attempts</span><span class="text-xs mono text-slate-200">${d.runs.length}</span></div>
        <div class="flex justify-between"><span class="text-xs text-slate-400">Avg Reward</span><span class="text-xs mono font-semibold ${rewardCls(avgR)}">${fmtN(avgR)}</span></div>
        <div class="flex justify-between"><span class="text-xs text-slate-400">Pass@1</span><span class="text-xs mono text-slate-200">${fmtN(r.pass_at_1)}</span></div>
        ${r.failure_class?`<div class="flex justify-between"><span class="text-xs text-slate-400">Failure class</span><span class="badge b-failed">${esc(r.failure_class)}</span></div>`:''}
      </div>
    </div>
    <div class="glass rounded-xl p-5">
      <h3 class="text-[10px] uppercase tracking-wider text-slate-500 mb-3">Tool Usage</h3>
      <div class="space-y-3">
        <div class="flex justify-between items-center"><span class="text-xs text-slate-400">Valid calls</span><span class="text-xs mono text-emerald-400 font-semibold">${fmtN(r.valid_tool_calls)}</span></div>
        <div class="flex justify-between items-center"><span class="text-xs text-slate-400">Invalid</span><span class="text-xs mono text-amber-400">${fmtN(r.invalid_tool_calls)}</span></div>
        <div class="flex justify-between items-center"><span class="text-xs text-slate-400">Errored</span><span class="text-xs mono text-rose-400">${fmtN(r.error_tool_calls)}</span></div>
      </div>
      <h3 class="text-[10px] uppercase tracking-wider text-slate-500 mt-5 mb-3">Tokens</h3>
      <div class="space-y-3">
        <div class="flex justify-between items-center"><span class="text-xs text-slate-400">Prompt</span><span class="text-xs mono text-slate-200">${fmtT(r.prompt_tokens)}</span></div>
        <div class="flex justify-between items-center"><span class="text-xs text-slate-400">LLM</span><span class="text-xs mono text-slate-200">${fmtT(r.llm_tokens)}</span></div>
        <div class="flex justify-between items-center"><span class="text-xs text-slate-400">Tool</span><span class="text-xs mono text-slate-200">${fmtT(r.tool_tokens)}</span></div>
      </div>
    </div>
    <div class="glass rounded-xl p-5 md:col-span-2">
      <h3 class="text-[10px] uppercase tracking-wider text-slate-500 mb-3">Attempts</h3>
      <div class="space-y-2">
        ${d.runs.map(x=>{const rw=(x.reward||{}).reward;const bw=rw==null?0:Math.min(100,rw*100);return `<div class="flex items-center gap-3 py-1.5">
          <span class="text-[11px] mono text-slate-500 w-16">${esc(x.run)}</span>
          <div class="flex-1 prog"><div style="width:${bw}%;background:${rewardBg(rw)}"></div></div>
          <span class="text-xs mono font-semibold ${rewardCls(rw)} w-16 text-right">${fmtN(rw)}</span>
          ${x.diagnosis&&x.diagnosis.failure_class?`<span class="badge b-failed">${esc(x.diagnosis.failure_class)}</span>`:'<span class="w-16"></span>'}
        </div>`}).join('')}
      </div>
    </div>
  </div>`;
}

function tabTrajectory(d){
  return d.runs.map(run=>{
    const steps=run.steps||[];
    return `<div class="mb-6">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm font-semibold text-slate-200">${esc(run.run)} · ${esc(run.model)}</h3>
        <span class="text-xs mono text-slate-500">${steps.length} steps</span>
      </div>
      ${run.final_message?`<div class="glass rounded-lg p-4 mb-4"><div class="text-[10px] uppercase tracking-wider text-slate-500 mb-2">Final Message</div><div class="text-xs text-slate-300 whitespace-pre-wrap mono">${esc((run.final_message||'').slice(0,1500))}</div></div>`:''}
      <div class="space-y-2">
        ${steps.map(s=>`<div class="glass rounded-lg p-3 fade-in">
          <div class="flex items-baseline gap-3 mb-2">
            <span class="text-[10px] mono text-slate-600 w-6 text-right">${s.step}</span>
            <span class="text-xs mono text-purple-400 font-semibold">${esc(s.tool||'?')}</span>
          </div>
          ${s.arguments&&Object.keys(s.arguments).length?`<div class="ml-9 text-[11px] mono text-slate-500 whitespace-pre-wrap break-all mb-1">args: ${esc(JSON.stringify(s.arguments).slice(0,400))}</div>`:''}
          ${s.response?`<div class="ml-9 text-[11px] mono text-slate-400 whitespace-pre-wrap break-all">→ ${esc((s.response||'').slice(0,500))}</div>`:''}
        </div>`).join('')||'<div class="text-slate-600 text-sm text-center py-8">No trajectory steps recorded.</div>'}
      </div>
    </div>`}).join('');
}

function tabReward(d){
  return d.runs.map(run=>{
    const rw=run.reward||{};
    const rep=run.report||{};
    return `<div class="mb-5 glass rounded-xl p-5 slide-in">
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-sm font-semibold text-slate-200">${esc(run.run)}</h3>
        <div class="text-2xl mono font-bold ${rewardCls(rw.reward)}">${fmtN(rw.reward)}</div>
      </div>
      <div class="prog mb-5"><div style="width:${(rw.reward||0)*100}%;background:${rewardBg(rw.reward)}"></div></div>
      <div class="grid grid-cols-2 md:grid-cols-3 gap-4">
        <div><div class="text-[10px] uppercase text-slate-500">Grader</div><div class="text-xs mono text-slate-300 mt-1">${esc(rw.grader||'—')}</div></div>
        <div><div class="text-[10px] uppercase text-slate-500">Completion</div><div class="text-xs mono text-slate-300 mt-1">${fmtN(rep.completion_rate!=null?rep.completion_rate:rw.completion_rate)}</div></div>
        <div><div class="text-[10px] uppercase text-slate-500">Misbehave</div><div class="text-xs mono text-slate-300 mt-1">${fmtN(rep.misbehaving_rate!=null?rep.misbehaving_rate:rw.misbehaving_rate)}</div></div>
        <div><div class="text-[10px] uppercase text-slate-500">Graph F1</div><div class="text-xs mono text-slate-300 mt-1">${fmtN(rw.graph_f1)}</div></div>
        <div><div class="text-[10px] uppercase text-slate-500">Rubric</div><div class="text-xs mono text-slate-300 mt-1">${fmtN(rw.rubric_score!=null?rw.rubric_score:rep.rubric_weights_percentage)}</div></div>
        <div><div class="text-[10px] uppercase text-slate-500">Tests %</div><div class="text-xs mono text-slate-300 mt-1">${fmtN(rep.test_weights_percentage)}</div></div>
      </div>
      ${run.diagnosis&&run.diagnosis.failure_class?`<div class="mt-5 p-4 rounded-lg bg-rose-500/5 border border-rose-500/20">
        <div class="text-[10px] uppercase text-rose-400 mb-2">Diagnosis</div>
        <div class="text-xs text-slate-300"><span class="mono text-rose-300">${esc(run.diagnosis.failure_class)}</span> — ${esc(run.diagnosis.reason||'')}</div>
      </div>`:''}
    </div>`}).join('');
}

function tabRaw(d){
  return `<div class="glass rounded-xl p-5"><pre class="text-[11px] mono text-slate-400 overflow-auto scrollbar" style="max-height:70vh">${esc(JSON.stringify(d,null,2))}</pre></div>`;
}

async function loadDetail(id){
  renderDetailHeader(id);
  const r=await fetch(`/api/runs/${encodeURIComponent(id)}`);const d=await r.json();
  const meta=runs.find(x=>x.id===id)||{};
  const renderers={overview:()=>tabOverview(d,meta),trajectory:()=>tabTrajectory(d),reward:()=>tabReward(d),raw:()=>tabRaw(d)};
  $('detail').innerHTML=(renderers[activeTab]||renderers.overview)();
}

async function loadList(){
  try{const r=await fetch('/api/runs');runs=await r.json();renderMetrics();renderRows();if(selected)loadDetail(selected);}
  catch(e){console.error(e)}
}

document.querySelectorAll('.tab-btn').forEach(b=>b.onclick=()=>{document.querySelectorAll('.tab-btn').forEach(x=>x.classList.remove('active'));b.classList.add('active');activeTab=b.dataset.tab;if(selected)loadDetail(selected)});
$('filter').oninput=e=>{filterText=e.target.value.toLowerCase();renderRows()};
$('refresh').onclick=()=>{loadList();tickLeft=3};

loadList();
setInterval(()=>{tickLeft--;if(tickLeft<=0){loadList();tickLeft=3}$('countdown').textContent=tickLeft+'s'},1000);
</script>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            self._send(200, INDEX_HTML.encode(), "text/html; charset=utf-8")
        elif u.path == "/api/runs":
            body = json.dumps(_collect_runs(), default=str).encode()
            self._send(200, body, "application/json")
        elif u.path.startswith("/api/runs/"):
            run_id = u.path[len("/api/runs/"):]
            d = _run_detail(run_id)
            body = json.dumps(d or {}, default=str).encode()
            self._send(200 if d else 404, body, "application/json")
        else:
            self._send(404, b"not found", "text/plain")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dir", default="output", help="Output directory to watch (default: output)")
    p.add_argument("--port", type=int, default=8080)
    args = p.parse_args()
    global OUTPUT_DIR
    OUTPUT_DIR = Path(args.dir)
    print(f"Dashboard: http://127.0.0.1:{args.port}  (watching {OUTPUT_DIR.resolve()})")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
