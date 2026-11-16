#!/usr/bin/env node
/*
 * The landing page has its own little checker, and it must agree with the
 * Python one. This script lifts the <script> block out of site/index.html,
 * runs it against a stub DOM, and asserts the same cases the Python tests
 * assert. Run it with `node tools/check_site.js`; tests/test_site.py does that
 * for you when node is installed.
 */

const fs = require("fs");
const path = require("path");

const root = path.dirname(__dirname);
const html = fs.readFileSync(path.join(root, "site", "index.html"), "utf8");

const start = html.indexOf("<script>");
const end = html.indexOf("</script>", start);
if (start < 0 || end < 0) {
  console.error("no <script> block found in site/index.html");
  process.exit(1);
}
const script = html.slice(start + "<script>".length, end);

const stub = `
var document = { getElementById: function () { return { value: "0", innerHTML: "" }; } };
`;
const api = new Function(
  stub + script + "\nreturn { evaluate: evaluate, money: money, amount: amount };"
)();

let failures = 0;
let checks = 0;

function eq(label, got, want) {
  checks++;
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) {
    failures++;
    console.log(`FAIL ${label}: got ${JSON.stringify(got)} want ${JSON.stringify(want)}`);
  }
}

// --- amount parsing, same cases as tests/test_money.py -----------------------
eq("plain", api.amount("67200.00"), 67200);
eq("indian grouping", api.amount("1,23,456.00"), 123456);
eq("rupee sign", api.amount("\u20b9 2,400.50"), 2400.5);
eq("trailing /-", api.amount("1,23,456/-"), 123456);
eq("negative round off", api.amount("-0.60"), -0.6);
eq("parentheses negative", api.amount("(1,234.00)"), -1234);
eq("empty is null", api.amount(""), null);

// --- formatting, must match billcheck.money.format_inr -----------------------
eq("format 71628", api.money(71628), "71,628.00");
eq("format 1234567.5", api.money(1234567.5), "12,34,567.50");
eq("format 100000", api.money(100000), "1,00,000.00");
eq("format -0.6", api.money(-0.6), "-0.60");
eq("format 999", api.money(999), "999.00");

// --- the three checks --------------------------------------------------------
function check(input, key) {
  return api.evaluate(input).checks.find((c) => c.key === key).status;
}

const broken = {
  taxable: "67,200.00", cgst: "2,226.00", sgst: "2,214.00",
  igst: "0.00", round: "0.00", total: "71,640.00",
};
eq("broken: verdict", api.evaluate(broken).verdict, "BROKEN");
eq("broken: the total still reconciles", check(broken, "total_reconciles"), "pass");
eq("broken: the split fails", check(broken, "tax_split"), "fail");

const clean = {
  taxable: "67,200.00", cgst: "2,214.00", sgst: "2,214.00",
  igst: "0.00", round: "0.00", total: "71,628.00",
};
eq("clean: verdict", api.evaluate(clean).verdict, "CLEAN");

const rounded = {
  taxable: "67,200.00", cgst: "2,214.30", sgst: "2,214.30",
  igst: "0.00", round: "-0.60", total: "71,628.00",
};
eq("round off: verdict", api.evaluate(rounded).verdict, "CLEAN");

const mixed = {
  taxable: "100.00", cgst: "9.00", sgst: "9.00",
  igst: "18.00", round: "0.00", total: "136.00",
};
eq("igst mixed with cgst: verdict", api.evaluate(mixed).verdict, "BROKEN");

const wrongTotal = {
  taxable: "67,200.00", cgst: "2,214.00", sgst: "2,214.00",
  igst: "0.00", round: "0.00", total: "71,700.00",
};
eq("wrong total: verdict", api.evaluate(wrongTotal).verdict, "BROKEN");
eq("wrong total: the total check fails", check(wrongTotal, "total_reconciles"), "fail");

const noTotal = {
  taxable: "67,200.00", cgst: "2,214.00", sgst: "2,214.00",
  igst: "0.00", round: "0.00", total: "",
};
eq("no total: skipped", check(noTotal, "total_reconciles"), "skip");
eq("no total: still clean on the split", api.evaluate(noTotal).verdict, "CLEAN");

if (failures) {
  console.log(`\n${failures} of ${checks} site checks failed`);
  process.exit(1);
}
console.log(`site ok: ${checks} checks`);
