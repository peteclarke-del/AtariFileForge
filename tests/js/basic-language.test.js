"use strict";

const assert = require("node:assert/strict");
const basic = require("../../app/static/basic-language.js");

function test(name, callback) {
  try { callback(); process.stdout.write(`ok - ${name}\n`); }
  catch (error) { process.stderr.write(`not ok - ${name}\n${error.stack}\n`); process.exitCode = 1; }
}

test("typed variables that resemble commands remain identifiers", () => {
  const names = ["print%", "load%", "if%", "then%", "else%", "rem%", "goto%", "run%", "for%", "next%", "while%", "end%", "line!", "screen#", "box&", "data|"];
  const tokens = basic.scan(names.map((name, index) => `${name}=${index}`).join(":"), "GFA BASIC 3");
  assert.deepEqual(tokens.filter(token => token.type === "identifier").map(token => token.text), names);
  assert.equal(tokens.some(token => token.type === "keyword"), false);
  assert.equal(tokens.some(token => token.type === "comment"), false);
});

test("real commands beside typed variables retain keyword identity", () => {
  const tokens = basic.scan('page%=1\nIF page%=1\n  PRINT "OK"\nENDIF', "GFA BASIC 3");
  assert.deepEqual(tokens.filter(token => token.type === "keyword").map(token => token.name), ["IF", "PRINT", "ENDIF"]);
  assert.deepEqual(tokens.filter(token => token.type === "identifier").map(token => token.text), ["page%", "page%"]);
});

test("a leading asterisk is multiplication, not a command", () => {
  const tokens = basic.scan("total%=columns%*rows%", "GFA BASIC 3");
  assert.equal(tokens.some(token => token.type === "star-command"), false);
  assert.deepEqual(tokens.filter(token => token.type === "identifier").map(token => token.text), ["total%", "columns%", "rows%"]);
  assert.deepEqual(tokens.filter(token => token.type === "operator").map(token => token.text), ["=", "*"]);
});

test("a GFA BASIC listing exposes every keyword it uses", () => {
  const source = `PROCEDURE draw(w%,h%)
  LOCAL x%,y%
  FOR y%=0 TO h%-1
    FOR x%=0 TO w%-1
      IF x%=0 OR y%=0
        PBOX x%,y%,x%+1,y%+1
      ELSE
        PLOT x%,y%
      ENDIF
    NEXT x%
  NEXT y%
RETURN`;
  const names = basic.scan(source, "GFA BASIC 3").filter(token => token.type === "keyword").map(token => token.name);
  for (const keyword of ["PROCEDURE", "LOCAL", "FOR", "TO", "IF", "OR", "PBOX", "ELSE", "PLOT", "ENDIF", "NEXT", "RETURN"]) {
    assert.ok(names.includes(keyword), `${keyword} was not recognised`);
  }
  assert.equal(names.filter(name => name === "FOR").length, 2);
  assert.equal(names.filter(name => name === "NEXT").length, 2);
});

test("a keyword glued to a name stays part of that name", () => {
  // This is the tokeniser's own rule: FORMAT, PRINTER and TOTAL are variables,
  // so the scanner must not colour a command inside them.
  const tokens = basic.scan("ending%=1\nprinter%=2\ntotal%=3\nformat%=4", "GFA BASIC 3");
  assert.deepEqual(
    tokens.filter(token => token.type === "identifier").map(token => token.text),
    ["ending%", "printer%", "total%", "format%"],
  );
  assert.equal(tokens.some(token => token.type === "keyword"), false);
});

test("every keyword each dialect lists is recognised under its own dialect", () => {
  const banks = [
    ["GFA BASIC 3", basic.GFA_KEYWORDS],
    ["STOS BASIC", basic.STOS_KEYWORDS],
    ["ST BASIC", basic.ST_BASIC_KEYWORDS],
  ];
  for (const [dialect, keywords] of banks) {
    for (const keyword of keywords) {
      const token = basic.scan(keyword, dialect)[0];
      assert.equal(token?.type, "keyword", `${keyword} was not a keyword in ${dialect}`);
      assert.equal(token?.name, keyword, `${keyword} was recognised under the wrong name in ${dialect}`);
    }
  }
});

test("compound keywords are read as one word, not two", () => {
  const stos = basic.scan("10 screen open 0,320,200,16,$0 : curs off : put bob 1,2,3 : music off", "STOS BASIC");
  assert.deepEqual(
    stos.filter(token => token.type === "keyword").map(token => token.name),
    ["SCREEN OPEN", "CURS OFF", "PUT BOB", "MUSIC OFF"],
  );
  const gfa = basic.scan("DO\n  EXIT IF done!\nLOOP\nIF a%\nELSE IF b%\nENDIF", "GFA BASIC 3");
  assert.deepEqual(
    gfa.filter(token => token.type === "keyword").map(token => token.name),
    ["DO", "EXIT IF", "LOOP", "IF", "ELSE IF", "ENDIF"],
  );
  assert.deepEqual(
    basic.scan("10 ON ERROR GOTO 900", "ST BASIC").filter(token => token.type === "keyword").map(token => token.name),
    ["ON ERROR", "GOTO"],
  );
});

