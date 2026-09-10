"""STOS BASIC 2.x token tables.

A tokenised STOS program stores each keyword as a byte from ``0x80`` upward.
Four of those bytes are escapes into wider tables:

* ``0xA0`` introduces an *extended instruction*: one further byte selects the
  command (``INSTRUCTION_TOKENS``).
* ``0xA8`` introduces an *extension instruction*: an extension number then a
  command byte (``EXTENSION_INSTRUCTIONS``). Extensions are the add-on
  packages (Sprites 600, Maestro, the Compiler and so on) that install their
  own commands.
* ``0xB8`` introduces an *extended function* (``FUNCTION_TOKENS``).
* ``0xC0`` introduces an *extension function* (``EXTENSION_FUNCTIONS``).

Everything else from ``0x80`` to ``0xF9`` is a single byte in ``BASE_TOKENS``,
and ``0xFA`` upward are the literal and variable encodings that ``stos.py``
decodes.

Where these tables come from, and what is missing
-------------------------------------------------
No published copy of STOS's own instruction table was available, so the
entries here were *derived*, not transcribed: 36 STOS programs that ship both
the tokenised ``.BAS`` and the ASCII ``.ASC`` listing STOS itself wrote were
decoded line by line, and each unresolved token was pinned to the text left
over between two resolved neighbours. Repeating that to a fixed point
recovered the 169 tokens below, every one of them observed in a real program.

That is not the whole table. STOS 2.x has several hundred commands, and a
keyword no program in the sample used is simply not here. ``stos.py`` prints
an unrecovered token as ``{&A0,&C9}`` rather than guessing, so a listing shows
plainly where the table stops rather than quietly inventing a keyword. The
separate ``STOS_KEYWORDS`` set below is the documented STOS 2.x vocabulary and
is used only for colouring an ASCII listing, where no byte value is at stake.
"""

from __future__ import annotations

#: Single-byte keywords, 0x80 upward.
BASE_TOKENS: dict[int, str] = {
    0x80: 'to',
    0x81: 'step',
    0x82: 'next',
    0x83: 'wend',
    0x84: 'until',
    0x85: 'dim',
    0x86: 'poke',
    0x89: 'read',
    0x8B: 'return',
    0x8C: 'pop',
    0x8E: 'resume',
    0x8F: 'on error',
    0x90: 'screen copy',
    0x92: 'plot',
    0x94: 'draw',
    0x96: 'polymark',
    0x98: 'goto',
    0x99: 'gosub',
    0x9A: 'then',
    0x9B: 'else',
    0x9C: 'restore',
    0x9D: 'for',
    0x9E: 'while',
    0x9F: 'repeat',
    0xA1: 'print',
    0xA2: 'if',
    0xA3: 'update',
    0xA6: 'off',
    0xA7: 'on',
    0xA9: 'locate',
    0xAA: 'paper',
    0xAB: 'pen',
    0xAC: 'home',
    0xB4: 'cls',
    0xB5: 'inc',
    0xB6: 'dec',
    0xB7: 'screen swap',
    0xC3: 'fkey',
    0xC4: 'sin',
    0xC5: 'cos',
    0xC7: 'timer',
    0xC8: 'logic',
    0xCA: 'not',
    0xCB: 'rnd',
    0xCC: 'val',
    0xCD: 'asc',
    0xCE: 'chr$',
    0xCF: 'inkey$',
    0xD1: 'mid$',
    0xD2: 'right$',
    0xD4: 'length',
    0xD5: 'start',
    0xD6: 'len',
    0xD7: 'pi',
    0xD8: 'peek',
    0xDB: 'zone',
    0xDE: 'x mouse',
    0xDF: 'y mouse',
    0xE0: 'mouse key',
    0xE1: 'physic',
    0xE2: 'back',
    0xE5: 'mode',
    0xE8: 'screen$',
    0xE9: 'default',
    0xEC: 'or',
    0xED: 'and',
    0xEE: '<>',
    0xEF: '<=',
    0xF0: '>=',
    0xF1: '=',
    0xF2: '<',
    0xF3: '>',
    0xF4: '+',
    0xF5: '-',
    0xF6: 'mod',
    0xF7: '*',
    0xF8: '/',
    0xF9: '^',
}

