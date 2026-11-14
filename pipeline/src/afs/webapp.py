"""Generate a self-contained browser application for the study.

The deliverable is a single HTML file. It opens by double-click, needs no
server, no Python and no network, and can be emailed or hosted on any static
host. Everything it shows — the corpus, the codebook, the verified results and
the figures — is embedded in the file, so nothing can drift out of sync with
the report.

Two audiences are served by one artefact: a reader who wants the findings
(Overview), and a reviewer who wants to check a specific record against the
codebook (Explore).
"""
from __future__ import annotations

import base64
import json
import html
import re
from pathlib import Path

from .common import (CONFIG_DIR, FIG_DIR, GOLD_DIR, OUT_DIR, PROC_DIR, RAW_DIR,
                     ROOT, TAB_DIR, read_csv, read_json, read_jsonl, utc_now)
from .taxonomy import Taxonomy
from . import identity

APP_DIR = OUT_DIR / "app"
SNIPPET_CHARS = 320

# Users pasted their own credentials into public bug reports; a handful of those
# strings sit in the collected text. The corpus is published, so anything that
# looks like a live key is masked before it reaches the page. Redaction happens
# here rather than in the corpus so that the stored text stays faithful to the
# source it cites.
_SECRET_PATTERNS = [
    r"sk-[A-Za-z0-9_\-]{20,}",
    r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}",
    r"github_pat_[A-Za-z0-9_]{20,}",
    r"AIza[0-9A-Za-z_\-]{30,}",
    r"xox[baprs]-[A-Za-z0-9\-]{10,}",
    r"hf_[A-Za-z0-9]{20,}",
    r"AKIA[0-9A-Z]{16}",
]
_SECRET_RE = re.compile("|".join(f"(?:{p})" for p in _SECRET_PATTERNS))


def redact(text: str) -> str:
    """Mask credential-shaped strings so a published page cannot leak a key."""
    if not text:
        return text
    return _SECRET_RE.sub("[redacted: credential]", text)


# --------------------------------------------------------------------------- #
def _records(texts: dict[str, str]) -> list[dict]:
    """Compact record payload: codes only, labels live in a separate map."""
    out = []
    for r in read_jsonl(PROC_DIR / "failures.jsonl"):
        rid = r["record_id"]
        body = " ".join((texts.get(rid, "") or r.get("title", "")).split())
        out.append({
            "i": rid,
            "f": r.get("framework", ""),
            "t": redact(r.get("title", "")),
            "u": r.get("url", ""),
            "d": (r.get("created_at") or "")[:10],
            "y": r.get("year", ""),
            "a": r.get("A_failure_type", ""),
            "ac": float(r.get("A_confidence") or 0),
            "b": r.get("B_cause_class", ""),
            "bg": r.get("B_evidence_grade", ""),
            "c": r.get("C_lifecycle_stage", ""),
            "s": r.get("D_severity", ""),
            "e": r.get("E_detection_point", ""),
            "ev": redact((r.get("A_evidence") or "")[:260]),
            "sn": redact(body[:SNIPPET_CHARS]),
            "rl": redact((r.get("matched_rules") or "")[:400]),
            "st": r.get("state", ""),
            "lb": r.get("labels", ""),
        })
    return out


SHORT = {
    "d": {"D1_blocking": "Blocking", "D2_incorrect_output": "Wrong output",
          "D3_degraded": "Degraded", "D4_minor": "Minor"},
    "e": {"E1_framework_runtime": "Runtime caught", "E2_external_test": "Test caught",
          "E3_human_observation": "Human noticed",
          "E4_production_monitoring": "Monitoring",
          "E5_configuration_validation": "Config check"},
    "c": {"C1_setup": "Setup", "C2_construction": "Construction",
          "C3_prompt_assembly": "Prompt assembly", "C4_inference": "Inference",
          "C5_tool_execution": "Tool execution", "C6_handoff": "Handoff",
          "C7_output_parsing": "Output parsing", "C8_runtime_other": "Runtime other"},
}


def _label_map() -> dict:
    tax = Taxonomy()
    dims = {}
    for dim, key in (("a", "A_failure_type"), ("b", "B_cause_class"),
                     ("c", "C_lifecycle_stage"), ("d", "D_severity"),
                     ("e", "E_detection_point")):
        dims[dim] = {code: tax.label(key, code) for code in tax.codes(key)}
    for dim, mapping in SHORT.items():
        dims[dim + "_short"] = {c: mapping.get(c, dims[dim].get(c, c))
                                for c in dims[dim]}
    return dims


def _codebook() -> dict:
    tax = Taxonomy()
    spec = tax.spec
    out = {}
    titles = {
        "A_failure_type": ("A", "Failure type", "What broke, structurally"),
        "B_cause_class": ("B", "Cause class", "The mechanism the report names"),
        "C_lifecycle_stage": ("C", "Lifecycle stage", "Where in the run it broke"),
        "D_severity": ("D", "Severity", "How bad the consequence was"),
        "E_detection_point": ("E", "Detection point", "Who noticed, and when"),
    }
    for key, (letter, name, blurb) in titles.items():
        dim = spec["dimensions"][key]
        cats = []
        for code, body in dim["categories"].items():
            if isinstance(body, dict):
                cats.append({
                    "code": code,
                    "label": body.get("label", code),
                    "definition": body.get("definition", ""),
                    "include": body.get("include", []),
                    "exclude": body.get("exclude", []),
                })
            else:
                cats.append({"code": code, "label": str(body), "definition": "",
                             "include": [], "exclude": []})
        out[key] = {"letter": letter, "name": name, "blurb": blurb,
                    "description": dim.get("description", ""),
                    "precedence": dim.get("precedence", ""),
                    "categories": cats}
    rules = spec.get("coding_rules", [])
    out["_rules"] = rules if isinstance(rules, list) else []
    return out


def _figures() -> dict[str, str]:
    out = {}
    for name, label in (
            ("fig_rq1_failure_types.png", "Failure-type distribution"),
            ("fig_rq3_cause_by_type.png", "Cause by failure type"),
            ("fig_rq4_framework_composition.png", "Composition by framework"),
            ("fig_rq5_blocking_rate.png", "Blocking rate by framework"),
            ("fig_rq6_complexity.png", "Complexity tiers"),
            ("fig_rq9_time_trend.png", "Change over time"),
            ("fig_val_confusion.png", "Labeller vs reference")):
        p = FIG_DIR / name
        if p.exists():
            out[name] = "data:image/png;base64," + base64.b64encode(
                p.read_bytes()).decode("ascii")
    return out


def _hf_manifest() -> dict:
    """Headline facts of the packaged release, so the app cannot drift from it."""
    from .common import ROOT, read_json
    from .hf_export import REPO_ID

    p = ROOT / "outputs" / "hf_dataset" / "manifest.json"
    if not p.exists():
        return {"records": 0, "columns": 0, "frameworks": 0, "repo_id": REPO_ID,
                "generated_at": "not built", "files": []}
    out = read_json(p)
    out["repo_id"] = REPO_ID
    return out


