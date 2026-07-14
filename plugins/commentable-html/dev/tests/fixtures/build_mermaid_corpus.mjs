// Generates tests/fixtures/mermaid-corpus.json: a broad, real-parser-labeled
// corpus used to PROVE the shipped Python mermaid checker has zero false
// positives (it must never flag a diagram the real parser accepts) and still
// catches the target bug classes.
//
// Each authored entry carries `py_flag`: whether the Python checker is EXPECTED
// to flag it. The real parser stamps `valid`. Invariants enforced here:
//   - py_flag === true  implies the real parser says INVALID (we never flag valid).
//   - the file is deterministic (sorted, stable) so `--check` can gate drift.
//
//   node tests/fixtures/build_mermaid_corpus.mjs           # (re)write the corpus
//   node tests/fixtures/build_mermaid_corpus.mjs --check   # fail if out of date

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { makeValidator } from "../../tools/validate_render.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(__dirname, "mermaid-corpus.json");

// --- Authored diagrams. kind defaults to "mermaid". -----------------------
const ENTRIES = [
  // ---- valid sequence diagrams (must never be flagged) ----
  { name: "seq-basic", py_flag: false, src: "sequenceDiagram\n  A->>B: hello" },
  { name: "seq-two-signals-semicolon", py_flag: false, src: "sequenceDiagram\n  A->>B: hi; C->>D: bye" },
  { name: "seq-semicolon-then-activate", py_flag: false, src: "sequenceDiagram\n  A->>B: hi; activate B\n  deactivate B" },
  { name: "seq-semicolon-then-note", py_flag: false, src: "sequenceDiagram\n  A->>B: hi; Note right of B: thinking" },
  { name: "seq-semicolon-then-participant", py_flag: false, src: "sequenceDiagram\n  A->>B: hi; participant C" },
  { name: "seq-arrow-in-message", py_flag: false, src: "sequenceDiagram\n  A->>B: project observations -> TceBehaviorInfo" },
  { name: "seq-arrow-in-message-double", py_flag: false, src: "sequenceDiagram\n  A->>B: maps ActionType --> observation type" },
  { name: "seq-colon-in-message", py_flag: false, src: "sequenceDiagram\n  A->>B: the ratio is 3:1 across runs" },
  { name: "seq-trailing-semicolon", py_flag: false, src: "sequenceDiagram\n  A->>B: hello;" },
  { name: "seq-inline-comment", py_flag: false, src: "sequenceDiagram\n  A->>B: hello  %% reuses the same store" },
  { name: "seq-async-arrow", py_flag: false, src: "sequenceDiagram\n  A-)B: async ping" },
  { name: "seq-cross-arrow", py_flag: false, src: "sequenceDiagram\n  A-xB: lost message" },
  { name: "seq-activation-plusminus", py_flag: false, src: "sequenceDiagram\n  A->>+B: open\n  B-->>-A: close" },
  { name: "seq-loop-alt-opt", py_flag: false, src: "sequenceDiagram\n  loop every minute\n    A->>B: poll\n  end\n  alt ok\n    B->>A: 200\n  else fail\n    B->>A: 500\n  end" },
  { name: "seq-par-and", py_flag: false, src: "sequenceDiagram\n  par to B\n    A->>B: x\n  and to C\n    A->>C: y\n  end" },
  { name: "seq-autonumber-title", py_flag: false, src: "sequenceDiagram\n  autonumber\n  title My Flow\n  A->>B: hi" },
  { name: "seq-box", py_flag: false, src: "sequenceDiagram\n  box Purple Group\n    participant A\n    participant B\n  end\n  A->>B: hi" },
  { name: "seq-frontmatter", py_flag: false, src: "---\ntitle: Flow\n---\nsequenceDiagram\n  A->>B: hi" },
  { name: "seq-init-directive", py_flag: false, src: "%%{init: {'theme':'dark'}}%%\nsequenceDiagram\n  A->>B: hi" },
  { name: "seq-message-with-parens-brackets", py_flag: false, src: "sequenceDiagram\n  A->>B: GetBehaviorsAsync([\"ProcessInjection\",\"SuspiciousDllLoad\"])" },
  { name: "seq-semicolon-then-signal-then-note", py_flag: false, src: "sequenceDiagram\n  A->>B: hi; C->>D: bye; Note over C,D: done" },

  // ---- invalid sequence diagrams the Python checker SHOULD flag ----
  { name: "seq-bug-original", py_flag: true, src: "sequenceDiagram\n  SEQ->>SEQ: validate against allowlist; map ActionType -> observation CLR type(s)" },
  { name: "seq-semicolon-arrow-no-colon", py_flag: true, src: "sequenceDiagram\n  A->>B: first step; then X -> Y happens" },
  { name: "seq-semicolon-arrow-no-colon-double", py_flag: true, src: "sequenceDiagram\n  A->>B: begin; Z --> W continues here" },
  { name: "seq-semicolon-arrow-async", py_flag: true, src: "sequenceDiagram\n  A->>B: kick off; worker -) queue drains" },

  // ---- invalid sequence the Python checker conservatively SKIPS (safe FN) ----
  { name: "seq-semicolon-bare-word", py_flag: false, src: "sequenceDiagram\n  A->>B: hi; world" },
  { name: "seq-semicolon-prose-tail", py_flag: false, src: "sequenceDiagram\n  A->>B: hi; then two more words" },

  // ---- valid flowcharts (must never be flagged) ----
  { name: "flow-basic", py_flag: false, src: "flowchart TD\n  A --> B --> C" },
  { name: "flow-graph-alias", py_flag: false, src: "graph LR\n  A-->B" },
  { name: "flow-quoted-label", py_flag: false, src: 'flowchart TD\n  A["a label"] --> B["another"]' },
  { name: "flow-arrow-in-quoted-label", py_flag: false, src: 'flowchart TD\n  A["maps x -> y"] --> B' },
  { name: "flow-quot-escape", py_flag: false, src: 'flowchart TD\n  A["say #quot;hi#quot;"] --> B' },
  { name: "flow-edge-label-quotes", py_flag: false, src: 'flowchart LR\n  A -->|"yes, ok"| B\n  A -->|"no"| C' },
  { name: "flow-shapes", py_flag: false, src: 'flowchart TD\n  A[/parallelogram/] --> B[(database)]\n  B --> C{{hexagon}}\n  C --> D[[subroutine]]' },
  { name: "flow-subgraph", py_flag: false, src: 'flowchart TB\n  subgraph one\n    A --> B\n  end\n  subgraph two\n    C --> D\n  end\n  B --> C' },
  { name: "flow-semicolons", py_flag: false, src: "flowchart TD\n  A --> B; B --> C; C --> D" },
  { name: "flow-multiline-many-quotes", py_flag: false, src: 'flowchart TD\n  A["one"] --> B["two"]\n  B --> C["three"]\n  C --> D["four"]' },

  // ---- invalid flowcharts (the Python checker delegates flowchart syntax to the
  //      repo-side oracle, so it does NOT flag these - py_flag stays false; the
  //      oracle still catches them via the real parser) ----
  { name: "flow-unterminated-quote", py_flag: false, src: 'flowchart TD\n  A["unterminated --> B' },
  { name: "flow-unterminated-quote-2", py_flag: false, src: 'flowchart TD\n  A["ok"] --> B["oops --> C' },

  // ---- regression: valid diagrams that EARLIER checker versions false-flagged.
  //      All are accepted by the real parser and must never be flagged. ----
  { name: "fp-acctitle-semicolon-arrow", py_flag: false, src: "sequenceDiagram\n  accTitle: A -> B; overview\n  A->>B: hi" },
  { name: "fp-accdescr-semicolon-arrow", py_flag: false, src: "sequenceDiagram\n  accDescr: A -> B; overview\n  A->>B: hi" },
  { name: "fp-inline-init-directive-semicolon", py_flag: false, src: "sequenceDiagram\n  %%{init: {'theme':'dark'}}%%\n  A->>B: hi; C->>D: bye" },
  { name: "fp-message-inline-directive-semi-arrow", py_flag: false, src: "sequenceDiagram\n  A->>B: msg %%{init: {'foo': ';->'} }%%" },
  { name: "fp-message-trailing-comment-semi-arrow", py_flag: false, src: "sequenceDiagram\n  A->>B: hi %% note; X -> Y" },
  { name: "fp-flow-percent-in-label", py_flag: false, src: 'flowchart TD\n  A["100%% done"] --> B' },
  { name: "fp-flow-slash-literal-quote", py_flag: false, src: 'flowchart LR\n  A[/x " y/] --> B' },
  { name: "fp-flow-subgraph-percent", py_flag: false, src: 'flowchart TD\n  subgraph "Group %% one"\n    A --> B\n  end' },

  // ---- valid other diagram types (Python must skip -> never flag) ----
  { name: "class-basic", py_flag: false, src: "classDiagram\n  Animal <|-- Dog\n  Animal : +int age\n  Animal : +String name" },
  { name: "state-basic", py_flag: false, src: "stateDiagram-v2\n  [*] --> Idle\n  Idle --> Running: start\n  Running --> [*]" },
  { name: "er-basic", py_flag: false, src: "erDiagram\n  CUSTOMER ||--o{ ORDER : places\n  ORDER ||--|{ LINE : contains" },
  { name: "gantt-basic", py_flag: false, src: "gantt\n  title A\n  dateFormat YYYY-MM-DD\n  section S\n  Task :a1, 2024-01-01, 30d" },
  { name: "pie-basic", py_flag: false, src: 'pie title Pets\n  "Dogs" : 40\n  "Cats" : 60' },
  { name: "journey-basic", py_flag: false, src: "journey\n  title My day\n  section Work\n    Code: 5: Me\n    Review: 3: Me" },
  { name: "mindmap-basic", py_flag: false, src: "mindmap\n  root((central))\n    a\n    b" },
  { name: "gitgraph-basic", py_flag: false, src: "gitGraph\n  commit\n  branch dev\n  commit\n  checkout main\n  merge dev" },
  { name: "timeline-basic", py_flag: false, src: "timeline\n  title History\n  2021 : one\n  2022 : two" },
  { name: "quadrant-basic", py_flag: false, src: "quadrantChart\n  title Reach\n  x-axis Low --> High\n  y-axis Low --> High\n  A: [0.3, 0.6]" },
];