#: Commands reached through the 0xA0 escape.
INSTRUCTION_TOKENS: dict[int, str] = {
    0x71: 'fade',
    0x77: 'wait key',
    0x7A: 'bload',
    0x7B: 'bsave',
    0x82: 'title',
    0x87: 'centre',
    0x89: 'volume',
    0x8B: 'boom',
    0x8C: 'shoot',
    0x8D: 'bell',
    0x8E: 'play',
    0x90: 'voice',
    0x92: 'box',
    0x94: 'bar',
    0x96: 'appear',
    0x9B: 'curs',
    0x9C: 'clw',
    0xA1: 'run',
    0xA2: 'clear key',
    0xA4: 'input',
    0xA6: 'data',
    0xA7: 'end',
    0xA8: 'erase',
    0xA9: 'reserve',
    0xAB: 'as work',
    0xAC: 'as screen',
    0xAF: 'def',
    0xB0: 'hide',
    0xB1: 'show',
    0xB2: 'change mouse',
    0xBD: 'anim',
    0xBF: 'set zone',
    0xC6: 'load',
    0xC7: 'save',
    0xC8: 'palette',
    0xC9: 'synchro',
    0xCC: 'let',
    0xCD: 'key',
    0xCE: 'open in',
    0xCF: 'open out',
    0xD0: 'open',
    0xD1: 'close',
    0xD4: 'put key',
    0xD5: 'get palette',
    0xDB: 'wait vbl',
    0xDE: 'flash',
    0xE1: 'auto back',
    0xE3: 'gr writing',
    0xE4: 'set mark',
    0xE5: 'set paint',
    0xEA: 'polygon',
    0xEC: 'earc',
    0xF1: 'ink',
    0xF2: 'wait',
    0xF3: 'click',
    0xF4: 'put',
    0xF6: 'set curs',
    0xF9: 'scroll',
    0xFA: 'inverse',
    0xFC: 'windopen',
    0xFF: 'windel',
}

#: Functions reached through the 0xB8 escape.
FUNCTION_TOKENS: dict[int, str] = {
    0x8A: 'errn',
    0x8D: 'input$',
    0x8F: 'free',
    0x90: 'str$',
    0x94: 'space$',
    0x95: 'instr',
    0x99: 'eof',
    0x9A: 'dir first$',
    0xA1: 'hunt',
    0xA2: 'true',
    0xA3: 'false',
    0xA6: 'jup',
    0xA7: 'jleft',
    0xA8: 'jright',
    0xA9: 'jdown',
    0xAE: 'tab',
    0xBF: 'file select$',
    0xC1: 'sgn',
    0xC4: 'int',
}

#: Commands installed by an extension: (extension number, command byte).
EXTENSION_INSTRUCTIONS: dict[tuple[int, int], str] = {
    (7, 0x80): 'set stars',
    (7, 0x82): 'go stars',
    (7, 0x84): 'wipe stars on',
    (12, 0x8A): 'mouseon',
    (16, 0x82): 'bob',
    (16, 0x88): 'world',
    (16, 0x92): 'set block',
    (19, 0x80): 'track play',
}

#: Functions installed by an extension: (extension number, function byte).
EXTENSION_FUNCTIONS: dict[tuple[int, int], str] = {
    (16, 0x81): 'overlap',
    (16, 0x87): 'palt',
    (16, 0x8B): 'which block',
}

#: Escape bytes and the literal encodings, named where ``stos.py`` uses them.
REM_TOKEN = 0x8A
BRANCH_TOKENS = range(0x98, 0xA0)
INSTRUCTION_ESCAPE = 0xA0
EXTENSION_INSTRUCTION_ESCAPE = 0xA8
FUNCTION_ESCAPE = 0xB8
EXTENSION_FUNCTION_ESCAPE = 0xC0
VARIABLE_TOKEN = 0xFA
BINARY_TOKEN = 0xFB
STRING_TOKEN = 0xFC
HEX_TOKEN = 0xFD
INTEGER_TOKEN = 0xFE
FLOAT_TOKEN = 0xFF

#: Tokens the lister prints as operators rather than as commands.
OPERATOR_TOKENS = frozenset(range(0xEC, 0xFA))