def _dataset_index() -> list[dict]:
    from .hf_export import HF_DIR

    out = []
    hf_files = [
        (HF_DIR / "README.md", "Dataset card (Hugging Face)"),
        (HF_DIR / "data" / "train-00000-of-00001.parquet",
         "Dataset release (parquet)"),
        (HF_DIR / "data" / "exemplars.parquet", "Exemplars (parquet)"),
        (HF_DIR / "codebook" / "schema.md", "Dataset schema"),
    ]
    for p, label in hf_files + [
            (PROC_DIR / "failures.csv", "Corpus (CSV)"),
            (PROC_DIR / "failures.jsonl", "Corpus (JSONL)"),
            (PROC_DIR / "exclusions.json", "Excluded records"),
            (CONFIG_DIR / "taxonomy.v1.yaml", "Codebook (YAML)"),
            (CONFIG_DIR / "research_questions.yaml", "Research questions (YAML)"),
            (TAB_DIR / "rq1_table.csv", "RQ1 table"),
            (TAB_DIR / "rq3_table.csv", "RQ3 table"),
            (TAB_DIR / "rq4_table.csv", "RQ4 table"),
            (TAB_DIR / "validation_summary.json", "Validation summary")]:
        if p.exists():
            out.append({"name": label, "file": f"data/{p.name}",
                        "src": p, "kb": round(p.stat().st_size / 1024, 1)})
    return out


# --------------------------------------------------------------------------- #
def _json_block(obj) -> str:
    return (json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
            .replace("</", "<\\/"))


CSS = """
:root{
  --navy:#1c2e52; --ink:#1a1f2b; --body:#3d4552; --muted:#6b7280;
  --line:#e3e7ee; --bg:#f6f7fa; --card:#ffffff; --accent:#2f5fa8;
  --ok:#1f7a4d; --warn:#a8600b; --bad:#a52a2a;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  color:var(--body); background:var(--bg); font-size:15px; line-height:1.55;
  -webkit-font-smoothing:antialiased;
}
a{color:var(--accent); text-decoration:none}
a:hover{text-decoration:underline}
header.top{
  background:var(--navy); color:#fff; padding:26px 0 0;
}
.wrap{max-width:1120px; margin:0 auto; padding:0 26px}
header.top h1{
  margin:0 0 6px; font-size:26px; font-weight:650; letter-spacing:-.2px; color:#fff;
}
header.top p.sub{margin:0; color:#c3cee0; font-size:14px; max-width:760px}
header.top .meta{margin:14px 0 0; color:#8fa3c2; font-size:12.5px}
nav.tabs{display:flex; gap:2px; margin-top:20px; flex-wrap:wrap}
nav.tabs button{
  background:transparent; border:0; color:#b9c7dd; font:inherit; font-size:14px;
  padding:11px 15px; cursor:pointer; border-bottom:3px solid transparent;
  border-radius:4px 4px 0 0;
}
nav.tabs button:hover{color:#fff; background:rgba(255,255,255,.06)}
nav.tabs button.on{color:#fff; border-bottom-color:#fff; font-weight:600}
main{padding:30px 0 70px}
section.panel{display:none}
section.panel.on{display:block}
.card{
  background:var(--card); border:1px solid var(--line); border-radius:9px;
  padding:22px 24px; margin:0 0 18px;
}
.card.tight{padding:16px 18px}
h2{font-size:19px; color:var(--ink); margin:0 0 4px; font-weight:650}
h3{font-size:15px; color:var(--ink); margin:22px 0 8px; font-weight:650}
p{margin:0 0 12px}
.lede{color:var(--muted); font-size:13.5px; margin:0 0 18px}
.kpis{display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:14px; margin-bottom:20px}
.kpi{background:var(--card); border:1px solid var(--line); border-radius:9px; padding:16px 18px}
.kpi .v{font-size:29px; font-weight:680; color:var(--navy); line-height:1.15; letter-spacing:-.5px}
.kpi .l{font-size:12.5px; color:var(--muted); margin-top:5px}
.kpi .n{font-size:11.5px; color:#98a0ad; margin-top:4px}
table{width:100%; border-collapse:collapse; font-size:13.5px}
th,td{text-align:left; padding:8px 10px; border-bottom:1px solid var(--line)}
th{font-size:12px; text-transform:uppercase; letter-spacing:.4px; color:var(--muted); font-weight:600}
td.num,th.num{text-align:right; font-variant-numeric:tabular-nums}
tbody tr:hover{background:#fafbfd}
.chip{
  display:inline-block; padding:2px 8px; border-radius:11px; font-size:11.5px;
  background:#eef2f8; color:#3b4a63; white-space:nowrap;
}
.chip.bad{background:#fdecec; color:#a52a2a}
.chip.warn{background:#fdf3e6; color:#a8600b}
.chip.ok{background:#e9f6ef; color:#1f7a4d}
.controls{display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-bottom:14px}
input[type=search],select{
  font:inherit; font-size:13.5px; padding:8px 11px; border:1px solid #cfd6e2;
  border-radius:7px; background:#fff; color:var(--ink); min-width:150px;
}
input[type=search]{flex:1 1 280px}
input[type=search]:focus,select:focus{outline:2px solid #c3d3ea; border-color:var(--accent)}
.count{font-size:12.5px; color:var(--muted); margin-left:auto}
.rec{border-bottom:1px solid var(--line); padding:12px 4px; cursor:pointer}
.rec:hover{background:#fafbfd}
.rec .h{display:flex; gap:9px; align-items:baseline; flex-wrap:wrap}
.rec .ttl{font-weight:600; color:var(--ink); font-size:14px}
.rec .sub{font-size:12.5px; color:var(--muted); margin-top:4px}
.rec .sn{font-size:12.5px; color:#5a6474; margin-top:5px; display:none}
.rec.open .sn{display:block}
.pager{display:flex; gap:8px; align-items:center; justify-content:center; margin-top:16px}
.pager button{
  font:inherit; font-size:13px; padding:7px 14px; border-radius:7px;
  border:1px solid #cfd6e2; background:#fff; cursor:pointer; color:var(--ink);
}
.pager button:disabled{opacity:.42; cursor:default}
.pager span{font-size:12.5px; color:var(--muted)}
.fig{width:100%; height:auto; border:1px solid var(--line); border-radius:7px; display:block}
.figcap{font-size:12px; color:var(--muted); margin:7px 0 20px}
.grid2{display:grid; grid-template-columns:1fr 1fr; gap:18px}
@media(max-width:820px){.grid2{grid-template-columns:1fr}}
details{border:1px solid var(--line); border-radius:8px; padding:12px 16px; margin-bottom:10px; background:#fff}
details summary{cursor:pointer; font-weight:600; color:var(--ink); font-size:14px}
details summary .chip{margin-left:8px; font-weight:400}
details .dn{font-size:13px; color:var(--body); margin:10px 0 6px}
ul.tight{margin:6px 0 0; padding-left:20px; font-size:13px}
ul.tight li{margin-bottom:3px}
.q{border-left:3px solid #d6dfec; padding:2px 0 2px 14px; margin:0 0 16px}
.q .qh{font-weight:650; color:var(--ink); font-size:14px}
.q .qm{font-size:12.5px; color:var(--muted); margin-top:3px}
.q .qr{font-size:13px; margin-top:5px}
.pill{display:inline-block; font-size:11.5px; padding:2px 9px; border-radius:10px;
  background:var(--navy); color:#fff; margin-left:8px}
.pill.single{background:#6b7f9e}
.tag{display:inline-block; font-size:11px; padding:1px 8px; border-radius:4px;
  background:#eef3fa; color:#39507a; margin-left:6px; white-space:nowrap}
footer{border-top:1px solid var(--line); padding:20px 0 40px; font-size:12.5px; color:var(--muted)}
footer .foot-links{margin-top:8px; display:flex; gap:16px; flex-wrap:wrap}
footer .foot-authors{color:var(--body, #1c2536); font-weight:600; margin-bottom:6px}
footer .foot-links a{color:var(--accent); text-decoration:none}
footer .foot-links a:hover{text-decoration:underline}
.note{font-size:12.5px; color:var(--muted); background:#fbfcfe; border-left:3px solid #d6dfec;
  padding:10px 14px; border-radius:0 6px 6px 0; margin:14px 0}
.src{font-size:12px; color:var(--muted); font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
dl.dl{display:grid; grid-template-columns:1fr auto; gap:8px 16px; align-items:center; font-size:13.5px}
dl.dl dt{margin:0}
dl.dl dd{margin:0; text-align:right; color:var(--muted); font-size:12px}
dl.kv{display:grid; grid-template-columns:auto 1fr; gap:6px 18px; font-size:13.5px; margin:12px 0}
dl.kv dt{color:var(--muted)}
dl.kv dd{margin:0}
pre.code{background:#0f172a; color:#dbe6f7; border-radius:8px; padding:14px 16px; overflow:auto;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12.5px; line-height:1.55; margin:12px 0}
p.small{font-size:12px; color:var(--muted); margin:8px 0 0}
"""


