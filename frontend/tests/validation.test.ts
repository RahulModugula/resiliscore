import assert from "node:assert/strict";
import test from "node:test";
import report from "../../contracts/validation_report.json";
import flood from "./fixtures/validation-flood.json";
import { parseValidationReport } from "../src/lib/validation";

test("the bundled report and populated flood sections meet the shared contract", () => {
  assert.deepEqual(parseValidationReport(report), report);
  assert.equal(parseValidationReport({ ...report, flood }).flood?.verdict, flood.verdict);
});

test("pending sections and missing fitted results remain null", () => {
  const pending = parseValidationReport({ ...report, status: "PENDING", flood: null, wildfire: null, benchmarks: [] });
  assert.equal(pending.flood, null);
  assert.equal(pending.wildfire, null);
  assert.deepEqual(pending.benchmarks, []);
});

test("schema defaults normalize omitted optional sections before rendering", () => {
  const minimal = { schema_version: report.schema_version, generated_at: report.generated_at, model_commit: report.model_commit, status: "PENDING", model_card: report.model_card };
  const normalized = parseValidationReport(minimal);
  assert.equal(normalized.flood, null);
  assert.equal(normalized.wildfire, null);
  assert.deepEqual(normalized.benchmarks, []);
});

test("malformed reports cannot replace the bundled evidence", () => {
  assert.throws(() => parseValidationReport({ ...report, model_card: {} }), /validation contract/);
  assert.throws(() => parseValidationReport({ ...report, flood: { ...flood, severity_by_depth: [{ ...flood.severity_by_depth[0], observed_mean_dr: "unknown" }] } }), /validation contract/);
});