#: The documented STOS 2.x vocabulary. This drives colouring of an ASCII
#: listing only; nothing here claims a byte value.
STOS_KEYWORDS: tuple[str, ...] = tuple(
    """
    ABS AFTER AND ANIM APPEAR ASC ATN AUTO BACK BAR BELL BGRAB BLOAD BOOM BORDER BOX BSAVE
    CALL CENTRE CHANGE CHR$ CIRCLE CLEAR CLICK CLOSE CLS CLW COLLIDE COLOUR COPY COS CURS CUT
    DATA DATE$ DEC DEEK DEF DEFAULT DEG DELETE DFREE DIM DIR DIR$ DIV DO DOKE DRAW DRAWTO
    EARC EDIT ELLIPSE ELSE END EOF ERASE ERR ERRN ERROR EXP FADE FALSE FILL FIX FKEY FLASH
    FLIP FOR FRE FREE GET GOSUB GOTO HARDCOPY HEX$ HIDE HOME HUNT IF INC INK INKEY$ INPUT
    INPUT$ INSTR INT INVERSE JDOWN JLEFT JRIGHT JUP KEY LDIR LEEK LEFT$ LEN LENGTH LET LIMIT
    LINE LIST LLIST LOAD LOCATE LOG LOGIC LOKE LOWER$ LPRINT MENU MENU$ MID$ MKDIR MODE MOUSE
    MOVE MUSIC NEW NEXT NOT OFF OLD ON OPEN OR PALETTE PALT PAPER PASTE PEEK PEN PHYSIC PI
    PLAY PLOT POINT POKE POLYGON POLYLINE POLYMARK POP PRINT PRIORITY PSET PUT RAD RANDOMIZE
    READ REM REPEAT RESERVE RESTORE RESUME RETURN RIGHT$ RND RUN SAVE SCAN SCREEN SCREEN$
    SCRN SCROLL SET SGN SHOOT SHOW SIN SORT SPACE$ SPRITE SQR START STEP STOP STR$ STRING$
    SWAP SYNCHRO SYSTEM TAB TAN TEXT THEN TIMER TO TRACK TROFF TRON TRUE UNPACK UNTIL UPDATE
    UPPER$ VAL VARPTR VOICE VOLUME WAIT WEND WHILE WINDEL WINDMOVE WINDOPEN WINDOW WINDSIZE
    WORLD XOR ZONE ZONE$ BOB OVERLAP MOUSEON
    """.split()
)

#: STOS spells these commands as two or three words. The scanner has to read
#: each as one keyword or it would colour ``OPEN`` inside ``SCREEN OPEN``.
STOS_COMPOUND_KEYWORDS: tuple[str, ...] = (
    "SCREEN OPEN", "SCREEN CLOSE", "SCREEN COPY", "SCREEN SWAP", "SCREEN$",
    "MOVE ON", "MOVE OFF", "MOVE X", "MOVE Y", "PUT BOB", "GET BOB", "DEF SCROLL",
    "MENU ON", "MENU OFF", "WINDOW OPEN", "WINDOW CLOSE", "SPRITE OFF", "MUSIC OFF",
    "LIMIT SPRITE", "LIMIT MOUSE", "SET LINE", "SET ZONE", "SET CURS", "SET MARK",
    "SET PAINT", "SET BLOCK", "SET PATTERN", "KEY OFF", "KEY ON", "KEY SPEED",
    "CURS OFF", "CURS ON", "CLEAR KEY", "PUT KEY", "WAIT KEY", "WAIT VBL",
    "AUTO BACK", "CHANGE MOUSE", "GR WRITING", "MOUSE KEY", "MOUSE SCREEN",
    "X MOUSE", "Y MOUSE", "ON ERROR", "OPEN IN", "OPEN OUT", "DEF FN",
    "TRACK PLAY", "TRACK LOAD", "TRACK STOP", "DIR FIRST$", "DIR NEXT$",
    "FILE SELECT$", "SCROLL ON", "SCROLL OFF", "CLICK ON", "CLICK OFF",
    "ANIM ON", "ANIM OFF", "ANIM FREEZE", "WHICH BLOCK", "LINE INPUT",
)

__all__ = [
    "BASE_TOKENS",
    "BINARY_TOKEN",
    "BRANCH_TOKENS",
    "EXTENSION_FUNCTIONS",
    "EXTENSION_FUNCTION_ESCAPE",
    "EXTENSION_INSTRUCTIONS",
    "EXTENSION_INSTRUCTION_ESCAPE",
    "FLOAT_TOKEN",
    "FUNCTION_ESCAPE",
    "FUNCTION_TOKENS",
    "HEX_TOKEN",
    "INSTRUCTION_ESCAPE",
    "INSTRUCTION_TOKENS",
    "INTEGER_TOKEN",
    "OPERATOR_TOKENS",
    "REM_TOKEN",
    "STOS_COMPOUND_KEYWORDS",
    "STOS_KEYWORDS",
    "STRING_TOKEN",
    "VARIABLE_TOKEN",
]