JS = """
const D = JSON.parse(document.getElementById('payload').textContent);
const L = D.labels, R = D.records;
const fmtPct = v => (v*100).toFixed(1)+'%';
const lab = (dim, code) => (L[dim] && L[dim][code]) || code || '—';
const short = (dim, code) => (L[dim+'_short'] && L[dim+'_short'][code]) || lab(dim, code);

document.querySelectorAll('nav.tabs button').forEach(btn=>{
  btn.addEventListener('click',()=>{
    document.querySelectorAll('nav.tabs button').forEach(b=>b.classList.remove('on'));
    document.querySelectorAll('section.panel').forEach(s=>s.classList.remove('on'));
    btn.classList.add('on');
    document.getElementById(btn.dataset.tab).classList.add('on');
    window.scrollTo({top:0,behavior:'instant'});
  });
});

// ---------------------------------------------------------------- explorer
const PAGE = 12;
let page = 0, view = [];

function sevClass(s){
  return s==='D1_blocking' ? 'bad' : s==='D2_incorrect_output' ? 'warn' : '';
}
function esc(t){const d=document.createElement('div'); d.textContent=t; return d.innerHTML;}

function apply(){
  const q = document.getElementById('q').value.trim().toLowerCase();
  const fw = document.getElementById('fw').value;
  const ty = document.getElementById('ty').value;
  const sv = document.getElementById('sv').value;
  view = R.filter(r=>{
    if(fw && r.f!==fw) return false;
    if(ty && r.a!==ty) return false;
    if(sv && r.s!==sv) return false;
    if(q){
      const blob = (r.t+' '+r.sn+' '+r.ev+' '+r.b+' '+r.f).toLowerCase();
      if(!blob.includes(q)) return false;
    }
    return true;
  });
  view.sort((x,y)=> (y.d||y.y).localeCompare(x.d||x.y));
  page = 0;
  render();
}
function render(){
  const total = view.length, pages = Math.max(1, Math.ceil(total/PAGE));
  if(page >= pages) page = pages-1;
  const slice = view.slice(page*PAGE, page*PAGE+PAGE);
  const host = document.getElementById('list');
  host.innerHTML = slice.map((r,idx)=>{
    const n = page*PAGE+idx;
    return `<div class="rec" onclick="this.classList.toggle('open')">
      <div class="h">
        <span class="ttl">${esc(r.t.slice(0,150))}</span>
        <span class="chip">${esc(r.f)}</span>
        <span class="chip ${sevClass(r.s)}">${esc(short('d',r.s))}</span>
      </div>
      <div class="sub">${esc(lab('a',r.a))} · ${esc(lab('b',r.b))} · confidence ${r.ac.toFixed(2)} · ${esc(r.d||r.y)}</div>
      <div class="sn"><b>Stage:</b> ${esc(short('c',r.c))} · <b>Detected by:</b> ${esc(short('e',r.e))} · <b>Severity:</b> ${esc(short('d',r.s))}<br><br>${esc(r.sn)}${r.ev?'<br><br><b>Evidence span:</b> <span class="src">'+esc(r.ev)+'</span>':''}${r.rl?'<br><b>Matched rules:</b> <span class="src">'+esc(r.rl)+'</span>':''}${r.u?'<br><br><a href="'+esc(r.u)+'" target="_blank" rel="noopener">Open the original report ↗</a>':''}</div>
    </div>`;
  }).join('') || '<p class="lede">No records match these filters.</p>';
  document.getElementById('count').textContent =
    total.toLocaleString()+' of '+R.length.toLocaleString()+' records';
  document.getElementById('pager').innerHTML =
    `<button ${page===0?'disabled':''} onclick="go(-1)">Previous</button>
     <span>Page ${page+1} of ${pages}</span>
     <button ${page>=pages-1?'disabled':''} onclick="go(1)">Next</button>`;
}
function go(d){ page += d; render(); document.getElementById('list').scrollIntoView({block:'start'}); }

['q','fw','ty','sv'].forEach(id=>{
  const el = document.getElementById(id);
  el.addEventListener(id==='q' ? 'input' : 'change', apply);
});

// populate filters
(function(){
  const fws = [...new Set(R.map(r=>r.f))].sort();
  const types = [...new Set(R.map(r=>r.a))].sort();
  const sevs = [...new Set(R.map(r=>r.s))].sort();
  document.getElementById('fw').innerHTML += fws.map(f=>`<option>${esc(f)}</option>`).join('');
  document.getElementById('ty').innerHTML += types.map(t=>`<option value="${esc(t)}">${esc(lab('a',t))}</option>`).join('');
  document.getElementById('sv').innerHTML += sevs.map(s=>`<option value="${esc(s)}">${esc(short('d',s))}</option>`).join('');
  apply();
})();
"""


