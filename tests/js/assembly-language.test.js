"use strict";

const assert = require("node:assert/strict");
const assembly = require("../../app/static/assembly-language.js");

function test(name, callback) {
  try { callback(); process.stdout.write(`ok - ${name}\n`); }
  catch (error) { process.stderr.write(`not ok - ${name}\n${error.stack}\n`); process.exitCode = 1; }
}

test("the MC68000 catalogue lists each mnemonic exactly once", () => {
  const base = assembly.CATALOGUES["68000"];
  assert.equal(new Set(base).size, base.length);
  for (const mnemonic of ["MOVE", "MOVEQ", "LEA", "PEA", "JSR", "RTS", "RTE", "DBRA", "TRAP", "SWAP"]) {
    assert.ok(assembly.isMnemonic("68000", mnemonic), mnemonic);
  }
  // Nothing from another processor family belongs in it.
  for (const mnemonic of ["LDA", "STA", "TAX", "PHA", "LDR", "SWI"]) {
    assert.equal(assembly.isMnemonic("68000", mnemonic), false, mnemonic);
  }
});

test("each processor adds only what its own generation introduced", () => {
  assert.equal(assembly.isMnemonic("68000", "MOVEC"), false);
  assert.ok(assembly.isMnemonic("68010", "MOVEC"));
  assert.equal(assembly.isMnemonic("68010", "BFINS"), false);
  assert.ok(assembly.isMnemonic("68020", "BFINS"));
  assert.equal(assembly.isMnemonic("68020", "PFLUSH"), false);
  assert.ok(assembly.isMnemonic("68030", "PFLUSH"));
  assert.equal(assembly.isMnemonic("68030", "MOVE16"), false);
  assert.ok(assembly.isMnemonic("68040", "MOVE16"));
  assert.equal(assembly.isMnemonic("68040", "LPSTOP"), false);
  assert.ok(assembly.isMnemonic("68060", "LPSTOP"));
});

test("every later catalogue is a superset of the one before it", () => {
  const order = ["68000", "68010", "68020", "68030", "68040", "68060"];
  order.slice(1).forEach((processor, index) => {
    const earlier = new Set(assembly.CATALOGUES[order[index]]);
    const later = new Set(assembly.CATALOGUES[processor]);
    for (const mnemonic of earlier) assert.ok(later.has(mnemonic), `${processor} lost ${mnemonic}`);
    assert.ok(later.size > earlier.size, `${processor} added nothing`);
  });
});

test("the floating-point overlay belongs to the coprocessor, not the 68030", () => {
  // A TT or Falcon has a 68030; the 68881 or 68882 is an option on it.
  for (const mnemonic of ["FMOVE", "FADD", "FSUB", "FMUL", "FDIV", "FCMP", "FTST", "FBEQ", "FDBEQ", "FSEQ", "FNOP", "FSAVE", "FRESTORE", "FMOVEM", "FSQRT", "FABS", "FNEG", "FINT", "FINTRZ", "FSIN", "FCOS", "FTAN", "FATAN", "FLOGN", "FLOG10", "FETOX", "FTWOTOX", "FTENTOX", "FGETEXP", "FGETMAN", "FSCALE", "FMOD", "FREM", "FSGLDIV", "FSGLMUL"]) {
    assert.ok(assembly.isFpuMnemonic(mnemonic), mnemonic);
    assert.equal(assembly.isMnemonic("68030", mnemonic), false, `${mnemonic} on a bare 68030`);
    assert.ok(assembly.isMnemonic("68030", mnemonic, true), `${mnemonic} with the FPU flag`);
    assert.ok(assembly.isMnemonic("68030+fpu", mnemonic), `${mnemonic} on 68030+fpu`);
    assert.ok(assembly.isMnemonic("68040", mnemonic), `${mnemonic} on the 68040's own unit`);
  }
  assert.equal(assembly.isMnemonic("68030-fpu", "FMOVE"), false);
  assert.ok(assembly.isMnemonic("68030+fpu", "PFLUSH"));
  assert.equal(assembly.isMnemonic("68000+fpu", "PFLUSH"), false);
});

test("an unknown processor falls back to the baseline 68000", () => {
  assert.ok(assembly.isMnemonic("something-else", "MOVE"));
  assert.equal(assembly.isMnemonic("something-else", "MOVEC"), false);
});
