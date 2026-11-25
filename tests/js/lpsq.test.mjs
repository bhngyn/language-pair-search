// Parity test: js/lpsq.mjs against golden vectors produced by this checkout's Python package.
// Generate: python scripts/golden.py      Run: node --test 'tests/js/*.test.mjs'
import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import * as lpsq from "../../js/lpsq.mjs";

const GOLDEN = fileURLToPath(new URL("../golden/lps_query.json", import.meta.url));
if (!existsSync(GOLDEN)) throw new Error("tests/golden/lps_query.json is missing: run `python scripts/golden.py` first");
const golden = JSON.parse(readFileSync(GOLDEN, "utf8"));

function run(fn) {
  try {
    return fn();
  } catch (e) {
    if (e instanceof lpsq.LpsQueryError) return { error: e.pyType };
    return { error: "JS:" + (e && e.name) + ": " + (e && e.message) };
  }
}

const show = (v) => JSON.stringify(v);
const cp = (c) => "U+" + c.toString(16).toUpperCase().padStart(4, "0");

function check(name, rows, describe, compute, expectedOf) {
  const bad = [];
  for (const row of rows) {
    const got = run(() => compute(row));
    const want = expectedOf(row);
    // JSON text equality: also catches key-order differences in expand() objects
    if (show(got) !== show(want)) bad.push({ input: describe(row), want, got });
  }
  if (bad.length) {
    const lines = bad.slice(0, 20).map((b, i) =>
      `  ${i + 1}. ${b.input}\n     python: ${show(b.want)}\n     js:     ${show(b.got)}`);
    assert.fail(`${name}: ${bad.length}/${rows.length} mismatches (first ${Math.min(20, bad.length)}):\n${lines.join("\n")}`);
  }
}

test("meta: versions match the golden file", () => {
  assert.equal(lpsq.KEY_VERSION, golden.meta.KEY_VERSION, "KEY_VERSION changed: re-port js/lpsq.mjs (README)");
  assert.equal(lpsq.FTS_VERSION, golden.meta.FTS_VERSION, "FTS_VERSION changed: re-port js/lpsq.mjs (README)");
  assert.equal(lpsq.ROMAN_PREFIX, golden.meta.ROMAN_PREFIX);
});

test("Unicode tables equal Python's", () => {
  assert.deepEqual(lpsq._internal.TABLES, golden.tables);
});

test("hand-copied lps constants equal Python's", () => {
  const js = lpsq._internal.constants();
  for (const [k, v] of Object.entries(golden.constants)) assert.deepStrictEqual(js[k], v, `constant ${k} differs`);
  assert.deepStrictEqual(Object.keys(js).sort(), Object.keys(golden.constants).sort());
});

test("normalize", () => {
  check("normalize", golden.normalize, ([t]) => show(t), ([t]) => lpsq.normalize(t), ([, o]) => o);
});

test("matchKey", () => {
  check("match_key", golden.match_key, ([t]) => show(t), ([t]) => lpsq.matchKey(t), ([, o]) => o);
});

test("ftsQuery", () => {
  check("fts_query", golden.fts_query, ([q]) => show(q), ([q]) => lpsq.ftsQuery(q), ([, o]) => o);
});

test("ftsScoped", () => {
  check("fts_scoped", golden.fts_scoped, ([e, t, n]) => show([e, t, n]), ([e, t, n]) => lpsq.ftsScoped(e, t, n),
    (r) => r[3]);
});

test("expand (no dictionary)", () => {
  check("expand", golden.expand, ([q, o]) => show(q) + (Object.keys(o).length ? " " + show(o) : ""),
    ([q, o]) => lpsq.expand(q, o), ([, , out]) => out);
});

test("code-point sweep: normalize(ch), matchKey('ab'+ch+'cd'), ftsQuery('ab'+ch+'cd')", () => {
  check("codepoints", golden.codepoints, ([c]) => cp(c), ([c]) => {
    const ch = String.fromCodePoint(c);
    return [c, lpsq.normalize(ch), lpsq.matchKey("ab" + ch + "cd"), lpsq.ftsQuery("ab" + ch + "cd")];
  }, (r) => r);
});

test("summary", () => {
  const n = ["normalize", "match_key", "fts_query", "fts_scoped", "expand", "codepoints"]
    .reduce((s, k) => s + golden[k].length, 0);
  console.log(`golden vectors: ${n} (KEY_VERSION ${golden.meta.KEY_VERSION}, Python ${golden.meta.python}, `
    + `Unicode ${golden.meta.unidata_version}; Node ${process.versions.node}, Unicode ${process.versions.unicode})`);
});