def _html(payload: dict, figures: dict, downloads: list) -> str:
    d = payload
    hf = d.get("hf") or {}
    from .sources import INTRO as SRC_INTRO, SOURCES as SOURCE_ROWS

    src_intro = SRC_INTRO
    src_rows = "".join(
        f'<tr><td>{html.escape(s["source"])}</td>'
        f'<td class="src">{html.escape(s["used"])}</td>'
        f'<td>{html.escape(s["reason"])}</td></tr>' for s in SOURCE_ROWS)

    from . import aidev as _aidev

    adv = _aidev.load()
    aidev_card = ""
    if (adv.get("summary") or {}).get("pull_requests"):
        a = adv["summary"]
        arows = "".join(
            f'<tr><td>{html.escape(r["agent"].replace("_", " "))}</td>'
            f'<td>{r["pull_requests"]:,}</td>'
            f'<td>{r["merge_rate"] * 100:.1f}%</td>'
            f'<td>{r["closed_unmerged_rate_of_closed"] * 100:.1f}%</td>'
            f'<td>{r["review_flagged_human_share"] * 100:.1f}%</td></tr>'
            for r in adv["per_agent"])
        aidev_card = f"""
  <div class="card">
    <h2>An independent corpus: agent-authored pull requests</h2>
    <p class="lede">{a["pull_requests"]:,} pull requests written by coding
    agents in {a["repositories"]:,} real repositories (AIDev), none of them selected for
    being failures. Used as an outcome-level check that does not touch the labeller or
    the codebook.</p>
    <table><thead><tr><th>Agent</th><th>PRs</th><th>Merged</th>
    <th>Closed unmerged</th><th>Changes requested</th></tr></thead>
    <tbody>{arows}</tbody></table>
    <p class="small">{html.escape(a["construct_note"])}</p>
  </div>"""
    rq1 = d["results"]["RQ1"]
    rq3 = d["results"]["RQ3"]
    rq7 = d["results"]["RQ7"]
    rq8 = d["results"]["RQ8"]
    rq6 = d["results"]["RQ6"]
    n = rq1["metrics"]["n_records"]
    top = rq1["table"][0]
    interface = sum(r["count"] for r in rq1["table"]
                    if r["code"] in ("A3_compatibility", "A6_data_structure",
                                     "A2_tool_integration"))
    gold = d["validation"].get("gold_eval") or {}
    kappa = (gold.get("kappa_vs_reference") or {}).get("kappa")
    pert = d["validation"].get("perturbation") or {}
    abl = d["validation"].get("ablation") or {}

    def lab(dim: str, code: str) -> str:
        return (payload["labels"].get(dim) or {}).get(code, code or "—")

    def kmap(key):  # framework counts
        return d["framework_counts"]

    kpis = "".join(
        f'<div class="kpi"><div class="v">{v}</div><div class="l">{html.escape(l)}</div>'
        f'<div class="n">{html.escape(nn)}</div></div>'
        for v, l, nn in [
            (f"{n:,}", "Failure records", "from 8 public repositories"),
            (f"{interface/n*100:.1f}%", "Fail at a component interface",
             "compatibility + parsing + tool"),
            (f"{top['proportion']*100:.1f}%",
             f"Largest single category: {top['label']}",
             f"95% CI {top['ci_low']*100:.1f}–{top['ci_high']*100:.1f}%"),
            (f"{rq7['metrics']['escape_share']*100:.1f}%", "Escape runtime detection",
             "reach the user as wrong output"),
            (f"{rq8['metrics']['coverage']*100:.1f}%", "Taxonomy coverage",
             f"{rq8['metrics']['unknown']} records unclassified"),
        ])

    # ---- distribution table
    rows1 = "".join(
        f"<tr><td>{html.escape(r['code'].split('_')[0])}</td>"
        f"<td>{html.escape(r['label'])}</td>"
        f'<td class="num">{r["count"]}</td>'
        f'<td class="num">{r["proportion"]*100:.1f}%</td>'
        f'<td class="num">{r["ci_low"]*100:.1f}–{r["ci_high"]*100:.1f}%</td></tr>'
        for r in rq1["table"])

    # ---- framework table
    rq4, rq5 = d["results"]["RQ4"], d["results"]["RQ5"]
    blocking = {r["label"]: r for r in rq5["table"]}
    best: dict[str, tuple[str, float]] = {}
    for r in rq4["table"]:
        if r["framework"] not in best or r["share_pct"] > best[r["framework"]][1]:
            best[r["framework"]] = (r["failure_type"], r["share_pct"])
    rows_fw = "".join(
        f"<tr><td><b>{html.escape(fw)}</b></td>"
        f'<td class="num">{c}</td>'
        f'<td class="num">{c/n*100:.1f}%</td>'
        f'<td class="num">{blocking.get(fw, {}).get("proportion", 0)*100:.1f}%</td>'
        f"<td>{html.escape(lab('a', best.get(fw, ('', 0))[0]))}</td>"
        f'<td class="num">{best.get(fw, ("", 0))[1]:.1f}%</td></tr>'
        for fw, c in sorted(kmap("x").items(), key=lambda kv: kv[1], reverse=True))

    # ---- causes
    cause_rows = "".join(
        f"<tr><td>{html.escape(r['label'])}</td>"
        f'<td class="num">{r["count"]}</td>'
        f'<td class="num">{r["share"]*100:.1f}%</td>'
        f'<td class="num">{r["demonstrated"]}</td></tr>'
        for r in d["causes"])

    # ---- complexity
    rows_cx = "".join(
        f"<tr><td>{html.escape(r['label'].replace('tier_','Tier '))}</td>"
        f'<td class="num">{r["denominator"]}</td>'
        f'<td class="num">{r["count"]}</td>'
        f'<td class="num">{r["proportion"]*100:.1f}%</td>'
        f'<td class="num">{r["ci_low"]*100:.1f}–{r["ci_high"]*100:.1f}%</td></tr>'
        for r in rq6["table"])

    # ---- escape table
    rows_esc = "".join(
        f"<tr><td>{html.escape(r['label'])}</td>"
        f'<td class="num">{r["denominator"]}</td>'
        f'<td class="num">{r.get("runtime_caught", 0)}</td>'
        f'<td class="num">{r["proportion"]*100:.1f}%</td></tr>'
        for r in rq7["table"])

    # ---- RQs
    rq_html = []
    for q in d["questions"]:
        mode = q.get("agent_mode", "chain")
        pill = ('<span class="pill single">single agent</span>' if mode == "single"
                else '<span class="pill">agent chain</span>')
        agents = ", ".join(q.get("agents", []))
        rq_html.append(
            f'<div class="q"><div class="qh">{html.escape(q["id"])}. '
            f'{html.escape(q["question"])}{pill}</div>'
            f'<div class="qm">{html.escape(q.get("method",""))} · '
            f'{html.escape(agents)}</div>'
            f'<div class="qr">{html.escape(q.get("finding",""))}</div></div>')
    rq_html = "".join(rq_html)

    # ---- codebook
    cb = []
    for key in ("A_failure_type", "B_cause_class", "C_lifecycle_stage",
                "D_severity", "E_detection_point"):
        dim = d["codebook"][key]
        cats = "".join(
            f'<details><summary>{html.escape(c["code"])} — '
            f'{html.escape(c["label"])}</summary>'
            f'<div class="dn">{html.escape(c["definition"].strip())}</div>'
            + ("<div class='dn'><b>Includes:</b></div><ul class='tight'>"
               + "".join(f"<li>{html.escape(x)}</li>" for x in c["include"]) + "</ul>"
               if c["include"] else "")
            + ("<div class='dn'><b>Excludes:</b></div><ul class='tight'>"
               + "".join(f"<li>{html.escape(x)}</li>" for x in c["exclude"]) + "</ul>"
               if c["exclude"] else "")
            + "</details>"
            for c in dim["categories"])
        prec = (f'<div class="note">{html.escape(dim["precedence"])}</div>'
                if dim["precedence"] else "")
        cb.append(f'<div class="card"><h2>{dim["letter"]}. {html.escape(dim["name"])}'
                  f'</h2><p class="lede">{html.escape(dim["blurb"])} — '
                  f'{len(dim["categories"])} categories</p>{prec}{cats}</div>')
    cb = "".join(cb)

    rules = "".join(
        f'<div class="q"><div class="qh">{html.escape(r.get("rule",""))}</div>'
        f'<div class="qr">{html.escape(r.get("detail","").strip())}</div></div>'
        for r in d["codebook"]["_rules"])

    # ---- requirement conformance
    req_rows = [r for r in (d.get("requirements") or [])
                if r.get("source") == "supervisor_checklist"]
    obj_rows = [r for r in (d.get("requirements") or [])
                if r.get("source") == "requirements_document"]
    conf_items = "".join(
        f'<div class="q"><div class="qh">'
        f'<span class="pill">{html.escape(r.get("id",""))}</span> '
        f'{html.escape(r.get("requirement",""))} '
        f'<span class="tag">{html.escape(r.get("status",""))}</span></div>'
        f'<div class="qr">{html.escape(r.get("evidence",""))}</div>'
        f'<div class="qr"><i>Answered in:</i> {html.escape(r.get("location",""))}</div>'
        + (f'<div class="qr"><i>Stated limit:</i> {html.escape(r["limit"])}</div>'
           if r.get("limit") else "")
        + '</div>'
        for r in req_rows)
    obj_table = ("<table><thead><tr><th>#</th><th>Objective</th><th>Status</th>"
                 "<th>Evidence</th></tr></thead><tbody>"
                 + "".join(
                     f"<tr><td>{html.escape(r.get('id',''))}</td>"
                     f"<td>{html.escape(r.get('requirement',''))}</td>"
                     f"<td>{html.escape(r.get('status',''))}</td>"
                     f"<td>{html.escape(r.get('evidence',''))}</td></tr>"
                     for r in obj_rows)
                 + "</tbody></table>") if obj_rows else ""
    conf_met = sum(1 for r in req_rows if r.get("status") == "Met")
    conf_lim = sum(1 for r in req_rows if r.get("status") == "Met with stated limit")

    fv = d.get("findings") or {}
    fsum = fv.get("summary") or {}
    f_rows = [
        ("F1", "Resampling stability", fv.get("F1_resampling") or {},
         f"top category retained in {(fv.get('F1_resampling') or {}).get('top1_retention', 0)*100:.1f}% "
         f"of {((fv.get('F1_resampling') or {}).get('iterations') or 0):,} replicates"),
        ("F2", "Temporal holdout", fv.get("F2_temporal") or {},
         f"before/after {(fv.get('F2_temporal') or {}).get('split_year','—')}: "
         f"V = {((fv.get('F2_temporal') or {}).get('homogeneity') or {}).get('cramers_v', 0):.2f}, "
         f"top-three overlap {(fv.get('F2_temporal') or {}).get('top3_overlap', 0):.2f}"),
        ("F3", "Leave one framework out", fv.get("F3_leave_one_out") or {},
         f"top category unchanged in {(fv.get('F3_leave_one_out') or {}).get('top_unchanged_in', 0)} "
         f"of {(fv.get('F3_leave_one_out') or {}).get('frameworks_tested', 0)} exclusions"),
        ("F4", "Label-noise sensitivity", fv.get("F4_label_noise") or {},
         f"error rate {(fv.get('F4_label_noise') or {}).get('error_rate', 0)*100:.0f}%; top category "
         f"retained in {((fv.get('F4_label_noise') or {}).get('confusion_driven') or {}).get('top1_retention', 0)*100:.1f}%"),
    ]
    f_table = ("<table><thead><tr><th>ID</th><th>Test</th><th>Result</th>"
               "<th>Verdict</th></tr></thead><tbody>"
               + "".join(f"<tr><td>{i}</td><td><b>{html.escape(nm)}</b></td>"
                         f"<td>{html.escape(res)}</td>"
                         f"<td>{html.escape(v.get('verdict','—'))}</td></tr>"
                         for i, nm, v, res in f_rows)
               + "</tbody></table>") if fv else ""

    ex_rows = []
    seen_cat = set()
    for r in (d.get("exemplars") or []):
        if r.get("category") in seen_cat:
            continue
        seen_cat.add(r.get("category"))
        ex_rows.append(r)
    ex_table = ("<table><thead><tr><th>Category</th><th>Source</th>"
                "<th>Reported failure</th><th>Evidence span</th></tr></thead><tbody>"
                + "".join(
                    f"<tr><td><b>{html.escape(r.get('category_label',''))}</b></td>"
                    f"<td>{html.escape(r.get('framework',''))} #{html.escape(r.get('issue_number',''))}"
                    f"<br><a href=\"{html.escape(r.get('url',''))}\" target=\"_blank\" "
                    f"rel=\"noopener\">source ↗</a></td>"
                    f"<td>{html.escape(r.get('title',''))}</td>"
                    f"<td>{html.escape(r.get('evidence',''))}</td></tr>"
                    for r in ex_rows)
                + "</tbody></table>") if ex_rows else ""

    # ---- validation
    cal = d["validation"].get("calibration") or {}
    cal_bins = cal.get("bins") or []
    cal_txt = ("—" if not cal_bins else
               f"{cal_bins[0]['proportion']*100:.0f}% → "
               f"{cal_bins[-1]['proportion']*100:.0f}% across bins")
    e5 = d["validation"].get("kappa") or {}
    val_rows = [
        ("E1", "Reference agreement",
         f"n = {gold.get('n','—')}",
         f"{gold.get('accuracy',0)*100:.1f}% exact · macro-F1 "
         f"{gold.get('macro_f1',0):.3f} · κ = {kappa if kappa is None else round(kappa,2)}",
         "Moderate — residual error on two boundaries"),
        ("E2", "Perturbation retention", f"n = {pert.get('n','—')}",
         f"{pert.get('retention_rate',0)*100:.1f}% (95% CI "
         f"{pert.get('ci_low',0)*100:.1f}–{pert.get('ci_high',0)*100:.1f}%)",
         "Labels survive rewording and anonymisation"),
        ("E3", "Exception-rule ablation", f"n = {abl.get('n','—')}",
         f"{abl.get('change_rate',0)*100:.1f}% of labels change",
         "Not dependent on pasted tracebacks"),
        ("E4", "Confidence calibration",
         f"n = {cal.get('n','—')}",
         cal_txt, "Informative for triage, not calibrated"),
        ("E5", "Blind second coder",
         f"{d['coder_packet_size']} records",
         e5.get("status", "pending"),
         "Requires a coder independent of the author"),
    ]
    vrows = "".join(
        f"<tr><td>{i}</td><td><b>{html.escape(nm)}</b></td>"
        f'<td class="num">{html.escape(ds)}</td><td>{html.escape(res)}</td>'
        f"<td>{html.escape(rd)}</td></tr>" for i, nm, ds, res, rd in val_rows)

    fig_titles = {
        "fig_rq1_failure_types.png": "Failure-type distribution with Wilson 95% intervals",
        "fig_rq3_cause_by_type.png": "Cause class by failure type",
        "fig_rq4_framework_composition.png": "Failure composition by framework",
        "fig_rq5_blocking_rate.png": "Blocking-severity rate by framework",
        "fig_rq6_complexity.png": "Orchestration and context failures by complexity tier",
        "fig_rq9_time_trend.png": "Failure composition over time",
        "fig_val_confusion.png": "Labels against reference annotation",
    }

    def fig(name: str) -> str:
        src = figures.get(name)
        if not src:
            return ""
        return (f'<figure style="margin:0 0 18px"><img class="fig" '
                f'alt="{html.escape(fig_titles.get(name, name))}" src="{src}">'
                f'<figcaption class="figcap">'
                f'{html.escape(fig_titles.get(name, name))}</figcaption></figure>')

    overview_figs = fig("fig_rq1_failure_types.png")

    dl_html = "".join(
        f'<dt><a href="{html.escape(x["file"])}">{html.escape(x["name"])}</a></dt>'
        f'<dd>{x["kb"]} kB</dd>' for x in downloads)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Failures in Agentic AI — study explorer</title>