test("GFA BASIC 3 keywords are marked as needing the later release", () => {
  assert.equal(basic.KEYWORD_GENERATION.SELECT, 3);
  assert.equal(basic.KEYWORD_GENERATION.ENDFUNC, 3);
  assert.equal(basic.KEYWORD_GENERATION.PRINT, undefined);
  assert.equal(basic.KEYWORD_GENERATION.IF, undefined);
  // The gate compares against the dialect's generation, so only GFA BASIC 2
  // is ever below the bar. Nothing else must be warned about a GFA word.
  assert.equal(basic.dialectProfile("GFA BASIC 2").generation, 2);
  for (const name of ["GFA BASIC 3", "STOS BASIC", "ST BASIC"]) {
    assert.equal(basic.dialectProfile(name).generation, 3, `${name} would be warned about GFA BASIC 3 words`);
  }
  assert.ok(basic.isKeywordToken("SELECT", "GFA BASIC 3"));
  assert.equal(basic.isKeywordToken("SELECT", "GFA BASIC 2"), false);
});

test("every base a dialect writes numbers in scans as a number", () => {
  assert.deepEqual(
    basic.scan("a%=&HDFF180\nb%=&O777\nc%=&X1010", "GFA BASIC 3").filter(token => token.type === "number").map(token => token.text),
    ["&HDFF180", "&O777", "&X1010"],
  );
  // STOS writes hexadecimal with $ and binary with %, and a % that follows a
  // name is that name's type suffix rather than the start of a number.
  assert.deepEqual(
    basic.scan("10 palette $777,%1010 : COUNT=64", "STOS BASIC").filter(token => token.type === "number").map(token => token.text),
    ["$777", "%1010", "64"],
  );
  assert.deepEqual(
    basic.scan("total%=1", "GFA BASIC 3").filter(token => token.type === "identifier").map(token => token.text),
    ["total%"],
  );
});

test("statement splitting respects strings and comments", () => {
  assert.deepEqual(basic.splitStatements('A=1:PRINT "A:B":REM C:D').map(row => row.text), ["A=1", 'PRINT "A:B"', "REM C:D"]);
  assert.deepEqual(basic.splitStatements("x%=a%*b% ! and a GFA comment: here").map(row => row.text), ["x%=a%*b%", "! and a GFA comment: here"]);
  assert.deepEqual(basic.splitStatements("PRINT x%:PRINT y%").map(row => row.text), ["PRINT x%", "PRINT y%"]);
});

test("masking leaves executable code positions stable", () => {
  const source = '10 PRINT "GOTO 90":REM GOTO 80\n20 GOTO 10';
  const masked = basic.maskStringsAndComments(source);
  assert.equal(masked.length, source.length);
  assert.equal(masked.includes("GOTO 90"), false);
  assert.equal(masked.includes("GOTO 80"), false);
  assert.equal(masked.includes("GOTO 10"), true);
  const gfa = "PRINT a$ ! GOSUB nowhere\n@really_call";
  assert.equal(basic.maskStringsAndComments(gfa).includes("GOSUB"), false);
  assert.equal(basic.maskStringsAndComments(gfa).includes("really_call"), true);
});

test("dialect profiles are explicit and default conservatively", () => {
  assert.deepEqual(Object.keys(basic.DIALECTS), ["GFA BASIC 3", "GFA BASIC 2", "STOS BASIC", "ST BASIC"]);
  assert.deepEqual(
    Object.values(basic.DIALECTS).map(profile => profile.id),
    ["gfa-basic-3", "gfa-basic-2", "stos-basic", "st-basic"],
  );
  // STOS is read-only in the Python codec, so the editor must not offer a save.
  assert.equal(basic.DIALECTS["STOS BASIC"].writable, false);
  assert.equal(basic.DIALECTS["GFA BASIC 3"].writable, true);
  assert.equal(basic.DIALECTS["GFA BASIC 3"].lineNumbers, false);
  assert.equal(basic.DIALECTS["ST BASIC"].lineNumbers, true);
  assert.ok(basic.DIALECTS["STOS BASIC"].extensions.includes(".bas"));
  assert.equal(basic.dialectProfile("unknown").id, "gfa-basic-3");
  assert.equal(basic.dialectProfile("stos-basic").id, "stos-basic");
});

test("line numbers are scanned only where the dialect has them", () => {
  assert.equal(basic.scan("10 PRINT", "ST BASIC")[0].type, "line-number");
  assert.equal(basic.scan("10 print", "STOS BASIC")[0].type, "line-number");
  // GFA BASIC has no line numbers, so a leading number is arithmetic.
  assert.equal(basic.scan("10 PRINT", "GFA BASIC 3")[0].type, "number");
  const line = basic.scanLine("20 GOTO 10", 100, { dialect: "ST BASIC" });
  assert.equal(line.tokens[0].start, 100);
  assert.equal(line.tokens[0].end, 102);
});