async function main() {
  const check = process.argv.includes("--check");
  const v = await makeValidator();
  const rows = [];
  try {
    for (const e of ENTRIES) {
      const kind = e.kind || "mermaid";
      const r = kind === "chart" ? await v.chart(e.src) : await v.mermaid(e.src);
      if (e.py_flag && r.ok) {
        throw new Error(`corpus invariant violated: "${e.name}" is py_flag=true but the real parser ACCEPTS it (would be a false positive)`);
      }
      rows.push({ name: e.name, kind, valid: r.ok, py_flag: !!e.py_flag, src: e.src });
    }
  } finally {
    await v.close();
  }
  rows.sort((a, b) => a.name.localeCompare(b.name));
  const json = JSON.stringify(rows, null, 2) + "\n";
  if (check) {
    const cur = fs.existsSync(OUT) ? fs.readFileSync(OUT, "utf8") : "";
    if (cur !== json) {
      console.error("mermaid-corpus.json is out of date; run: node tests/fixtures/build_mermaid_corpus.mjs");
      return 1;
    }
    console.log(`mermaid-corpus.json up to date (${rows.length} entries)`);
    return 0;
  }
  fs.writeFileSync(OUT, json);
  console.log(`wrote ${OUT} (${rows.length} entries, ${rows.filter((r) => r.py_flag).length} py_flag)`);
  return 0;
}

process.exit(await main());