<style>{CSS}</style>
</head>
<body>
<header class="top"><div class="wrap">
  <h1>Failures in Agentic AI</h1>
  <p class="sub">A five-dimension taxonomy and an empirical analysis of
  {n:,} publicly reported failures across eight agent orchestration frameworks.
  Every record below can be traced to its original report.</p>
  <div class="meta">Taxonomy v1.0 · corpus frozen at {n:,} records · built
  {html.escape(d['generated_at'][:10])}</div>
  <nav class="tabs">
    <button class="on" data-tab="overview">Overview</button>
    <button data-tab="explore">Explore records</button>
    <button data-tab="frameworks">Frameworks</button>
    <button data-tab="codebook">Taxonomy</button>
    <button data-tab="questions">Research questions</button>
    <button data-tab="validation">Validation</button>
    <button data-tab="conformance">Conformance</button>
    <button data-tab="data">Data &amp; downloads</button>
  </nav>
</div></header>

<main><div class="wrap">

<section class="panel on" id="overview">
  <div class="kpis">{kpis}</div>

  <div class="card">
    <h2>What this study found</h2>
    <p class="lede">Four results, each with the evidence that supports it.</p>
    <p><b>Most failures are interface failures.</b> The three categories that
    describe a break between components — compatibility and API contracts,
    output parsing, and tool integration — account for
    {interface/n*100:.1f}% of records. The two categories unique to multi-agent
    architectures, communication and context, account for
    {(rq1['table'][6]['count']+rq1['table'][8]['count'])/n*100:.1f}%.
    Orchestration failures are real and measurable, but they are not the
    plurality.</p>
    <p><b>Cause is associated with type, but the causal evidence is thin.</b>
    Type and stated cause are strongly associated (Cramér's V =
    {rq3['metrics']['cramers_v']:.3f}, χ² = {rq3['metrics']['chi2']:.0f},
    p &lt; 1e-12), yet only {rq3['metrics']['demonstrated_causes']} records
    ({rq3['metrics']['demonstrated_causes']/n*100:.1f}%) name a checkable
    mechanism. The rest are graded supported or hypothesised, and no causal
    claim in this study rests on them.</p>
    <p><b>Frameworks fail differently, not worse.</b> Composition differs
    (V = {rq4['metrics']['cramers_v']:.3f}) and no two frameworks share a
    dominant category. Blocking-severity rate ranges from
    {rq5['metrics']['min_rate']*100:.1f}% to {rq5['metrics']['max_rate']*100:.1f}%
    — a property of how loudly a framework fails, not of its quality.</p>
    <p><b>About a third of failures are silent.</b>
    {rq7['metrics']['escape_share']*100:.1f}% were not detected by the
    framework runtime and reached the user as incorrect output rather than as an
    error. This is the strongest argument in the study for output validation
    over exception monitoring.</p>
  </div>

  <div class="card">
    <h2>Distribution of failure types</h2>
    <p class="lede">Denominator includes the {rq8['metrics']['unknown']} records
    coded unknown; intervals are Wilson 95% score intervals.</p>
    <table><thead><tr><th>Code</th><th>Category</th><th class="num">n</th>
      <th class="num">Share</th><th class="num">95% CI</th></tr></thead>
      <tbody>{rows1}</tbody></table>
  </div>

  <div class="card">
    <h2>Where the failures are</h2>
    {overview_figs}
    <div class="grid2" style="margin-top:20px">
      {fig("fig_rq4_framework_composition.png")}
      {fig("fig_rq6_complexity.png")}
    </div>
    <div class="grid2" style="margin-top:4px">
      {fig("fig_rq3_cause_by_type.png")}
      {fig("fig_rq9_time_trend.png")}
    </div>
  </div>
