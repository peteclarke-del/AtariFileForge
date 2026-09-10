(function initialiseAtariAssemblyLanguage(globalObject) {
  "use strict";

  // Every Atari ST runs a 68000-family processor: a 68000 in the ST, STE and
  // their Mega variants, a 68030 in the TT and Falcon. There is one
  // instruction set with additions per generation rather than several
  // unrelated ones. The base list is the MC68000 user and supervisor
  // instruction set; each later list holds only what that processor added.
  // The floating-point instructions are an overlay, because a 68881 or 68882
  // is an option on a TT or Falcon rather than part of the 68030.
  const MC68000 = (
    "ABCD ADD ADDA ADDI ADDQ ADDX AND ANDI ASL ASR "
    + "BCC BCS BEQ BGE BGT BHI BLE BLS BLT BMI BNE BPL BVC BVS BHS BLO "
    + "BCHG BCLR BRA BSET BSR BTST CHK CLR CMP CMPA CMPI CMPM "
    + "DBCC DBCS DBEQ DBF DBGE DBGT DBHI DBLE DBLS DBLT DBMI DBNE DBPL DBRA DBT DBVC DBVS "
    + "DIVS DIVU EOR EORI EXG EXT ILLEGAL JMP JSR LEA LINK LSL LSR "
    + "MOVE MOVEA MOVEM MOVEP MOVEQ MULS MULU NBCD NEG NEGX NOP NOT "
    + "OR ORI PEA RESET ROL ROR ROXL ROXR RTE RTR RTS SBCD "
    + "SCC SCS SEQ SF SGE SGT SHI SLE SLS SLT SMI SNE SPL ST SVC SVS "
    + "STOP SUB SUBA SUBI SUBQ SUBX SWAP TAS TRAP TRAPV TST UNLK"
  ).split(/\s+/);
  const MC68010_ADDITIONS = "BKPT MOVEC MOVES RTD".split(/\s+/);
  const MC68020_ADDITIONS = (
    "BFCHG BFCLR BFEXTS BFEXTU BFFFO BFINS BFSET BFTST CALLM CAS CAS2 CHK2 "
    + "CMP2 DIVSL DIVUL EXTB PACK RTM TRAPCC TRAPCS TRAPEQ TRAPF TRAPGE TRAPGT TRAPHI "
    + "TRAPLE TRAPLS TRAPLT TRAPMI TRAPNE TRAPPL TRAPT TRAPVC TRAPVS UNPK"
  ).split(/\s+/);
  const MC68030_ADDITIONS = "PFLUSH PFLUSHA PLOAD PMOVE PTEST".split(/\s+/);
  const MC68040_ADDITIONS = "CINV CPUSH MOVE16".split(/\s+/);
  const MC68060_ADDITIONS = "LPSTOP PLPA".split(/\s+/);

  // The MC68881 and MC68882 coprocessor instruction set. The 68040 and 68060
  // carry a floating-point unit on the chip and decode these directly.
  const FPU = (
    "FMOVE FADD FSUB FMUL FDIV FCMP FTST FBEQ FBNE FBGT FBGE FBLT FBLE FBGL FBGLE FBNGLE FBNGL "
    + "FBNLE FBNLT FBNGE FBNGT FBOGT FBOGE FBOLT FBOLE FBOGL FBOR FBUN FBUEQ FBUGT FBUGE FBULT "
    + "FBULE FBSEQ FBSNE FBST FBSF FBT FBF FDBEQ FDBNE FDBGT FDBGE FDBLT FDBLE FDBOR FDBUN FDBT FDBF "
    + "FSEQ FSNE FSGT FSGE FSLT FSLE FSOR FSUN FST FSF FNOP FSAVE FRESTORE FMOVEM FSQRT FABS FNEG "
    + "FINT FINTRZ FSIN FCOS FTAN FATAN FLOGN FLOG10 FETOX FTWOTOX FTENTOX FGETEXP FGETMAN "
    + "FSCALE FMOD FREM FSGLDIV FSGLMUL FASIN FACOS FSINCOS FSINH FCOSH FTANH FATANH FLOG2 FLOGNP1 FETOXM1"
  ).split(/\s+/);

  const unique = values => Object.freeze([...new Set(values)]);
  const with68010 = [...MC68000, ...MC68010_ADDITIONS];
  const with68020 = [...with68010, ...MC68020_ADDITIONS];
  const with68030 = [...with68020, ...MC68030_ADDITIONS];
  const with68040 = [...with68030, ...MC68040_ADDITIONS, ...FPU];
  const with68060 = [...with68040, ...MC68060_ADDITIONS];
  const CATALOGUES = Object.freeze({
    "68000": unique(MC68000),
    "68010": unique(with68010),
    "68020": unique(with68020),
    "68030": unique(with68030),
    "68040": unique(with68040),
    "68060": unique(with68060),
    fpu: unique(FPU),
    m68k: unique(MC68000),
  });
  const SETS = Object.freeze(Object.fromEntries(Object.entries(CATALOGUES).map(([key, values]) => [key, new Set(values)])));
  const WITH_FPU = Object.freeze(Object.fromEntries(Object.entries(CATALOGUES).map(([key, values]) => [key, new Set([...values, ...FPU])])));

  // "68030+fpu" and "68030-fpu" spell the overlay in the architecture name,
  // which is how a target profile can be passed around as one string.
  function resolve(architecture, fpu = null) {
    const text = String(architecture || "68000").toLowerCase();
    const match = text.match(/^([a-z0-9]+)(?:([+-])fpu)?$/);
    const base = match ? match[1] : text;
    const overlay = fpu ?? (match?.[2] === "+");
    const sets = overlay ? WITH_FPU : SETS;
    return sets[base] || sets["68000"];
  }

  const mnemonicsFor = (architecture, fpu = null) => resolve(architecture, fpu);
  const isMnemonic = (architecture, mnemonic, fpu = null) => resolve(architecture, fpu).has(String(mnemonic || "").toUpperCase());
  const isFpuMnemonic = mnemonic => SETS.fpu.has(String(mnemonic || "").toUpperCase());

  const api = Object.freeze({
    CATALOGUES,
    MC68000,
    MC68010_ADDITIONS,
    MC68020_ADDITIONS,
    MC68030_ADDITIONS,
    MC68040_ADDITIONS,
    MC68060_ADDITIONS,
    FPU,
    mnemonicsFor,
    isMnemonic,
    isFpuMnemonic,
  });
  globalObject.AtariAssemblyLanguage = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
