"use strict";

const assert = require("node:assert/strict");

global.window = {
  AtariBasicLanguage: require("../../app/static/basic-language.js"),
  AtariAssemblyLanguage: require("../../app/static/assembly-language.js"),
};
window.AtariCallCatalogue = require("../../app/static/atari-call-catalogue.js");
require("../../app/static/code-editor.js");

function test(name, callback) {
  try { callback(); process.stdout.write(`ok - ${name}\n`); }
  catch (error) { process.stderr.write(`not ok - ${name}\n${error.stack}\n`); process.exitCode = 1; }
}

const GFA = "GFA BASIC 3.0";
const ST = { machine: "st" };

test("source help names the GEMDOS call a GEMDOS() statement invokes", () => {
  const source = "~GEMDOS(9,L:ADDR(a$))";
  const start = source.indexOf("GEMDOS");
  const item = window.AtariCodeEditor.contextHelp(source, "basic", start, start + 6, "GEMDOS", ST);
  assert.match(item.notes, /Cconws/);
  assert.match(item.notes, /TRAP #1/);
  assert.match(item.notes, /2\(sp\)\.l string/);
});

test("source help names the XBIOS and BIOS calls with their stack arguments", () => {
  const xbios = window.AtariCodeEditor.contextHelp("~XBIOS(7,3,&H777)", "basic", 1, 6, "XBIOS", ST);
  assert.match(xbios.notes, /Setcolor/);
  assert.match(xbios.notes, /2\(sp\)\.w index = 3/);
  assert.match(xbios.notes, /yellow/);
  const bios = window.AtariCodeEditor.contextHelp("~BIOS(3,2,65)", "basic", 1, 5, "BIOS", ST);
  assert.match(bios.notes, /Bconout/);
  assert.match(bios.notes, /CON, the console/);
  assert.match(bios.notes, /'A'/);
});

test("source help names the AES and VDI functions GEMSYS and VDISYS invoke", () => {
  const aes = window.AtariCodeEditor.contextHelp("GEMSYS 52", "basic", 0, 6, "GEMSYS", ST);
  assert.match(aes.notes, /form_alert/);
  const vdi = window.AtariCodeEditor.contextHelp("VDISYS 11,2,0,1", "basic", 0, 6, "VDISYS", ST);
  assert.match(vdi.notes, /v_bar/);
});

test("source help names a hardware register a DPOKE writes to", () => {
  const source = "DPOKE &HFF8240,&H777";
  const item = window.AtariCodeEditor.contextHelp(source, "basic", 0, 5, "DPOKE", ST);
  assert.match(item.notes, /palette register 0/);
  assert.match(item.notes, /directly to the hardware/);
});

test("source help warns when DPOKE uses an odd address", () => {
  const item = window.AtariCodeEditor.contextHelp("DPOKE &H4BB,0", "basic", 0, 5, "DPOKE", ST);
  assert.match(item.notes, /is odd/);
  const stos = window.AtariCodeEditor.contextHelp("10 DOKE $4BB,0", "basic", 3, 7, "DOKE", ST);
  assert.match(stos.notes, /is odd/);
});

test("source help names the _hz_200 timer read from absolute address $4BA", () => {
  const basic = window.AtariCodeEditor.contextHelp("t%=LPEEK(&H4BA)", "basic", 3, 8, "LPEEK", ST);
  assert.match(basic.notes, /_hz_200/);
  const assembly = window.AtariCodeEditor.contextHelp("\tmove.l\t$4BA.w,d0", "68000", 1, 7, "MOVE", ST);
  assert.match(assembly.notes, /_hz_200/);
  assert.match(assembly.notes, /supervisor mode/);
});

test("source help names a hardware register written from assembly", () => {
  const item = window.AtariCodeEditor.contextHelp("\tmove.w\t#$777,$FFFF8240", "68000", 1, 7, "MOVE", ST);
  assert.match(item.notes, /palette register 0/);
  const mfp = window.AtariCodeEditor.contextHelp("\tbclr\t#3,$FFFA07", "68000", 1, 5, "BCLR", ST);
  assert.match(mfp.notes, /MFP IERA/);
});

test("source help decodes SOUND and SETCOLOR arguments and confirms the ST target", () => {
  const sound = window.AtariCodeEditor.contextHelp("SOUND 1,15,5,4,25", "basic", 0, 5, "SOUND", ST);
  assert.match(sound.notes, /voice = 1/);
  assert.match(sound.notes, /Atari ST target is within the documented platform scope/);
});

test("help reports a Falcon-only XBIOS call as outside an ST target profile", () => {
  const item = window.AtariCodeEditor.contextHelp("~XBIOS(88,-1)", "basic", 1, 6, "XBIOS", ST);
  assert.match(item.notes, /VsetMode/);
  assert.match(item.notes, /Target warning/);
  assert.match(item.notes, /Atari Falcon030, not the configured Atari ST target/);
  const falcon = window.AtariCodeEditor.contextHelp("~XBIOS(88,-1)", "basic", 1, 6, "XBIOS", { machine: "falcon030" });
  assert.match(falcon.notes, /configured Atari Falcon030 target is within the documented platform scope/);
});

test("help reports an STE-only XBIOS call as outside a plain ST target", () => {
  const item = window.AtariCodeEditor.contextHelp("~XBIOS(83,0,&HFFF)", "basic", 1, 6, "XBIOS", { targetHardware: "st-gemdos" });
  assert.match(item.notes, /EsetColor/);
  assert.match(item.notes, /Target warning/);
  const ste = window.AtariCodeEditor.contextHelp("~XBIOS(83,0,&HFFF)", "basic", 1, 6, "XBIOS", { machine: "ste" });
  assert.doesNotMatch(ste.notes, /Target warning/);
});

test("a MINT.CNF line names the program it starts", () => {
  const item = window.AtariCodeEditor.contextHelp("GEM=C:\\MINT\\XAAES\\XAAES.KM", "script", 0, 3, "GEM");
  assert.match(item.notes, /XAAES\.KM/);
  assert.match(item.notes, /before the desktop appears/);
});

test("a desktop record names the path it refers to", () => {
  const item = window.AtariCodeEditor.contextHelp("#Z 01 C:\\GEM\\PROGRAM.PRG@", "script", 0, 2, "#Z");
  assert.match(item.summary, /automatically/);
  assert.match(item.notes, /PROGRAM\.PRG/);
});

test("assembly names the GEMDOS call a pushed function number and TRAP #1 make", () => {
  const source = "\tpea\tmessage(pc)\n\tmove.w\t#9,-(sp)\n\ttrap\t#1\n\taddq.l\t#6,sp";
  const start = source.indexOf("trap");
  const item = window.AtariCodeEditor.contextHelp(source, "68000", start, start + 4, "TRAP", ST);
  assert.match(item.notes, /GEMDOS call/);
  assert.match(item.notes, /Cconws/);
});

test("assembly names an XBIOS call with its proved arguments", () => {
  const source = "\tmove.w\t#$777,-(sp)\n\tmove.w\t#0,-(sp)\n\tmove.w\t#7,-(sp)\n\ttrap\t#14\n\taddq.l\t#6,sp";
  const start = source.indexOf("trap");
  const item = window.AtariCodeEditor.contextHelp(source, "68000", start, start + 4, "TRAP", ST);
  assert.match(item.notes, /Setcolor/);
  assert.match(item.notes, /index = 0/);
  assert.match(item.notes, /white/);
});

test("assembly names the AES when D0 holds $C8 before TRAP #2", () => {
  const source = "\tlea\taespb,a0\n\tmove.l\ta0,d1\n\tmove.l\t#$C8,d0\n\ttrap\t#2";
  const start = source.indexOf("trap");
  const item = window.AtariCodeEditor.contextHelp(source, "68000", start, start + 4, "TRAP", ST);
  assert.match(item.notes, /AES/);
  const vdi = window.AtariCodeEditor.contextHelp("\tmove.l\t#$73,d0\n\ttrap\t#2", "68000", 17, 21, "TRAP", ST);
  assert.match(vdi.notes, /VDI/);
});

test("assembly reports a Falcon-only XBIOS call as outside an ST target", () => {
  const source = "\tmove.w\t#-1,-(sp)\n\tmove.w\t#88,-(sp)\n\ttrap\t#14";
  const start = source.indexOf("trap");
  const item = window.AtariCodeEditor.contextHelp(source, "68000", start, start + 4, "TRAP", ST);
  assert.match(item.notes, /VsetMode/);
  assert.match(item.notes, /Target warning/);
});

test("a Line-A opcode placed with DC.W is named", () => {
  const item = window.AtariCodeEditor.contextHelp("\tdc.w\t$A00A", "68000", 1, 5, "DC.W", ST);
  assert.match(item.notes, /hide mouse/);
});

test("a floating-point instruction is flagged on a target without an FPU", () => {
  const item = window.AtariCodeEditor.contextHelp("\tfmove.x\tfp0,fp1", "68030", 1, 8, "FMOVE", { machine: "tt030" });
  assert.match(item.notes, /no 68881 or 68882/);
  const fitted = window.AtariCodeEditor.contextHelp("\tfmove.x\tfp0,fp1", "68030+fpu", 1, 8, "FMOVE", { machine: "tt030", fpu: true });
  assert.doesNotMatch(fitted.notes, /no 68881 or 68882/);
  assert.equal(window.AtariCodeEditor.processorFor({ machine: "tt030", fpu: true }), "68030+fpu");
  assert.equal(window.AtariCodeEditor.processorFor({ machine: "ste" }), "68000");
});

test("compact PRINT TAB is not mistaken for an undimensioned array", () => {
  const source = `CLS
PRINT TAB(15);"Insert disk"
DIM names$(10)
PRINT names$(0)`;
  const issues = window.AtariCodeEditor.diagnostics(source, "basic", GFA);
  assert.equal(issues.some(issue => /TAB.*array/i.test(issue.message)), false);
  assert.equal(issues.some(issue => /names\$.*DIM/i.test(issue.message)), false);
});

test("a genuine array reference without DIM is still reported", () => {
  const issues = window.AtariCodeEditor.diagnostics("PRINT scores%(1)", "basic", GFA);
  assert.equal(issues.some(issue => /scores%.*array before a preceding DIM/i.test(issue.message)), true);
});

test("a GFA @procedure call without a matching PROCEDURE is reported", () => {
  const issues = window.AtariCodeEditor.diagnostics("@redraw\nGOSUB tidy", "basic", GFA);
  assert.equal(issues.some(issue => /redraw has no PROCEDURE/i.test(issue.message)), true);
  assert.equal(issues.some(issue => /tidy has no PROCEDURE/i.test(issue.message)), true);
});

test("a PROCEDURE without RETURN is reported", () => {
  const source = `@redraw
PROCEDURE redraw
  PRINT "x"`;
  const issues = window.AtariCodeEditor.diagnostics(source, "basic", GFA);
  assert.equal(issues.some(issue => /PROCEDURE redraw on line 2 has no RETURN/i.test(issue.message)), true);
});

test("missing ENDIF, NEXT, WEND, UNTIL and LOOP closers are reported", () => {
  const source = `IF a%=1
FOR i%=1 TO 3
WHILE b%
REPEAT
DO`;
  const issues = window.AtariCodeEditor.diagnostics(source, "basic", GFA).map(issue => issue.message);
  for (const closer of ["ENDIF", "NEXT", "WEND", "UNTIL", "LOOP"]) {
    assert.ok(issues.some(message => message.includes(`has no ${closer}`)), closer);
  }
  const closed = `IF a%=1 THEN PRINT "one"
FOR i%=1 TO 3
NEXT i%
PROCEDURE tidy
RETURN
@tidy`;
  assert.deepEqual(window.AtariCodeEditor.diagnostics(closed, "basic", GFA), []);
});

test("GFA typed names and comments do not create speculative warnings", () => {
  const source = `a$="900":a%=0 ! typed names
' a comment with IF and FOR in it
DEFFN double(x)=x*2
PRINT FN double(2)`;
  assert.deepEqual(window.AtariCodeEditor.diagnostics(source, "basic", GFA), []);
});

test("a numbered STOS listing still checks its line numbers and destinations", () => {
  const source = `10 PRINT "x"
20 GOTO 40
5 END`;
  const issues = window.AtariCodeEditor.diagnostics(source, "basic", "STOS BASIC").map(issue => issue.message);
  assert.ok(issues.some(message => /Referenced line 40 does not exist/.test(message)));
  assert.ok(issues.some(message => /Line 5 is not greater/.test(message)));
});

test("hover help knows TOS calls and system variables by name", () => {
  assert.match(window.AtariCodeEditor.lookup("68000", "Fopen").summary, /GEMDOS 61/);
  assert.match(window.AtariCodeEditor.lookup("68000", "Fopen").syntax, /TRAP #1/);
  assert.match(window.AtariCodeEditor.lookup("68000", "_hz_200").summary, /\$4BA/);
  assert.match(window.AtariCodeEditor.lookup("68000", "v_opnvwk").summary, /VDI 100/);
  assert.match(window.AtariCodeEditor.lookup("basic", "PROCEDURE").summary, /procedure/);
  assert.match(window.AtariCodeEditor.lookup("basic", "SCREEN").syntax, /SCREEN OPEN/);
  assert.equal(window.AtariCodeEditor.describeAddress(0xFFFFFA01).name, "MFP GPIP");
});