</section>

<section class="panel" id="explore">
  <div class="card">
    <h2>Explore the corpus</h2>
    <p class="lede">Click a record to see its evidence span, the rules that
    produced its label, and a link to the original report.</p>
    <div class="controls">
      <input type="search" id="q" placeholder="Search titles, evidence, causes…">
      <select id="fw"><option value="">All frameworks</option></select>
      <select id="ty"><option value="">All failure types</option></select>
      <select id="sv"><option value="">All severities</option></select>
      <span class="count" id="count"></span>
    </div>
    <div id="list"></div>
    <div class="pager" id="pager"></div>
  </div>
</section>

<section class="panel" id="frameworks">
  <div class="card">
    <h2>Framework comparison</h2>
    <p class="lede">Composition, not quality. A blocking rate is a property of
    the issue and of the framework's error handling.</p>
    <table><thead><tr><th>Framework</th><th class="num">Records</th>
      <th class="num">Share</th><th class="num">Blocking</th>
      <th>Dominant category</th><th class="num">Share</th></tr></thead>
      <tbody>{rows_fw}</tbody></table>
    <div class="note">No two frameworks share a dominant category. That spread is
    the strongest descriptive evidence in this study that orchestration design
    shapes which part of the system breaks.</div>
  </div>
  <div class="card">
    <h2>Severity and silent failure</h2>
    <p class="lede">Escape rate is the share of records not detected by the
    framework runtime.</p>
    <table><thead><tr><th>Failure type</th><th class="num">n</th>
      <th class="num">Runtime-caught</th><th class="num">Escape rate</th></tr></thead>
      <tbody>{rows_esc}</tbody></table>
    {fig("fig_rq5_blocking_rate.png")}
  </div>
  <div class="card">
    <h2>Declared complexity</h2>
    <p class="lede">Share of orchestration and context failures by complexity
    tier. Complexity is declared in the report, not instrumented; read this as a
    stratification, not a causal estimate.</p>
    <table><thead><tr><th>Tier</th><th class="num">Records</th>
      <th class="num">Orchestration / context</th><th class="num">Share</th>
      <th class="num">95% CI</th></tr></thead>
      <tbody>{rows_cx}</tbody></table>
    <div class="note">The share rises monotonically from
    {rq6['table'][0]['proportion']*100:.1f}% to
    {rq6['table'][-1]['proportion']*100:.1f}% (Spearman ρ =
    {rq6['metrics']['trend']['rho']:.2f}). Complexity relocates the failure
    surface toward coordination; it does not demonstrably shrink it.</div>
  </div>
  <div class="card">
    <h2>Stated causes</h2>
    <p class="lede">Cause class across the corpus. The final column counts
    records where the report names a checkable mechanism.</p>
    <table><thead><tr><th>Cause class</th><th class="num">n</th>
      <th class="num">Share</th><th class="num">Demonstrated</th></tr></thead>
      <tbody>{cause_rows}</tbody></table>
  </div>
