(function initialiseAtariBasicLanguage(globalObject) {
  "use strict";

  // The Atari ST had three BASICs and the editor has to colour all of them.
  // The keyword lists below are generated from the tables in atarinut/basic,
  // so the browser and the tokeniser agree on what a keyword is: GFA BASIC's
  // list comes from its token tables, STOS's from its documented vocabulary,
  // and ST BASIC's from the interpreter Atari shipped.

  // Every word GFA BASIC 3 has a token for, from atarinut/basic/gfa_tables.py.
  const GFA_KEYWORDS = (
    "ABS ABSOLUTE ACHAR ACLIP ACOS ADD ADDRIN ADDROUT AFTER ALERT ALINE AND APOLY APPL_FIND APPL_READ "
    + "APPL_TPLAY APPL_TRECORD APPL_WRITE ARECT ARRAYFILL ARRPTR AS ASC ASIN AT ATEXT ATN BASE BASEPAGE "
    + "BCHG BCLR BGET BIN$ BIOS BITBLT BLOAD BMOVE BOUNDARY BOX BPUT BREAK BSAVE BSET BTST BUTTON BYTE "
    + "CALL CARD CASE CFLOAT CHAIN CHDIR CHDRIVE CHR$ CINT CIRCLE CLEAR CLEARW CLIP CLOSE CLOSEW CLR "
    + "CLS COLOR COMBIN CONT CONTRL COS COSQ CPY CRSCOL CRSLIN CURVE CVD CVF CVI CVL CVS DATA DATE$ DEC "
    + "DEFAULT DEFBIT DEFBYT DEFFILL DEFFLT DEFFN DEFINT DEFLINE DEFLIST DEFMARK DEFMOUSE DEFNUM DEFSTR "
    + "DEFTEXT DEFWRD DEG DELAY DELETE DET DFREE DIM DIM? DIR DIR$ DIV DMACONTROL DMASOUND DO DOWNTO "
    + "DPEEK DPOKE DRAW DUMP EDIT ELLIPSE ELSE END ENDFUNC ENDIF ENDSELECT EQV ERASE ERR ERR$ ERROR "
    + "EVEN EVERY EVNT_BUTTON EVNT_DCLICK EVNT_MESAG EVNT_MOUSE EVNT_MULTI EVNT_TIMER EXEC EXIST EXIT "
    + "EXP FACT FALSE FATAL FIELD FILES FILESELECT FILL FIX FN FOR FORM FORM_ALERT FORM_BUTTON "
    + "FORM_CENTER FORM_DIAL FORM_DO FORM_ERROR FORM_KEYBD FRAC FRE FSEL_INPUT FSETDTA FSFIRST FULLW "
    + "FUNCTION GB GCONTRL GDOS? GEMDOS GEMSYS GET GETSIZE GINTIN GINTOUT GOSUB GOTO GRAF_DRAGBOX "
    + "GRAF_GROWBOX GRAF_HANDLE GRAF_MKSTATE GRAF_MOUSE GRAF_MOVEBOX GRAF_RUBBERBOX GRAF_SHRINKBOX "
    + "GRAF_SLIDEBOX GRAF_WATCHBOX GRAPHMODE HARDCOPY HEX$ HIDEM HIMEM HLINE HTAB IBOX IF IMP INC INFOW "
    + "INKEY$ INLINE INP INP? INPAUX$ INPMID$ INPUT INPUT$ INSERT INSTR INT INTIN INTOUT INV KEY KEYDEF "
    + "KEYGET KEYLOOK KEYPAD KEYPRESS KEYTEST KILL LEFT$ LEN LET LINE LIST LLIST LOAD LOCAL LOCATE LOG "
    + "LOG10 LOOP LPEEK LPENX LPENY LPOKE LPOS LPRINT LSET MALLOC MAT MAX MENU MENU_BAR MENU_ICHECK "
    + "MENU_IENABLE MENU_REGISTER MENU_TEXT MENU_TNORMAL MESSAGE MFREE MID$ MIN MKD$ MKDIR MKF$ MKI$ "
    + "MKL$ MKS$ MOD MODE MONITOR MOUSE MOUSEK MOUSEX MOUSEY MSHRINK MUL MW_OUT NAME NEG NEW NEXT NORM "
    + "NOT OBJC_ADD OBJC_CHANGE OBJC_DELETE OBJC_DRAW OBJC_EDIT OBJC_FIND OBJC_OFFSET OBJC_ORDER OBOX "
    + "OB_ADR OB_FLAGS OB_H OB_HEAD OB_NEXT OB_SPEC OB_STATE OB_TAIL OB_TYPE OB_W OB_X OB_Y OCT$ ODD "
    + "OFF OFFSET ON ONE OPEN OPENW OPTION OR OUT OUT? PADT PADX PADY PAUSE PBOX PCIRCLE PEEK PELLIPSE "
    + "PI PLOT POINT POKE POLYFILL POLYLINE POLYMARK POS PRBOX PRED PRINT PROCEDURE PSAVE PSET PTSIN "
    + "PTSOUT PTST PUT QDET QSORT QUIT RAD RAND RANDOM RANDOMIZE RANG RBOX RCALL RC_COPY RC_INTERSECT "
    + "READ RECALL RECORD RELSEEK REM RENAME REPEAT RESERVE RESTORE RESUME RETURN RIGHT$ RINSTR RMDIR "
    + "RND ROL ROR ROUND RSET RSRC_GADDR RSRC_LOAD RSRC_OBFIX RSRC_SADDR RUN SAVE SCALE SCRP_READ "
    + "SCRP_WRITE SDPOKE SEEK SELECT SET SETCOLOR SETDRAW SETMOUSE SETTIME SGET SGN SHEL_ENVRN "
    + "SHEL_FIND SHEL_GET SHEL_PUT SHEL_READ SHEL_WRITE SHL SHOWM SHR SIN SINQ SLPOKE SOUND SPACE$ SPC "
    + "SPOKE SPRITE SPUT SQR SSORT STE? STEP STICK STOP STORE STR$ STRIG STRING$ SUB SUCC SWAP SYSTEM "
    + "TAB TAN TEXT THEN TIME$ TIMER TITLEW TO TOPW TOUCH TRACE$ TRANS TRIM$ TROFF TRON TRUE TRUNC TT? "
    + "TYPE UNTIL UPPER$ USING VAL VAL? VAR VARIAT VARPTR VDIBASE VDISYS VOID VQT_EXTENT VQT_NAME "
    + "VSETCOLOR VST_LOAD_FONTS VST_UNLOAD_FONTS VSYNC VTAB V_OPNVWK V_OPNWK WAVE WEND WHILE WINDTAB "
    + "WIND_CALC WIND_CLOSE WIND_CREATE WIND_DELETE WIND_FIND WIND_GET WIND_OPEN WIND_SET WIND_UPDATE "
    + "WITH WORD WORK_OUT WRITE XBIOS XCPY XOR"
  ).split(/\s+/);

  // The words GFA BASIC 3.0 added. A GFA 2 listing that uses one will not run.
  const GFA_3_ONLY_KEYWORDS = (
    "ALERT ARRAYFILL BMOVE CARD CASE CLIP DEFAULT DEFBIT DEFBYT DEFFLT DEFLIST DEFNUM DEFWRD DO "
    + "DOWNTO DPEEK DPOKE ENDFUNC ENDSELECT EXIT FILESELECT FRAC FUNCTION INLINE LOCAL LOOP LPEEK LPOKE "
    + "MENU OB_ADR PRED RCALL RC_INTERSECT SELECT SETTIME SUCC TEXT TRUNC VAR"
  ).split(/\s+/);

  // The documented STOS 2.x vocabulary, from atarinut/basic/stos_tables.py.
  const STOS_KEYWORDS = (
    "ABS AFTER AND ANIM APPEAR ASC ATN AUTO BACK BAR BELL BGRAB BLOAD BOB BOOM BORDER BOX BSAVE CALL "
    + "CENTRE CHANGE CHR$ CIRCLE CLEAR CLICK CLOSE CLS CLW COLLIDE COLOUR COPY COS CURS CUT DATA DATE$ "
    + "DEC DEEK DEF DEFAULT DEG DELETE DFREE DIM DIR DIR$ DIV DO DOKE DRAW DRAWTO EARC EDIT ELLIPSE "
    + "ELSE END EOF ERASE ERR ERRN ERROR EXP FADE FALSE FILL FIX FKEY FLASH FLIP FOR FRE FREE GET GOSUB "
    + "GOTO HARDCOPY HEX$ HIDE HOME HUNT IF INC INK INKEY$ INPUT INPUT$ INSTR INT INVERSE JDOWN JLEFT "
    + "JRIGHT JUP KEY LDIR LEEK LEFT$ LEN LENGTH LET LIMIT LINE LIST LLIST LOAD LOCATE LOG LOGIC LOKE "
    + "LOWER$ LPRINT MENU MENU$ MID$ MKDIR MODE MOUSE MOUSEON MOVE MUSIC NEW NEXT NOT OFF OLD ON OPEN "
    + "OR OVERLAP PALETTE PALT PAPER PASTE PEEK PEN PHYSIC PI PLAY PLOT POINT POKE POLYGON POLYLINE "
    + "POLYMARK POP PRINT PRIORITY PSET PUT RAD RANDOMIZE READ REM REPEAT RESERVE RESTORE RESUME RETURN "
    + "RIGHT$ RND RUN SAVE SCAN SCREEN SCREEN$ SCRN SCROLL SET SGN SHOOT SHOW SIN SORT SPACE$ SPRITE "
    + "SQR START STEP STOP STR$ STRING$ SWAP SYNCHRO SYSTEM TAB TAN TEXT THEN TIMER TO TRACK TROFF TRON "
    + "TRUE UNPACK UNTIL UPDATE UPPER$ VAL VARPTR VOICE VOLUME WAIT WEND WHILE WINDEL WINDMOVE WINDOPEN "
    + "WINDOW WINDSIZE WORLD XOR ZONE ZONE$"
  ).split(/\s+/);

  // Atari's own ST BASIC, from atarinut/basic/stbasic.py.
  const ST_BASIC_KEYWORDS = (
    "ABS AND ASC ATN AUTO BLOAD BREAK BSAVE CDBL CHAIN CHR$ CINT CIRCLE CLEAR CLEARW CLOSE CLOSEW CLS "
    + "COLOR COMMON CONT COS CSNG CVD CVI CVS DATA DATE$ DEF DEFDBL DEFINT DEFSNG DEFSTR DELETE DIM DIR "
    + "ELLIPSE ELSE END EOF EQV ERASE ERL ERR ERROR EXP FIELD FILL FIX FN FOLLOW FOR FRE FULLW GEMSYS "
    + "GET GOSUB GOTO GOTOXY HEX$ IF IMP INKEY$ INP INPUT INSTR INT KILL LEFT$ LEN LET LINEF LIST LLIST "
    + "LOAD LOC LOCATE LOF LOG LPRINT LSET MERGE MID$ MKD$ MKI$ MKS$ MOD NAME NEW NEXT NOT OCT$ ON OPEN "
    + "OPENW OPTION OR OUT PCIRCLE PEEK PELLIPSE POKE POS PRINT PUT QUIT RANDOMIZE READ REM RENUM "
    + "RESTORE RESUME RETURN RIGHT$ RND RSET RUN SAVE SGN SIN SOUND SPACE$ SPC SQR STEP STOP STR$ "
    + "STRING$ SWAP SYSTAB SYSTEM TAB TAN THEN TIME$ TIMER TITLEW TO TROFF TRON USING VAL VARPTR VDISYS "
    + "WAVE WEND WHILE WIDTH WRITE XOR"
  ).split(/\s+/);

  // Words a dialect spells as two, which the scanner has to read as one or it
  // would colour OPEN inside SCREEN OPEN and IF inside EXIT IF.
  const GFA_COMPOUND_KEYWORDS = [
    "EXIT IF", "ELSE IF", "END SELECT", "END IF", "DO WHILE", "DO UNTIL",
    "LOOP WHILE", "LOOP UNTIL", "ON ERROR", "ON MENU", "OPEN OUT",
  ];
  const STOS_COMPOUND_KEYWORDS = [
    "SCREEN OPEN", "SCREEN CLOSE", "SCREEN COPY", "SCREEN SWAP", "MOVE ON", "MOVE OFF",
    "MOVE X", "MOVE Y", "PUT BOB", "GET BOB", "DEF SCROLL", "MENU ON", "MENU OFF",
    "WINDOW OPEN", "WINDOW CLOSE", "SPRITE OFF", "MUSIC OFF", "LIMIT SPRITE", "LIMIT MOUSE",
    "SET LINE", "SET ZONE", "SET CURS", "SET MARK", "SET PAINT", "SET BLOCK", "SET PATTERN",
    "KEY OFF", "KEY ON", "KEY SPEED", "CURS OFF", "CURS ON", "CLEAR KEY", "PUT KEY",
    "WAIT KEY", "WAIT VBL", "AUTO BACK", "CHANGE MOUSE", "GR WRITING", "MOUSE KEY",
    "MOUSE SCREEN", "X MOUSE", "Y MOUSE", "ON ERROR", "OPEN IN", "OPEN OUT", "DEF FN",
    "TRACK PLAY", "TRACK LOAD", "TRACK STOP", "SCROLL ON", "SCROLL OFF", "CLICK ON",
    "CLICK OFF", "ANIM ON", "ANIM OFF", "ANIM FREEZE", "LINE INPUT",
  ];
  const ST_BASIC_COMPOUND_KEYWORDS = [
    "ON ERROR", "LINE INPUT", "OPTION BASE", "DEF FN", "DEF SEG", "GO TO", "GO SUB",
    "ERROR GOTO", "RESUME NEXT", "PRINT USING",
  ];

  // A typed name ends with one of these. GFA BASIC has the widest set: # float,
  // $ string, % integer, ! boolean, & word and | byte. STOS types only strings
  // and floats, ST BASIC strings, integers and single-precision numbers.
  const TYPE_SUFFIXES = {
    "gfa-basic-3": "$%&!#|",
    "gfa-basic-2": "$%!#",
    "stos-basic": "$#",
    "st-basic": "$%!",
  };

  const set = words => new Set(words.map(word => word.toUpperCase()));
  const GFA_3 = set(GFA_KEYWORDS);
  const GFA_2 = set(GFA_KEYWORDS.filter(word => !GFA_3_ONLY_KEYWORDS.includes(word)));
  const STOS = set(STOS_KEYWORDS);
  const ST_BASIC = set(ST_BASIC_KEYWORDS);
  // The editor is often asked to colour a listing before anything has decided
  // which BASIC it is, so the default vocabulary is all of them at once.
  const KEYWORDS = new Set([...GFA_3, ...STOS, ...ST_BASIC]);

  // `generation` gates KEYWORD_GENERATION, and KEYWORD_GENERATION holds only
  // the words GFA BASIC 3.0 added. It is therefore 3 for every dialect except
  // GFA BASIC 2, so that opening a listing as 2.x warns about words 2.x does
  // not have and no other dialect is ever warned about a GFA word.
  const DIALECTS = Object.freeze({
    "GFA BASIC 3": {
      id: "gfa-basic-3", label: "GFA BASIC 3.x", generation: 3, writable: true,
      lineNumbers: false, structured: true, tokenised: true, inlineAssembler: false,
      processor: "68000", extensions: [".gfa", ".lst"],
    },
    "GFA BASIC 2": {
      id: "gfa-basic-2", label: "GFA BASIC 2.x listing", generation: 2, writable: true,
      lineNumbers: false, structured: true, tokenised: false, inlineAssembler: false,
      processor: "68000", extensions: [".lst"],
    },
    "STOS BASIC": {
      id: "stos-basic", label: "STOS BASIC", generation: 3, writable: false,
      lineNumbers: true, structured: false, tokenised: true, inlineAssembler: false,
      processor: "68000", extensions: [".bas", ".asc"],
    },
    "ST BASIC": {
      id: "st-basic", label: "Atari ST BASIC", generation: 3, writable: true,
      lineNumbers: true, structured: false, tokenised: false, inlineAssembler: false,
      processor: "68000", extensions: [".bas"],
    },
  });

  const KEYWORD_GENERATION = Object.freeze(
    Object.fromEntries(GFA_3_ONLY_KEYWORDS.map(keyword => [keyword.toUpperCase(), 3])),
  );

  const PROFILES = Object.freeze({
    "gfa-basic-3": { keywords: GFA_3, compound: GFA_COMPOUND_KEYWORDS, suffixes: TYPE_SUFFIXES["gfa-basic-3"] },
    "gfa-basic-2": { keywords: GFA_2, compound: GFA_COMPOUND_KEYWORDS, suffixes: TYPE_SUFFIXES["gfa-basic-2"] },
    "stos-basic": { keywords: STOS, compound: STOS_COMPOUND_KEYWORDS, suffixes: TYPE_SUFFIXES["stos-basic"] },
    "st-basic": { keywords: ST_BASIC, compound: ST_BASIC_COMPOUND_KEYWORDS, suffixes: TYPE_SUFFIXES["st-basic"] },
    "": {
      keywords: KEYWORDS,
      compound: [...new Set([...GFA_COMPOUND_KEYWORDS, ...STOS_COMPOUND_KEYWORDS, ...ST_BASIC_COMPOUND_KEYWORDS])],
      suffixes: "$%&!#|",
    },
  });

  function dialectProfile(name) {
    return DIALECTS[name] || DIALECTS[Object.keys(DIALECTS).find(key => DIALECTS[key].id === name)] || DIALECTS["GFA BASIC 3"];
  }

  function vocabulary(dialect) {
    if (!dialect) return PROFILES[""];
    const profile = DIALECTS[dialect];
    return PROFILES[profile ? profile.id : dialect] || PROFILES[""];
  }

  // A keyword is only a keyword when it is not glued to a name character on
  // either side. This is the rule the tokeniser in atarinut applies, so
  // highlighting and storage always agree about TOTAL, PRINTER and FORMAT.
  const isNameCharacter = character => Boolean(character) && /[A-Za-z0-9_.]/.test(character);
  const normaliseKeyword = value => String(value || "").toUpperCase();
  const identifierPattern = /^[A-Za-z][A-Za-z0-9_.]*/;

  const compactKeywordBoundary = (character, suffixes = "$%&!#|") =>
    !character || !suffixes.includes(character);

  function isTypedIdentifier(value, dialect) {
    const suffixes = vocabulary(dialect).suffixes;
    const last = String(value || "").slice(-1);
    return Boolean(last) && suffixes.includes(last);
  }

  function isKeywordToken(value, dialect) {
    const raw = String(value || "");
    const { keywords, compound, suffixes } = vocabulary(dialect);
    const upper = normaliseKeyword(raw);
    // A compound keyword is one word to the scanner even though the set holds
    // its halves separately, so SCREEN OPEN is a keyword and so is CURS OFF.
    if (compound.includes(upper)) return true;
    // A trailing type suffix makes the word a name, unless the keyword itself
    // ends in one, as CHR$ and MID$ do.
    if (suffixes.includes(raw.slice(-1)) && !keywords.has(upper)) return false;
    return keywords.has(upper);
  }

  function keywordPrefix(value, candidates, suffixes = "$%&!#|") {
    const source = String(value || "");
    const upper = source.toUpperCase();
    return [...candidates]
      .sort((left, right) => right.length - left.length)
      .find(candidate => upper.startsWith(candidate)
        && compactKeywordBoundary(source[candidate.length], suffixes)
        && !isNameCharacter(source[candidate.length])) || "";
  }

  function compoundAt(value, dialect) {
    const source = String(value || "");
    const upper = source.toUpperCase();
    const { compound } = vocabulary(dialect);
    return compound.find(phrase => upper.startsWith(phrase) && !isNameCharacter(source[phrase.length])) || "";
  }

  function lexemeAt(value, dialect) {
    const source = String(value || "");
    const { keywords, suffixes } = vocabulary(dialect);
    const compound = compoundAt(source, dialect);
    if (compound) return source.slice(0, compound.length);
    let identifier = source.match(identifierPattern)?.[0] || "";
    if (!identifier) return "";
    // GFA BASIC asks a few questions: DIM?, GDOS? and STE? end in one.
    if (source[identifier.length] === "?" && keywords.has(`${identifier.toUpperCase()}?`)) {
      identifier += "?";
      return identifier;
    }
    const suffix = suffixes.includes(source[identifier.length]) ? source[identifier.length] : "";
    const typed = identifier + suffix;
    if (keywords.has(typed.toUpperCase())) return typed;
    // print%, len! and screen# are variables, not compact spellings of the
    // corresponding command, and FNname is one indivisible user symbol.
    if (suffix || /^FN.+/i.test(identifier)) return typed;
    if (keywords.has(identifier.toUpperCase())) return identifier;
    // Otherwise a joined form exposes its leading keyword first, so IFA,
    // PRINT"x" and GOTO90 still colour their command.
    const prefix = keywordPrefix(identifier, keywords, suffixes);
    return prefix ? identifier.slice(0, prefix.length) : identifier;
  }

  function scanLine(line, lineOffset = 0, state = {}) {
    const tokens = [];
    const dialect = state.dialect || "";
    const { suffixes } = vocabulary(dialect);
    const profile = dialect ? dialectProfile(dialect) : null;
    let offset = 0;
    // GFA BASIC has no line numbers; STOS and ST BASIC number every line.
    if (!profile || profile.lineNumbers) {
      const number = String(line).match(/^\s*(\d+)(?=[ \t]|$)/);
      if (number) {
        const local = number[0].lastIndexOf(number[1]);
        tokens.push({ type: "line-number", text: number[1], start: lineOffset + local, end: lineOffset + local + number[1].length });
        offset = number[0].length;
      }
    }
    while (offset < line.length) {
      const character = line[offset];
      if (character === '"') {
        let end = offset + 1;
        while (end < line.length) {
          if (line[end] === '"') {
            if (line[end + 1] === '"') { end += 2; continue; }
            end += 1;
            break;
          }
          end += 1;
        }
        tokens.push({ type: "string", text: line.slice(offset, end), start: lineOffset + offset, end: lineOffset + end });
        offset = end;
        continue;
      }
      // GFA BASIC comments a line with ' or !; STOS and ST BASIC use REM only.
      if (character === "'" || (character === "!" && offset > 0 && line[offset - 1] === " ")) {
        tokens.push({ type: "comment", text: line.slice(offset), start: lineOffset + offset, end: lineOffset + line.length });
        break;
      }
      // Numbers may be decimal, &H hexadecimal, &O octal, &X or % binary, or
      // $ hexadecimal as STOS writes it.
      const numeric = line.slice(offset).match(/^(?:&[HOX][0-9A-Fa-f]+|\$[0-9A-Fa-f]+|%[01]+|\d+(?:\.\d+)?(?:[ED][-+]?\d+)?)/i)?.[0];
      if (numeric && !(character === "%" && offset > 0 && isNameCharacter(line[offset - 1]))) {
        tokens.push({ type: "number", text: numeric, start: lineOffset + offset, end: lineOffset + offset + numeric.length });
        offset += numeric.length;
        continue;
      }
      const identifier = lexemeAt(line.slice(offset), dialect);
      if (identifier) {
        const keyword = isKeywordToken(identifier, dialect);
        const type = keyword ? "keyword" : "identifier";
        const name = identifier.toUpperCase();
        tokens.push({ type, text: identifier, name, start: lineOffset + offset, end: lineOffset + offset + identifier.length });
        offset += identifier.length;
        if (keyword && (name === "REM" || name === "DATA")) {
          if (offset < line.length) tokens.push({ type: "comment", text: line.slice(offset), start: lineOffset + offset, end: lineOffset + line.length });
          break;
        }
        continue;
      }
      if (/[-+*/^\\=<>(),;:#[\]{}@~]/.test(character)) {
        tokens.push({ type: "operator", text: character, start: lineOffset + offset, end: lineOffset + offset + 1 });
      }
      offset += 1;
    }
    return { tokens };
  }

  function scan(source, dialect = "") {
    const tokens = [];
    let lineOffset = 0;
    const lines = String(source || "").split("\n");
    lines.forEach((line, index) => {
      const result = scanLine(line, lineOffset, { dialect });
      tokens.push(...result.tokens.map(token => ({ ...token, line: index + 1 })));
      lineOffset += line.length + 1;
    });
    return tokens;
  }

  const remainderIsComment = (source, index, suffixes) =>
    /^REM/i.test(source.slice(index))
    && !suffixes.includes(source[index + 3] || "")
    && !isNameCharacter(source[index + 3] || "")
    && (index === 0 || !isNameCharacter(source[index - 1]));

  function splitStatements(body, dialect = "") {
    const source = String(body || "");
    const { suffixes } = vocabulary(dialect);
    const statements = [];
    let start = 0;
    let quoted = false;
    for (let index = 0; index < source.length; index += 1) {
      const character = source[index];
      if (character === '"') {
        if (quoted && source[index + 1] === '"') { index += 1; continue; }
        quoted = !quoted;
        continue;
      }
      if (quoted) continue;
      const comment = character === "'"
        || (character === "!" && index > 0 && source[index - 1] === " ")
        || remainderIsComment(source, index, suffixes);
      if (comment) {
        // The comment is a statement of its own, and the colons inside it are
        // text rather than separators, so the scan stops here.
        statements.push({ text: source.slice(start, index).trim(), start, end: index });
        statements.push({ text: source.slice(index).trim(), start: index, end: source.length });
        return statements.filter(statement => statement.text);
      }
      if (character === ":") {
        statements.push({ text: source.slice(start, index).trim(), start, end: index });
        start = index + 1;
      }
    }
    statements.push({ text: source.slice(start).trim(), start, end: source.length });
    return statements.filter(statement => statement.text);
  }

  function maskStringsAndComments(source, dialect = "") {
    const value = String(source || "");
    const { suffixes } = vocabulary(dialect);
    const mask = [...value];
    let quoted = false;
    for (let index = 0; index < value.length; index += 1) {
      if (value[index] === "\n") { quoted = false; continue; }
      if (value[index] === '"') {
        mask[index] = " ";
        if (quoted && value[index + 1] === '"') { mask[index + 1] = " "; index += 1; continue; }
        quoted = !quoted;
        continue;
      }
      if (quoted) { mask[index] = " "; continue; }
      const comment = value[index] === "'"
        || (value[index] === "!" && index > 0 && value[index - 1] === " ")
        || remainderIsComment(value, index, suffixes);
      if (comment) {
        while (index < value.length && value[index] !== "\n") { mask[index] = " "; index += 1; }
        index -= 1;
      }
    }
    return mask.join("");
  }

  const api = Object.freeze({
    DIALECTS,
    KEYWORDS,
    KEYWORD_GENERATION,
    GFA_KEYWORDS,
    GFA_3_ONLY_KEYWORDS,
    STOS_KEYWORDS,
    ST_BASIC_KEYWORDS,
    GFA_COMPOUND_KEYWORDS,
    STOS_COMPOUND_KEYWORDS,
    ST_BASIC_COMPOUND_KEYWORDS,
    TYPE_SUFFIXES,
    compactKeywordBoundary,
    compoundAt,
    dialectProfile,
    isKeywordToken,
    isTypedIdentifier,
    keywordPrefix,
    lexemeAt,
    maskStringsAndComments,
    scan,
    scanLine,
    splitStatements,
    vocabulary,
  });

  globalObject.AtariBasicLanguage = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
