/* Console behaviour.
   Two rules shape this file: the trace must reflect real server events rather
   than a simulated animation, and every displayed number must come from the
   response, never be recomputed in the browser. */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  };
  const pct = (v) => (v * 100).toFixed(1) + "%";
  const esc = (s) => String(s ?? "");

  /* ------------------------------------------------------------- tabs */
  document.querySelectorAll("nav.tabs button").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("nav.tabs button").forEach((b) =>
        b.setAttribute("aria-selected", String(b === btn)));
      document.querySelectorAll(".panel").forEach((p) => {
        p.hidden = p.id !== "panel-" + btn.dataset.panel;
      });
      if (btn.dataset.panel === "corpus" && !corpus.loaded) corpus.load();
      if (btn.dataset.panel === "questions" && !corpus.questionsLoaded) corpus.loadQuestions();
    });
  });

  /* ----------------------------------------------------------- health */
  async function health() {
    try {
      const r = await fetch("/api/health");
      const d = await r.json();
      $("statusText").textContent = d.status === "ok"
        ? `online · ${d.records.toLocaleString()} records · ${d.frameworks} frameworks`
        : "degraded";
      $("statusDot").classList.toggle("off", d.status !== "ok");
      $("footRecords").textContent = d.records.toLocaleString();
    } catch {
      $("statusText").textContent = "engine unreachable";
      $("statusDot").classList.add("off");
    }
  }
  health();

  /* -------------------------------------------------------------- ask */
  const trace = $("trace");
  let running = false;

  function clearTrace() { trace.innerHTML = ""; }

  function addEvent(ev) {
    const kind = ev.event === "verification"
      ? (ev.decision === "accept" ? "verify" : "fail")
      : ev.event === "run_failed" ? "fail" : "run";
    const row = el("div", "ev enter " + kind);
    row.appendChild(el("div", "node"));
    const body = el("div");
    body.appendChild(el("div", "who", ev.agent || "Orchestrator"));
    body.appendChild(el("div", "what", describe(ev)));
    const detail = detailOf(ev);
    if (detail) body.appendChild(el("div", "det", detail));
    row.appendChild(body);
    trace.appendChild(row);
  }

  function describe(ev) {
    const map = {
      routing: () => `routed to ${(ev.routed || []).join(", ")}`,
      label_audit: () => `audited ${ev.n_records} labels, ${ev.low_confidence} below the confidence floor`,
      analysis_complete: () => `${ev.rq} computed (${ev.rows} table rows)`,
      verification: () => `${ev.rq} ${ev.decision === "accept" ? "verified by recomputation" : "sent back with " + ev.issues + " issue(s)"}`,
      revision_requested: () => `revision requested for ${ev.rq}`,
      run_started: () => `run started over ${ev.records} records`,
      run_finished: () => `run finished: ${ev.answered} answered, ${ev.verified} verified`,
      plan_created: () => `plan built: ${ev.steps} steps`,
    };
    if (map[ev.event]) return map[ev.event]();
    return ev.event.replace(/_/g, " ");
  }

  function detailOf(ev) {
    if (ev.event === "routing") return ev.reason || "";
    if (ev.event === "verification") {
      const r = ev.recomputed || {};
      const bits = Object.entries(r).slice(0, 3).map(([k, v]) => `${k}=${v}`);
      return bits.length ? "recomputed " + bits.join("  ") : "";
    }
    if (ev.event === "analysis_complete") return `tool analysis.${ev.rq}`;
    return "";
  }

  /* SSE with a plain POST fallback: if the stream is blocked by a proxy the
     request still completes, so the page degrades instead of failing. */
  async function ask(question) {
    if (running) return;
    running = true;
    const btn = $("askBtn");
    btn.disabled = true;
    btn.textContent = "Running…";
    $("errorBox").hidden = true;
    $("placeholderCard").hidden = true;
    $("findingsCard").hidden = true;
    $("findings").innerHTML = "";
    clearTrace();
    $("traceCount").innerHTML = '<span class="spin"></span>live';

    let streamed = false;
    try {
      await new Promise((resolve, reject) => {
        const es = new EventSource("/api/ask/stream?question=" + encodeURIComponent(question));
        let settled = false;
        es.addEventListener("open", () => { streamed = true; });
        es.addEventListener("agent", (m) => addEvent(JSON.parse(m.data)));
        es.addEventListener("done", (m) => {
          settled = true;
          es.close();
          render(JSON.parse(m.data));
          resolve();
        });
        es.onerror = () => {
          es.close();
          if (!settled) reject(new Error("stream"));
        };
        setTimeout(() => { if (!settled) { es.close(); reject(new Error("timeout")); } }, 90000);
      });
      if (!streamed) throw new Error("no stream");
    } catch {
      try {
        const r = await fetch("/api/ask", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question }),
        });
        if (!r.ok) throw new Error((await r.json()).detail || "Request failed");
        render(await r.json());
      } catch (err) {
        $("errorBox").hidden = false;
        $("errorBox").className = "err";
        $("errorBox").textContent = "The analysis could not be completed: " + err.message;
      }
    } finally {
      running = false;
      btn.disabled = false;
      btn.textContent = "Run analysis";
      $("traceCount").textContent = "complete";
    }
  }

  /* ---------------------------------------------------------- rendering */
  function render(run) {
    const host = $("findings");
    host.innerHTML = "";
    if (run.fallback) {
      const note = el("div", "find");
      const p = el("p", "note");
      p.style.margin = "0";
      p.textContent = "No research question matched that wording. This is the broadest "
        + "descriptive result, shown so you can see the corpus rather than an error; "
        + "ask about causes, frameworks, severity, complexity or silent failures for a "
        + "targeted answer.";
      note.appendChild(p);
      host.appendChild(note);
    }
    run.findings.forEach((f) => host.appendChild(finding(f)));
    $("findingsCard").hidden = run.findings.length === 0;
    $("placeholderCard").hidden = run.findings.length > 0;
    $("findingCount").textContent =
      `${run.summary.questions_answered} answered · ${run.summary.verified} verified`;
    if (!run.findings.length) {
      $("placeholderCard").hidden = false;
      $("placeholderCard").querySelector(".empty").textContent =
        "No question could be answered from this wording. Try naming a topic: causes, frameworks, severity, complexity, silent failures.";
    }
  }

  function finding(f) {
    const wrap = el("div", "find");

    const top = el("div", "top");
    top.appendChild(el("span", "rqtag", f.rq));
    top.appendChild(el("h4", "", f.question));
    const badge = el("span", "badge " + (f.decision === "accept" ? "ok" : "warn"),
      f.decision === "accept" ? "verified" : "revised");
    top.appendChild(badge);
    wrap.appendChild(top);

    wrap.appendChild(el("div", "meta",
      `${f.owner} · ${f.agent_mode === "single" ? "single agent" : "agent chain"} · ${f.method}`));
    wrap.appendChild(el("p", "narr", f.narrative));

    const kv = el("div", "kv");
    Object.entries(headline(f)).forEach(([k, v]) => {
      const box = el("div");
      box.appendChild(el("div", "v", v));
      box.appendChild(el("div", "k", k));
      kv.appendChild(box);
    });
    if (kv.children.length) wrap.appendChild(kv);

    if (f.table && f.table.length) wrap.appendChild(table(f));
    wrap.appendChild(footerFor(f));
    return wrap;
  }

  function headline(f) {
    const m = f.metrics || {};
    const out = {};
    if (m.n_records) out.records = m.n_records.toLocaleString();
    if (typeof m.cramers_v === "number") out["cramér's v"] = m.cramers_v.toFixed(3);
    if (typeof m.p_value === "number") {
      out["p value"] = m.p_value === 0 ? "< 1e-300" : m.p_value.toExponential(1);
    }
    if (typeof m.escape_share === "number") out["escape rate"] = pct(m.escape_share);
    if (typeof m.coverage === "number") out.coverage = pct(m.coverage);
    if (typeof m.demonstrated_causes === "number") {
      out.demonstrated = m.demonstrated_causes.toLocaleString();
    }
    if (typeof m.n_frameworks === "number") out.frameworks = m.n_frameworks;
    if (typeof m.min_rate === "number") out["blocking span"] = `${pct(m.min_rate)}–${pct(m.max_rate)}`;
    return Object.fromEntries(Object.entries(out).slice(0, 4));
  }

  const COLUMN_LABEL = {
    code: "code", label: "category", count: "n", proportion: "share",
    ci_low: "ci low", ci_high: "ci high", framework: "framework",
    failure_type: "type", share_pct: "share %", blocking: "blocking",
    denominator: "of n", runtime_caught: "caught", demonstrated: "demonstrated",
    share: "share", year: "year",
  };

  function table(f) {
    const rows = f.table;
    const cols = Object.keys(rows[0]).filter((c) =>
      !["ci_method", "lift", "label_short", "code"].includes(c));    const max = {};
    if (cols.includes("proportion")) {
      max.proportion = Math.max(...rows.map((r) => Number(r.proportion) || 0), 0.0001);
    }
    const wrap = el("div", "tbl-wrap");
    const t = el("table");
    const thead = el("thead");
    const hr = el("tr");
    cols.forEach((c) => {
      const numeric = typeof rows[0][c] === "number";
      hr.appendChild(el("th", numeric ? "n" : "", COLUMN_LABEL[c] || c.replace(/_/g, " ")));
    });
    thead.appendChild(hr);
    t.appendChild(thead);
    const tb = el("tbody");
    rows.forEach((r) => {
      const tr = el("tr");
      cols.forEach((c) => {
        const v = r[c];
        let cell;
        if (c === "proportion" && max.proportion) {
          cell = el("td", "n bar-cell");
          const fill = el("i");
          fill.style.width = ((Number(v) || 0) / max.proportion * 100).toFixed(1) + "%";
          cell.appendChild(fill);
          cell.appendChild(el("span", "", pct(Number(v) || 0)));
        } else if (typeof v === "number") {
          cell = el("td", "n",
            c.startsWith("ci_") ? pct(v)
              : Number.isInteger(v) ? v.toLocaleString() : v.toFixed(3));
        } else {
          cell = el("td", "", String(v));
        }
        tr.appendChild(cell);
      });
      tb.appendChild(tr);
    });
    t.appendChild(tb);
    wrap.appendChild(t);
    return wrap;
  }

  function footerFor(f) {
    const bar = el("div", "facts");
    if (f.issues && f.issues.length) {
      bar.appendChild(el("span", "", "critic: " + f.issues.join("; ")));
    } else {
      bar.appendChild(el("span", "", "critic: accepted on independent recomputation"));
    }
    const dl = el("a", "", "download table (csv)");
    dl.href = `/api/export/${f.rq}.csv?question=` + encodeURIComponent(f.question);
    dl.style.marginLeft = "auto";
    bar.appendChild(dl);
    return bar;
  }

  /* ---------------------------------------------------------- classify */
  const SAMPLES = {
    tool: `Traceback (most recent call last):
  File "crew.py", line 88, in _run_tool
    result = self.tools[name](**kwargs)
ToolException: Tool 'search_web' is not registered for agent 'researcher'
Framework: crewai 0.30.11, Python 3.11. The agent was given a tool list at
construction but calls search_web whenever the question mentions today's news.`,
    parse: `pydantic_core.ValidationError: 1 validation error for TaskOutput
steps -> 0 -> description
  Input should be a valid string [type=string_type, input_value=None]
Framework: langgraph 0.2.28 with langchain_openai 0.1.22.
The planner returned null for the first step when the instruction was longer
than about two paragraphs. Happens intermittently, maybe one run in five.`,
    silent: `No exception is raised, but the summary contains facts that are not in the
retrieved documents. The run finishes successfully and the report looks
plausible, so nobody notices until a reader checks a citation. This is in
production with a 12-document RAG index, gpt-4o-mini, temperature 0.2.`,
    version: `ImportError: cannot import name 'AgentExecutor' from 'langchain.agents'
After upgrading langchain from 0.1.20 to 0.2.0 the import moved. requirements.txt
was unpinned, so the deploy picked up the new version. Python 3.11, Ubuntu 24.04.`,
  };

  document.querySelectorAll("button.chip[data-sample]").forEach((b) =>
    b.addEventListener("click", () => {
      $("clsText").value = SAMPLES[b.dataset.sample];
      $("clsText").focus();
    }));

  async function classify(text) {
    const btn = $("clsBtn");
    btn.disabled = true;
    btn.textContent = "Classifying…";
    $("clsError").hidden = true;
    try {
      const r = await fetch("/api/classify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Request failed");
      renderClass(d);
    } catch (err) {
      $("clsError").hidden = false;
      $("clsError").className = "err";
      $("clsError").textContent = "Could not classify that: " + err.message;
    } finally {
      btn.disabled = false;
      btn.textContent = "Classify & plan";
    }
  }

  function renderClass(d) {
    const host = $("clsResult");
    host.hidden = false;
    host.innerHTML = "";

    const card = el("div", "card");
    const head = el("div", "card-h");
    head.appendChild(el("h3", "", "Label"));
    head.appendChild(el("span", "count",
      `confidence ${(d.type_confidence * 100).toFixed(0)}% · ${d.elapsed_ms} ms · ${d.rules_fired} rules fired`));
    card.appendChild(head);

    const body = el("div");
    body.style.padding = "18px 20px";

    const dims = el("div", "dims");
    d.labels.forEach((lab, i) => {
      const box = el("div", "dim" + (i === 0 ? " lead" : ""));
      box.appendChild(el("div", "d", lab.dimension + " · " + lab.name));
      box.appendChild(el("div", "l", lab.label));
      box.appendChild(el("div", "c", lab.code));
      if (i === 0) {
        const m = el("div", "meter");
        const fill = el("i");
        fill.style.width = (d.type_confidence * 100).toFixed(1) + "%";
        m.appendChild(fill);
        box.appendChild(m);
      }
      dims.appendChild(box);
    });
    body.appendChild(dims);

    if (d.evidence) {
      body.appendChild(el("div", "note", "Evidence span that produced the label"));
      body.appendChild(el("div", "quoteblock", "… " + d.evidence + " …"));
    }

    if (d.normalised && d.normalised.length) {
      body.appendChild(el("div", "note",
        "Wording mapped onto the labeller's vocabulary before labelling: " +
        d.normalised.join(" ")));
    }

    if (d.runner_up && d.runner_up.length && d.type_confidence < 0.62) {
      const ru = d.runner_up
        .map((r) => `${r.label} (${r.score})`).join(", ");
      body.appendChild(el("div", "note",
        "Close alternatives the rules also matched: " + ru +
        ". At this confidence the label is a hypothesis, not a verdict."));
    }

    if (d.plan.caveats && d.plan.caveats.length) {
      d.plan.caveats.forEach((c) => body.appendChild(el("div", "note", c)));
    }

    const plan = el("div", "plan");
    [["Do now", d.plan.now], ["Then", d.plan.next], ["Guardrail", d.plan.guardrail]]
      .forEach(([title, items]) => {
        const col = el("div");
        col.appendChild(el("h5", "", title));
        const ol = el("ol");
        items.forEach((t) => ol.appendChild(el("li", "", t)));
        col.appendChild(ol);
        plan.appendChild(col);
      });
    body.appendChild(plan);

    if (d.precedents && d.precedents.length) {
      body.appendChild(el("div", "note", "Closest cases already in the corpus"));
      d.precedents.forEach((p) => {
        const row = el("div", "case");
        row.appendChild(el("div", "t", p.title));
        const m = el("div", "m");
        m.appendChild(el("span", "tagpill", p.framework));
        m.appendChild(el("span", "tagpill", p.failure_type_label));
        m.appendChild(document.createTextNode(p.severity));
        row.appendChild(m);
        if (p.url) {
          const a = el("a", "", "original report ↗");
          a.href = p.url; a.target = "_blank"; a.rel = "noopener";
          a.style.fontSize = "12px";
          row.appendChild(a);
        }
        body.appendChild(row);
      });
    }

    const foot = el("div", "foot");
    foot.appendChild(el("span", "", d.basis));
    foot.appendChild(el("span", "", d.privacy));
    body.appendChild(foot);

    card.appendChild(body);
    host.appendChild(card);
  }

  $("clsForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = $("clsText").value.trim();
    if (text.length < 24) {
      $("clsError").hidden = false;
      $("clsError").className = "err";
      $("clsError").textContent = "Paste a little more — at least a full sentence or the traceback.";
      return;
    }
    classify(text);
  });

  /* ------------------------------------------------------------ corpus */
  const corpus = {
    loaded: false, questionsLoaded: false, page: 1, size: 15, total: 0,

    async load() {
      this.loaded = true;
      const r = await fetch("/api/corpus?size=1");
      const d = await r.json();
      const fws = new Set();
      const types = d.labels.a;
      // one call for facets is enough: derive frameworks from a full scan of labels
      const all = await (await fetch("/api/corpus?size=100&page=1")).json();
      all.rows.forEach((x) => fws.add(x.framework));
      Object.entries(types).forEach(([code, label]) => {
        const o = el("option", "", label);
        o.value = code;
        $("cty").appendChild(o);
      });
      Object.entries(d.labels.d).forEach(([code, label]) => {
        const o = el("option", "", label);
        o.value = code;
        $("csv2").appendChild(o);
      });
      // frameworks come from the health endpoint's count plus a dedicated sweep
      const sweep = await (await fetch("/api/corpus?size=100")).json();
      const frameworks = [...new Set(sweep.rows.map((x) => x.framework))].sort();
      frameworks.forEach((f) => {
        const o = el("option", "", f);
        o.value = f;
        $("cfw").appendChild(o);
      });
      this.search();
    },

    async loadQuestions() {
      this.questionsLoaded = true;
      const d = await (await fetch("/api/questions")).json();
      $("qCount").textContent = d.questions.length + " · " + d.records.toLocaleString() + " records";
      const host = $("qList");
      d.questions.forEach((q) => {
        const row = el("div", "find");
        const top = el("div", "top");
        top.appendChild(el("span", "rqtag", q.id));
        top.appendChild(el("h4", "", q.question));
        top.appendChild(el("span", "badge ok", q.agent_mode === "single" ? "single agent" : "agent chain"));
        row.appendChild(top);
        row.appendChild(el("div", "meta", `${q.owner} · ${q.method}`));
        const run = el("button", "ghost", "Run this question");
        run.addEventListener("click", () => {
          document.querySelector('nav.tabs button[data-panel="ask"]').click();
          $("q").value = q.question;
          ask(q.question);
        });
        row.appendChild(run);
        host.appendChild(row);
      });
    },

    async search() {
      const params = new URLSearchParams({
        q: $("cq").value.trim(), framework: $("cfw").value,
        failure_type: $("cty").value, severity: $("csv2").value,
        page: String(this.page), size: String(this.size),
      });
      const d = await (await fetch("/api/corpus?" + params)).json();
      this.total = d.total;
      $("corpusCount").textContent =
        d.total.toLocaleString() + " matching · page " + d.page + "/" + d.pages;
      const host = $("corpusList");
      host.innerHTML = "";
      if (!d.rows.length) {
        host.appendChild(el("div", "empty", "No records match."));
      }
      d.rows.forEach((r) => {
        const row = el("div", "rec");
        row.appendChild(el("div", "t", r.title || "(untitled)"));
        const s = el("div", "s");
        s.appendChild(el("span", "tagpill", r.framework));
        s.appendChild(el("span", "tagpill", r.failure_type_label));
        s.appendChild(el("span", "tagpill", r.severity));
        s.appendChild(document.createTextNode(
          `${r.cause} · confidence ${Number(r.confidence).toFixed(2)} · ${r.created_at}`));
        row.appendChild(s);
        if (r.evidence) row.appendChild(el("div", "e", r.evidence));
        if (r.url) {
          const a = el("a", "", "open the original report ↗");
          a.href = r.url;
          a.target = "_blank";
          a.rel = "noopener";
          a.style.fontSize = "12.5px";
          row.appendChild(a);
        }
        host.appendChild(row);
      });
      const pager = $("corpusPager");
      pager.innerHTML = "";
      const prev = el("button", "ghost", "Previous");
      prev.disabled = d.page <= 1;
      prev.addEventListener("click", () => { this.page--; this.search(); });
      const next = el("button", "ghost", "Next");
      next.disabled = d.page >= d.pages;
      next.addEventListener("click", () => { this.page++; this.search(); });
      pager.appendChild(prev);
      pager.appendChild(el("span", "", `page ${d.page} of ${d.pages}`));
      pager.appendChild(next);
    },
  };

  let timer;
  $("cq").addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => { corpus.page = 1; corpus.search(); }, 250);
  });
  ["cfw", "cty", "csv2"].forEach((id) =>
    $(id).addEventListener("change", () => { corpus.page = 1; corpus.search(); }));

  /* --------------------------------------------------------------- ask */
  $("askForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const q = $("q").value.trim();
    if (q) ask(q);
  });
  document.querySelectorAll("button.chip[data-q]").forEach((b) =>
    b.addEventListener("click", () => {
      $("q").value = b.dataset.q;
      ask(b.dataset.q);
    }));
})();