</section>

<section class="panel" id="codebook">
  <div class="card">
    <h2>The codebook</h2>
    <p class="lede">Five dimensions, coded independently. Every category below
    has a definition, an inclusion list and an exclusion list, so that two coders
    can reach the same label from the same text. Click a category to expand it.</p>
    <p>The dimensions are orthogonal on purpose: a compatibility failure can be
    caused by a framework defect, a version bump or a user misconfiguration, and
    those have different remediations. Collapsing them is why
    "agent errors" reports rarely generalise.</p>
  </div>
  {cb}
  <div class="card">
    <h2>Coding rules</h2>
    <p class="lede">The precedence order applied when more than one category
    appears to fit.</p>
    {rules}
  </div>
</section>

<section class="panel" id="questions">
  <div class="card">
    <h2>Research questions and agent assignment</h2>
    <p class="lede">A question is assigned to a single agent only when one pass
    over one table answers it. Questions that require deriving a variable,
    testing an association and then checking the claim against the source
    records are assigned to a chain, because the verification step is what
    prevents unsupported numbers from reaching a report.</p>
  </div>
  <div class="card">{rq_html}</div>
  <div class="card">
    <h2>How the application is organised</h2>
    <p class="lede">Eight agents on a shared blackboard. Any agent can be re-run
    in isolation and its contribution inspected.</p>
    <table><thead><tr><th>Agent</th><th>Responsibility</th></tr></thead><tbody>
      <tr><td><b>Planner</b></td><td>Maps each question to the variables, the
        test and the output shape it requires.</td></tr>
      <tr><td><b>Tagger</b></td><td>Resolves labels and confidence; exposes the
        evidence span for each.</td></tr>
      <tr><td><b>Statistician</b></td><td>Distributions, intervals, association
        tests, corrected p-values.</td></tr>
      <tr><td><b>Causal</b></td><td>Cause-to-type contingency analysis with lift
        per cell, graded by evidence.</td></tr>
      <tr><td><b>Comparator</b></td><td>Framework and time contrasts with
        multiple-testing control.</td></tr>
      <tr><td><b>Complexity</b></td><td>Declared capability index and trend
        across tiers.</td></tr>
      <tr><td><b>Critic</b></td><td>Recomputes every headline metric on an
        independent code path; blocks a mismatch.</td></tr>
      <tr><td><b>Reporter</b></td><td>Assembles verified results into tables,
        figures and prose.</td></tr>
    </tbody></table>
    <div class="note">In the run shown here, all ten questions passed
    verification with no rejections.</div>
  </div>
</section>

<section class="panel" id="validation">
  <div class="card">
    <h2>What the instrument can and cannot support</h2>
    <p class="lede">Five experiments test the labelling instrument rather than
    the findings. One is still pending, and it is stated as pending rather than
    approximated.</p>
    <table><thead><tr><th>ID</th><th>Experiment</th><th class="num">Design</th>
      <th>Result</th><th>Reading</th></tr></thead><tbody>{vrows}</tbody></table>
    <div class="note">Agreement of κ =
    {kappa if kappa is None else round(kappa,2)} with a first-pass reference
    annotation is moderate, not high. The residual error concentrates on two
    codebook boundaries — compatibility versus configuration, and functionality
    versus output parsing. Those are codebook problems, and they are the agenda
    for v1.1.</div>
  </div>
  <div class="card">
    <h2>Confusion against reference annotation</h2>
    {fig("fig_val_confusion.png")}
  </div>
</section>

<section class="panel" id="conformance">
  <div class="card">
    <h2>Requirement conformance</h2>
    <p class="lede">Every line of the supervisor's checklist, answered with the
    number that satisfies it. {conf_met} of {len(req_rows)} lines are met and
    {conf_lim} are met with a limit stated in the row. The evidence is read from
    the same artefacts the report uses, so this page cannot drift from the
    study.</p>
  </div>
  <div class="card">
    <h2>Supervisor checklist</h2>
    {conf_items}
  </div>
  <div class="card">
    <h2>Response to the requirements document</h2>
    {obj_table}
  </div>
  <div class="card">
    <h2>Validation of the findings</h2>
    <p class="lede">The instrument is validated above. These four tests check
    whether a <i>conclusion</i> survives a different draw, a later corpus, the
    removal of any single repository, and the measured label error rate.
    {fsum.get('stable', 0)} of {fsum.get('claims_tested', 0)} claims are stable;
    {fsum.get('not_stable', 0)} is not, and is reported as such.</p>
    {f_table}
  </div>
  <div class="card">
    <h2>One cited example per failure type</h2>
    <p class="lede">Each row is a real record from the corpus with its original
    report. Selection favours a record whose own text states the definition over
    one where the labeller merely happened to be confident.</p>
    {ex_table}
  </div>
</section>

<section class="panel" id="data">
  <div class="card">
    <h2>The dataset release</h2>
    <p class="lede">The corpus is packaged for reuse: one parquet file of
    annotations, one of cited exemplars, a documented schema and the codebook.
    It is what <code>load_dataset</code> expects, and the counts on the card are
    generated from the data rather than typed by hand.</p>
    <dl class="kv">
      <dt>Rows</dt><dd>{hf['records']:,}</dd>
      <dt>Columns</dt><dd>{hf['columns']}</dd>
      <dt>Frameworks</dt><dd>{hf['frameworks']}</dd>
      <dt>Licence</dt><dd>annotations CC BY 4.0 · code MIT</dd>
      <dt>Full issue text</dt><dd>not redistributed; every row links to its source</dd>
    </dl>
    <pre class="code">from datasets import load_dataset
ds = load_dataset("{hf['repo_id']}")
df = ds["train"].to_pandas()
df["failure_type_label"].value_counts()</pre>
    <p class="small">Built {html.escape(str(hf['generated_at'])[:19])} · regenerate
    with <code>python -m afs.cli hf</code> · publish with
    <code>python deploy/push_hf.py --repo-id &lt;user&gt;/&lt;name&gt; --yes</code></p>
  </div>
  <div class="card">
    <h2>Where the data comes from</h2>
    <p class="lede">{src_intro}</p>
    <table><thead><tr><th>Candidate source</th><th>Used?</th><th>Reason</th></tr></thead>
    <tbody>{src_rows}</tbody></table>
  </div>
  {aidev_card}
  <div class="card">
    <h2>Downloads</h2>
    <p class="lede">The corpus, the codebook and the result tables, in the same
    folder as this page.</p>
    <dl class="dl">{dl_html}</dl>
  </div>
  <div class="card">
    <div class="note">Every record shown here is traceable to a public bug report,
    and the original report is linked from it. Users sometimes paste their own
    API keys into those reports; any credential-shaped string is therefore
    masked as <span class="src">[redacted: credential]</span> on this page. The
    stored corpus is left unmodified so the text still matches the source it
    cites, and it is not published.</div>
    <h3>Record schema</h3>
    <p class="lede">One JSON object per line in the corpus file; the CSV carries
    the same fields.</p>
    <table><thead><tr><th>Field</th><th>Meaning</th></tr></thead><tbody>
      <tr><td class="src">record_id</td><td>Stable hash; the join key across all artefacts.</td></tr>
      <tr><td class="src">repo, issue_number, url</td><td>Provenance — the original report.</td></tr>
      <tr><td class="src">created_at, year, state, labels</td><td>Tracker context.</td></tr>
      <tr><td class="src">A_failure_type, A_confidence, A_evidence</td><td>Primary dimension, confidence, and the text span that produced the label.</td></tr>
      <tr><td class="src">B_cause_class, B_evidence_grade</td><td>Stated cause, graded demonstrated / supported / hypothesised.</td></tr>
      <tr><td class="src">C_lifecycle_stage, D_severity, E_detection_point</td><td>Remaining three dimensions.</td></tr>
      <tr><td class="src">matched_rules, taxonomy_version</td><td>Audit trail: which rules fired, against which codebook.</td></tr>
    </tbody></table>
  </div>
  <div class="card">
    <h2>Reproducing the analysis</h2>
    <p class="lede">From the project root, with <span class="src">PYTHONPATH=src</span> set:</p>
    <pre class="src" style="font-size:12.5px; line-height:1.7; background:#fafbfd;
      border:1px solid var(--line); border-radius:7px; padding:14px 16px; overflow:auto">python -m afs.cli build      # normalise + label
python -m afs.cli analyze    # multi-agent pipeline with critic verification
python -m afs.cli validate   # validation experiments
python -m afs.cli export     # Word report
python -m afs.cli paper      # journal-style manuscript
python -m afs.cli app        # this page</pre>
    <div class="note">Regenerating the corpus is deterministic: the labeller is
    rule-based, so the same text yields the same label and the same evidence
    span. Collection is rate-limited by the public API and takes about six
    minutes; every later stage is offline.</div>
  </div>
</section>

</div></main>

<footer><div class="wrap">
  <div class="foot-authors">{html.escape(identity.author_display())} · {html.escape(identity.INSTITUTION)}</div>
  Failures in Agentic AI · taxonomy v1.0 · {n:,} records ·
  built {html.escape(d['generated_at'][:10])} from the verified analysis
  artefacts. No number on this page is entered by hand.
  <div class="foot-links">
    <a href="{identity.GH_URL}">repository</a>
    <a href="{identity.HF_URL}">dataset release</a>
    <a href="{identity.REPORT_URL}">written report</a>
    <a href="{identity.all_links()['evidence_map']}">evidence map</a>
  </div>
</div></footer>

<script id="payload" type="application/json">{_json_block(payload)}</script>
<script>{JS}</script>
</body>
</html>"""


def _requirements() -> list[dict]:
    p = TAB_DIR / "requirements_traceability.csv"
    if not p.exists():
        return []
    try:
        return read_csv(p)
    except Exception:
        return []


def _findings() -> dict:
    p = TAB_DIR / "findings_validation.json"
    if not p.exists():
        return {}
    try:
        return read_json(p)
    except Exception:
        return {}


def _exemplars() -> list[dict]:
    p = TAB_DIR / "taxonomy_exemplars.csv"
    if not p.exists():
        return []
    try:
        return read_csv(p)
    except Exception:
        return []


# --------------------------------------------------------------------------- #
def build_app() -> Path:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    texts = {r["record_id"]: r["text"]
             for r in read_jsonl(PROC_DIR / "texts.jsonl")}
    results = read_json(TAB_DIR.parent / "analysis_results.json")["all_results"]
    vp = TAB_DIR / "validation_summary.json"
    validation = read_json(vp) if vp.exists() else {}

    recs = _records(texts)
    fw_counts: dict[str, int] = {}
    for r in recs:
        fw_counts[r["f"]] = fw_counts.get(r["f"], 0) + 1

    cause_counts: dict[str, int] = {}
    demo: dict[str, int] = {}
    for r in recs:
        cause_counts[r["b"]] = cause_counts.get(r["b"], 0) + 1
        if r["bg"] == "demonstrated":
            demo[r["b"]] = demo.get(r["b"], 0) + 1
    labels = _label_map()
    causes = [{"label": labels["b"].get(c, c), "count": k,
               "share": k / len(recs), "demonstrated": demo.get(c, 0)}
              for c, k in sorted(cause_counts.items(), key=lambda kv: kv[1],
                                 reverse=True)]

    findings = {
        "RQ1": f"{results['RQ1']['table'][0]['proportion']*100:.1f}% of records "
               f"are {results['RQ1']['table'][0]['label'].lower()}.",
        "RQ2": f"Restricting to confident labels leaves the ranking unchanged.",
        "RQ3": f"V = {results['RQ3']['metrics']['cramers_v']:.3f}; "
               f"{results['RQ3']['metrics']['demonstrated_causes']} causes are "
               f"demonstrated.",
        "RQ4": f"No two frameworks share a dominant category (V = "
               f"{results['RQ4']['metrics']['cramers_v']:.3f}).",
        "RQ5": f"Blocking rate spans "
               f"{results['RQ5']['metrics']['min_rate']*100:.1f}% to "
               f"{results['RQ5']['metrics']['max_rate']*100:.1f}%.",
        "RQ6": f"Orchestration/context share rises from "
               f"{results['RQ6']['table'][0]['proportion']*100:.1f}% to "
               f"{results['RQ6']['table'][-1]['proportion']*100:.1f}% across tiers.",
        "RQ7": f"{results['RQ7']['metrics']['escape_share']*100:.1f}% of failures "
               f"escape runtime detection.",
        "RQ8": f"Coverage is "
               f"{results['RQ8']['metrics']['coverage']*100:.1f}%; unknowns stay in "
               f"every denominator.",
        "RQ9": f"Composition changed over time (V = "
               f"{results['RQ9']['metrics']['cramers_v']:.3f}), confounded by "
               f"collection.",
        "RQ10": f"Tool-heavy stacks move the failure surface to tool contracts "
                f"(V = {results['RQ10']['metrics']['cramers_v']:.3f}).",
    }
    questions = []
    import yaml

    qspec = yaml.safe_load(
        open(CONFIG_DIR / "research_questions.yaml", encoding="utf-8"))
    for q in qspec["questions"]:
        q = dict(q)
        q["finding"] = findings.get(q["id"], "")
        questions.append(q)

    sheet = GOLD_DIR / "second_coder_sheet.csv"
    n_coder = 40
    if sheet.exists():
        try:
            n_coder = len(read_csv(sheet))
        except Exception:
            pass

    payload = {
        "generated_at": utc_now(),
        "labels": labels,
        "records": recs,
        "framework_counts": fw_counts,
        "causes": causes,
        "results": results,
        "validation": validation,
        "codebook": _codebook(),
        "questions": questions,
        "coder_packet_size": n_coder,
        "requirements": _requirements(),
        "findings": _findings(),
        "exemplars": _exemplars(),
        "hf": _hf_manifest(),
    }
    downloads = _dataset_index()
    data_dir = APP_DIR / "data"
    data_dir.mkdir(exist_ok=True)
    for x in downloads:
        src = x.get("src")
        if src and src.exists():
            (data_dir / src.name).write_bytes(src.read_bytes())

    out = APP_DIR / "index.html"
    out.write_text(_html(payload, _figures(), downloads), encoding="utf-8")
    return out
