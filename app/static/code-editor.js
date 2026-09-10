window.AtariCodeEditor = (() => {
  //  The application's own question, notice and single-value dialogs. The
  //  editor used the browser's native ones because it runs inside a modal and
  //  a second <dialog> cannot be opened over one; these layer over whatever is
  //  already on screen, so the editor is no longer the one place in the
  //  application that raises unstyled operating-system alerts.
  //
  //  They are looked up when they are called rather than when this file
  //  loads, because the language analysis in here is also exercised by the
  //  Node tests, which have no interface to take them from.
  const alertNotice = (...args) => window.AtariUI.alertNotice(...args);
  const confirmChoice = (...args) => window.AtariUI.confirmChoice(...args);
  const promptValue = (...args) => window.AtariUI.promptValue(...args);
  const BASIC_LANGUAGE = window.AtariBasicLanguage;
  const ASSEMBLY_LANGUAGE = window.AtariAssemblyLanguage;
  const CALL_CATALOGUE = window.AtariCallCatalogue;
  // Every Atari ST decodes the same 68000 instruction set: the ST, Mega ST,
  // STE and Mega STE carry a 68000, the TT030 and Falcon030 a 68030, and a
  // TT or Falcon may add a 68881 or 68882 floating-point unit. The editor
  // treats them as one language and varies only the extensions it accepts.
  const MACHINE_PROCESSORS = Object.freeze({ st: "68000", megast: "68000", ste: "68000", megaste: "68000", tt030: "68030", falcon030: "68030" });
  const M68K_TARGETS = ["68000", "68010", "68020", "68030", "68040", "68060", "68030+fpu", "68040+fpu", "68060+fpu", "m68k"];
  const PLATFORM_NAMES = Object.freeze({
    st: "Atari ST", megast: "Mega ST", ste: "Atari STE", megaste: "Mega STE", tt030: "Atari TT030", falcon030: "Atari Falcon030",
  });
  const esc = value => String(value ?? "").replace(/[&<>"']/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  }[character]));

  const help = (summary, syntax, requirements = "None beyond the active language or filing system.", notes = "") => ({
    summary, syntax, requirements, notes,
  });

  // GFA BASIC is the dialect most ST source arrives in, so its spellings lead
  // each entry; STOS and ST BASIC forms of the same command are named where
  // they differ. Keys are the upper-case keyword as the scanner reports it.
  const GFA_HELP = {
    PROCEDURE: help("Begins a named procedure; RETURN ends it.", "PROCEDURE name[(parameters)]", "Every PROCEDURE needs one RETURN at its end, and it is called with @name or GOSUB name.", "Parameters are passed by value unless written VAR; LOCAL hides variables from the caller."),
    RETURN: help("Ends a PROCEDURE, or returns from GOSUB in STOS and ST BASIC.", "RETURN", "In GFA BASIC a RETURN belongs to the PROCEDURE it closes; in a numbered listing it needs an active GOSUB.", "A FUNCTION returns its value with RETURN expression and ends with ENDFUNC."),
    FUNCTION: help("Begins a named function that returns a value.", "FUNCTION name[(parameters)]", "Ends with ENDFUNC; the value comes from RETURN expression and is read with @name(...).", "GFA BASIC 3 only; GFA 2 has DEFFN for single-line functions."),
    ENDFUNC: help("Ends a FUNCTION block.", "ENDFUNC", "A matching FUNCTION must be open."),
    DEFFN: help("Defines a single-line function.", "DEFFN name[(parameters)]=expression", "Called as FN name(...) or @name(...). The definition must run before the first call."),
    FN: help("Calls a DEFFN function.", "FN name(arguments)", "A matching DEFFN must have been executed."),
    GOSUB: help("Calls a PROCEDURE by name, or a numbered subroutine in STOS and ST BASIC.", "GOSUB name  or  GOSUB line", "The procedure or line must exist; GFA BASIC also writes the call as @name."),
    GOTO: help("Jumps to a label or a line number.", "GOTO label  or  GOTO line", "In GFA BASIC the destination is a label written label: on its own line; numbered dialects take a line number."),
    LOCAL: help("Makes variables local to the enclosing PROCEDURE or FUNCTION.", "LOCAL variable[,variable...]", "Must appear inside the procedure before the variables are used.", "A local hides a global of the same name until RETURN."),
    REPEAT: help("Starts a loop tested at its end.", "REPEAT", "A matching UNTIL condition ends the loop; the body runs at least once."),
    UNTIL: help("Ends a REPEAT loop when its condition becomes true.", "UNTIL condition", "A matching REPEAT must be open."),
    DO: help("Starts an endless loop that is left with EXIT IF or LOOP UNTIL.", "DO [WHILE condition | UNTIL condition]", "A matching LOOP ends the block; without EXIT IF or a condition it never ends."),
    LOOP: help("Ends a DO loop.", "LOOP [WHILE condition | UNTIL condition]", "A matching DO must be open."),
    EXIT: help("Leaves the innermost loop when a condition holds.", "EXIT IF condition", "Only valid inside FOR, WHILE, REPEAT or DO."),
    WHILE: help("Starts a loop tested before each pass.", "WHILE condition", "A matching WEND ends the loop."),
    WEND: help("Returns to the matching WHILE test.", "WEND", "A matching WHILE must be open."),
    FOR: help("Starts a counted loop.", "FOR variable=start TO limit [STEP amount] [DOWNTO limit]", "A matching NEXT completes the loop."),
    NEXT: help("Advances the active FOR loop.", "NEXT [variable]", "The named variable must belong to the active FOR loop."),
    IF: help("Runs a block of statements when a condition holds.", "IF condition [THEN]\n ...\n[ELSE IF condition]\n[ELSE]\nENDIF", "In GFA BASIC IF always opens a block closed by ENDIF. STOS and ST BASIC also accept IF condition THEN statement on one line."),
    ELSE: help("Starts the alternative branch of an IF block.", "ELSE  or  ELSE IF condition", "An IF block must be open."),
    ENDIF: help("Closes an IF block.", "ENDIF", "An IF block must be open; STOS writes it END IF."),
    SELECT: help("Chooses one of several CASE branches by value.", "SELECT expression\nCASE value[,value...] [TO value]\nDEFAULT\nENDSELECT", "Closed with ENDSELECT; values must match the expression's type."),
    CASE: help("One branch of a SELECT block.", "CASE value[,value...] or CASE low TO high", "Must appear inside SELECT ... ENDSELECT."),
    DEFAULT: help("The branch taken when no CASE matched.", "DEFAULT", "Must be the last branch of a SELECT block."),
    ENDSELECT: help("Closes a SELECT block.", "ENDSELECT", "A SELECT block must be open."),
    DIM: help("Reserves an array.", "DIM array(size[,size...])", "Indexes run from 0 to size. Enough free memory must remain; ERASE releases the array.", "GFA BASIC does not create arrays on first use, so an undimensioned reference is an error."),
    ERASE: help("Releases an array.", "ERASE array()", "The array must have been dimensioned."),
    INLINE: help("Reserves bytes inside the program for machine code or data.", "INLINE address%,length", "The bytes are entered in the GFA editor and saved with the program; call them with C: or CALL and read them with PEEK."),
    CALL: help("Runs machine code at an address.", "CALL address%[(parameters)]  or  ~C:address%(parameters)", "The code must be valid 68000 code that ends in RTS and preserves the registers GFA BASIC expects.", "A wrong address takes the machine down; TT and Falcon code must also respect the 68030 caches."),
    "~": help("Calls a function and discards its result.", "~function(arguments)", "Used for GEMDOS, BIOS, XBIOS and other functions whose return value is not wanted."),
    PEEK: help("Reads one byte from an address.", "PEEK(address%)", "The address must exist; reading an unmapped address raises a bus error.", "DPEEK and LPEEK read a word and a long, and both need an even address on a 68000."),
    DPEEK: help("Reads one 16-bit word from an even address.", "DPEEK(address%)", "The address must be even; an odd address raises an address error on a 68000."),
    LPEEK: help("Reads one 32-bit long from an even address.", "LPEEK(address%)", "The address must be even; an odd address raises an address error on a 68000."),
    POKE: help("Writes one byte to an address.", "POKE address%,value", "Writing to an address TOS owns, or to a hardware register, changes the machine state directly.", "DPOKE and LPOKE write a word and a long, and both need an even address. System variables above $400 can only be written in supervisor mode."),
    DPOKE: help("Writes one 16-bit word to an even address.", "DPOKE address%,value", "The address must be even; an odd address raises an address error on a 68000."),
    LPOKE: help("Writes one 32-bit long to an even address.", "LPOKE address%,value", "The address must be even; an odd address raises an address error on a 68000."),
    SPOKE: help("Writes one byte in supervisor mode, so protected system variables can be changed.", "SPOKE address%,value", "Use SDPOKE and SLPOKE for a word and a long."),
    GEMDOS: help("Calls a GEMDOS function through TRAP #1.", "GEMDOS(function[,argument...])", "Arguments are pushed as words; prefix a long with L: and an address with L:VARPTR or L:ADDR.", "The returned long is the value in D0; a negative value is a GEMDOS error code."),
    BIOS: help("Calls a BIOS function through TRAP #13.", "BIOS(function[,argument...])", "Arguments are pushed as words unless prefixed with L:."),
    XBIOS: help("Calls an XBIOS function through TRAP #14.", "XBIOS(function[,argument...])", "Arguments are pushed as words unless prefixed with L:.", "Calls above 63 need an STE, TT or Falcon and are refused with an error on an ST."),
    GEMSYS: help("Calls an AES function through TRAP #2 using the GINTIN, GINTOUT, ADDRIN and ADDROUT arrays.", "GEMSYS [opcode]", "The opcode goes into CONTRL(0) when given; the other CONTRL words and the arrays must be filled first.", "GFA BASIC keeps the parameter block at GCONTRL, GINTIN, GINTOUT, ADDRIN and ADDROUT; ST BASIC uses CONTRL, GINTIN, GINTOUT, ADDRIN and ADDROUT."),
    VDISYS: help("Calls a VDI function through TRAP #2 using the CONTRL, INTIN, PTSIN, INTOUT and PTSOUT arrays.", "VDISYS [opcode[,vertices,intin,subopcode]]", "CONTRL(0) is the opcode, CONTRL(1) the number of PTSIN pairs, CONTRL(3) the number of INTIN words and CONTRL(5) the escape or GDP sub-opcode.", "The VDI handle in CONTRL(6) is the one the desktop opened for BASIC."),
    VSYNC: help("Waits for the next vertical blank.", "VSYNC", "Smooth animation changes the screen straight after VSYNC; it also paces a loop to 50 or 60 frames a second."),
    SOUND: help("Programs one voice of the YM2149 sound chip.", "SOUND voice,volume,note,octave[,duration]", "The voice is 1 to 3, the volume 0 to 15, the note 1 to 12 and the octave 1 to 8; note 0 takes a period in the octave position."),
    WAVE: help("Sets the sound chip's envelope and noise mixer.", "WAVE voices,envelope,shape,period[,duration]", "Both masks use bit 0 for voice 1; the shape is 0 to 15."),
    PBOX: help("Draws a filled rectangle.", "PBOX x1,y1,x2,y2", "Uses the DEFFILL pattern and colour and the GRAPHMODE writing mode."),
    BOX: help("Draws a rectangle outline.", "BOX x1,y1,x2,y2", "Uses the DEFLINE style and colour."),
    RBOX: help("Draws a rounded rectangle outline.", "RBOX x1,y1,x2,y2", "PRBOX fills it."),
    CIRCLE: help("Draws a circle outline, or an arc when angles are given.", "CIRCLE x,y,radius[,start,end]", "Angles are in tenths of a degree; PCIRCLE fills the shape. STOS and ST BASIC take the same arguments.", "ST BASIC: CIRCLE x,y,radius[,start,end] in degrees, PCIRCLE for a filled circle."),
    PCIRCLE: help("Draws a filled circle or pie slice.", "PCIRCLE x,y,radius[,start,end]", "Uses the DEFFILL pattern and colour."),
    ELLIPSE: help("Draws an ellipse outline, or an elliptical arc.", "ELLIPSE x,y,xradius,yradius[,start,end]", "PELLIPSE fills it."),
    PLINE: help("Draws a polyline through points held in an array.", "PLINE count,array%()[,offset]", "The array holds x and y pairs; POLYLINE is the same statement in full."),
    FILL: help("Flood fills from a point up to a boundary.", "FILL x,y[,boundary]", "The starting point must lie inside a closed area; uses the DEFFILL pattern and colour."),
    DEFFILL: help("Sets the fill colour, pattern type and pattern index for filled shapes.", "DEFFILL [colour][,type[,index]]  or  DEFFILL colour,pattern%()", "Type 0 is hollow, 1 solid, 2 pattern and 3 hatch; the index runs from 1 to 24 for patterns and 1 to 12 for hatches."),
    DEFLINE: help("Sets the line style, width and end shapes.", "DEFLINE [style][,width[,start,end]]", "Style 1 is solid, 2 long dash, 3 dot, 4 dash dot, 5 dash, 6 dash dot dot, or a 16-bit pattern above 255. The width must be odd."),
    DEFTEXT: help("Sets the colour, effects, rotation and size for TEXT output.", "DEFTEXT [colour][,effects[,rotation[,size]]]", "Effects are bit 0 bold, 1 light, 2 italic, 3 underline, 4 outline, 5 shadow; rotation is in tenths of a degree; the size is in points, 4 to 32 on the system font."),
    GRAPHMODE: help("Sets the VDI writing mode for drawing.", "GRAPHMODE mode", "1 replace, 2 transparent, 3 XOR, 4 reverse transparent."),
    GET: help("Copies a screen rectangle into a string, or reads a record from a file.", "GET x1,y1,x2,y2,buffer$  or  GET #channel[,record]", "The string must be large enough; GET on a channel needs a record length given with OPEN."),
    PUT: help("Draws a string saved with GET back onto the screen, or writes a record to a file.", "PUT x,y,buffer$[,mode]  or  PUT #channel[,record]", "The mode is a VDI logic operation 0 to 15; 3 replaces and 6 uses XOR."),
    BITBLT: help("Copies a raster block between memory form definition blocks through vro_cpyfm.", "BITBLT source%(),destination%(),parameters%()  or  BITBLT array%()", "The MFDB arrays describe width, height and planes; a wrong plane count corrupts memory outside the screen."),
    ALERT: help("Shows a GEM alert box and returns the button chosen.", "ALERT icon,message$,default,buttons$,result%", "The icon is 0 none, 1 exclamation, 2 question, 3 stop; lines in the message and buttons are separated by |.", "Up to five lines of 30 characters and three buttons of ten characters fit."),
    FILESELECT: help("Shows the GEM file selector.", "FILESELECT [#title$,]path$,default$,result$", "The path must end in a mask such as \\*.*; the result is empty when Cancel is chosen. The title needs TOS 1.04 or later."),
    MENU: help("Installs, polls or changes a GEM menu bar.", "MENU array$()  MENU OFF  MENU KILL  MENU index,state  ON MENU GOSUB name", "Titles and items come from the string array, with empty strings ending each column; ON MENU handles selection and MENU(0) reports the item chosen.", "STOS: MENU$(n)=title$ defines a title and MENU ON shows the bar."),
    OPENW: help("Opens one of GFA BASIC's GEM windows.", "OPENW number[,x,y,w,h,attributes]", "Window numbers run 1 to 4; attributes are the AES window element bits. CLOSEW closes it.", "ST BASIC: OPENW n opens one of its four output windows."),
    CLOSEW: help("Closes a GEM window opened with OPENW.", "CLOSEW number", "The window must be open."),
    TITLEW: help("Sets a window's title.", "TITLEW number,title$", "The window must be open."),
    CLEARW: help("Clears a window to the background colour.", "CLEARW number", "The window must be open."),
    INFOW: help("Sets a window's information line.", "INFOW number,text$", "The window must have been opened with the INFO element bit."),
    FULLW: help("Enlarges a window to the full screen.", "FULLW number", "The window must be open."),
    RESERVE: help("Changes how much memory GFA BASIC keeps for itself, releasing the rest to TOS.", "RESERVE [bytes]", "Needed before EXEC or MALLOC so the called program or the allocation has memory to use; RESERVE alone restores the default.", "Reserving less than the program and its strings need crashes GFA BASIC."),
    MALLOC: help("Allocates memory from GEMDOS and returns its address.", "MALLOC(bytes)", "Memory released with RESERVE is what GEMDOS can give; -1 reports the largest free block. Free it with MFREE.", "TOS limits a program to about 20 Malloc blocks, so allocate in large pieces."),
    MFREE: help("Frees a block allocated with MALLOC.", "~MFREE(address%)", "The address must be one MALLOC returned."),
    EXEC: help("Runs another program through Pexec.", "EXEC mode,program$,command$,environment$", "Mode 0 loads and runs; memory must have been released with RESERVE first. The command string starts with a length byte."),
    CHAIN: help("Loads and runs another GFA BASIC program in place of this one.", 'CHAIN "program.gfa"', "The file must be a GFA BASIC program in the same saved format; variables are lost."),
    BLOAD: help("Loads a file straight into memory.", 'BLOAD "file"[,address%]', "The memory must have been reserved; without an address the file loads where it was saved from.", "STOS: BLOAD name$,address or BLOAD name$,bank."),
    BSAVE: help("Saves a block of memory to a file.", 'BSAVE "file",address%,length', "The destination must be writable.", "STOS: BSAVE name$,start TO end."),
    OPEN: help("Opens a file or device on a numbered channel.", 'OPEN "mode",#channel,"file"[,record]', 'The mode is "I" input, "O" output, "A" append, "R" random or "U" update; the channel runs from 0 to 99.', 'STOS: OPEN IN #n,name$ or OPEN OUT #n,name$. ST BASIC: OPEN "I",#n,name$.'),
    CLOSE: help("Closes one channel, or every channel when used bare.", "CLOSE [#channel]", "The channel must be open."),
    "INPUT#": help("Reads values from an open channel.", "INPUT #channel,variable[,variable...]", "The channel must be open for input and hold textual data; LINE INPUT # reads a whole line."),
    "PRINT#": help("Writes values to an open channel.", "PRINT #channel,expression[;expression...]", "The channel must be open for output; WRITE # quotes strings."),
    SEEK: help("Moves a channel's read and write position.", "SEEK #channel,offset", "The channel must be open; a negative offset is relative to the end."),
    LOF: help("Returns the length of an open file.", "LOF(#channel)", "The channel must be open."),
    LOC: help("Returns the current position in an open file.", "LOC(#channel)", "The channel must be open."),
    EOF: help("Reports whether a channel has reached its end.", "EOF(#channel)", "The channel must be open for input."),
    DIR: help("Lists a directory to the screen or a channel.", 'DIR ["mask"] [TO "file"]', 'The mask follows GEMDOS wildcards, such as "*.PRG". DIR$(n) returns one entry at a time.', "STOS: DIR lists the current folder and DIR$ holds the current path."),
    CHDIR: help("Changes the current directory, and the drive when one is given.", 'CHDIR "path"', "The path must exist.", "STOS and ST BASIC: CHDIR path$."),
    MKDIR: help("Creates a directory.", 'MKDIR "path"', "The parent must exist and be writable."),
    RMDIR: help("Removes an empty directory.", 'RMDIR "path"', "The directory must be empty."),
    KILL: help("Deletes a file.", 'KILL "file"', "The file must exist and not be read-only."),
    NAME: help("Renames or moves a file within a drive.", 'NAME "old" AS "new"', "The new name must not already exist."),
    TOUCH: help("Sets a channel's file date and time stamp to the current time.", "TOUCH #channel", "The channel must be open for writing."),
    PRINT: help("Writes values to the screen or the current window.", "PRINT [AT(column,line);] expression[;expression...]", "A semicolon joins items, a comma tabs to the next zone, and a trailing semicolon suppresses the line feed."),
    TEXT: help("Writes graphic text at a pixel position using DEFTEXT.", "TEXT x,y[,width],text$", "Uses the VDI text attributes rather than the text cursor."),
    INPUT: help("Reads values from the keyboard.", 'INPUT ["prompt",] variable[,variable...]', "Each value must be compatible with its variable; INPUT$(n) reads n characters without echo."),
    CLS: help("Clears the screen or the current output window.", "CLS", "None."),
    DATA: help("Stores constant values for READ.", "DATA value[,value...]", "READ variables must match the stored values; RESTORE repositions the stream, to a label in GFA BASIC."),
    READ: help("Reads the next value from the program's DATA stream.", "READ variable[,variable...]", "Enough DATA values must remain."),
    RESTORE: help("Moves the DATA read pointer to the start or to a label.", "RESTORE [label]", "A named label must exist."),
    ON: help("Selects a branch by value, or installs an event handler.", "ON expression GOSUB name,name...  ON MENU GOSUB name  ON BREAK CONT  ON ERROR GOSUB name", "Branch destinations must exist; ON ERROR GOSUB routes every run-time error to a procedure until RESUME or RETURN."),
    ERROR: help("Raises a run-time error with a numeric code.", "ERROR number", "The active ON ERROR handler may intercept it; ERR holds the code and ERR$(n) its text."),
    RESUME: help("Continues after an error handler.", "RESUME [NEXT | label]", "Only valid inside an ON ERROR GOSUB handler."),
    END: help("Ends the program.", "END", "Open channels are closed and windows restored."),
    STOP: help("Halts the program and returns to the editor.", "STOP", "CONT resumes where STOP left off."),
    REM: help("Introduces a comment; the rest of the line is ignored.", "REM comment  ' comment  ! trailing comment", "GFA BASIC also accepts ' at the start of a line and ! after a statement."),
    RANDOMIZE: help("Reseeds the random number generator.", "RANDOMIZE [seed]", "Without a seed GFA BASIC uses the clock."),
    SWAP: help("Exchanges the values of two variables of the same type.", "SWAP first,second", "Both variables must have the same type; arrays may be swapped whole."),
    HIDEM: help("Hides the mouse pointer.", "HIDEM", "SHOWM shows it again; each HIDEM needs a SHOWM."),
    SHOWM: help("Shows the mouse pointer.", "SHOWM", "None."),
    MOUSE: help("Reads the mouse position and button state.", "MOUSE x,y,k", "k holds bit 0 for the left button and bit 1 for the right. MOUSEX, MOUSEY and MOUSEK are the same values as functions."),
    SETCOLOR: help("Sets one palette register.", "SETCOLOR index,colour  or  SETCOLOR index,red,green,blue", "The index runs 0 to 15 and each component 0 to 7 on an ST, 0 to 15 on an STE.", "Writes the hardware register through Setcolor, so the VDI colour indexes may not match the register numbers."),
    VSETCOLOR: help("Sets one VDI colour index in VDI order.", "VSETCOLOR index,red,green,blue", "Components run 0 to 7; the index is the VDI logical colour, not the hardware register."),
    COLOR: help("Sets the drawing colour, or the text and background pens in STOS and ST BASIC.", "COLOR index  or  COLOR foreground[,background]", "The index must exist in the current resolution: 16 in low, 4 in medium, 2 in high.", "ST BASIC: COLOR text,fill,line[,pattern,style]."),
    LINEF: help("Draws a line between two points (ST BASIC).", "LINEF x1,y1,x2,y2", "Uses the current COLOR line colour.", "GFA BASIC: LINE x1,y1,x2,y2. STOS: DRAW x1,y1 TO x2,y2."),
    LINE: help("Draws a line between two points.", "LINE x1,y1,x2,y2", "Uses the DEFLINE style and colour."),
    PLOT: help("Sets one pixel.", "PLOT x,y", "Uses the current COLOR. STOS and ST BASIC: PLOT x,y."),
    DRAW: help("Draws from the current position, or along a path.", "DRAW [x1,y1] TO x2,y2  or  DRAW \"FD10 RT90\"", "The turtle string form accepts FD, BK, LT, RT, MA, TT and colour commands."),
    GOTOXY: help("Moves the text cursor (ST BASIC).", "GOTOXY column,line", "The position must lie inside the output window.", "GFA BASIC: PRINT AT(column,line). STOS: LOCATE column,line."),
    SYSTAB: help("Returns the address of ST BASIC's system table, which holds the GEM parameter block addresses.", "SYSTAB", "PEEK(SYSTAB+n) reads the table; offsets 8, 12, 16, 20 and 24 hold CONTRL, INTIN, PTSIN, INTOUT and PTSOUT."),
    LOCATE: help("Moves the text cursor.", "LOCATE column,line", "The position must lie inside the screen or window."),
    KEYDEF: help("Defines a function key string.", "KEYDEF key,text$", "Keys run 1 to 20, with 11 to 20 for shifted function keys."),
    KEYTEST: help("Reports whether a key is held down.", "KEYTEST(scancode)", "Uses the scan code, not the character."),
    INKEY$: help("Returns the key pressed, or an empty string.", "INKEY$", "A function or cursor key returns two characters, the first a null."),
    VARPTR: help("Returns the address of a variable.", "VARPTR(variable)  or  V:variable", "The address is only valid until GFA BASIC moves its variables; ARRPTR gives an array's descriptor."),
    ADDR: help("Returns the address of a string's characters or an array's data (GFA BASIC 3).", "ADDR(string$)  or  ADDR(array())", "The address is only valid until the string or array is reassigned."),
    TIMER: help("Returns the 200 Hz system timer, the _hz_200 count.", "TIMER", "Counts in 1/200 second since boot; divide by 200 for seconds."),
    PAUSE: help("Waits for a number of fiftieths of a second.", "PAUSE fiftieths", "The program is idle until the time passes; STOS WAIT n does the same."),
    WAIT: help("Waits for a time, or for a vertical blank (STOS).", "WAIT fiftieths  or  WAIT VBL  or  WAIT KEY", "STOS WAIT VBL synchronises with the screen; WAIT KEY waits for any key."),
  };

  // STOS spells many ST things its own way: memory banks, sprites and bobs,
  // and its own sound and palette commands.
  const STOS_HELP = {
    SCREEN: help("Selects a logical or physical screen, or works on a screen held in a bank.", "SCREEN OPEN bank,width,height,mode  SCREEN COPY source TO destination  SCREEN SWAP  SCREEN CLOSE bank", "SCREEN OPEN needs a free bank; the mode is 0 low, 1 medium or 2 high.", "SCREEN SWAP exchanges the logical and physical screens at the next vertical blank, which is how STOS double-buffers."),
    SPRITE: help("Shows one of STOS's 15 hardware-style sprites.", "SPRITE number,x,y,image  SPRITE OFF [number]", "The sprite bank (bank 1) must hold the image; sprites are drawn by an interrupt."),
    BOB: help("Draws a software sprite (blitter object) into the logical screen.", "BOB number,x,y,image  BOB OFF", "Needs the Missing Link or STOS extension that adds bobs; the image comes from the sprite bank."),
    ANIM: help("Animates a sprite through a sequence of images.", 'ANIM number,"(image,delay)(image,delay)..."  ANIM ON  ANIM OFF', "The sprite must exist; ANIM ON starts every defined animation."),
    MOVE: help("Moves a sprite along a path in the background.", 'MOVE X number,"(speed,step,count)..."  MOVE Y number,"..."  MOVE ON  MOVE OFF', "The sprite must exist; MOVE ON starts the movement and MOVON(n) reports whether it is still moving."),
    MUSIC: help("Plays music from the music bank.", "MUSIC number  MUSIC OFF  MUSIC FREQ value", "Bank 3 must hold music made with the STOS music editor."),
    BOOM: help("Plays the built-in explosion sound.", "BOOM", "Uses all three voices of the sound chip."),
    SHOOT: help("Plays the built-in shot sound.", "SHOOT", "Uses the sound chip noise generator."),
    BELL: help("Plays the built-in bell sound.", "BELL", "None."),
    PALETTE: help("Sets several palette registers at once.", "PALETTE colour0[,colour1,...]", "Each value is $RGB; up to sixteen may be given.", "ST BASIC and GFA BASIC use SETCOLOR for one register."),
    COLOUR: help("Sets or reads one palette register.", "COLOUR index,value  or  COLOUR(index)", "The index runs 0 to 15 and the value is $RGB."),
    FADE: help("Fades the palette to new colours over a number of frames.", "FADE speed[,colour0,colour1,...]", "Without colours FADE goes to black; the speed is in vertical blanks per step."),
    RAINBOW: help("Installs a changing colour bar on one palette register.", "RAINBOW number,offset,line,height  RAINBOW DEL", "The rainbow data comes from SET RAINBOW; it is redrawn by the interrupt."),
    SCROLL: help("Scrolls part of the screen as defined with DEF SCROLL.", "SCROLL number", "DEF SCROLL number,x1,y1 TO x2,y2,dx,dy must have defined the zone."),
    WINDOW: help("Opens, selects or closes a text window.", "WINDOW number  WINDOPEN number,x,y,width,height[,border[,set]]  WINDOW OFF  WINDCLOSE", "Up to 13 windows; WINDOPEN defines one and WINDOW selects it."),
    ZONE: help("Defines or tests a screen zone for the mouse.", "SET ZONE number,x1,y1 TO x2,y2  ZONE(number)  RESET ZONE", "Zones are tested with ZONE(0) for the mouse position or ZONE(n) for a sprite."),
    LOAD: help("Loads a program, or a file into a memory bank.", 'LOAD "file"[,bank]', "A bank number loads the file into that bank, reserving it if necessary; without one the file replaces the program."),
    SAVE: help("Saves the program, or a bank, to a file.", 'SAVE "file"[,bank]', "The destination must be writable; a bank saves with its type header."),
    RESERVE: help("Reserves a memory bank for screens, sprites, music or data.", "RESERVE AS SCREEN bank  RESERVE AS DATA bank,length  RESERVE AS WORK bank,length  RESERVE AS SET bank,length", "Banks run 1 to 15; 1 is the sprite bank and 3 the music bank by convention. ERASE bank releases one.", "GFA BASIC: RESERVE bytes changes the memory left to TOS."),
    ERASE: help("Releases a memory bank (STOS), or an array (GFA BASIC).", "ERASE bank  or  ERASE array()", "The bank or array must exist."),
    DOKE: help("Writes one 16-bit word to an even address (STOS).", "DOKE address,value", "The address must be even on a 68000.", "GFA BASIC: DPOKE."),
    LOKE: help("Writes one 32-bit long to an even address (STOS).", "LOKE address,value", "The address must be even on a 68000.", "GFA BASIC: LPOKE."),
    DEEK: help("Reads one 16-bit word from an even address (STOS).", "DEEK(address)", "The address must be even on a 68000.", "GFA BASIC: DPEEK."),
    LEEK: help("Reads one 32-bit long from an even address (STOS).", "LEEK(address)", "The address must be even on a 68000.", "GFA BASIC: LPEEK."),
    DIR$: help("Holds the current directory path (STOS), or returns a directory entry (GFA BASIC).", "DIR$  or  DIR$(n)", "STOS: assign DIR$ to change folder. GFA BASIC: DIR$(n) returns the nth entry after DIR."),
    START: help("Returns the start address of a memory bank.", "START(bank)", "The bank must be reserved."),
    LENGTH: help("Returns the length of a memory bank.", "LENGTH(bank)", "The bank must be reserved."),
    PHYSIC: help("Returns the address of the physical screen.", "PHYSIC", "Equivalent to Physbase; LOGIC is the logical screen and BACK the background screen."),
    LOGIC: help("Returns the address of the logical screen STOS draws into.", "LOGIC", "Use SCREEN SWAP to show it."),
    DREG: help("Holds a data register value for CALL or TRAP.", "DREG(n)=value  CALL address", "Registers 0 to 7; AREG(n) holds the address registers."),
    AREG: help("Holds an address register value for CALL or TRAP.", "AREG(n)=value", "Registers 0 to 6."),
    TRAP: help("Raises a 68000 TRAP with the DREG and AREG values loaded (STOS).", "TRAP number[,parameters...]", "TRAP 1 is GEMDOS, 13 the BIOS and 14 the XBIOS; the parameters are pushed like GEMDOS()."),
  };

  // Atari ST BASIC (the MetaComCo interpreter shipped with early STs) uses
  // numbered lines, GEM windows and GEMSYS/VDISYS for the system.
  const STBASIC_HELP = {
    SYSTAB: GFA_HELP.SYSTAB,
    GOTOXY: GFA_HELP.GOTOXY,
    FULLW: GFA_HELP.FULLW,
    CLEARW: GFA_HELP.CLEARW,
    LINEF: GFA_HELP.LINEF,
    PCIRCLE: GFA_HELP.PCIRCLE,
    DEF: help("Defines a single-line function (ST BASIC).", "DEF FNname(x)=expression", "The definition must be executed before the function is called.", "GFA BASIC: DEFFN name(x)=expression."),
    LET: help("Assigns a value to a variable.", "[LET] variable=expression", "The LET keyword is optional in every ST dialect."),
    ELLIPSE: GFA_HELP.ELLIPSE,
    PELLIPSE: help("Draws a filled ellipse.", "PELLIPSE x,y,xradius,yradius[,start,end]", "Uses the current fill settings."),
    WIDTH: help("Sets the line width of a channel or the output window.", "WIDTH [#channel,] columns", "The channel must be open."),
    WRITE: help("Writes values in comma-separated, quoted form.", "WRITE [#channel,] expression[,expression...]", "Intended to be read back by INPUT."),
    RUN: help("Runs the current program, or loads and runs a named one.", 'RUN [line | "program"]', "A named target must be a program in the same dialect."),
    NEW: help("Clears the program and variables.", "NEW", "Unsaved changes are lost."),
    LIST: help("Lists the program.", "LIST [first][-last]", "None."),
    TRON: help("Turns on line tracing.", "TRON", "TROFF turns it off."),
    TROFF: help("Turns off line tracing.", "TROFF", "None."),
    BREAK: help("Sets or clears break key handling (ST BASIC), or leaves a loop (GFA BASIC).", "BREAK ON  BREAK OFF  ON BREAK GOSUB name", "ST BASIC: BREAK OFF stops Control-G interrupting the program."),
    QUIT: help("Leaves ST BASIC and returns to the desktop.", "QUIT", "Unsaved changes are lost."),
    AUTO: help("Starts automatic line numbering in the editor.", "AUTO [start][,step]", "Only meaningful in a numbered dialect."),
    RENUM: help("Renumbers the program lines.", "RENUM [new][,old][,step]", "GOTO, GOSUB and THEN destinations are rewritten."),
    MERGE: help("Merges the lines of a saved program into the current one.", 'MERGE "program"', "The file must be a plain text listing."),
    FILES: help("Lists the current directory (ST BASIC).", 'FILES ["mask"]', "The path must be readable.", "GFA BASIC: DIR. STOS: DIR."),
  };

  const BASIC_HELP = { ...STBASIC_HELP, ...STOS_HELP, ...GFA_HELP };

  // The desktop reads DESKTOP.INF (TOS 1) or NEWDESK.INF (TOS 2 and later)
  // at boot, one record per line introduced by # and a letter. MINT.CNF is
  // the kernel's own configuration, read line by line before the AES starts.
  const SCRIPT_HELP = {
    "#A": help("General desktop settings: the date format, blitter and write verify switches.", "#a 000000", "One record per file, first in DESKTOP.INF.", "The digits are read positionally; a TOS that does not know a position keeps its default."),
    "#B": help("Desktop preferences: the confirm-delete and confirm-copy switches and the sort order.", "#b 000000", "One record per file."),
    "#C": help("The desktop colour palette, sixteen colours as one hexadecimal digit per component.", "#c 7770007000600070005000400030002000000555075507550755070007000700", "One record per file; TOS writes it when Save Desktop is chosen."),
    "#D": help("Icon and name for folders.", "#D FF 01 @ *.*@", "The two numbers are the icon index and an unused field; the text is the name mask."),
    "#E": help("Desktop options: the resolution and blitter, sort and confirmation bits.", "#E 18 11", "The first number holds the view and sort mode, the second the resolution on a TOS 1 desktop.", "Changing the resolution value here is how a desktop boots into medium resolution."),
    "#F": help("Icon and name mask for plain files.", "#F FF 04 @ *.*@", "Followed by the program assignments the desktop opens such files with."),
    "#G": help("Assigns a GEM program to a document type so double-clicking the document starts the program.", "#G 03 FF PROGRAM.PRG@ *.DOC@", "The program must be on the boot drive's path; 03 FF are the icon indexes."),
    "#I": help("An icon assigned to a file or program (NEWDESK.INF).", "#I 03 FF PROGRAM.PRG@ @", "NEWDESK.INF only."),
    "#K": help("Keyboard shortcuts for desktop menu items (NEWDESK.INF).", "#K 4F 53 4C 00 46 42 43 57 45 58 00 53 48 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 @", "TOS 2.05 or later."),
    "#M": help("A disk drive icon on the desktop.", "#M 00 00 00 FF A FLOPPY DISK@ @", "The first two numbers are the grid position, the fourth the icon index, then the drive letter and its label."),
    "#N": help("Icon and name mask for files without an application (NEWDESK.INF).", "#N FF 04 000 @ *.*@", "NEWDESK.INF only."),
    "#P": help("Assigns a TOS program to a document type.", "#P 03 FF PROGRAM.TOS@ *.TXT@", "The program runs in the TOS screen rather than under GEM."),
    "#Q": help("Desk accessory loading flags (NEWDESK.INF).", "#Q 41 40 43 40 43 40", "TOS 2.05 or later."),
    "#T": help("The trash can icon.", "#T 00 03 02 FF   TRASH@ @", "The numbers are the grid position and icon index."),
    "#V": help("Video mode for a Falcon desktop (NEWDESK.INF).", "#V 0000 0000 0000 0000 0000 0000", "TOS 4 only."),
    "#W": help("A desktop window: position, size, scroll position and path.", "#W 00 00 0E 01 1A 09 00 @", "Up to four windows on TOS 1, eight on TOS 2; the path is the folder it shows, with \\*.* at the end.", "A window record with a path on a drive that is not present is skipped at boot."),
    "#X": help("Extended desktop options (NEWDESK.INF).", "#X 0000 0000 0000", "TOS 2.05 or later."),
    "#Y": help("Assigns a TOS program that takes parameters (a TTP) to a document type.", "#Y 03 FF PROGRAM.TTP@ *.ARC@", "The document name is passed on the command line."),
    "#Z": help("Starts a program automatically when the desktop appears (NEWDESK.INF).", "#Z 01 C:\\GEM\\PROGRAM.PRG@", "TOS 2.05 or later; 01 marks a GEM program and 00 a TOS program."),
    INIT: help("Names the program MiNT runs as the shell or initial process.", "INIT=C:\\MINT\\SHELL.TOS", "Only one of INIT and GEM should be set; GEM starts an AES instead."),
    GEM: help("Names the AES MiNT starts once the kernel is ready.", "GEM=C:\\MINT\\XAAES\\XAAES.KM", "The path must exist; a .km kernel module is loaded directly, a .prg is run."),
    CON: help("Redirects the console during boot.", "CON=U:\\DEV\\MODEM1", "The device must exist in U:\\DEV."),
    PRN: help("Redirects the printer device.", "PRN=U:\\DEV\\PRN", "The device must exist in U:\\DEV."),
    AUX: help("Redirects the auxiliary serial device.", "AUX=U:\\DEV\\MODEM1", "The device must exist in U:\\DEV."),
    BIOBUF: help("Sets the number of buffers for the BIOS.", "BIOBUF=20,20", "Two values: buffers for the largest and the smallest sector size."),
    DEBUG_LEVEL: help("Sets how much the kernel reports while booting.", "DEBUG_LEVEL=2", "0 is silent and 4 traces everything; output goes to DEBUG_DEVNO."),
    DEBUG_DEVNO: help("Selects the BIOS device debug output goes to.", "DEBUG_DEVNO=2", "2 is the console, 1 the serial port, 6 Modem 1."),
    MAXMEM: help("Limits the memory a process may allocate.", "MAXMEM=4096", "In kilobytes; 0 removes the limit."),
    SLICES: help("Sets the scheduler time slice.", "SLICES=2", "In 1/200 second ticks; 0 gives every process the whole tick."),
    INITIALMEM: help("Sets the memory a process starts with when its program flags ask for protection.", "INITIALMEM=4096", "In kilobytes."),
    NEWFATFS: help("Switches the kernel's own FAT file system on for drives.", "NEWFATFS=C,D,E", "Drive letters separated by commas; needed for VFAT long names and large partitions."),
    VFAT: help("Enables VFAT long file names on drives using NEWFATFS.", "VFAT=C,D", "The drives must be listed in NEWFATFS."),
    FASTLOAD: help("Skips clearing memory when programs are loaded.", "FASTLOAD=YES", "Programs that expect zeroed memory break; set per program with the fast-load flag instead."),
    HIDE_B: help("Hides drive B when only one floppy is present.", "HIDE_B=YES", "Avoids the insert-disk alert for a missing second drive."),
    WRITEPROTECT: help("Makes drives read-only to the kernel.", "WRITEPROTECT=C", "Drive letters separated by commas."),
    CACHE: help("Sets the file system cache size.", "CACHE=200", "In kilobytes."),
    SECURELEVEL: help("Sets how strictly the kernel separates users.", "SECURELEVEL=0", "0 is no security, 1 restricts Super, 2 requires root for privileged calls."),
    MEMPROTECT: help("Turns memory protection on or off on a 68030 or later.", "MEMPROTECT=YES", "Needs a processor with an MMU; TT and Falcon programs that poke other processes' memory stop working."),
    CLOCKMODE: help("Says whether the hardware clock keeps local time or UTC.", "CLOCKMODE=LOCAL", "LOCAL or UTC."),
    SETENV: help("Sets an environment variable for every program MiNT starts.", "setenv PATH C:\\MINT;C:\\BIN", "The value follows the name after a space."),
    ALIAS: help("Makes a drive letter point at a folder.", "alias X: U:\\C\\MINT", "The letter must be free and the folder must exist."),
    SLN: help("Creates a symbolic link in the U: file system.", "sln u:\\c\\mint u:\\mint", "The target must exist."),
    ECHO: help("Writes a line during boot.", "echo Starting MiNT", "None."),
    CD: help("Changes the current directory during boot.", "cd c:\\mint", "The folder must exist."),
    EXEC: help("Runs a program during boot and waits for it.", "exec c:\\mint\\program.prg arguments", "The program must exist; it runs before the AES."),
    INCLUDE: help("Reads another configuration file at this point.", "include c:\\mint\\local.cnf", "The file must exist."),
    REN: help("Renames a file during boot.", "ren c:\\old.txt c:\\new.txt", "Both paths must be on the same drive."),
  };

  const BASIC_KEYWORDS = BASIC_LANGUAGE?.KEYWORDS || new Set();
  const SCRIPT_COMMANDS = new Set([...Object.keys(SCRIPT_HELP)]);
  const ASM_HELP = {
    MOVE: help("Copies a value and sets the condition codes from it.", "MOVE.size source,destination", "The size suffix and both addressing modes must be legal for the operation.", "MOVE.W #n,-(SP) before a TRAP pushes a function number or a word argument."),
    MOVEQ: help("Loads a sign-extended byte constant into a data register.", "MOVEQ #value,Dn", "The value must be between -128 and 127."),
    MOVEA: help("Copies a value into an address register without touching the condition codes.", "MOVEA.W/L source,An", "A word source is sign-extended to the full 32 bits."),
    MOVEM: help("Saves or restores a set of registers in one instruction.", "MOVEM.size list,destination", "The same register list and size must be used to restore them."),
    LEA: help("Loads the effective address of an operand into an address register.", "LEA source,An", "The source must use a control addressing mode."),
    PEA: help("Pushes the effective address of an operand onto the stack.", "PEA source", "A common way to pass a pointer argument to GEMDOS: PEA string then MOVE.W #9,-(SP) then TRAP #1."),
    JSR: help("Calls a subroutine, pushing the return address on the stack.", "JSR destination", "The destination must contain code that returns with RTS."),
    BSR: help("Calls a subroutine at a displacement from the program counter.", "BSR[.B|.W] label", "The label must be within the displacement range."),
    JMP: help("Transfers control without pushing a return address.", "JMP destination", "The destination must contain executable code."),
    RTS: help("Returns from a subroutine.", "RTS", "The stack must hold a valid return address."),
    RTE: help("Returns from an exception handler.", "RTE", "Only valid in supervisor mode with an intact exception frame; on a 68030 the frame carries a format word."),
    TRAP: help("Raises one of the sixteen TRAP exceptions; TOS answers #1 (GEMDOS), #2 (AES and VDI), #13 (BIOS) and #14 (XBIOS).", "TRAP #vector", "The function number is the word on top of the stack; the caller removes the arguments afterwards with ADDQ.L or LEA n(SP),SP.", "TRAP #2 needs D0 = $C8 for the AES or $73 for the VDI and D1 pointing at the parameter block."),
    CMP: help("Compares two values by setting the condition codes.", "CMP.size source,Dn", "A conditional branch normally follows."),
    TST: help("Sets the condition codes from one operand.", "TST.size operand", "Useful for testing a value a MOVE did not already set flags for."),
    BEQ: help("Branches when the zero flag is set.", "BEQ[.B|.W] label", "The label must be within the displacement range."),
    BNE: help("Branches when the zero flag is clear.", "BNE[.B|.W] label", "The label must be within the displacement range."),
    DBRA: help("Decrements a counter and loops until it passes -1.", "DBRA Dn,label", "The counter is the low word of Dn, so the loop runs count+1 times."),
    BTST: help("Tests one bit and sets the zero flag from it.", "BTST #bit,operand", "Bit numbering starts at zero from the least significant bit."),
    ADD: help("Adds a value and sets the condition codes.", "ADD.size source,destination", "ADDA is used when the destination is an address register."),
    ADDQ: help("Adds a constant from 1 to 8.", "ADDQ.size #value,destination", "ADDQ.L #n,SP is how arguments are removed after a TRAP."),
    SUB: help("Subtracts a value and sets the condition codes.", "SUB.size source,destination", "SUBA is used when the destination is an address register."),
    ANDI: help("Combines an immediate value with a destination using AND.", "ANDI.size #value,destination", "ANDI to SR is privileged."),
    ORI: help("Combines an immediate value with a destination using OR.", "ORI.size #value,destination", "ORI to SR is privileged."),
    CLR: help("Clears an operand to zero and sets the condition codes.", "CLR.size destination", "CLR.W -(SP) pushes a zero word argument."),
    FMOVE: help("Moves a value to, from or between floating-point registers.", "FMOVE.fmt source,FPn", "Needs a 68881 or 68882, or the on-chip unit of a 68040 or 68060.", "A TT or Falcon without the optional coprocessor raises an F-line exception."),
  };

  const INLINE_ASSEMBLER_HELP = {
    "DC.B": help("Places one or more bytes in the output.", 'DC.B value[,value...] or DC.B "text",0', "Follow an odd number of bytes with EVEN before any word-sized data."),
    "DC.W": help("Places one or more 16-bit words in the output.", "DC.W value[,value...]", "The address must be even.", "DC.W $A000 to $A00F invokes a Line-A routine."),
    "DC.L": help("Places one or more 32-bit longs in the output.", "DC.L value[,value...]", "The address must be even."),
    "DS.B": help("Reserves a number of bytes.", "DS.B count", "None."),
    "DS.W": help("Reserves a number of words.", "DS.W count", "The address must be even."),
    "DS.L": help("Reserves a number of longs.", "DS.L count", "The address must be even."),
    EVEN: help("Advances the assembly address to the next even address.", "EVEN", "Required after an odd number of bytes, because a 68000 word access must be even."),
    CNOP: help("Aligns the assembly address to a chosen boundary.", "CNOP offset,alignment", "The alignment is normally 2 or 4."),
    EQU: help("Gives a name to a constant value.", "name EQU value", "The value must be known when the line is assembled."),
    TEXT: help("Starts the code section of a GEMDOS program.", "TEXT", "A .PRG has one text, one data and one BSS segment, in that order."),
    DATA: help("Starts the initialised data section.", "DATA", "Data follows the text segment in the program file."),
    BSS: help("Starts the uninitialised data section, which takes no space in the file.", "BSS", "Only DS directives may appear in it; TOS clears it when the program loads unless fast load is set."),
    SECTION: help("Starts a named section of code, data or BSS.", "SECTION name,TEXT|DATA|BSS", "The linker joins sections of the same kind."),
    INCLUDE: help("Assembles the contents of another source file at this point.", 'INCLUDE "file"', "The file must be reachable through the assembler's include path."),
    INCBIN: help("Includes the bytes of a binary file.", 'INCBIN "file"', "Follow with EVEN when the file has an odd length."),
    XREF: help("Declares a symbol defined in another object file.", "XREF name", "The linker resolves it."),
    XDEF: help("Makes a symbol visible to other object files.", "XDEF name", "The symbol must be defined in this file."),
    OPT: help("Sets assembler options.", "OPT option[,option...]", "The accepted options depend on the assembler."),
    RSRESET: help("Resets the structure offset counter used by RS directives.", "RSRESET", "Devpac and vasm."),
    MACRO: help("Begins a macro definition.", "name MACRO ... ENDM", "Parameters are written \\1, \\2 and so on."),
  };

  //: The documented TOS system variables from $380 to $5FF, with the low
  //: exception vectors TOS installs, so a decoded address can be named.
  const SYSTEM_VARIABLES = Object.freeze([
    [0x008, "bus error vector", "l", "exception vector 2"], [0x00C, "address error vector", "l", "exception vector 3"],
    [0x010, "illegal instruction vector", "l", "exception vector 4"], [0x014, "divide by zero vector", "l", "exception vector 5"],
    [0x020, "privilege violation vector", "l", "exception vector 8"], [0x024, "trace vector", "l", "exception vector 9"],
    [0x028, "Line-A vector", "l", "exception vector 10, the $Axxx opcodes"], [0x02C, "Line-F vector", "l", "exception vector 11, the $Fxxx opcodes"],
    [0x068, "HBL vector", "l", "level 2 autovector, horizontal blank"], [0x070, "VBL vector", "l", "level 4 autovector, vertical blank"],
    [0x078, "MFP vector", "l", "level 6 autovector, the MFP 68901"],
    [0x080, "TRAP #0 vector", "l", ""], [0x084, "TRAP #1 vector", "l", "GEMDOS"], [0x088, "TRAP #2 vector", "l", "AES and VDI"],
    [0x08C, "TRAP #3 vector", "l", ""], [0x090, "TRAP #4 vector", "l", ""], [0x094, "TRAP #5 vector", "l", ""],
    [0x098, "TRAP #6 vector", "l", ""], [0x09C, "TRAP #7 vector", "l", ""], [0x0A0, "TRAP #8 vector", "l", ""],
    [0x0A4, "TRAP #9 vector", "l", ""], [0x0A8, "TRAP #10 vector", "l", ""], [0x0AC, "TRAP #11 vector", "l", ""],
    [0x0B0, "TRAP #12 vector", "l", ""], [0x0B4, "TRAP #13 vector", "l", "BIOS"], [0x0B8, "TRAP #14 vector", "l", "XBIOS"],
    [0x0BC, "TRAP #15 vector", "l", ""],
    [0x100, "MFP interrupt vectors", "l", "vectors 64 to 79 for the MFP 68901"],
    [0x380, "proc_lives", "l", "$12345678 when the processor state below is valid after a crash"],
    [0x384, "proc_dregs", "l", "D0 to D7 saved at the last exception"], [0x3A4, "proc_aregs", "l", "A0 to A7 saved at the last exception"],
    [0x3C4, "proc_enum", "l", "the exception number"], [0x3C8, "proc_usp", "l", "the user stack pointer at the exception"],
    [0x3CC, "proc_stk", "w", "sixteen words from the stack at the exception"],
    [0x400, "etv_timer", "l", "timer event vector, called every system tick"], [0x404, "etv_critic", "l", "critical error handler"],
    [0x408, "etv_term", "l", "process termination vector"], [0x40C, "etv_xtra", "l", "reserved event vectors"],
    [0x420, "memvalid", "l", "$752019F3 when the memory configuration is valid"], [0x424, "memcntlr", "b", "the memory controller configuration byte"],
    [0x42E, "phystop", "l", "the end of ST RAM"], [0x432, "_membot", "l", "the bottom of the TPA"], [0x436, "_memtop", "l", "the top of the TPA"],
    [0x43A, "memval2", "l", "$237698AA when the memory configuration is valid"], [0x440, "seekrate", "w", "the floppy seek rate"],
    [0x442, "_timr_ms", "w", "the system timer period in milliseconds, 20"], [0x444, "_fverify", "w", "non-zero to verify floppy writes"],
    [0x446, "_bootdev", "w", "the device the system booted from"], [0x448, "palmode", "w", "0 for NTSC 60 Hz, non-zero for PAL 50 Hz"],
    [0x44A, "defshiftmd", "b", "the default resolution after a monitor change"], [0x44C, "sshiftmd", "w", "the current shifter mode: 0 low, 1 medium, 2 high"],
    [0x44E, "_v_bas_ad", "l", "the logical screen base address"], [0x452, "vblsem", "w", "the VBL semaphore; 0 disables the VBL handler"],
    [0x454, "nvbls", "w", "the number of entries in the VBL queue"], [0x456, "_vblqueue", "l", "pointer to the VBL queue"],
    [0x45A, "colorptr", "l", "a palette to load at the next VBL, or 0"], [0x45E, "screenpt", "l", "a physical screen base to set at the next VBL, or 0"],
    [0x462, "_vbclock", "l", "the number of VBLs since boot"], [0x466, "_frclock", "l", "the number of VBLs processed"],
    [0x46A, "hdv_init", "l", "hard disk initialisation vector"], [0x46E, "swv_vec", "l", "the monitor change vector"],
    [0x472, "hdv_bpb", "l", "the Getbpb vector"], [0x476, "hdv_rw", "l", "the Rwabs vector"], [0x47A, "hdv_boot", "l", "the boot vector"],
    [0x47E, "hdv_mediach", "l", "the Mediach vector"], [0x482, "_cmdload", "w", "non-zero to load COMMAND.PRG at boot"],
    [0x484, "conterm", "b", "console attributes: bit 0 key click, bit 1 key repeat, bit 2 bell, bit 3 return shift state from Bconin"],
    [0x48E, "themd", "l", "the memory descriptor TOS boots with"], [0x49E, "_md", "l", "space for additional memory descriptors"],
    [0x4A2, "savptr", "l", "pointer to the BIOS register save area"], [0x4A6, "_nflops", "w", "the number of floppy drives, 0 to 2"],
    [0x4A8, "con_state", "l", "the VT52 emulator state vector"], [0x4AC, "save_row", "w", "saved cursor row for the VT52 emulator"],
    [0x4AE, "sav_context", "l", "pointer to the saved processor context"], [0x4B2, "_bufl", "l", "the two GEMDOS buffer list pointers"],
    [0x4BA, "_hz_200", "l", "the 200 Hz system timer count"], [0x4BC, "the_env", "l", "the default environment string"],
    [0x4C2, "_drvbits", "l", "a bit for each drive present, bit 0 for A:"], [0x4C6, "_dskbufp", "l", "pointer to the 1 KiB disk buffer"],
    [0x4CA, "_autopath", "l", "pointer to the AUTO folder path"], [0x4CE, "_vbl_list", "l", "the eight default VBL queue slots"],
    [0x4EE, "_dumpflg", "w", "non-zero when Alt-Help asked for a screen dump"], [0x4F0, "_prtabt", "w", "the printer abort flag"],
    [0x4F2, "_sysbase", "l", "pointer to the OS header, which holds the TOS version and date"], [0x4F6, "_shell_p", "l", "pointer to the shell's own data"],
    [0x4FA, "end_os", "l", "the end of the operating system's RAM"], [0x4FE, "exec_os", "l", "the address of the AES entry point"],
    [0x502, "scr_dump", "l", "the screen dump vector"], [0x506, "prv_lsto", "l", "the printer status vector"], [0x50A, "prv_lst", "l", "the printer output vector"],
    [0x50E, "prv_auxo", "l", "the auxiliary status vector"], [0x512, "prv_aux", "l", "the auxiliary output vector"],
    [0x516, "pun_ptr", "l", "pointer to the AHDI partition table (the PUN_INFO)"], [0x51A, "memval3", "l", "$5555AAAA when TT RAM is valid (TOS 1.02 or later)"],
    [0x51E, "xconstat", "l", "the eight Bconstat vectors"], [0x53E, "xconin", "l", "the eight Bconin vectors"],
    [0x55E, "xcostat", "l", "the eight Bcostat vectors"], [0x57E, "xconout", "l", "the eight Bconout vectors"],
    [0x59E, "_longframe", "w", "non-zero when the processor uses long exception frames (68010 or later)"],
    [0x5A0, "_p_cookies", "l", "pointer to the cookie jar"], [0x5A2, "ramtop", "l", "the end of TT RAM"],
    [0x5A6, "ramvalid", "l", "$1357BD13 when ramtop is valid"], [0x5A8, "bell_hook", "l", "the bell sound vector"],
    [0x5AC, "kcl_hook", "l", "the key click vector"],
  ]);

  //: Hardware registers at $FF8000 and above, reached at $FFFF8xxx when the
  //: assembler sign-extends a short absolute address.
  const HARDWARE_REGISTERS = Object.freeze([
    [0xFF8001, "memory configuration", "MMU bank sizes"],
    [0xFF8201, "video base high", "bits 23-16 of the screen address"], [0xFF8203, "video base mid", "bits 15-8 of the screen address"],
    [0xFF8205, "video address counter high", ""], [0xFF8207, "video address counter mid", ""], [0xFF8209, "video address counter low", ""],
    [0xFF820A, "sync mode", "bit 1 selects 50 Hz, bit 0 external sync"], [0xFF820D, "video base low", "STE: bits 7-1 of the screen address"],
    [0xFF820F, "line offset", "STE: words skipped at the end of each line"], [0xFF8240, "palette register 0", "$RGB"],
    [0xFF8242, "palette register 1", "$RGB"], [0xFF8244, "palette register 2", "$RGB"], [0xFF8246, "palette register 3", "$RGB"],
    [0xFF8248, "palette register 4", "$RGB"], [0xFF824A, "palette register 5", "$RGB"], [0xFF824C, "palette register 6", "$RGB"],
    [0xFF824E, "palette register 7", "$RGB"], [0xFF8250, "palette register 8", "$RGB"], [0xFF8252, "palette register 9", "$RGB"],
    [0xFF8254, "palette register 10", "$RGB"], [0xFF8256, "palette register 11", "$RGB"], [0xFF8258, "palette register 12", "$RGB"],
    [0xFF825A, "palette register 13", "$RGB"], [0xFF825C, "palette register 14", "$RGB"], [0xFF825E, "palette register 15", "$RGB"],
    [0xFF8260, "shifter mode", "0 low, 1 medium, 2 high"], [0xFF8265, "horizontal scroll", "STE: pixel offset 0 to 15"],
    [0xFF8266, "Falcon shift mode", "Falcon VIDEL"], [0xFF82C0, "VIDEL clock", "Falcon"],
    [0xFF8604, "DMA sector count and data", "floppy and ACSI"], [0xFF8606, "DMA status and mode", "floppy and ACSI"],
    [0xFF8609, "DMA base high", ""], [0xFF860B, "DMA base mid", ""], [0xFF860D, "DMA base low", ""],
    [0xFF8800, "PSG register select", "YM2149; reading returns the selected register"], [0xFF8802, "PSG register data", "YM2149 write"],
    [0xFF8900, "DMA sound control", "STE: bit 0 play, bit 1 repeat"], [0xFF8903, "DMA sound frame start high", "STE"],
    [0xFF8905, "DMA sound frame start mid", "STE"], [0xFF8907, "DMA sound frame start low", "STE"],
    [0xFF890F, "DMA sound frame end high", "STE"], [0xFF8911, "DMA sound frame end mid", "STE"], [0xFF8913, "DMA sound frame end low", "STE"],
    [0xFF8921, "DMA sound mode", "STE: bits 0-1 rate, bit 7 mono"], [0xFF8922, "microwire data", "STE: volume and tone"], [0xFF8924, "microwire mask", "STE"],
    [0xFF8A00, "blitter halftone RAM", ""], [0xFF8A20, "blitter source x increment", ""], [0xFF8A22, "blitter source y increment", ""],
    [0xFF8A24, "blitter source address", ""], [0xFF8A28, "blitter endmask 1", ""], [0xFF8A2A, "blitter endmask 2", ""], [0xFF8A2C, "blitter endmask 3", ""],
    [0xFF8A2E, "blitter destination x increment", ""], [0xFF8A30, "blitter destination y increment", ""], [0xFF8A32, "blitter destination address", ""],
    [0xFF8A36, "blitter x count", ""], [0xFF8A38, "blitter y count", ""], [0xFF8A3A, "blitter halftone operation", ""],
    [0xFF8A3B, "blitter logic operation", ""], [0xFF8A3C, "blitter control", "bit 7 busy, bit 6 hog, bit 5 smudge"], [0xFF8A3D, "blitter skew", ""],
    [0xFF9200, "joypad fire buttons", "STE and Falcon enhanced joystick ports"], [0xFF9202, "joypad directions and paddles", "STE and Falcon"],
    [0xFF9800, "Falcon palette", "256 longs of $RRGGBB00"],
    [0xFFFA01, "MFP GPIP", "general purpose I/O: bit 0 Centronics busy, 1 RS-232 DCD, 2 RS-232 CTS, 3 blitter done, 4 ACIA interrupt, 5 DMA done, 6 RS-232 RI, 7 monochrome monitor"],
    [0xFFFA03, "MFP AER", "active edge register"], [0xFFFA05, "MFP DDR", "data direction register"],
    [0xFFFA07, "MFP IERA", "interrupt enable A: timers A and B, RS-232"], [0xFFFA09, "MFP IERB", "interrupt enable B: timers C and D, GPIP"],
    [0xFFFA0B, "MFP IPRA", "interrupt pending A"], [0xFFFA0D, "MFP IPRB", "interrupt pending B"],
    [0xFFFA0F, "MFP ISRA", "interrupt in service A"], [0xFFFA11, "MFP ISRB", "interrupt in service B"],
    [0xFFFA13, "MFP IMRA", "interrupt mask A"], [0xFFFA15, "MFP IMRB", "interrupt mask B"], [0xFFFA17, "MFP VR", "vector register"],
    [0xFFFA19, "MFP TACR", "timer A control"], [0xFFFA1B, "MFP TBCR", "timer B control"], [0xFFFA1D, "MFP TCDCR", "timers C and D control"],
    [0xFFFA1F, "MFP TADR", "timer A data"], [0xFFFA21, "MFP TBDR", "timer B data"], [0xFFFA23, "MFP TCDR", "timer C data, the 200 Hz system timer"],
    [0xFFFA25, "MFP TDDR", "timer D data, the RS-232 baud rate"], [0xFFFA27, "MFP SCR", "sync character"], [0xFFFA29, "MFP UCR", "USART control"],
    [0xFFFA2B, "MFP RSR", "receiver status"], [0xFFFA2D, "MFP TSR", "transmitter status"], [0xFFFA2F, "MFP UDR", "USART data"],
    [0xFFFA81, "TT MFP GPIP", "the second MFP of a TT"],
    [0xFFFC00, "keyboard ACIA control and status", "IKBD"], [0xFFFC02, "keyboard ACIA data", "IKBD"],
    [0xFFFC04, "MIDI ACIA control and status", ""], [0xFFFC06, "MIDI ACIA data", ""],
    [0xFFFC20, "real-time clock", "Mega ST RP5C15 registers"],
  ]);

  const SYSTEM_ADDRESS_HELP = new Map();
  const SYSTEM_ADDRESS_DETAIL = new Map();
  for (const [address, name, size, meaning] of SYSTEM_VARIABLES) {
    SYSTEM_ADDRESS_HELP.set(address, name);
    SYSTEM_ADDRESS_DETAIL.set(address, { name, size, meaning, kind: /vector/.test(name) ? "vector" : "variable" });
  }
  for (const [address, name, meaning] of HARDWARE_REGISTERS) {
    SYSTEM_ADDRESS_HELP.set(address, name);
    SYSTEM_ADDRESS_DETAIL.set(address, { name, size: "", meaning, kind: "register" });
  }
  const SYSTEM_VARIABLE_HELP = Object.fromEntries(SYSTEM_VARIABLES
    .filter(([, name]) => /^[_a-z]/.test(name) && !/\s/.test(name))
    .map(([address, name, size, meaning]) => [name.toUpperCase(), help(
      `TOS system variable at $${address.toString(16).toUpperCase()}: ${meaning || name}.`,
      `${size === "w" ? "MOVE.W" : size === "b" ? "MOVE.B" : "MOVE.L"} $${address.toString(16).toUpperCase()}.W,${size === "w" ? "D0" : size === "b" ? "D0" : "D0"}`,
      "Readable only in supervisor mode on a 68000 TOS, because addresses below $800 are protected; use Super or Supexec.",
    )]));

  // A short absolute address is sign-extended by the processor, so $FFFA01
  // and $FFFFFA01 are the same register. Both spellings are folded to one.
  function canonicalAddress(value) {
    if (!Number.isFinite(value)) return null;
    let address = value >>> 0;
    if (address >= 0xFFFF8000) address &= 0xFFFFFF;
    if (address >= 0xFF8000 && address <= 0xFFFFFF) return address;
    return address;
  }

  function describeAddress(value) {
    const address = canonicalAddress(value);
    if (address == null) return null;
    const detail = SYSTEM_ADDRESS_DETAIL.get(address);
    if (detail) return { address, ...detail };
    // A palette write lands on a register even when the address is odd by
    // one, and the MFP registers sit on odd bytes of word slots.
    if (address >= 0xFF8240 && address <= 0xFF825F) return { address, name: `palette register ${(address - 0xFF8240) >> 1}`, size: "w", meaning: "$RGB", kind: "register" };
    return null;
  }

  const formatAddress = value => `$${canonicalAddress(value).toString(16).toUpperCase()}`;

  // TOS calls by name, for hovering Fopen or v_opnvwk in source or a
  // disassembly comment.
  const SYSTEM_CALL_HELP = (() => {
    const table = {};
    const families = [["GEMDOS", CALL_CATALOGUE?.GEMDOS, 1], ["BIOS", CALL_CATALOGUE?.BIOS, 13], ["XBIOS", CALL_CATALOGUE?.XBIOS, 14]];
    for (const [family, entries, trap] of families) {
      for (const [number, spec] of Object.entries(entries || {})) {
        const value = Number(number);
        const words = (spec.parameters || []).reduce((total, parameter) => total + (parameter.size === "l" ? 4 : 2), 2);
        table[spec.name.toUpperCase()] = help(
          `${family} ${value} (\$${value.toString(16).toUpperCase()}): ${spec.summary}.`,
          `${(spec.parameters || []).map(parameter => `${parameter.size === "l" ? "MOVE.L" : "MOVE.W"} ${parameter.name},-(SP)`).reverse().join(" / ")}${spec.parameters?.length ? " / " : ""}MOVE.W #${value},-(SP) / TRAP #${trap}${words > 2 ? ` / ${words <= 8 ? `ADDQ.L #${words},SP` : `LEA ${words}(SP),SP`}` : " / ADDQ.L #2,SP"}`,
          spec.requires ? `Requires ${spec.requires}.` : `Any TOS; the result is returned in D0.`,
        );
      }
    }
    for (const [number, spec] of Object.entries(CALL_CATALOGUE?.AES || {})) {
      table[spec.name.toUpperCase()] = help(`AES ${number}: ${spec.summary}.`, `control[0]=${number} / MOVE.L #$C8,D0 / LEA aespb,A0 / MOVE.L A0,D1 / TRAP #2`, spec.requires ? `Requires ${spec.requires}.` : "An AES must be running; a TOS program started from the desktop has one.");
    }
    for (const [number, spec] of Object.entries(CALL_CATALOGUE?.VDI || {})) {
      if (spec.subfunctions) {
        for (const [sub, inner] of Object.entries(spec.subfunctions)) {
          table[inner.name.toUpperCase()] = help(`VDI ${number}/${sub}: ${inner.summary}.`, `contrl[0]=${number} / contrl[5]=${sub} / MOVE.L #$73,D0 / LEA vdipb,A0 / MOVE.L A0,D1 / TRAP #2`, "A VDI workstation handle in contrl[6].");
        }
      } else {
        table[spec.name.toUpperCase()] = help(`VDI ${number}: ${spec.summary}.`, `contrl[0]=${number} / MOVE.L #$73,D0 / LEA vdipb,A0 / MOVE.L A0,D1 / TRAP #2`, spec.requires ? `Requires ${spec.requires}.` : "A VDI workstation handle in contrl[6].");
      }
    }
    return table;
  })();

  const normaliseHelpKey = value => String(value || "").trim().replace(/[^A-Za-z0-9$_.#~]/g, "").toUpperCase();
  const COMMAND_CASE = Object.freeze(Object.fromEntries([["basic", "upper"], ["script", "mixed"], ...M68K_TARGETS.map(target => [target, "upper"])]));
  const isAssemblyLanguage = language => M68K_TARGETS.includes(String(language || "").toLowerCase()) || /^680[0-9]0(?:[+-]fpu)?$/i.test(String(language || ""));
  const dictionary = language => language === "basic"
    ? { ...BASIC_HELP }
    : language === "script"
      ? { ...SCRIPT_HELP }
      : { ...INLINE_ASSEMBLER_HELP, ...ASM_HELP, ...SYSTEM_CALL_HELP, ...SYSTEM_VARIABLE_HELP };
  const lookup = (language, key) => {
    const normal = normaliseHelpKey(key);
    const found = dictionary(language)[normal];
    if (found) return { key: normal, ...found };
    if (language === "script" && /^#[A-Z]$/.test(normal)) {
      return { key: normal, ...help("A desktop information record.", `${normal.toLowerCase()} ...`, "DESKTOP.INF or NEWDESK.INF; unknown record letters are ignored by the desktop.") };
    }
    if (language === "script" && /^[A-Z][A-Z0-9_]*$/.test(normal)) {
      return { key: normal, ...help("Configuration directive.", `${normal}=value`, "The kernel or desktop that reads this file must understand it; unknown lines are ignored.") };
    }
    if (language === "basic" && BASIC_KEYWORDS.has(normal)) return { key: normal, ...help("BASIC keyword.", normal, "Syntax and availability depend on the dialect: GFA BASIC, STOS or ST BASIC.") };
    if (isAssemblyLanguage(language)) {
      const base = normal.replace(/\.(?:B|W|L|S|X|D|P)$/, "");
      if (ASSEMBLY_LANGUAGE?.isMnemonic(language, base)) {
        const fpu = ASSEMBLY_LANGUAGE.isFpuMnemonic?.(base);
        return { key: normal, ...help(`${fpu ? "Floating-point coprocessor" : language.toUpperCase().replace("+FPU", " with FPU")} instruction.`, normal, fpu ? "A 68881 or 68882, or a 68040 or later with its own floating-point unit." : "Operands and addressing modes must be valid for the selected processor.") };
      }
      if (ASSEMBLY_LANGUAGE?.isFpuMnemonic?.(base)) {
        return { key: normal, ...help("Floating-point coprocessor instruction.", normal, "A 68881 or 68882 fitted to a TT or Falcon, or a 68040 or later.", "The configured processor has no floating-point unit, so this raises an F-line exception on it.") };
      }
      if (/^[A-Z_][A-Z0-9_.]*$/.test(normal)) {
        return { key: normal, ...help(`${language.toUpperCase()} instruction or assembler pseudo-operation.`, normal, "The decoded operands, processor and execution context determine its exact effect.") };
      }
    }
    return null;
  };

  // Numbers as GFA BASIC, STOS and a 68000 assembler write them: $ or &H
  // for hexadecimal, % or &X for binary, &O for octal, and plain decimal.
  const sourceNumber = value => {
    const match = String(value || "").trim().match(/^(-?)(?:(?:&H|\$|0x)([0-9a-f]+)|(?:&X|%)([01]+)|&O([0-7]+)|&([0-9a-f]+)|(\d+))/i);
    if (!match) return null;
    const number = match[2] != null ? Number.parseInt(match[2], 16)
      : match[3] != null ? Number.parseInt(match[3], 2)
        : match[4] != null ? Number.parseInt(match[4], 8)
          : match[5] != null ? Number.parseInt(match[5], 16)
            : Number.parseInt(match[6], 10);
    return match[1] ? -number : number;
  };

  const NUMBER_PATTERN = /^-?(?:(?:&H|\$|0x)[0-9a-f]+|(?:&X|%)[01]+|&O[0-7]+|&[0-9a-f]+|\d+)/i;

  // The comma-separated arguments of a statement or call, each proved to a
  // number or left null. A GFA L: or W: size prefix is dropped, parentheses
  // are respected and a string stops nothing.
  function argumentValues(text) {
    let source = String(text || "").trim();
    if (source.startsWith("(")) source = source.slice(1);
    const parts = [];
    let depth = 0;
    let quoted = false;
    let current = "";
    for (const character of source) {
      if (character === '"') quoted = !quoted;
      if (!quoted) {
        if (character === "(") depth += 1;
        if (character === ")") { if (depth === 0) break; depth -= 1; }
        if (character === ":" && depth === 0 && !/[LWVB]$/i.test(current.trim())) break;
        if (character === "!" && depth === 0) break;
        if (character === "," && depth === 0) { parts.push(current); current = ""; continue; }
      }
      current += character;
    }
    parts.push(current);
    return parts.map(part => {
      const bare = part.trim().replace(/^[LWVB]:/i, "").trim();
      return NUMBER_PATTERN.test(bare) && /^-?(?:&[HXO]?[0-9a-f]+|\$[0-9a-f]+|0x[0-9a-f]+|%[01]+|\d+)$/i.test(bare) ? sourceNumber(bare) : null;
    });
  }

  function constantNumbers(value) {
    return argumentValues(value).filter(number => number != null);
  }

  // The values a program pushed before a TRAP, read back from the lines that
  // precede it. The nearest push is the function number; the ones before it
  // are its arguments, in stack order.
  function precedingPushes(lines, lineIndex, relativeStart) {
    const pushes = [];
    let d0 = null;
    let reads = 0;
    const consider = statement => {
      const text = statement.replace(/;.*$/, "").trim();
      if (!text) return true;
      if (/^\s*trap\b/i.test(text) && reads > 0) return false;
      let match = text.match(/^(?:move|movea)\.([wl])\s+#\s*([^,]+),\s*-\(\s*(?:sp|a7)\s*\)/i);
      if (match) { pushes.push({ size: match[1].toLowerCase(), value: sourceNumber(match[2]), symbol: match[2].trim() }); return true; }
      match = text.match(/^clr\.([wl])\s+-\(\s*(?:sp|a7)\s*\)/i);
      if (match) { pushes.push({ size: match[1].toLowerCase(), value: 0 }); return true; }
      match = text.match(/^(?:move|movea)\.([wl])\s+([^,#]+),\s*-\(\s*(?:sp|a7)\s*\)/i);
      if (match) { pushes.push({ size: match[1].toLowerCase(), value: sourceNumber(match[2].replace(/\.[wl]$/i, "")) }); return true; }
      match = text.match(/^pea(?:\.l)?\s+(.+)$/i);
      if (match) { pushes.push({ size: "l", value: /^[$&%\d-]/.test(match[1].trim()) && !/\(/.test(match[1]) ? sourceNumber(match[1]) : null }); return true; }
      match = text.match(/^(?:move(?:\.[wl])?|moveq(?:\.l)?)\s+#\s*([^,]+),\s*d0\b/i);
      if (match && d0 == null) { d0 = sourceNumber(match[1]); return true; }
      return true;
    };
    const statementsOf = line => line.replace(/^\s*[A-Za-z_.][A-Za-z0-9_.]*:\s*/, "").split(/(?<!\S)\s*;(?!\S)/)[0].split(/\s*:\s*(?=[a-z])/i);
    const current = lines[lineIndex].slice(0, relativeStart);
    let keepGoing = statementsOf(current).reverse().every(statement => { reads += 1; return consider(statement); });
    for (let index = lineIndex - 1; keepGoing && index >= 0 && index >= lineIndex - 16; index -= 1) {
      keepGoing = statementsOf(lines[index]).reverse().every(statement => { reads += 1; return consider(statement); });
    }
    return { pushes, d0 };
  }

  function configuredPlatform(profile = {}) {
    const identify = value => {
      const text = String(value || "").toLowerCase();
      if (!text) return "";
      if (/falcon/.test(text)) return "falcon030";
      if (/\btt\b|tt030|tt-|tt_/.test(text)) return "tt030";
      if (/mega\s*-?\s*ste|megaste/.test(text)) return "megaste";
      if (/\bste\b|1040ste|520ste|\bste[-_]/.test(text)) return "ste";
      if (/mega\s*-?\s*st\b|megast\b/.test(text)) return "megast";
      if (/\bst\b|stfm|\bstf\b|520st|1040st|^st[-_]/.test(text)) return "st";
      return "";
    };
    return identify(profile.machine) || identify(profile.targetHardware) || identify(profile.name) || "auto";
  }

  // The processor a profile implies: 68000 on every ST and STE, 68030 on the
  // TT and Falcon, with the FPU overlay when the profile says one is fitted.
  function processorFor(profile = {}) {
    const platform = configuredPlatform(profile);
    const explicit = String(profile.processor || "").toLowerCase().replace(/^mc/, "");
    const base = /^680[0-9]0$/.test(explicit) ? explicit : MACHINE_PROCESSORS[platform] || "68000";
    const fpu = Boolean(profile.fpu) || /688[12]/.test(String(profile.fpu || profile.coprocessor || ""));
    return fpu && ["68030", "68020"].includes(base) ? `${base}+fpu` : base;
  }

  function platformHelp(result, profile = {}) {
    const platform = configuredPlatform(profile);
    const targetName = platform === "auto" ? "the automatic target" : PLATFORM_NAMES[platform];
    const documented = result?.platforms || [];
    const requirements = result?.requires ? ` Requirements: ${result.requires}.` : "";
    if (platform === "auto") return `The hardware profile is automatic, so compatibility cannot be confirmed.${requirements}`;
    if (!documented.length) return `The catalogue cannot prove that this machine-specific operation is supported by the configured ${targetName} target.${requirements}`;
    if (!documented.includes(platform)) {
      const designedFor = documented.map(item => PLATFORM_NAMES[item] || item).join(", ");
      return `Target warning: this operation is documented for ${designedFor}, not the configured ${targetName} target. It is outside the target profile and, if accepted at all, may cause unexpected behaviour.${requirements}`;
    }
    return `The configured ${targetName} target is within the documented platform scope.${requirements}`;
  }

  function catalogueText(result, profile) {
    if (!result) return "";
    const detail = (result.details || []).filter(Boolean).join(". ");
    const warnings = (result.warnings || []).filter(Boolean).join(" ");
    return `${result.summary}.${detail ? ` ${detail}.` : ""}${warnings ? ` ${warnings}` : ""} ${platformHelp(result, profile)}`;
  }

  const WORD_POKES = new Set(["DPOKE", "LPOKE", "SDPOKE", "SLPOKE", "DOKE", "LOKE"]);
  const WORD_PEEKS = new Set(["DPEEK", "LPEEK", "DEEK", "LEEK"]);
  const ALL_POKES = new Set(["POKE", "SPOKE", ...WORD_POKES]);
  const ALL_PEEKS = new Set(["PEEK", ...WORD_PEEKS]);

  function addressNote(address, verb) {
    const detail = describeAddress(address);
    if (!detail) return "";
    const what = detail.kind === "register" ? `the ${detail.name} hardware register` : detail.kind === "vector" ? `the ${detail.name}` : `the TOS system variable ${detail.name}`;
    const meaning = detail.meaning ? ` (${detail.meaning})` : "";
    return `Address ${formatAddress(address)} is ${what}${meaning}, so this ${verb} ${detail.kind === "register" ? "goes directly to the hardware" : "touches the operating system's own state"} rather than program memory.`;
  }

  function sourceContextHelp(source, language, start, end, key, targetProfile = {}) {
    const base = lookup(language, key);
    if (!base) return base;
    const lineStart = source.lastIndexOf("\n", Math.max(0, start - 1)) + 1;
    const lineEnd = source.indexOf("\n", end);
    const line = source.slice(lineStart, lineEnd < 0 ? source.length : lineEnd);
    const relativeStart = start - lineStart;
    const relativeEnd = end - lineStart;
    const tail = line.slice(relativeEnd);
    const normal = normaliseHelpKey(key);
    const additions = [];
    const assembly = isAssemblyLanguage(language);
    if (language === "basic" && ["GEMDOS", "BIOS", "XBIOS", "GEMSYS", "VDISYS", "SOUND", "WAVE", "SETCOLOR", "VSYNC"].includes(normal)) {
      const decoded = CALL_CATALOGUE?.explainBasicCall(normal, argumentValues(tail));
      if (decoded) additions.push(catalogueText(decoded, targetProfile));
    }
    if (language === "basic" && normal === "TRAP") {
      const [vector, ...rest] = argumentValues(tail);
      if (vector != null) additions.push(catalogueText(CALL_CATALOGUE?.explainTrapCall(vector, rest[0], rest.slice(1)), targetProfile));
    }
    if (language === "basic" && ALL_POKES.has(normal)) {
      const [address] = argumentValues(tail);
      if (address != null) {
        const note = addressNote(address, "write");
        if (note) additions.push(note);
        if (WORD_POKES.has(normal) && address % 2) {
          additions.push(`Address ${formatAddress(address)} is odd, and a 68000 word or long access must be even; this raises an address error on an ST.`);
        }
        if (address >= 0x400 && address < 0x800 && !/^S/.test(normal) && normal !== "DOKE" && normal !== "LOKE") {
          additions.push("Addresses below $800 are supervisor-only on a 68000 TOS, so a plain POKE here raises a bus error; use SPOKE, SDPOKE or SLPOKE.");
        }
      }
    }
    if (language === "basic" && ALL_PEEKS.has(normal)) {
      const [address] = argumentValues(tail);
      if (address != null) {
        const note = addressNote(address, "read");
        if (note) additions.push(note);
        if (WORD_PEEKS.has(normal) && address % 2) {
          additions.push(`Address ${formatAddress(address)} is odd, and a 68000 word or long access must be even; this raises an address error on an ST.`);
        }
      }
    }
    if (language === "basic" && normal === "XBIOS") {
      const [number] = argumentValues(tail);
      if (number === 5) additions.push("Setscreen with a resolution other than -1 changes the shifter mode for every program until it is changed back.");
    }
    if (language === "script" && /^#[A-Z]$/.test(normal)) {
      const path = tail.match(/([A-Z]:\\[^@\s]*)/i)?.[1];
      if (path) additions.push(`This record refers to ${JSON.stringify(path)}; the desktop skips it at boot when that drive is not present.`);
    }
    if (language === "script" && ["INIT", "GEM", "EXEC"].includes(normal)) {
      const target = tail.replace(/^\s*=?\s*/, "").trim().split(/\s+/)[0];
      if (target) additions.push(`${normal === "GEM" ? "The AES" : "The program"} ${JSON.stringify(target)} must exist at that path when MiNT boots; ${normal === "INIT" ? "it becomes the first process and MiNT ends when it does" : normal === "GEM" ? "MiNT waits for it before the desktop appears" : "MiNT waits for it to finish before reading the next line"}.`);
    }
    if (assembly && normal === "TRAP") {
      const vector = sourceNumber(tail.replace(/^\s*#\s*/, ""));
      if (vector != null) {
        const lines = source.split("\n");
        const lineIndex = source.slice(0, lineStart).split("\n").length - 1;
        const { pushes, d0 } = precedingPushes(lines, lineIndex, relativeStart);
        if (vector === 2) {
          additions.push(catalogueText(CALL_CATALOGUE?.explainGemTrap(d0, null), targetProfile));
        } else if (vector === 1 || vector === 13 || vector === 14) {
          const [number, ...stack] = pushes;
          const values = stack.map(push => push.value);
          // A function number is often written as its name, Cconws or
          // Fopen, through an equate; the catalogue knows those names.
          const named = number?.value == null && number?.symbol ? CALL_CATALOGUE?.lookupName(number.symbol) : null;
          if (named && named.family === CALL_CATALOGUE.TRAPS[vector].name && number) number.value = named.number;
          additions.push(number && number.value != null
            ? `This is a ${CALL_CATALOGUE?.TRAPS[vector].name} call: ${catalogueText(CALL_CATALOGUE?.explainTrapCall(vector, number.value, values), targetProfile)}`
            : `This is a ${CALL_CATALOGUE?.TRAPS[vector].name} call whose function number was not proved: the word pushed last before the TRAP selects the function.`);
        } else {
          additions.push(catalogueText(CALL_CATALOGUE?.explainTrapCall(vector, null, []), targetProfile));
        }
      }
    }
    if (assembly && /^DC\.W$/.test(normal)) {
      const [value] = argumentValues(tail);
      if (value != null && value >= 0xA000 && value <= 0xA00F) additions.push(catalogueText(CALL_CATALOGUE?.explainLineA(value), targetProfile));
    }
    if (assembly && !/^DC\.|^DS\./.test(normal)) {
      const operands = tail.replace(/;.*$/, "");
      const comma = operands.search(/,(?![^(]*\))/);
      const sourceText = comma >= 0 ? operands.slice(0, comma) : operands;
      const destinationText = comma >= 0 ? operands.slice(comma + 1) : "";
      const absolute = text => [...text.matchAll(/(?<![\w#])(?:\$|&H)([0-9a-f]+)(?:\.[wl])?(?![\w(])/gi)].map(match => Number.parseInt(match[1], 16));
      for (const address of absolute(sourceText)) {
        const detail = describeAddress(address);
        if (!detail) continue;
        const what = detail.kind === "register" ? `the ${detail.name} hardware register` : detail.kind === "vector" ? `the ${detail.name}` : `the TOS system variable ${detail.name}`;
        additions.push(`Absolute address ${formatAddress(address)} holds ${what}${detail.meaning ? `, ${detail.meaning}` : ""}.${detail.kind === "variable" || detail.kind === "vector" ? " Reading it needs supervisor mode on a 68000 TOS." : ""}`);
      }
      for (const address of absolute(destinationText)) {
        const detail = describeAddress(address);
        if (!detail) continue;
        const what = detail.kind === "register" ? `the ${detail.name} hardware register` : detail.kind === "vector" ? `the ${detail.name}` : `the TOS system variable ${detail.name}`;
        additions.push(`This writes ${what} at ${formatAddress(address)}${detail.meaning ? ` (${detail.meaning})` : ""}.${detail.kind === "register" ? "" : " Writing it needs supervisor mode on a 68000 TOS."}`);
      }
      if (ASSEMBLY_LANGUAGE?.isFpuMnemonic?.(normal.replace(/\.[A-Z]$/, ""))) {
        const processor = processorFor(targetProfile);
        if (!/\+fpu$|^680[46]0$/.test(processor)) additions.push(`Target warning: this is a floating-point instruction and the configured ${PLATFORM_NAMES[configuredPlatform(targetProfile)] || "target"} profile has no 68881 or 68882, so it raises an F-line exception there.`);
      }
    }
    if (!additions.length) return base;
    return { ...base, notes: [base.notes, ...additions].filter(Boolean).join(" ") };
  }

  function disassemblyInstructionHelp(row, architecture) {
    const mnemonic = normaliseHelpKey(row?.mnemonic || "DATA") || "DATA";
    const operand = String(row?.operand || "").trim();
    const known = lookup(architecture, mnemonic);
    let summary = known?.summary || `${architecture.toUpperCase()} decoded operation.`;
    if (isAssemblyLanguage(architecture) && !ASM_HELP[mnemonic] && !INLINE_ASSEMBLER_HELP[mnemonic]) {
      const base = mnemonic.replace(/\.(?:B|W|L|S)$/, "");
      if (/^MOVE/.test(base)) summary = "Moves the decoded source value to the destination register or memory location.";
      else if (/^LEA$/.test(base)) summary = "Loads the effective address of the operand into an address register.";
      else if (/^PEA$/.test(base)) summary = "Pushes the effective address of the operand onto the stack.";
      else if (/^(ADD|SUB|MUL|DIV|NEG|CMP|EXT|CLR|TST)/.test(base)) summary = "Performs an arithmetic, comparison or size operation using the decoded size and operands.";
      else if (/^(AND|OR|EOR|NOT|BTST|BSET|BCLR|BCHG)/.test(base)) summary = "Performs a logical or bit operation on the decoded destination.";
      else if (/^(AS|LS|RO|ROX|SWAP)/.test(base)) summary = "Shifts, rotates or exchanges halves of the decoded operand.";
      else if (/^(B|DB|S)(?:RA|SR|CC|CS|EQ|F|GE|GT|HI|LE|LS|LT|MI|NE|PL|T|VC|VS)/.test(base)) summary = "Applies the encoded condition to branch, loop or set a result byte.";
      else if (/^(JMP|JSR|RTS|RTE|RTR|LINK|UNLK|MOVEM)$/.test(base)) summary = "Changes control flow, or saves and restores a subroutine's registers and stack frame.";
      else if (/^(TRAP|TRAPV|CHK|STOP|RESET|NOP|ILLEGAL)$/.test(base)) summary = "Invokes a processor exception, or a control operation that is often privileged.";
      else if (/^F/.test(base)) summary = "A floating-point coprocessor operation.";
    }
    let addressing = "No explicit operand; the operation uses implied processor state.";
    if (operand) {
      const trap = mnemonic === "TRAP" ? sourceNumber(operand.replace(/^#/, "")) : null;
      const absolute = operand.match(/(?<![\w#])\$([0-9a-f]+)(?:\.[wl])?/i);
      const named = absolute ? describeAddress(Number.parseInt(absolute[1], 16)) : null;
      if (trap != null && CALL_CATALOGUE?.TRAPS[trap]) addressing = `TRAP #${trap} enters ${CALL_CATALOGUE.TRAPS[trap].name}; the function number is the word on top of the stack.`;
      else if (trap === 2) addressing = "TRAP #2 enters GEM: D0 selects the AES ($C8) or the VDI ($73) and D1 points at the parameter block.";
      else if (operand.startsWith("#")) addressing = `Immediate operand ${operand}.`;
      else if (/\(a\d\)\+/i.test(operand)) addressing = `Post-increment through ${operand}.`;
      else if (/-\((?:a\d|sp)\)/i.test(operand)) addressing = `Pre-decrement through ${operand}${/-\((?:a7|sp)\)/i.test(operand) ? ", a push onto the stack" : ""}.`;
      else if (/\([^)]*pc[^)]*\)/i.test(operand)) addressing = `Program-counter relative operand ${operand}, so the code is position independent.`;
      else if (named) addressing = `Absolute operand ${operand} is ${named.kind === "register" ? `the ${named.name} hardware register` : named.name}${named.meaning ? ` (${named.meaning})` : ""}.`;
      else if (/\([^)]*a\d[^)]*\)/i.test(operand)) addressing = `Address-register operand ${operand}.`;
      else addressing = `Decoded operand: ${operand}.`;
    }
    const context = [addressing];
    if (row?.comment) context.push(`Analysis: ${row.comment}.`);
    if (Array.isArray(row?.references) && row.references.length) context.push(`Referenced from ${row.references.map(value => `$${Number(value).toString(16).toUpperCase()}`).join(", ")}.`);
    if (row?.bytes) context.push(`Encoding: ${row.bytes}.`);
    return {
      key: mnemonic,
      summary,
      syntax: `${mnemonic}${operand ? ` ${operand}` : ""}`,
      requirements: known?.requirements || `Valid ${architecture.toUpperCase()} code for the selected processor.`,
      notes: [known?.notes, ...context].filter(Boolean).join(" "),
    };
  }

  const token = (type, text, start, helpKey = "", helpLanguage = "") => ({ type, text, start, end: start + text.length, helpKey, helpLanguage });

  // Help keys deliberately discard punctuation, but a BASIC trailing `%`,
  // `$`, `&`, `!` or `#` is semantic: it types the variable. Keep lexical
  // classification separate so names such as page%, load% and print% cannot
  // be mistaken for commands during highlighting or refactoring.
  const isBasicKeywordToken = (raw, key) => BASIC_LANGUAGE?.isKeywordToken(raw) ?? (!/[%$&!#|]$/.test(raw) && BASIC_KEYWORDS.has(key));

  function assemblerMnemonic(raw, architecture) {
    const key = normaliseHelpKey(raw);
    const base = key.replace(/\.(?:B|W|L|S|X|D|P)$/, "");
    if (ASSEMBLY_LANGUAGE?.isMnemonic(architecture, base) || ASSEMBLY_LANGUAGE?.isFpuMnemonic?.(base)) return key;
    return "";
  }

  // Built-in functions a BASIC scanner may or may not list as keywords; none
  // of them is an array, however it is tokenised.
  const BASIC_BUILTIN_FUNCTIONS = new Set((
    "TAB SPC AT PEEK DPEEK LPEEK DEEK LEEK CHR$ STR$ LEFT$ RIGHT$ MID$ INSTR ASC VAL LEN ABS INT SQR SIN COS TAN ATN LOG EXP RND RANDOM "
    + "MAX MIN HEX$ BIN$ OCT$ SPACE$ STRING$ UPPER$ LOWER$ TRIM$ LTRIM$ RTRIM$ POINT XBIOS BIOS GEMDOS INP OUT FRE MALLOC VARPTR ARRPTR ADDR "
    + "TIMER KEYTEST FIX FRAC SGN TRUNC ROUND CINT CVI CVL CVS CVD MKI$ MKL$ MKS$ MKD$ INKEY$ INPUT$ LOF LOC EOF DIR$ MOUSEX MOUSEY MOUSEK "
    + "PRED SUCC EVEN ODD SHL SHR ROL ROR BYTE CARD WORD SWAP XOR IMP EQV MOD DIV AND OR NOT TRUE FALSE PI CRSCOL CRSLIN POS CSRLIN "
    + "ERR ERR$ ERL DATE$ TIME$ START LENGTH PHYSIC LOGIC BACK SCREEN HSCROLL JOY FKEY ZONE SCANCODE ASC$ DEC$ DEG RAD BIT COLOUR COLOR "
    + "FN EXIST DFREE STICK STRIG VSETCOLOR SETCOLOR OPENW ARRAYFILL DIM? TYPE WINDTAB W_HAND V~H GB GCONTRL GINTIN GINTOUT ADDRIN ADDROUT CONTRL INTIN PTSIN INTOUT PTSOUT"
  ).split(/\s+/));

  function sourceTokens(text, language, inlineAssemblyLanguage = "68000") {
    const tokens = [];
    let lineStart = 0;
    const assembly = isAssemblyLanguage(language);
    for (const line of String(text).split("\n")) {
      let offset = 0;
      const indent = line.match(/^\s*/)?.[0].length || 0;
      if (assembly) {
        // A label starts the line; a comment starts with ; or a * in the
        // first column; everything else is a mnemonic, a directive, an
        // absolute address or a system call name.
        if (/^\s*[;*]/.test(line)) { tokens.push(token("comment", line.slice(indent), lineStart + indent)); lineStart += line.length + 1; continue; }
        let statementStart = true;
        while (offset < line.length) {
          const character = line[offset];
          if (character === ";") { tokens.push(token("comment", line.slice(offset), lineStart + offset)); break; }
          if (character === '"' || character === "'") {
            let end = offset + 1;
            while (end < line.length && line[end] !== character) end += 1;
            tokens.push(token("string", line.slice(offset, end + 1), lineStart + offset));
            offset = end + 1;
            continue;
          }
          const word = line.slice(offset).match(/^(?:[A-Za-z_.][A-Za-z0-9_.]*|\$[0-9A-Fa-f]+|%[01]+|\d+)/);
          if (!word) { offset += 1; continue; }
          const raw = word[0];
          const key = normaliseHelpKey(raw);
          if (/^\$/.test(raw)) {
            const named = describeAddress(Number.parseInt(raw.slice(1), 16));
            tokens.push(named ? token("api", raw, lineStart + offset, named.name.toUpperCase().replace(/\s+/g, "_"), language) : token("number", raw, lineStart + offset));
          } else if (/^[%\d]/.test(raw)) tokens.push(token("number", raw, lineStart + offset));
          else if (offset === 0 && !/^\s/.test(line[0] || "") && !assemblerMnemonic(raw, language) && !INLINE_ASSEMBLER_HELP[key]) {
            tokens.push(token("symbol", raw, lineStart + offset));
          } else if (assemblerMnemonic(raw, language)) { tokens.push(token("keyword", raw, lineStart + offset, assemblerMnemonic(raw, language), language)); statementStart = false; }
          else if (INLINE_ASSEMBLER_HELP[key]) { tokens.push(token("keyword", raw, lineStart + offset, key, language)); statementStart = false; }
          else if (SYSTEM_CALL_HELP[key] || SYSTEM_VARIABLE_HELP[key]) tokens.push(token("api", raw, lineStart + offset, key, language));
          else if (statementStart && /^[A-Za-z]/.test(raw) && offset > 0) { tokens.push(token("keyword", raw, lineStart + offset, key, language)); statementStart = false; }
          offset += raw.length;
        }
        lineStart += line.length + 1;
        continue;
      }
      if (language === "script") {
        // A desktop record is # and one letter; a MINT.CNF directive is the
        // first word, with or without an = after it; # followed by anything
        // else is a comment.
        const record = line.match(/^\s*(#[A-Za-z])(?=\s|$)/);
        if (record) {
          tokens.push(token("keyword", record[1], lineStart + line.indexOf(record[1]), record[1].toUpperCase()));
          const path = line.match(/[A-Za-z]:\\[^@\s]*/);
          if (path) tokens.push(token("string", path[0], lineStart + path.index));
        } else if (/^\s*#/.test(line)) {
          tokens.push(token("comment", line.slice(indent), lineStart + indent));
        } else {
          const directive = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)/);
          if (directive) tokens.push(token("keyword", directive[1], lineStart + indent, normaliseHelpKey(directive[1])));
          for (const match of line.matchAll(/"[^"]*"/g)) tokens.push(token("string", match[0], lineStart + match.index));
          for (const match of line.matchAll(/(?<![\w.])\d+(?![\w.])/g)) tokens.push(token("number", match[0], lineStart + match.index));
        }
        lineStart += line.length + 1;
        continue;
      }
      const number = language === "basic" ? line.match(/^\s*(\d+)\s/) : null;
      if (number) { tokens.push(token("line-number", number[1], lineStart + number.index + number[0].lastIndexOf(number[1]))); offset = number[0].length; }
      while (offset < line.length) {
        const character = line[offset];
        if (character === '"') {
          let end = offset + 1;
          while (end < line.length) {
            if (line[end] === '"') { end += 1; break; }
            end += 1;
          }
          tokens.push(token("string", line.slice(offset, end), lineStart + offset));
          offset = end;
          continue;
        }
        if (language === "basic" && (character === "'" || (character === "!" && /\s/.test(line[offset - 1] || " ")))) {
          tokens.push(token("comment", line.slice(offset), lineStart + offset));
          break;
        }
        if (language === "basic" && character === "@") {
          const name = line.slice(offset + 1).match(/^[A-Za-z_][A-Za-z0-9_.]*/);
          if (name) { tokens.push(token("symbol", `@${name[0]}`, lineStart + offset, "PROCEDURE")); offset += name[0].length + 1; continue; }
        }
        if (language === "basic" && character === "~" && /^\s*[A-Za-z]/.test(line.slice(offset + 1))) {
          tokens.push(token("keyword", "~", lineStart + offset, "~"));
          offset += 1;
          continue;
        }
        const remainder = line.slice(offset);
        const basicLexeme = language === "basic" && /^[A-Za-z]/.test(remainder) ? BASIC_LANGUAGE?.lexemeAt(remainder) : "";
        const word = basicLexeme ? [basicLexeme] : remainder.match(/^(?:[A-Za-z_][A-Za-z0-9_$%&!#|.]*|&[HXO]?[0-9A-Fa-f]+|\$[0-9A-Fa-f]+|\d+(?:\.\d+)?)/);
        if (!word) { offset += 1; continue; }
        const raw = word[0];
        const key = normaliseHelpKey(raw);
        if (language === "basic" && key === "REM" && isBasicKeywordToken(raw, key)) {
          tokens.push(token("comment", line.slice(offset), lineStart + offset, "REM"));
          break;
        }
        const isNumber = /^\d|^&|^\$/.test(raw);
        // The scanner decides what a keyword is; the help table is the
        // fallback for a dialect word it does not list, so GFA and STOS
        // commands highlight whichever scanner build is loaded.
        const isKeyword = language === "basic" && (isBasicKeywordToken(raw, key) || (Boolean(BASIC_HELP[key]) && !/[$%&!#|]$/.test(raw)));
        if (isNumber) tokens.push(token("number", raw, lineStart + offset));
        else if (isKeyword) {
          tokens.push(token("keyword", raw, lineStart + offset, key));
          // INPUT # and PRINT # have their own help entries.
          if (["INPUT", "PRINT"].includes(key) && /^\s*#/.test(line.slice(offset + raw.length))) tokens.at(-1).helpKey = `${key}#`;
        } else if (/^(?:FN)[A-Za-z]/i.test(raw)) tokens.push(token("symbol", raw, lineStart + offset, "FN"));
        else if (language === "basic" && /^[A-Za-z_][A-Za-z0-9_]*$/.test(raw) && /^:/.test(line.slice(offset + raw.length)) && offset === indent) {
          tokens.push(token("symbol", raw, lineStart + offset, "GOTO"));
        }
        offset += raw.length;
      }
      lineStart += line.length + 1;
    }
    return tokens.sort((left, right) => left.start - right.start || right.end - left.end);
  }

  function highlightedHtml(text, tokens) {
    let cursor = 0;
    const output = [];
    for (const item of tokens) {
      if (item.start < cursor) continue;
      output.push(esc(text.slice(cursor, item.start)));
      const helpAttributes = item.helpKey ? ` data-help-key="${esc(item.helpKey)}"${item.helpLanguage ? ` data-help-language="${esc(item.helpLanguage)}"` : ""} data-token-start="${item.start}" data-token-end="${item.end}"` : "";
      output.push(`<span class="code-token code-token-${item.type}${item.helpKey ? " code-help-token" : ""}"${helpAttributes}>${esc(item.text)}</span>`);
      cursor = item.end;
    }
    output.push(esc(text.slice(cursor)));
    return `${output.join("")}${text.endsWith("\n") ? "\n" : ""}`;
  }

  function highlightedSourceLines(lines, language, inlineAssemblyLanguage) {
    const source = lines.join("\n");
    const tokens = sourceTokens(source, language, inlineAssemblyLanguage);
    let offset = 0;
    return lines.map(line => {
      const end = offset + line.length;
      const local = tokens.filter(item => item.start >= offset && item.end <= end).map(item => ({
        ...item, start: item.start - offset, end: item.end - offset,
      }));
      const markup = highlightedHtml(line, local);
      offset = end + 1;
      return markup;
    });
  }

  // GFA BASIC source has no line numbers; STOS and ST BASIC listings do. The
  // dialect decides when it is known, and the listing itself otherwise.
  function usesLineNumbers(text, dialect) {
    const exact = BASIC_LANGUAGE?.DIALECTS?.[dialect];
    if (exact && typeof exact.lineNumbers === "boolean") return exact.lineNumbers;
    const name = `${dialect || ""} ${exact?.id || ""}`.toLowerCase();
    if (/gfa/.test(name)) return false;
    if (/stos|st[ -]?basic|stbasic/.test(name)) return true;
    const first = String(text).split("\n").find(line => line.trim());
    return Boolean(first && /^\s*\d+\s/.test(first));
  }

  // GFA BASIC has no inline assembler; machine code arrives through INLINE
  // and is called with C: or CALL. Nothing in a BASIC listing is assembler.
  function basicInlineAssemblerLines(text) {
    return String(text).split("\n").map(() => false);
  }

  function blockIssues(rows, lineOffsets) {
    const issues = [];
    const stack = [];
    const closers = { procedure: "RETURN", function: "ENDFUNC", for: "NEXT", while: "WEND", repeat: "UNTIL", do: "LOOP", if: "ENDIF", select: "ENDSELECT" };
    rows.forEach((row, lineIndex) => row.events.forEach(event => {
      if (event.kind === "open") { stack.push({ ...event, lineIndex }); return; }
      if (event.kind !== "close") return;
      const stackIndex = stack.findLastIndex(item => item.type === event.type);
      if (stackIndex < 0) {
        // A bare RETURN outside any PROCEDURE is a GOSUB return in a
        // numbered dialect, so only the structural closers are reported.
        if (event.type !== "procedure") issues.push({ severity: "warning", line: lineIndex + 1, offset: lineOffsets[lineIndex], message: `${closers[event.type]} has no open ${event.type === "if" ? "IF" : event.type === "select" ? "SELECT" : event.type.toUpperCase()} block to close.` });
        return;
      }
      const unclosed = stack.splice(stackIndex + 1);
      unclosed.forEach(item => issues.push({ severity: "warning", line: item.lineIndex + 1, offset: lineOffsets[item.lineIndex], message: `${item.label} on line ${item.lineIndex + 1} has no ${closers[item.type]} before the enclosing block closes.` }));
      stack.pop();
    }));
    stack.forEach(item => issues.push({ severity: "warning", line: item.lineIndex + 1, offset: lineOffsets[item.lineIndex], message: `${item.label} on line ${item.lineIndex + 1} has no ${closers[item.type]}.` }));
    return issues;
  }

  function diagnostics(text, language, dialect = "GFA BASIC 3") {
    const issues = [];
    const add = (severity, line, message, offset = 0) => issues.push({ severity, line, message, offset });
    const lines = String(text).split("\n");
    const lineOffsets = [];
    lines.reduce((offset, line) => { lineOffsets.push(offset); return offset + line.length + 1; }, 0);
    lines.forEach((line, index) => {
      if (language === "script") {
        if (/^\s*#[A-Za-z]\s/.test(line) && !/@\s*$/.test(line) && /^\s*#[DFGIMNPTWYZ]/.test(line)) add("warning", index + 1, "A desktop record normally ends with @; the desktop may read the next line as part of this one.", lineOffsets[index]);
        if (/^\s*GEM\s*=/i.test(line) && lines.some(other => /^\s*INIT\s*=/i.test(other))) add("warning", index + 1, "Both GEM= and INIT= are set; MiNT starts only one of them.", lineOffsets[index]);
        if (/^\s*(?:INIT|GEM|EXEC)\b/i.test(line) && /[A-Za-z]:\/[^\s]*/.test(line)) add("warning", index + 1, "GEMDOS paths use a backslash; a forward slash here is read as part of the name by TOS.", lineOffsets[index]);
        return;
      }
      const code = language === "basic" ? line.replace(/'.*$/, "").replace(/\s!.*$/, "") : line;
      const quotes = (code.match(/"/g) || []).length;
      if (quotes % 2) add("error", index + 1, "String quotation mark is not closed.", lineOffsets[index] + line.indexOf('"'));
    });
    if (language !== "basic") return issues;
    const numbered = [];
    const lineSet = new Set();
    const lineNumbers = usesLineNumbers(text, dialect);
    if (lineNumbers) {
      lines.forEach((line, index) => {
        if (!line.trim()) return;
        const match = line.match(/^\s*(\d+)\s/);
        if (!match) return add("error", index + 1, `${dialect} source lines require a line number followed by a space.`, lineOffsets[index]);
        const value = Number(match[1]);
        if (lineSet.has(value)) add("error", index + 1, `Line number ${value} is duplicated.`, lineOffsets[index]);
        lineSet.add(value);
        if (numbered.length && value <= numbered.at(-1).value) add("error", index + 1, `Line ${value} is not greater than the preceding line number.`, lineOffsets[index]);
        numbered.push({ value, index: index + 1, text: line, offset: lineOffsets[index] });
      });
      numbered.forEach(row => {
        for (const match of row.text.matchAll(/\b(?:GOTO|GOSUB|RESTORE)\s+(\d+)/gi)) {
          if (!lineSet.has(Number(match[1]))) add("error", row.index, `Referenced line ${match[1]} does not exist.`, row.offset + match.index);
        }
      });
    }
    const masked = sourceMask(text, language);
    // A GFA procedure is defined once with PROCEDURE and called with @name or
    // GOSUB name; a function is defined with FUNCTION or DEFFN and called with
    // @name(...) or FN name(...).
    const procedures = new Set([...masked.matchAll(/^\s*PROCEDURE\s+([A-Za-z_][A-Za-z0-9_.]*)/gim)].map(match => match[1].toUpperCase()));
    const functions = new Set([...masked.matchAll(/^\s*(?:FUNCTION|DEFFN)\s+([A-Za-z_][A-Za-z0-9_.]*)/gim)].map(match => match[1].toUpperCase()));
    const labels = new Set([...masked.matchAll(/^\s*([A-Za-z_][A-Za-z0-9_]*):\s*$/gm)].map(match => match[1].toUpperCase()));
    const lineOf = index => text.slice(0, index).split("\n").length;
    for (const match of masked.matchAll(/(?<![A-Za-z0-9_$%])@([A-Za-z_][A-Za-z0-9_.]*)/g)) {
      const name = match[1].toUpperCase();
      if (!procedures.has(name) && !functions.has(name)) add("warning", lineOf(match.index), `Procedure ${match[1]} has no PROCEDURE or FUNCTION definition in this file.`, match.index);
    }
    for (const match of masked.matchAll(/\bGOSUB\s+([A-Za-z_][A-Za-z0-9_.]*)/gi)) {
      const name = match[1].toUpperCase();
      if (!procedures.has(name) && !labels.has(name) && !(lineNumbers && /^\d/.test(name))) add("warning", lineOf(match.index), `Procedure ${match[1]} has no PROCEDURE definition in this file.`, match.index);
    }
    for (const match of masked.matchAll(/\bFN\s+([A-Za-z_][A-Za-z0-9_.]*)/gi)) {
      if (!functions.has(match[1].toUpperCase())) add("warning", lineOf(match.index), `Function ${match[1]} has no DEFFN or FUNCTION definition in this file.`, match.index);
    }
    if (!lineNumbers) {
      for (const match of masked.matchAll(/\bGOTO\s+([A-Za-z_][A-Za-z0-9_]*)/gi)) {
        if (!labels.has(match[1].toUpperCase())) add("error", lineOf(match.index), `Label ${match[1]} does not exist in this file.`, match.index);
      }
    }
    for (const match of masked.matchAll(/^\s*(?:PROCEDURE|FUNCTION|DEFFN)\s+([A-Za-z_][A-Za-z0-9_.]*)/gim)) {
      const name = match[1];
      const calls = [...masked.matchAll(new RegExp(`(?<![A-Za-z0-9_.])${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?![A-Za-z0-9_.])`, "gi"))].filter(call => call.index < match.index || call.index > match.index + match[0].length);
      if (!calls.length) add("info", lineOf(match.index), `${name} is defined but not called in this file.`, match.index);
    }
    issues.push(...blockIssues(basicStructureRows(text), lineOffsets));
    if (lineNumbers) {
      numbered.forEach((row, index) => {
        if (!/\b(?:END|STOP|GOTO\s*\d+)\s*$/i.test(row.text)) return;
        const next = numbered[index + 1];
        if (next && ![...masked.matchAll(/\b(?:GOTO|GOSUB|RESTORE|THEN)\s*(\d+)/gi)].some(match => Number(match[1]) === next.value)) {
          add("info", next.index, `Line ${next.value} may be unreachable after an unconditional transfer.`, next.offset);
        }
      });
    }
    if (BASIC_LANGUAGE) {
      issues.push(...advancedBasicDiagnostics(text));
      const exact = BASIC_LANGUAGE.DIALECTS?.[dialect];
      if (exact && BASIC_LANGUAGE.KEYWORD_GENERATION) {
        BASIC_LANGUAGE.scan(text).filter(item => item.type === "keyword").forEach(item => {
          const required = Number(BASIC_LANGUAGE.KEYWORD_GENERATION[item.name] || 0);
          if (required && required > Number(exact.generation || 0)) issues.push({
            severity: "warning", line: item.line, offset: item.start,
            message: `${item.name} needs a later release than ${dialect}.`,
          });
        });
      }
    }
    return issues;
  }

  function advancedBasicDiagnostics(text) {
    const issues = [];
    const scannedTokens = BASIC_LANGUAGE.scan(text);
    const masked = BASIC_LANGUAGE.maskStringsAndComments(text);
    const dimmed = new Set();
    const forStack = [];
    const lineOffsets = [];
    text.split("\n").reduce((offset, line) => { lineOffsets.push(offset); return offset + line.length + 1; }, 0);
    text.split("\n").forEach((line, index) => {
      const lineOffset = lineOffsets[index];
      const code = masked.slice(lineOffset, lineOffset + line.length).replace(/^\s*\d+\s*/, "").replace(/'.*$/, "").replace(/\s!.*$/, "");
      const lineEnd = lineOffset + line.length;
      const lineTokens = scannedTokens.filter(item => item.start >= lineOffset && item.start < lineEnd);
      for (const [tokenIndex, item] of lineTokens.entries()) {
        if (item.type !== "identifier" || !/^\s*\(/.test(masked.slice(item.end, lineEnd))) continue;
        const name = item.text.toUpperCase();
        const previous = lineTokens[tokenIndex - 1];
        const before = text.slice(Math.max(0, item.start - 1), item.start);
        const previousName = String(previous?.name || previous?.text || "").toUpperCase();
        const followsDim = /^(?:DIM|ERASE|LOCAL|ARRAYFILL|PROCEDURE|FUNCTION|DEFFN|SWAP|INSERT|DELETE|QSORT|SSORT|DSORT)$/.test(previousName);
        // FN name(...) and @name(...) call functions, built-ins such as
        // TAB(...) are not arrays whichever way the scanner types them, and
        // anything named in a DIM, LOCAL or parameter list is declared.
        if (followsDim) { dimmed.add(name); continue; }
        if (before === "@" || /^FN.+/i.test(item.text) || BASIC_BUILTIN_FUNCTIONS.has(name) || BASIC_BUILTIN_FUNCTIONS.has(name.replace(/[$%&!#|]$/, ""))) continue;
        if (previousName === "FN") continue;
        if (!dimmed.has(name)) {
          issues.push({ severity: "warning", line: index + 1, offset: item.start, message: `${item.text} is used as an array before a preceding DIM was found.` });
        }
      }
      for (const match of code.matchAll(/\bFOR\s*([A-Za-z_][A-Za-z0-9_.]*[$%&!#|]?)/gi)) forStack.push({ name: match[1].toUpperCase(), line: index + 1 });
      for (const match of code.matchAll(/\bNEXT\s+([A-Za-z_][A-Za-z0-9_.]*[$%&!#|]?)/gi)) {
        const active = forStack.pop();
        if (active && active.name !== match[1].toUpperCase()) issues.push({ severity: "warning", line: index + 1, offset: lineOffset + match.index, message: `NEXT ${match[1]} closes the active FOR ${active.name} from line ${active.line}.` });
      }
    });
    // a, a% and a$ are deliberately distinct variables in every ST dialect,
    // so sharing a base name across types is not itself suspicious. Likewise,
    // do not report apparently unused assignments: a variable can be read by
    // a PROCEDURE, by a CHAINed program, or by machine code reached through
    // CALL, so the absence of a later textual read is not evidence of a defect.
    return issues.slice(0, 500);
  }

  function symbols(text, language) {
    const rows = [];
    if (language === "basic") {
      for (const match of text.matchAll(/^\s*(\d+)\s/gm)) rows.push({ name: `Line ${match[1]}`, kind: "line", offset: match.index });
      for (const match of text.matchAll(/^\s*(PROCEDURE|FUNCTION|DEFFN)\s+([A-Za-z_][A-Za-z0-9_.]*)/gim)) rows.push({ name: `${match[1].toUpperCase()} ${match[2]}`, kind: "definition", offset: match.index });
      for (const match of text.matchAll(/^\s*([A-Za-z_][A-Za-z0-9_]*):\s*$/gm)) rows.push({ name: `${match[1]}:`, kind: "label", offset: match.index });
    } else if (language === "script") {
      for (const match of text.matchAll(/^\s*(#[GPYZFD])\s+(?:[0-9A-F]+\s+)*([^@\s]+)@/gim)) rows.push({ name: `${match[1].toUpperCase()} ${match[2].trim()}`, kind: "record", offset: match.index });
      for (const match of text.matchAll(/^\s*(INIT|GEM|EXEC|SETENV|ALIAS|INCLUDE|CD)\s*=?\s*([^\r\n]+)/gim)) rows.push({ name: `${match[1].toUpperCase()} ${match[2].trim()}`, kind: "directive", offset: match.index });
    } else if (isAssemblyLanguage(language)) {
      for (const match of text.matchAll(/^([A-Za-z_.][A-Za-z0-9_.]*):?(?=\s|$)/gm)) rows.push({ name: match[1], kind: "label", offset: match.index });
    }
    return rows.slice(0, 500);
  }

  function identifierAt(text, offset, language) {
    const allowed = language === "basic" ? /[A-Za-z0-9_$%&!#|.@]/ : /[A-Za-z0-9_.$]/;
    let start = Math.max(0, Math.min(offset, text.length));
    let end = start;
    while (start > 0 && allowed.test(text[start - 1])) start -= 1;
    while (end < text.length && allowed.test(text[end])) end += 1;
    const name = text.slice(start, end);
    return /^@?[A-Za-z_.][A-Za-z0-9_.$%&!#|]*$/.test(name) ? { name, start, end } : null;
  }

  function sourceMask(text, language) {
    if (language === "basic" && BASIC_LANGUAGE) {
      const masked = BASIC_LANGUAGE.maskStringsAndComments(text);
      // GFA BASIC also comments with ' at a statement start and ! after one.
      return masked.split("\n").map(line => {
        const apostrophe = line.search(/(?:^|:)\s*'/);
        let cut = apostrophe >= 0 ? line.indexOf("'", apostrophe) : -1;
        const bang = line.search(/\s!/);
        if (bang >= 0 && (cut < 0 || bang < cut)) cut = bang;
        return cut >= 0 ? `${line.slice(0, cut)}${" ".repeat(line.length - cut)}` : line;
      }).join("\n");
    }
    const mask = [...text].map(character => character === "\n" ? "\n" : character);
    let quoted = false;
    for (let index = 0; index < text.length; index += 1) {
      if (text[index] === "\n") { quoted = false; continue; }
      if (text[index] === '"') { mask[index] = " "; quoted = !quoted; continue; }
      if (quoted) { mask[index] = " "; continue; }
      const rest = text.slice(index);
      if ((language === "basic" && /^REM(?![$%])/i.test(rest)) ||
          (language === "script" && /^#(?![A-Za-z](?:\s|$))/.test(rest)) ||
          (isAssemblyLanguage(language) && (/^;/.test(rest) || (/^\*/.test(rest) && (index === 0 || text[index - 1] === "\n"))))) {
        while (index < text.length && text[index] !== "\n") { mask[index] = " "; index += 1; }
        index -= 1;
      }
    }
    return mask.join("");
  }

  function symbolReferences(text, offset, language) {
    const selected = identifierAt(text, offset, language);
    if (!selected) return { name: "", rows: [] };
    const masked = sourceMask(text, language);
    const bare = selected.name.replace(/^@/, "");
    const escaped = bare.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const pattern = new RegExp(`(?<![A-Za-z0-9_.$%&!#|])${escaped}(?![A-Za-z0-9_.$%&!#|])`, "giu");
    const rows = [...masked.matchAll(pattern)].map(match => ({
      offset: match.index,
      line: text.slice(0, match.index).split("\n").length,
      context: text.slice(text.lastIndexOf("\n", match.index - 1) + 1, text.indexOf("\n", match.index) < 0 ? text.length : text.indexOf("\n", match.index)).trim(),
    }));
    return { name: bare, rows };
  }

  // The block structure of a listing, as GFA BASIC, STOS and ST BASIC write
  // it: PROCEDURE ... RETURN, FUNCTION ... ENDFUNC, FOR ... NEXT, WHILE ...
  // WEND, REPEAT ... UNTIL, DO ... LOOP, IF ... ENDIF and SELECT ...
  // ENDSELECT. A one-line IF ... THEN statement opens nothing.
  function basicStructureRows(text) {
    return String(text).split("\n").map(line => {
      const masked = [...line];
      let quoted = false;
      for (let index = 0; index < line.length; index += 1) {
        const character = line[index];
        if (character === '"') {
          masked[index] = " ";
          if (quoted && line[index + 1] === '"') { masked[index + 1] = " "; index += 1; continue; }
          quoted = !quoted;
          continue;
        }
        if (quoted) { masked[index] = " "; continue; }
        if (character === "'" && /^\s*$|:\s*$/.test(line.slice(0, index))) { masked.fill(" ", index); break; }
        if (character === "!" && /\s/.test(line[index - 1] || " ") && index > 0) { masked.fill(" ", index); break; }
        if (/^REM(?![$%])/i.test(line.slice(index)) && (index === 0 || /[^A-Za-z0-9_$%]/.test(line[index - 1]))) {
          masked.fill(" ", index);
          break;
        }
      }
      const code = masked.join("").replace(/^\s*\d+\s*/, "");
      const events = [];
      // A line holding only name: is a GOTO label, not a statement.
      if (/^\s*[A-Za-z_][A-Za-z0-9_]*:\s*$/.test(code)) return { line, events };
      code.split(":").forEach((part, statementIndex) => {
        const statement = part.trim();
        if (!statement) return;
        const event = { leading: statementIndex === 0, statement };
        let match = statement.match(/^PROCEDURE\s+([A-Za-z_][A-Za-z0-9_.]*)/i);
        if (match) return events.push({ ...event, kind: "open", type: "procedure", label: `PROCEDURE ${match[1]}` });
        match = statement.match(/^FUNCTION\s+([A-Za-z_][A-Za-z0-9_.]*)/i);
        if (match) return events.push({ ...event, kind: "open", type: "function", label: `FUNCTION ${match[1]}` });
        if (/^ENDFUNC\b/i.test(statement)) return events.push({ ...event, kind: "close", type: "function" });
        if (/^RETURN(?![$%!#&|A-Za-z0-9_])/i.test(statement)) return events.push({ ...event, kind: "close", type: "procedure" });
        match = statement.match(/^FOR\s*([A-Za-z_][A-Za-z0-9_.$%!#&|]*)(?=\s*=)/i);
        if (match) return events.push({ ...event, kind: "open", type: "for", label: `FOR ${match[1]}` });
        if (/^NEXT(?![$%!#&|])(?:\b|(?=[A-Za-z]))/i.test(statement)) return events.push({ ...event, kind: "close", type: "for" });
        if (/^WHILE(?![$%!#&|])(?:\b|(?=[A-Za-z(]))/i.test(statement)) return events.push({ ...event, kind: "open", type: "while", label: "WHILE loop" });
        if (/^WEND(?![$%!#&|])/i.test(statement)) return events.push({ ...event, kind: "close", type: "while" });
        if (/^REPEAT(?![$%!#&|A-Za-z0-9_])/i.test(statement)) return events.push({ ...event, kind: "open", type: "repeat", label: "REPEAT loop" });
        if (/^UNTIL(?![$%!#&|])(?:\b|(?=[A-Za-z(]))/i.test(statement)) return events.push({ ...event, kind: "close", type: "repeat" });
        if (/^DO(?![$%!#&|A-Za-z0-9_])/i.test(statement)) return events.push({ ...event, kind: "open", type: "do", label: "DO loop" });
        if (/^LOOP(?![$%!#&|A-Za-z0-9_])/i.test(statement)) return events.push({ ...event, kind: "close", type: "do" });
        if (/^IF(?![$%!#&|])(?:\b|(?=[A-Za-z(]))/i.test(statement)) {
          // IF cond THEN statement on one line is complete; IF cond, or IF
          // cond THEN with nothing after it, opens a block.
          const then = statement.match(/\bTHEN\b(.*)$/i);
          const opensBlock = !then || !then[1].trim();
          if (opensBlock) return events.push({ ...event, kind: "open", type: "if", label: "IF block" });
          return;
        }
        if (/^ELSE\s+IF\b|^ELSEIF\b|^ELSE(?![$%!#&|A-Za-z0-9_])/i.test(statement)) return events.push({ ...event, kind: "branch", type: "if" });
        if (/^END\s*IF\b/i.test(statement)) return events.push({ ...event, kind: "close", type: "if" });
        if (/^SELECT(?![$%!#&|])(?:\b|(?=[A-Za-z(]))/i.test(statement)) return events.push({ ...event, kind: "open", type: "select", label: "SELECT block" });
        if (/^CASE(?![$%!#&|])(?:\b|(?=[A-Za-z(]))/i.test(statement) || /^DEFAULT(?![$%!#&|A-Za-z0-9_])/i.test(statement)) return events.push({ ...event, kind: "branch", type: "select" });
        if (/^END\s*SELECT\b/i.test(statement)) return events.push({ ...event, kind: "close", type: "select" });
      });
      return { line, events };
    });
  }

  function foldBlocks(text, language) {
    if (language !== "basic") return [];
    const rows = basicStructureRows(text);
    const offsets = [];
    rows.reduce((offset, row) => { offsets.push(offset); return offset + row.line.length + 1; }, 0);
    const stack = [];
    const blocks = [];
    rows.forEach((row, lineIndex) => row.events.forEach(event => {
      if (event.kind === "open") { stack.push({ ...event, startLine: lineIndex }); return; }
      if (event.kind !== "close") return;
      const stackIndex = stack.findLastIndex(item => item.type === event.type);
      if (stackIndex < 0) return;
      const opener = stack[stackIndex];
      stack.splice(stackIndex);
      if (lineIndex <= opener.startLine) return;
      blocks.push({
        id: `${opener.type}:${opener.startLine}:${lineIndex}`,
        type: opener.type,
        label: opener.label,
        startLine: opener.startLine,
        endLine: lineIndex,
        start: offsets[opener.startLine],
        end: offsets[lineIndex] + rows[lineIndex].line.length,
      });
    }));
    return blocks.sort((left, right) => left.startLine - right.startLine || right.endLine - left.endLine);
  }

  function basicStatements(body) {
    const normal = String(body)
      .replace(/^IF(?![$%])(?=\S)/i, "$& ")
      .replace(/\bTHEN(?![$%])(?=\d)/gi, "$& ")
      .replace(/(\d)ELSE(?![$%])(?=\S)/gi, "$1 ELSE ")
      .replace(/\bELSE(?![$%])(?=[A-Za-z])/gi, "$& ");
    const statements = BASIC_LANGUAGE
      ? BASIC_LANGUAGE.splitStatements(normal).map(statement => statement.text)
      : [normal.trim()].filter(Boolean);
    return statements.map(statement => statement
      .replace(/^IF(?![$%])(?=\S)/i, "$& ")
      .replace(/\bTHEN(?![$%])(?=\S)/gi, "$& ")
      .replace(/(\d)ELSE(?![$%])(?=\S)/gi, "$1 ELSE "));
  }

  function keywordOutsideQuotes(text, keyword, from = 0) {
    let quoted = false;
    const upper = String(text).toUpperCase();
    for (let index = from; index <= text.length - keyword.length; index += 1) {
      if (text[index] === '"') quoted = !quoted;
      if (quoted || upper.slice(index, index + keyword.length) !== keyword) continue;
      const before = index === 0 ? " " : text[index - 1];
      const after = text[index + keyword.length] || " ";
      if (!/[A-Z0-9_$%]/i.test(before) && !/[A-Z0-9_$%]/i.test(after)) return index;
    }
    return -1;
  }

  function inlineIfElseChain(body, nextNumber) {
    if (nextNumber == null || !/^\s*IF(?![$%])/i.test(body)) return null;
    const branches = [];
    let remaining = String(body).trim();
    while (/^IF(?![$%])/i.test(remaining)) {
      const thenAt = keywordOutsideQuotes(remaining, "THEN", 2);
      const elseAt = keywordOutsideQuotes(remaining, "ELSE", thenAt >= 0 ? thenAt + 4 : 2);
      if (elseAt < 0) return null;
      let condition;
      let action;
      if (thenAt >= 0) {
        condition = remaining.slice(2, thenAt).trim();
        action = remaining.slice(thenAt + 4, elseAt).trim();
      } else {
        const beforeElse = remaining.slice(2, elseAt).trim();
        const falseBranch = remaining.slice(elseAt + 4).trim();
        const assignment = falseBranch.match(/^([A-Za-z][A-Za-z0-9_]*[$%]?(?:\([^)]*\))?)\s*=/);
        let actionAt = null;
        if (assignment) {
          actionAt = [...beforeElse.matchAll(/(?:^|\s)([A-Za-z][A-Za-z0-9_]*[$%]?(?:\([^)]*\))?)\s*=/g)].at(-1) || null;
        } else {
          actionAt = [...beforeElse.matchAll(/(?:^|\s)(PRINT|CALL|CHAIN|GOTO|GOSUB|RETURN|RUN|SCREEN|WINDOW|SOUND|WAVE|LINE|LINEF|CIRCLE|PCIRCLE|PLOT|DRAW|FILL|PALETTE|COLOR|COLOUR|CLS|LOCATE|GOTOXY|INPUT|READ|RESTORE|ERROR|STOP|END|POKE|DPOKE|LPOKE|DOKE|LOKE|PUT|GET|OPEN|CLOSE|WRITE|KILL|NAME|WAIT|PAUSE|VSYNC|SPRITE|BOB|MUSIC|BOOM|SHOOT|BELL|FADE|SCROLL|OPENW|CLOSEW|CLEARW|FULLW|GEMSYS|VDISYS|QUIT|BLOAD|BSAVE|LOAD|SAVE)\b/gi)].at(-1) || null;
        }
        if (!actionAt) return null;
        const leadingSpace = /^\s/.test(actionAt[0]) ? 1 : 0;
        const boundary = actionAt.index + leadingSpace;
        condition = beforeElse.slice(0, boundary).trim();
        action = beforeElse.slice(boundary).trim();
      }
      if (!condition || !action || /^IF(?![$%])/i.test(action)) return null;
      branches.push({ condition, action });
      remaining = remaining.slice(elseAt + 4).trim();
    }
    if (!branches.length || !remaining) return null;
    const actions = branches.map(branch => basicStatements(branch.action));
    const finalActions = basicStatements(remaining);
    if (actions.some(items => !items.length) || !finalActions.length) return null;
    const starts = [];
    let nextStart = 0;
    actions.forEach(items => {
      starts.push(nextStart);
      nextStart += 1 + items.length + 1;
    });
    const finalStart = nextStart;
    const statements = [];
    branches.forEach(({ condition }, index) => {
      statements.push(`IF NOT(${condition}) THEN {{SELF:${starts[index + 1] ?? finalStart}}}`);
      statements.push(...actions[index]);
      statements.push("GOTO {{END}}");
    });
    statements.push(...finalActions);
    return statements;
  }

  function basicStartsStatement(text) {
    const value = String(text).trimStart();
    if (!value) return false;
    if (/^[A-Za-z][A-Za-z0-9_]*[$%!#]?(?:\([^)]*\))?\s*=/.test(value)) return true;
    // A listing commonly omits the space between a command and its first
    // argument: PRINT"A", COLOR1, CHAINf$ and so on. These are statements, not
    // computed line-number expressions after THEN.
    return /^(?:BELL|BLOAD|BOB|BOOM|BSAVE|CALL|CHAIN|CHDIR|CIRCLE|CLEAR|CLEARW|CLOSE|CLOSEW|CLS|COLOR|COLOUR|DATA|DEF|DIM|DOKE|DPOKE|DRAW|ERASE|ERROR|FADE|FILES|FILL|FOR|FULLW|GEMSYS|GET|GOSUB|GOTO|GOTOXY|IF|INPUT|KILL|LET|LINE|LINEF|LOAD|LOCATE|LOKE|LPOKE|MENU|MERGE|MID\$|MUSIC|NAME|NEXT|ON|OPEN|OPENW|PALETTE|PAUSE|PCIRCLE|PLOT|POKE|PRINT|PUT|QUIT|RANDOMIZE|READ|REM|RESTORE|RESUME|RETURN|RUN|SAVE|SCREEN|SCROLL|SETCOLOR|SHOOT|SOUND|SPRITE|STOP|SWAP|VDISYS|VSYNC|WAIT|WAVE|WEND|WHILE|WIDTH|WINDOW|WRITE)/i.test(value);
  }

  function inlineIfExpansion(statements, nextNumber) {
    const ifIndex = statements.findIndex(statement => /^IF(?![$%])/i.test(statement));
    if (ifIndex < 0) return statements;
    const statement = statements[ifIndex];
    const prefix = statements.slice(0, ifIndex);
    const tail = statements.slice(ifIndex + 1);
    const directElse = statement.match(/^IF(?![$%])\s*(.*?)\s+THEN\s*(\d+)\s+ELSE\s*(.+)$/i);
    if (directElse) {
      const falseAction = /^\d+\s*$/.test(directElse[3]) ? `GOTO ${directElse[3].trim()}` : directElse[3];
      return [...prefix, `IF ${directElse[1]} THEN ${directElse[2]}`, falseAction, ...tail];
    }
    if (nextNumber == null || /\bELSE\b/i.test(statement)) return null;
    let condition = "";
    let action = "";
    const withThen = statement.match(/^IF(?![$%])\s*(.*?)\s+THEN\s*(.+)$/i);
    if (withThen) {
      [, condition, action] = withThen;
    } else {
      // STOS and ST BASIC permit THEN to be omitted. Only split when the beginning of
      // the consequent is a proven statement command; guessing where an
      // arbitrary assignment starts could change the condition.
      const actionAt = [...statement.matchAll(/\s+/g)]
        .map(space => space.index + space[0].length)
        .find(index => basicStartsStatement(statement.slice(index)));
      if (actionAt != null) {
        condition = statement.slice(2, actionAt).trim();
        action = statement.slice(actionAt).trim();
      } else {
        const assignments = [...statement.matchAll(/\s+([A-Za-z][A-Za-z0-9_]*[$%]?(?:\([^)]*\))?)\s*=/g)];
        const assignment = assignments.at(-1);
        if (!assignment) return null;
        const boundary = assignment.index + 1;
        condition = statement.slice(2, boundary).trim();
        action = statement.slice(boundary).trim();
      }
    }
    if (!condition || !action) return null;
    // A bare number after THEN is a destination, not an executable statement
    // that can be moved onto its own line.
    if (/^\d+\s*$/.test(action)) return null;
    return [...prefix, `IF NOT(${condition}) THEN ${nextNumber}`, action, ...tail];
  }

  function tangledBasicLine(line, nextNumber = null) {
    const match = String(line).match(/^\s*(\d+)\s+(.*)$/);
    if (!match) return null;
    // A numbered listing does not accept an empty numbered source line. A colon by
    // itself is the executable no-op used for visual separators, so preserve
    // it exactly instead of producing an invalid blank line.
    if (/^\s*:+\s*$/.test(match[2])) {
      return null;
    }
    // ON ERROR owns the remainder of its physical line. Split it by installing
    // an explicit handler target and a normal-flow jump over the extracted
    // handler; simply putting its colon-separated actions on following lines
    // would execute them immediately and change the program.
    const onError = match[2].trim().match(/^ON\s*ERROR(.*)$/i);
    if (onError) {
      const handler = basicStatements(onError[1]);
      if (nextNumber == null || handler.length < 2) return null;
      return {
        number: Number(match[1]),
        body: match[2],
        statements: ["ON ERROR GOTO {{SELF:2}}", "GOTO {{END}}", ...handler],
      };
    }
    const ifAt = keywordOutsideQuotes(match[2], "IF");
    const prefixText = ifAt > 0 ? match[2].slice(0, ifAt).replace(/:\s*$/, "") : "";
    const prefix = prefixText && !/\bREM(?![$%])/i.test(prefixText) ? basicStatements(prefixText) : [];
    const conditionalChain = ifAt >= 0
      ? inlineIfElseChain(match[2].slice(ifAt), nextNumber)
      : null;
    if (conditionalChain) {
      const shiftedChain = conditionalChain.map(statement => statement.replace(
        /\{\{SELF:(\d+)\}\}/g,
        (_whole, index) => `{{SELF:${Number(index) + prefix.length}}}`,
      ));
      return { number: Number(match[1]), body: match[2], statements: [...prefix, ...shiftedChain] };
    }
    const statements = basicStatements(match[2]);
    if (statements.length < 2 && !/^IF(?![$%])/i.test(statements[0] || "")) return null;
    const expanded = inlineIfExpansion(statements, nextNumber);
    if (!expanded) return null;
    if (statements.length < 2 && expanded.length === statements.length && expanded.every((statement, index) => statement === statements[index])) return null;
    return { number: Number(match[1]), body: match[2], statements: expanded };
  }

  function nextBasicLineNumber(lines, index) {
    for (let following = index + 1; following < lines.length; following += 1) {
      const number = lines[following].match(/^\s*(\d+)\s+/)?.[1];
      if (number != null) return Number(number);
    }
    return null;
  }

  function maskedBasicCode(text) {
    const value = String(text);
    const mask = [...value];
    let quoted = false;
    for (let index = 0; index < value.length; index += 1) {
      if (value[index] === '"') { quoted = !quoted; mask[index] = " "; continue; }
      if (quoted) mask[index] = " ";
    }
    const comment = mask.join("").search(/\bREM(?![$%])/i);
    if (comment >= 0) mask.fill(" ", comment);
    return mask.join("");
  }

  function basicDestinations(text) {
    const mask = maskedBasicCode(text);
    const matches = [];
    const positions = new Set();
    const add = (start, digits) => {
      if (positions.has(start)) return;
      positions.add(start);
      matches.push({ start, end: start + digits.length, target: Number(digits) });
    };
    for (const match of mask.matchAll(/\b(?:GOTO|GOSUB|RESTORE|THEN|RUN)(?![$%])\s*(\d+)\b/gi)) {
      const digits = match[1];
      add(match.index + match[0].lastIndexOf(digits), digits);
    }
    for (const match of mask.matchAll(/\b(?:GOTO|GOSUB)(?![$%])\s+(\d+(?:\s*,\s*\d+)+)/gi)) {
      const listAt = match.index + match[0].indexOf(match[1]);
      for (const number of match[1].matchAll(/\d+/g)) add(listAt + number.index, number[0]);
    }
    return matches.sort((left, right) => left.start - right.start);
  }

  function rewriteBasicDestinations(text, numbers) {
    let updated = String(text);
    basicDestinations(updated).reverse().forEach(match => {
      const replacement = String(numbers.get(match.target) ?? match.target);
      updated = `${updated.slice(0, match.start)}${replacement}${updated.slice(match.end)}`;
    });
    return updated;
  }

  function basicHasDynamicDestination(text) {
    const mask = maskedBasicCode(text);
    for (const match of mask.matchAll(/\b(GOTO|GOSUB|RESTORE|RUN)(?![$%])/gi)) {
      const remainder = mask.slice(match.index + match[0].length).split(":", 1)[0].trimStart();
      if (!remainder && /^(RESTORE|RUN)$/i.test(match[1])) continue;
      if (!/^\d+\b/.test(remainder)) return true;
    }
    for (const match of mask.matchAll(/\bTHEN(?![$%])/gi)) {
      const remainder = mask.slice(match.index + match[0].length).split(/\bELSE\b|:/i, 1)[0].trim();
      if (!remainder || /^\d+\b/.test(remainder)) continue;
      if (basicStartsStatement(remainder)) continue;
      if (/^[A-Za-z][A-Za-z0-9_]*[$%]?(?:\([^)]*\))?\s*=/.test(remainder)) continue;
      return true;
    }
    return false;
  }

  function basicHasSemanticErl(text) {
    const code = maskedBasicCode(text);
    if (!/\bERL(?![$%])/i.test(code)) return false;
    // Merely printing ERL reports the newly assigned physical line number and
    // remains correct after a refactor. Assignments, comparisons and other
    // uses can make program behaviour depend on the old number and must keep
    // the conservative safety stop.
    return basicStatements(code).some(statement => (
      /\bERL(?![$%])/i.test(statement)
      && !/^\s*PRINT(?=\s|['";,(]|$)/i.test(statement)
    ));
  }

  function basicCondenseBoundaryBefore(body) {
    return /^\s*(?:ELSE|CASE|DEFAULT|ENDIF|END\s+IF|ENDSELECT|END\s+SELECT|WEND|UNTIL|LOOP|NEXT|RETURN|ENDFUNC|PROCEDURE|FUNCTION)(?![$%])/i.test(maskedBasicCode(body));
  }

  function basicCondenseBoundaryAfter(body) {
    const mask = maskedBasicCode(body);
    if (/\bIF(?![$%])/i.test(mask) || /^\s*ON\s+ERROR(?![$%])/i.test(mask)) return true;
    if (String(body).replace(/"(?:[^"]|"")*"/g, "").match(/\bREM(?![$%])/i)) return true;
    const finalStatement = basicStatements(body).at(-1) || "";
    return /^(?:GOTO|RETURN|END|STOP|CHAIN|RUN|ERROR|RESUME|QUIT|FOR|WHILE|REPEAT|DO|SELECT|PROCEDURE|FUNCTION)(?![$%!#])/i.test(finalStatement);
  }

  function rebuildBasic(lines, expansions, { startAt = null, fromIndex = 0, step = 10 } = {}) {
    const sourceRows = lines.map((line, index) => {
      const match = line.match(/^\s*(\d+)\s+(.*)$/);
      return match ? { index, old: Number(match[1]), bodies: expansions.get(index) || [match[2]] } : { index, old: null, bodies: [line] };
    });
    const map = new Map();
    let next = startAt;
    for (const row of sourceRows) {
      if (row.old == null) continue;
      const assigned = next == null || row.index < fromIndex ? row.old : next;
      map.set(row.old, assigned);
      if (next != null && row.index >= fromIndex) next += row.bodies.length * step;
    }
    return sourceRows.flatMap(row => {
      if (row.old == null) return row.bodies;
      let number = map.get(row.old);
      return row.bodies.map((body, bodyIndex) => {
        const rewritten = rewriteBasicDestinations(body, map)
          .replace(/\{\{SELF:(\d+)\}\}/g, (_whole, index) => String(map.get(row.old) + Number(index) * step))
          .replace(/\{\{END\}\}/g, () => String(map.get(nextBasicLineNumber(lines, row.index))));
        const result = `${number} ${rewritten}`;
        number += step;
        return result;
      });
    });
  }

  function normaliseBasicControlSpacing(line) {
    const match = String(line).match(/^(\s*\d+\s+)(.*)$/);
    if (!match || /^\s*:+\s*$/.test(match[2])) return line;
    // Detokenised listings often join a structural keyword directly to its
    // expression or loop variable. At statement start these forms are
    // unambiguous and a separating space materially improves readability.
    const body = match[2].replace(/^\s*(IF|FOR|NEXT|WHILE|WEND|CASE|REPEAT|UNTIL|SELECT|PROCEDURE)(?![$%!#])(?=\S)/i, (_whole, keyword) => `${keyword} `);
    return `${match[1]}${body}`;
  }

  const languageName = language => {
    const names = { basic: "BASIC (GFA, STOS, ST BASIC)", script: "TOS configuration", text: "plain text", m68k: "MC68000 assembly", fpu: "MC68881 floating-point" };
    if (names[language]) return names[language];
    const match = String(language || "").match(/^(680[0-9]0)(\+fpu)?$/i);
    return match ? `MC${match[1]} assembly${match[2] ? " with FPU" : ""}` : language;
  };

  function helpMarkup(item) {
    if (!item) return '<p class="code-empty-message">No built-in help is available for that token.</p>';
    return `<article class="code-help-detail"><h3>${esc(item.key)}</h3><p>${esc(item.summary)}</p><dl><dt>Syntax</dt><dd><code>${esc(item.syntax)}</code></dd><dt>Requirements</dt><dd>${esc(item.requirements)}</dd>${item.notes ? `<dt>Watch for</dt><dd>${esc(item.notes)}</dd>` : ""}</dl></article>`;
  }

  let hoverHelpRequest = 0;
  let lastHoverPointerMove = 0;
  let hoverHelpListenersInstalled = false;

  function dismissHoverHelp(owner = document) {
    hoverHelpRequest += 1;
    owner.querySelectorAll(".code-hover-help").forEach(node => node.remove());
    owner.querySelectorAll('[aria-describedby^="code-help-"]').forEach(node => node.removeAttribute("aria-describedby"));
  }

  function installHoverHelpDismissal(owner = document) {
    if (hoverHelpListenersInstalled) return;
    hoverHelpListenersInstalled = true;
    owner.addEventListener("pointermove", () => { lastHoverPointerMove = performance.now(); }, { passive: true });
    owner.addEventListener("pointerdown", () => dismissHoverHelp(owner), true);
    owner.addEventListener("scroll", () => dismissHoverHelp(owner), { capture: true, passive: true });
    owner.addEventListener("keydown", event => { if (event.key === "Escape") dismissHoverHelp(owner); }, true);
    owner.addEventListener("visibilitychange", () => dismissHoverHelp(owner));
    window.addEventListener("blur", () => dismissHoverHelp(owner));
  }

  function attachTooltip(root, language, element, key, suppliedItem = null) {
    const item = suppliedItem || lookup(language, key);
    if (!item) return;
    installHoverHelpDismissal(element.ownerDocument);
    let tooltip = null;
    let showTimer = null;
    const hide = () => {
      clearTimeout(showTimer);
      showTimer = null;
      tooltip?.remove();
      tooltip = null;
      element.removeAttribute("aria-describedby");
    };
    element.addEventListener("mouseenter", () => {
      const owner = element.ownerDocument;
      dismissHoverHelp(owner);
      const request = hoverHelpRequest;
      showTimer = setTimeout(() => {
        if (request !== hoverHelpRequest || !element.isConnected || !element.matches(":hover")) return;
        // Replacing highlighted source beneath a stationary pointer must not
        // manufacture a tooltip. A recent real pointer movement identifies a
        // deliberate hover over the token.
        if (performance.now() - lastHoverPointerMove > 750) return;
        tooltip = owner.createElement("div");
        tooltip.className = "code-hover-help";
        tooltip.id = `code-help-${Math.random().toString(36).slice(2)}`;
        tooltip.setAttribute("role", "tooltip");
        tooltip.innerHTML = `<strong>${esc(item.key)}</strong><span>${esc(item.summary)}</span><dl><dt>Syntax</dt><dd><code>${esc(item.syntax)}</code></dd><dt>Requirements</dt><dd>${esc(item.requirements)}</dd>${item.notes ? `<dt>Watch for</dt><dd>${esc(item.notes)}</dd>` : ""}</dl>`;
        // Native dialogs occupy the browser's top layer. Keep the tooltip in
        // the active dialog so it is painted above the editor.
        (root.closest("dialog") || owner.body).append(tooltip);
        const tokenRect = element.getBoundingClientRect();
        const tipRect = tooltip.getBoundingClientRect();
        tooltip.style.left = `${Math.max(8, Math.min(tokenRect.left, window.innerWidth - tipRect.width - 8))}px`;
        tooltip.style.top = `${tokenRect.bottom + tipRect.height + 8 < window.innerHeight ? tokenRect.bottom + 7 : Math.max(8, tokenRect.top - tipRect.height - 7)}px`;
        element.setAttribute("aria-describedby", tooltip.id);
      }, 300);
    });
    element.addEventListener("mouseleave", () => { hide(); dismissHoverHelp(element.ownerDocument); });
    element.addEventListener("focusout", () => { hide(); dismissHoverHelp(element.ownerDocument); });
    root.addEventListener("code-editor-destroy", hide, { once: true });
  }

  function enhance({ textarea, root, language = "text", dialect = "GFA BASIC 3", inlineAssemblyLanguage = "68000", validateBasic = null, packBasic = null, initialHistory = [], targetProfile = {} }) {
    if (!textarea || !root || textarea.closest(".code-editor-surface")) return null;
    const surface = document.createElement("div");
    surface.className = "code-editor-surface";
    const visual = document.createElement("div");
    visual.className = "code-highlight-layer";
    visual.setAttribute("aria-hidden", "true");
    visual.innerHTML = "<pre></pre>";
    const hit = document.createElement("div");
    hit.className = "code-hit-layer";
    hit.setAttribute("aria-hidden", "true");
    hit.innerHTML = "<pre></pre>";
    const guides = document.createElement("div");
    guides.className = "code-structure-guides";
    guides.setAttribute("aria-hidden", "true");
    const gutter = document.createElement("div");
    gutter.className = "code-fold-gutter";
    gutter.setAttribute("aria-label", "Code folding controls");
    const foldView = document.createElement("div");
    foldView.className = "code-fold-view";
    foldView.hidden = true;
    foldView.setAttribute("aria-label", "Collapsed code outline. Double-click a visible line to expand all blocks and edit it.");
    textarea.before(surface);
    surface.append(gutter, guides, visual, textarea, hit, foldView);
    const panel = document.createElement("section");
    panel.className = "code-intelligence-drawer";
    panel.hidden = true;
    root.insertBefore(panel, root.querySelector(".editor-status"));
    let state = { tokens: [], issues: [], symbols: [], blocks: [] };
    const collapsedBlocks = new Set();
    let structureGuides = language === "basic" ? { size: 4 } : null;
    let refactorPlan = null;
    let timer = null;
    const refactorUndo = [];
    const refactorRedo = [];
    const editorHistory = Array.isArray(initialHistory) ? initialHistory.slice(-200) : [];
    const pendingHistory = [];

    const historyEntry = (action, detail = "") => {
      const entry = { time: new Date().toISOString(), action, detail };
      editorHistory.push(entry);
      pendingHistory.push(entry);
      if (editorHistory.length > 200) editorHistory.shift();
    };

    const syncScroll = () => {
      for (const layer of [visual, hit, gutter, guides]) {
        layer.scrollTop = textarea.scrollTop;
        layer.scrollLeft = textarea.scrollLeft;
      }
    };
    const foldButtonMarkup = block => `<button type="button" class="code-fold-toggle" data-fold-id="${esc(block.id)}" aria-expanded="${collapsedBlocks.has(block.id) ? "false" : "true"}" title="${collapsedBlocks.has(block.id) ? "Expand" : "Collapse"} ${esc(block.label)}">${collapsedBlocks.has(block.id) ? "+" : "−"}</button>`;
    const blockStartingOn = lineIndex => state.blocks.find(block => block.startLine === lineIndex);
    const bindFoldButtons = host => host.querySelectorAll("[data-fold-id]").forEach(button => {
      button.onclick = event => {
        event.stopPropagation();
        const id = button.dataset.foldId;
        if (collapsedBlocks.has(id)) collapsedBlocks.delete(id);
        else collapsedBlocks.add(id);
        renderFolds();
      };
    });
    const renderFolds = () => {
      dismissHoverHelp(textarea.ownerDocument);
      if (refactorPlan) {
        const rendered = refactorPlan.preview;
        const renderedMarkup = highlightedSourceLines(rendered, language, inlineAssemblyLanguage);
        const original = refactorPlan.before || [];
        const originalMarkup = highlightedSourceLines(original, language, inlineAssemblyLanguage);
        surface.classList.add("code-editor-folded");
        foldView.hidden = false;
        gutter.innerHTML = "";
        const operation = refactorPlan.mode === "condense" ? "condensation" : "refactor";
        const maximum = Math.max(original.length, rendered.length);
        const reviewRows = Array.from({ length: maximum }, (_unused, index) => {
          const before = original[index] ?? "";
          const after = rendered[index] ?? "";
          const changed = before !== after;
          return `<div class="code-transform-row${changed ? " changed" : ""}"><span>${index + 1}</span><pre>${originalMarkup[index] || " "}</pre><pre>${renderedMarkup[index] || " "}</pre></div>`;
        }).join("");
        const verification = refactorPlan.verification;
        foldView.innerHTML = `<section class="code-transform-review"><header><div><strong>Original</strong><small>${original.length} lines</small></div><div><strong>Proposed ${operation}</strong><small>${rendered.length} lines</small></div><div class="code-transform-actions"><button type="button" class="code-untangle-cancel" title="Cancel without changing the program">Cancel</button><button type="button" class="code-untangle-commit" title="Accept the proposed ${operation}">Accept</button></div></header>${verification ? `<p class="code-transform-verification ${verification.roundTripExact ? "pass" : "warn"}">${verification.roundTripExact ? "✓ Exact BASIC token round trip" : "! Round-trip warning"} · ${Number(verification.byteLength || 0).toLocaleString()} tokenised bytes · ${Number(verification.lineCount || 0).toLocaleString()} lines</p>` : ""}<div class="code-transform-columns"><span></span><strong>Before</strong><strong>After</strong></div>${reviewRows}</section>`;
        foldView.querySelector(".code-untangle-commit").onclick = () => commitRefactor();
        foldView.querySelector(".code-untangle-cancel").onclick = () => cancelRefactor();
        return;
      }
      const validIds = new Set(state.blocks.map(block => block.id));
      [...collapsedBlocks].forEach(id => { if (!validIds.has(id)) collapsedBlocks.delete(id); });
      const canFold = state.blocks.length > 0;
      const foldAll = root.querySelector('[data-editor-action="fold-toggle-all"]');
      if (foldAll) {
        foldAll.disabled = !canFold;
        foldAll.querySelector("span").textContent = collapsedBlocks.size ? "Expand all blocks" : "Collapse all blocks";
      }
      const guideToggle = root.querySelector('[data-editor-action="structure-guides"] span');
      if (guideToggle) guideToggle.textContent = structureGuides ? "Hide structure guides" : "Show structure guides";
      const lines = textarea.value.split("\n");
      const displayLines = lines;
      const displayMarkup = highlightedSourceLines(displayLines, language, inlineAssemblyLanguage);
      gutter.innerHTML = `<div>${lines.map((_line, index) => `<span>${blockStartingOn(index) ? foldButtonMarkup(blockStartingOn(index)) : ""}</span>`).join("")}</div>`;
      bindFoldButtons(gutter);
      const outlined = collapsedBlocks.size > 0;
      surface.classList.toggle("code-editor-folded", outlined);
      foldView.hidden = !outlined;
      if (!outlined) return;
      const offsets = [];
      lines.reduce((offset, line) => { offsets.push(offset); return offset + line.length + 1; }, 0);
      const visibleRows = [];
      lines.forEach((line, lineIndex) => {
        const hidingBlock = state.blocks.find(block => collapsedBlocks.has(block.id) && lineIndex > block.startLine && lineIndex <= block.endLine);
        if (hidingBlock) return;
        const block = blockStartingOn(lineIndex);
        const hiddenCount = block && collapsedBlocks.has(block.id) ? block.endLine - block.startLine : 0;
        const displayLine = displayLines[lineIndex] ?? line;
        visibleRows.push(`<div class="code-fold-row" data-code-offset="${offsets[lineIndex]}"><span class="code-fold-row-gutter">${block ? foldButtonMarkup(block) : ""}</span><pre>${displayMarkup[lineIndex]}</pre>${hiddenCount ? `<small>${hiddenCount.toLocaleString()} line${hiddenCount === 1 ? "" : "s"} folded</small>` : ""}</div>`);
      });
      foldView.innerHTML = visibleRows.join("");
      bindFoldButtons(foldView);
      foldView.querySelectorAll(".code-help-token").forEach(element => attachTooltip(root, element.dataset.helpLanguage || language, element, element.dataset.helpKey));
      foldView.querySelectorAll(".code-fold-row").forEach(row => row.ondblclick = event => {
        if (event.target.closest("button")) return;
        const offset = Number(row.dataset.codeOffset);
        showOriginalView();
        goTo(offset);
      });
      foldView.scrollTop = Math.min(foldView.scrollHeight, textarea.scrollTop);
    };
    const expandAll = () => {
      if (!collapsedBlocks.size) return;
      collapsedBlocks.clear();
      renderFolds();
      textarea.focus();
    };
    const collapseAll = () => {
      state.blocks.forEach(block => collapsedBlocks.add(block.id));
      renderFolds();
    };
    const toggleAll = () => collapsedBlocks.size ? expandAll() : collapseAll();
    const renderStructureGuides = () => {
      if (!structureGuides || language !== "basic") {
        guides.replaceChildren();
        guides.hidden = true;
        return;
      }
      guides.hidden = false;
      const lines = textarea.value.split("\n");
      const cursorLine = textarea.value.slice(0, textarea.selectionStart).split("\n").length - 1;
      const active = state.blocks
        .filter(block => cursorLine >= block.startLine && cursorLine <= block.endLine)
        .sort((left, right) => (left.endLine - left.startLine) - (right.endLine - right.startLine))[0];
      const size = [2, 4, 8].includes(Number(structureGuides.size)) ? Number(structureGuides.size) : 4;
      const guideWidth = Math.max(textarea.scrollWidth, textarea.clientWidth);
      guides.style.setProperty("--structure-guide-step", `${size}ch`);
      guides.innerHTML = lines.map((_line, lineIndex) => {
        const depth = state.blocks.filter(block => lineIndex > block.startLine && lineIndex <= block.endLine).length;
        const activeLine = active && lineIndex >= active.startLine && lineIndex <= active.endLine;
        const bars = Array.from({ length: depth }, (_unused, index) => `<i style="--guide-index:${index}"></i>`).join("");
        return `<span class="${activeLine ? "active" : ""}" style="width:${guideWidth}px">${bars}</span>`;
      }).join("");
      guides.scrollTop = textarea.scrollTop;
      guides.scrollLeft = textarea.scrollLeft;
    };
    const toggleStructureGuides = size => {
      structureGuides = structureGuides ? null : { size: Number(size) };
      renderStructureGuides();
      renderFolds();
    };
    const setStructureGuideSize = size => {
      if (!structureGuides) structureGuides = { size: Number(size) };
      else structureGuides.size = Number(size);
      renderStructureGuides();
    };
    const showOriginalView = () => {
      refactorPlan = null;
      collapsedBlocks.clear();
      renderFolds();
      textarea.focus();
    };
    const goTo = offset => {
      if (collapsedBlocks.size) {
        collapsedBlocks.clear();
        renderFolds();
      }
      textarea.focus();
      textarea.setSelectionRange(offset, offset);
      const before = textarea.value.slice(0, offset).split("\n");
      textarea.scrollTop = Math.max(0, (before.length - 3) * parseFloat(getComputedStyle(textarea).lineHeight || "16"));
      syncScroll();
      textarea.dispatchEvent(new Event("click", { bubbles: true }));
    };
    const closePanel = () => { panel.hidden = true; };
    const renderPanel = (title, body) => {
      panel.hidden = false;
      panel.innerHTML = `<header><div><small>CODE-AWARE HELP</small><h3>${esc(title)}</h3></div><button type="button" class="code-drawer-close" aria-label="Close code help">×</button></header><div class="code-drawer-body">${body}</div>`;
      panel.querySelector(".code-drawer-close").onclick = closePanel;
      panel.querySelectorAll("[data-code-offset]").forEach(button => button.onclick = () => goTo(Number(button.dataset.codeOffset)));
      panel.querySelectorAll("[data-code-help]").forEach(button => button.onclick = () => renderPanel(button.dataset.codeHelp, helpMarkup(lookup(language, button.dataset.codeHelp))));
      panel.querySelectorAll("[data-code-completion]").forEach(button => button.onclick = () => {
        const selected = identifierAt(textarea.value, textarea.selectionStart, language);
        const start = selected?.start ?? textarea.selectionStart;
        const end = selected?.end ?? textarea.selectionEnd;
        const value = button.dataset.codeCompletion;
        textarea.setRangeText(value, start, end, "end");
        textarea.dispatchEvent(new Event("input", { bubbles: true }));
        closePanel();
        textarea.focus();
      });
      panel.querySelectorAll("[data-code-snippet]").forEach(button => button.onclick = () => {
        const value = button.dataset.codeSnippet;
        textarea.setRangeText(value, textarea.selectionStart, textarea.selectionEnd, "end");
        textarea.dispatchEvent(new Event("input", { bubbles: true }));
        closePanel();
        textarea.focus();
      });
      const filter = panel.querySelector("[data-code-reference-filter]");
      if (filter) filter.oninput = () => panel.querySelectorAll("[data-code-help]").forEach(button => button.hidden = !button.textContent.toLowerCase().includes(filter.value.toLowerCase()));
    };
    const showCustom = (title, body) => renderPanel(title, body);
    const overview = () => {
      const recognised = [...new Set(state.tokens.map(item => item.helpKey).filter(Boolean))];
      const profile = BASIC_LANGUAGE?.dialectProfile(dialect);
      renderPanel(`${languageName(language)} overview`, `<div class="code-overview"><p>This file contains <strong>${textarea.value.split("\n").length.toLocaleString()} lines</strong>, <strong>${state.symbols.length.toLocaleString()} navigable symbols</strong> and <strong>${state.issues.length.toLocaleString()} diagnostics</strong>.</p><p>${language === "basic" ? `Detected dialect: <strong>${esc(dialect)}</strong>. ${usesLineNumbers(textarea.value, dialect) ? "Numbered source is tokenised when saved and line destinations are checked while you type." : "GFA BASIC source has no line numbers; PROCEDURE, FUNCTION and label definitions are checked while you type."} ${profile?.processor ? `Machine code it calls runs on a ${esc(profile.processor)}.` : ""} Block structure (IF/ENDIF, FOR/NEXT, WHILE/WEND, REPEAT/UNTIL, DO/LOOP, SELECT/ENDSELECT, PROCEDURE/RETURN) is checked for missing closers.` : language === "script" ? "Desktop records (DESKTOP.INF, NEWDESK.INF) and MINT.CNF directives are read in order at boot. Paths that would be skipped and directives that contradict one another are highlighted." : "Readable text is preserved as Atari ST character set. Syntax-specific checks are intentionally not imposed."}</p>${recognised.length ? `<h4>Commands used in this file</h4><div class="code-command-chips">${recognised.map(key => `<button type="button" data-code-help="${esc(key)}">${esc(key)}</button>`).join("")}</div>` : ""}</div>`);
    };
    const helpAtCursor = () => {
      const offset = textarea.selectionStart;
      const lineStart = textarea.value.lastIndexOf("\n", Math.max(0, offset - 1)) + 1;
      const found = state.tokens.find(item => item.start <= offset && item.end >= offset && item.helpKey)
        || state.tokens.filter(item => item.start >= lineStart && item.end <= offset && item.helpKey).at(-1);
      const item = found ? sourceContextHelp(textarea.value, found.helpLanguage || language, found.start, found.end, found.helpKey, targetProfile) : null;
      renderPanel(item?.key || "Help at cursor", helpMarkup(item));
    };
    const showProblems = () => renderPanel("Problems", state.issues.length ? `<div class="code-problem-list">${state.issues.map(item => `<button type="button" data-code-offset="${item.offset}"><b class="${esc(item.severity)}">${esc(item.severity)}</b><span>Line ${item.line}: ${esc(item.message)}</span></button>`).join("")}</div>` : '<p class="code-empty-message">No problems were found by the live checks.</p>');
    const showSymbols = () => renderPanel("Document symbols", state.symbols.length ? `<div class="code-symbol-list">${state.symbols.map(item => `<button type="button" data-code-offset="${item.offset}"><b>${esc(item.kind)}</b><span>${esc(item.name)}</span></button>`).join("")}</div>` : '<p class="code-empty-message">No navigable symbols were found in this file.</p>');
    const showCompletions = () => {
      const selected = identifierAt(textarea.value, textarea.selectionStart, language);
      const prefix = String(selected?.name || "").toUpperCase();
      const identifiers = language === "basic" && BASIC_LANGUAGE
        ? BASIC_LANGUAGE.scan(textarea.value).filter(item => item.type === "identifier").map(item => item.text)
        : [];
      const commands = language === "basic" ? [...BASIC_KEYWORDS] : language === "script" ? [...SCRIPT_COMMANDS] : [];
      const candidates = [...new Set([...commands, ...identifiers, ...state.symbols.map(item => item.name.replace(/^Line\s+/, ""))])]
        .filter(value => !prefix || value.toUpperCase().startsWith(prefix))
        .sort((left, right) => left.localeCompare(right)).slice(0, 200);
      const snippets = language === "basic" ? [
        ["FOR loop", "FOR i%=1 TO 10\nNEXT i%"], ["REPEAT loop", "REPEAT\nUNTIL condition"],
        ["DO loop", "DO\n  EXIT IF condition\nLOOP"], ["Conditional", "IF condition\nENDIF"],
        ["Procedure", "PROCEDURE name\n  LOCAL a%\nRETURN"], ["GEMDOS call", "~GEMDOS(9,L:ADDR(a$))"],
        ["Wait for the vertical blank", "VSYNC"],
      ] : language === "script" ? [
        ["Start an AES", "GEM=C:\\MINT\\XAAES\\XAAES.KM"], ["Set a variable", "setenv PATH C:\\MINT;C:\\BIN"],
        ["Run a program at boot", "exec c:\\mint\\program.prg"],
        ["Auto-start a desktop program", "#Z 01 C:\\GEM\\PROGRAM.PRG@"],
      ] : [];
      renderPanel("Completion and snippets", `<p class="code-empty-message">${prefix ? `Candidates beginning with ${esc(prefix)}.` : "Choose a known command, identifier or template."}</p><div class="code-completion-list">${candidates.map(value => `<button type="button" data-code-completion="${esc(value)}">${esc(value)}</button>`).join("") || "<small>No matching candidates.</small>"}</div>${snippets.length ? `<h4 class="code-drawer-section-title">Templates</h4><div class="code-snippet-list">${snippets.map(([label, value]) => `<button type="button" data-code-snippet="${esc(value)}"><b>${esc(label)}</b><code>${esc(value)}</code></button>`).join("")}</div>` : ""}`);
    };
    const formatCode = async () => {
      if (textarea.readOnly) return false;
      const hasSelection = textarea.selectionStart !== textarea.selectionEnd;
      const lineStart = textarea.value.lastIndexOf("\n", Math.max(0, textarea.selectionStart - 1)) + 1;
      const lineEndAt = textarea.value.indexOf("\n", textarea.selectionEnd);
      const rangeStart = hasSelection ? lineStart : 0;
      const rangeEnd = hasSelection ? (lineEndAt < 0 ? textarea.value.length : lineEndAt) : textarea.value.length;
      const original = textarea.value.slice(rangeStart, rangeEnd);
      const formatted = original.split("\n").map(line => {
        let updated = line.replace(/[ \t]+$/g, "");
        if (language === "basic") updated = normaliseBasicControlSpacing(updated.replace(/^\s*(\d+)\s*/, "$1 "));
        if (language === "script") updated = updated.replace(/^\s*\*\s*/, "*");
        return updated;
      }).join("\n");
      if (formatted === original) {
        showCustom("Format source", '<p class="code-empty-message">The selected source already follows the conservative formatter rules.</p>');
        return false;
      }
      const candidate = `${textarea.value.slice(0, rangeStart)}${formatted}${textarea.value.slice(rangeEnd)}`;
      if (language === "basic" && validateBasic) {
        const check = await validateBasic(candidate, textarea.value);
        if (!check.roundTrip) {
          showCustom("Format source", `<p class="code-empty-message">Formatting was not applied because the BASIC token round trip failed: ${esc(check.message || "unknown error")}</p>`);
          return false;
        }
      }
      if (!await confirmChoice("Reformat the source?", `Conservative whitespace formatting is applied to ${hasSelection ? "the selected lines" : "the complete file"}.`, { confirmLabel: "Format source", note: "Editor undo reverses it, and nothing is written to the image until you save." })) return false;
      const before = documentSnapshot();
      const selectionEnd = rangeStart + formatted.length;
      const after = { value: candidate, selectionStart: rangeStart, selectionEnd, scrollTop: textarea.scrollTop, scrollLeft: textarea.scrollLeft };
      refactorUndo.push({ before, after });
      refactorRedo.length = 0;
      applyDocumentSnapshot(after);
      historyEntry("Formatted source", hasSelection ? "Selected lines" : "Complete file");
      return true;
    };
    const findReferences = () => {
      const result = symbolReferences(textarea.value, textarea.selectionStart, language);
      renderPanel(result.name ? `References to ${result.name}` : "Find all references", result.rows.length
        ? `<p>${result.rows.length.toLocaleString()} code occurrence${result.rows.length === 1 ? "" : "s"}; strings and comments are excluded.</p><div class="code-reference-results">${result.rows.map(row => `<button type="button" data-code-offset="${row.offset}"><b>Line ${row.line}</b><code>${esc(row.context)}</code></button>`).join("")}</div>`
        : '<p class="code-empty-message">Place the cursor on a symbol or variable to find its references.</p>');
    };
    const renameSymbol = async () => {
      if (textarea.readOnly) return;
      const result = symbolReferences(textarea.value, textarea.selectionStart, language);
      if (!result.name || !result.rows.length) return alertNotice("Rename a symbol", "Place the cursor on a symbol or variable first.");
      if (language === "basic" && BASIC_KEYWORDS.has(result.name.toUpperCase())) return alertNotice("Rename a symbol", `${result.name} is a BASIC command, and commands cannot be renamed.`);
      const replacement = await promptValue(`Rename ${result.name}`, "New name", {
        value: result.name,
        message: `${result.rows.length} code occurrence${result.rows.length === 1 ? "" : "s"} will be renamed.`,
        note: "Text inside strings and comments is left alone.",
        confirmLabel: "Rename",
        pattern: "[A-Za-z_.][A-Za-z0-9_.$%]*",
      });
      if (!replacement || replacement === result.name || !/^[A-Za-z_.][A-Za-z0-9_.$%]*$/.test(replacement)) return;
      const before = documentSnapshot();
      let updated = textarea.value;
      [...result.rows].reverse().forEach(row => { updated = `${updated.slice(0, row.offset)}${replacement}${updated.slice(row.offset + result.name.length)}`; });
      const cursor = Math.min(updated.length, textarea.selectionStart + replacement.length - result.name.length);
      const after = { value: updated, selectionStart: cursor, selectionEnd: cursor, scrollTop: textarea.scrollTop, scrollLeft: textarea.scrollLeft };
      refactorUndo.push({ before, after });
      refactorRedo.length = 0;
      applyDocumentSnapshot(after);
      historyEntry("Renamed symbol", `${result.name} → ${replacement}; ${result.rows.length} references`);
    };
    const showOutline = () => {
      if (language !== "basic") return showSymbols();
      const definitions = [...textarea.value.matchAll(/^\s*(?:PROCEDURE|FUNCTION|DEFFN)\s+([A-Za-z_][A-Za-z0-9_.]*)/gim)].map(match => ({
        name: match[1].toUpperCase(), offset: match.index,
        calls: [...sourceMask(textarea.value, language).matchAll(new RegExp(`(?<![A-Za-z0-9_.])${match[1].replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?![A-Za-z0-9_.])`, "gi"))].filter(call => call.index < match.index || call.index > match.index + match[0].length),
      }));
      renderPanel("Program outline and call graph", definitions.length
        ? `<div class="code-outline-list">${definitions.map(item => `<article><button type="button" data-code-offset="${item.offset}"><b>${esc(item.name)}</b><span>${item.calls.length} call${item.calls.length === 1 ? "" : "s"}</span></button>${item.calls.map(call => `<button type="button" data-code-offset="${call.index}">Called at physical line ${textarea.value.slice(0, call.index).split("\n").length}</button>`).join("")}</article>`).join("")}</div>`
        : '<p class="code-empty-message">No procedures or functions were defined in this file.</p>');
    };
    const showHistory = () => renderPanel("Editor history", editorHistory.length
      ? `<div class="code-history-list">${[...editorHistory].reverse().map(item => `<article><time>${esc(new Date(item.time).toLocaleTimeString())}</time><b>${esc(item.action)}</b><span>${esc(item.detail)}</span></article>`).join("")}</div>`
      : '<p class="code-empty-message">No transformations or symbol changes have been made in this editor window.</p>');
    const compareWith = baseline => {
      const before = String(baseline || "").split("\n");
      const after = textarea.value.split("\n");
      const maximum = Math.max(before.length, after.length);
      const rows = Array.from({ length: maximum }, (_unused, index) => ({ before: before[index] ?? "", after: after[index] ?? "" }))
        .map((row, index) => `<div class="code-inline-diff-row${row.before === row.after ? "" : " changed"}"><span>${index + 1}</span><pre>${esc(row.before) || " "}</pre><pre>${esc(row.after) || " "}</pre></div>`).join("");
      renderPanel("Current source compared with saved file", `<div class="code-inline-diff"><header><span></span><b>Saved</b><b>Current</b></header>${rows}</div>`);
    };
    const verifyRoundTrip = async () => {
      if (!validateBasic) return;
      try {
        const result = await validateBasic(textarea.value, textarea.dataset.savedValue || "");
        renderPanel("BASIC round-trip verification", `<div class="code-verification"><p class="${result.roundTripExact ? "pass" : "warn"}"><strong>${result.roundTripExact ? "Exact token round trip" : "Review required"}</strong></p><dl><dt>Lines</dt><dd>${Number(result.lineCount || 0).toLocaleString()}</dd><dt>Tokenised size</dt><dd>${Number(result.byteLength || 0).toLocaleString()} bytes</dd><dt>Destinations</dt><dd>${(result.destinations || []).length.toLocaleString()}</dd></dl>${(result.warnings || []).map(message => `<p>${esc(message)}</p>`).join("") || "<p>The listing tokenises, detokenises and reproduces identical token bytes.</p>"}</div>`);
        return result;
      } catch (error) { await alertNotice("Round-trip verification failed", error.message || String(error), { danger: true }); return null; }
    };
    const reference = () => {
      const keys = [...new Set([...Object.keys(dictionary(language)), ...(language === "basic" ? [...BASIC_KEYWORDS] : [])])].sort();
      renderPanel(`${languageName(language)} reference`, `<label class="code-reference-filter">Filter commands<input type="search" data-code-reference-filter placeholder="Type a command name"></label><div class="code-reference-list">${keys.map(key => `<button type="button" data-code-help="${esc(key)}">${esc(key)}</button>`).join("")}</div>`);
      panel.querySelector("[data-code-reference-filter]")?.focus();
    };
    const goToLine = async () => {
      const requested = await promptValue("Go to line", language === "basic" ? "BASIC line or editor line" : "Editor line", {
        placeholder: "1", confirmLabel: "Go",
        message: language === "basic" ? "A BASIC line number is looked for first, then the physical editor line." : "",
      });
      if (requested == null || !requested.trim()) return;
      const number = Number.parseInt(requested, 10);
      if (!Number.isInteger(number) || number < 1) return;
      let offset = null;
      if (language === "basic") {
        const match = [...textarea.value.matchAll(/^\s*(\d+)\s/gm)].find(item => Number(item[1]) === number);
        if (match) offset = match.index;
      }
      if (offset == null) {
        const lines = textarea.value.split("\n");
        if (number > lines.length) return;
        offset = lines.slice(0, number - 1).reduce((total, line) => total + line.length + 1, 0);
      }
      goTo(offset);
    };
    const normaliseCommands = () => {
      const convention = COMMAND_CASE[language];
      if (!convention) return;
      showOriginalView();
      const convert = value => convention === "lower" ? value.toLowerCase() : value.toUpperCase();
      const replacements = state.tokens.filter(item => item.type === "keyword" && item.text !== convert(item.text)).reverse();
      if (!replacements.length) return;
      const selectionStart = textarea.selectionStart;
      const selectionEnd = textarea.selectionEnd;
      let updated = textarea.value;
      replacements.forEach(item => { updated = `${updated.slice(0, item.start)}${convert(item.text)}${updated.slice(item.end)}`; });
      textarea.setRangeText(updated, 0, textarea.value.length, "end");
      textarea.setSelectionRange(selectionStart, selectionEnd);
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      textarea.focus();
      historyEntry("Normalised commands", `${replacements.length} recognised token${replacements.length === 1 ? "" : "s"}`);
    };
    const currentPhysicalLines = () => {
      const start = textarea.value.lastIndexOf("\n", Math.max(0, textarea.selectionStart - 1)) + 1;
      const endBreak = textarea.value.indexOf("\n", textarea.selectionEnd);
      const end = endBreak < 0 ? textarea.value.length : endBreak;
      const first = textarea.value.slice(0, start).split("\n").length - 1;
      const last = first + textarea.value.slice(start, end).split("\n").length - 1;
      return { first, last };
    };
    const lineOperation = action => {
      if (textarea.readOnly) return false;
      showOriginalView();
      const range = currentPhysicalLines();
      const lines = textarea.value.split("\n");
      const selected = lines.slice(range.first, range.last + 1);
      if (!selected.length) return false;
      const before = documentSnapshot();
      let first = range.first;
      if (action === "delete") lines.splice(range.first, selected.length);
      else if (action === "duplicate") { lines.splice(range.last + 1, 0, ...selected); first = range.last + 1; }
      else if (action === "move-up" && range.first > 0) {
        const previous = lines.splice(range.first - 1, 1)[0];
        lines.splice(range.last, 0, previous);
        first -= 1;
      } else if (action === "move-down" && range.last < lines.length - 1) {
        const following = lines.splice(range.last + 1, 1)[0];
        lines.splice(range.first, 0, following);
        first += 1;
      } else if (action === "join" && language !== "basic") {
        lines.splice(range.first, selected.length, selected.map(line => line.trim()).join(" "));
      } else return false;
      const updated = lines.join("\n");
      const start = lines.slice(0, first).reduce((total, line) => total + line.length + 1, 0);
      const count = action === "duplicate" ? selected.length : action === "join" ? 1 : action === "delete" ? 0 : selected.length;
      const end = count ? start + lines.slice(first, first + count).join("\n").length : start;
      const after = { value: updated, selectionStart: start, selectionEnd: end, scrollTop: textarea.scrollTop, scrollLeft: textarea.scrollLeft };
      refactorUndo.push({ before, after });
      refactorRedo.length = 0;
      applyDocumentSnapshot(after);
      historyEntry(`${action.replace("-", " ")} lines`, `${selected.length} line${selected.length === 1 ? "" : "s"}`);
      return true;
    };
    const sourcePosition = offset => {
      const rows = textarea.value.slice(0, Math.max(0, offset)).split("\n");
      return { line: rows.length - 1, column: rows.at(-1).length };
    };
    const rebuiltPosition = (position, lines, expansions, rebuiltLines) => {
      const sourceLine = Math.min(position.line, Math.max(0, lines.length - 1));
      let targetLine = 0;
      for (let index = 0; index < sourceLine; index += 1) {
        targetLine += expansions.get(index)?.length || 1;
      }
      targetLine = Math.min(targetLine, Math.max(0, rebuiltLines.length - 1));
      const column = Math.min(position.column, rebuiltLines[targetLine]?.length || 0);
      return rebuiltLines.slice(0, targetLine).reduce((total, line) => total + line.length + 1, 0) + column;
    };
    const documentSnapshot = () => ({
      value: textarea.value,
      selectionStart: textarea.selectionStart,
      selectionEnd: textarea.selectionEnd,
      scrollTop: textarea.scrollTop,
      scrollLeft: textarea.scrollLeft,
    });
    const applyDocumentSnapshot = snapshot => {
      textarea.focus();
      textarea.value = snapshot.value;
      textarea.setSelectionRange(snapshot.selectionStart, snapshot.selectionEnd);
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      const restoreView = () => {
        textarea.scrollTop = snapshot.scrollTop;
        textarea.scrollLeft = snapshot.scrollLeft;
        syncScroll();
      };
      restoreView();
      requestAnimationFrame(restoreView);
      setTimeout(restoreView, 0);
      setTimeout(restoreView, 100);
    };
    const recordRefactor = after => {
      refactorUndo.push({ before: documentSnapshot(), after });
      refactorRedo.length = 0;
      applyDocumentSnapshot(after);
      clearTimeout(timer);
      render();
      historyEntry("Accepted transformation", `${after.value.split("\n").length} lines`);
    };
    const undo = () => {
      const transaction = refactorUndo.at(-1);
      if (!transaction || textarea.value !== transaction.after.value) return false;
      refactorUndo.pop();
      refactorRedo.push(transaction);
      applyDocumentSnapshot(transaction.before);
      clearTimeout(timer);
      render();
      return true;
    };
    const redo = () => {
      const transaction = refactorRedo.at(-1);
      if (!transaction || textarea.value !== transaction.before.value) return false;
      refactorRedo.pop();
      refactorUndo.push(transaction);
      applyDocumentSnapshot(transaction.after);
      clearTimeout(timer);
      render();
      return true;
    };
    const cancelRefactor = () => {
      refactorPlan = null;
      renderFolds();
      textarea.focus();
    };
    const commitRefactor = async () => {
      if (!refactorPlan) return;
      const condensing = refactorPlan.mode === "condense";
      const message = condensing
        ? "Accept this condensation? The reviewed proposal will replace the selected code as one undoable operation. Safe adjacent statements will share physical lines; surviving line numbers and all explicit destinations are preserved."
        : "Accept this refactor? The reviewed proposal will now replace the program as one undoable operation. Lines will be renumbered and direct GOTO, GOSUB, RESTORE, THEN and ON GOTO/GOSUB destinations will be updated. Dynamic line-number expressions cannot be rewritten automatically.";
      if (!await confirmChoice("Renumber this program?", message, { confirmLabel: "Renumber", note: "Editor undo reverses it, and nothing is written to the image until you save." })) return;
      const after = refactorPlan.after;
      refactorPlan = null;
      recordRefactor(after);
      renderFolds();
    };
    const refactor = async () => {
      if (language !== "basic" || textarea.readOnly) return;
      const range = currentPhysicalLines();
      const noSelection = textarea.selectionStart === textarea.selectionEnd;
      const lines = textarea.value.split("\n");
      const selectionStart = sourcePosition(textarea.selectionStart);
      const selectionEnd = sourcePosition(textarea.selectionEnd);
      const scrollTop = textarea.scrollTop;
      const scrollLeft = textarea.scrollLeft;
      const first = noSelection ? 0 : range.first;
      const last = noSelection ? lines.length - 1 : range.last;
      const assemblerLines = basicInlineAssemblerLines(textarea.value);
      const numberedBodies = lines.map(line => line.match(/^\s*\d+\s+(.*)$/)?.[1]).filter(body => body != null);
      if (!numberedBodies.length) {
        await alertNotice("Nothing to renumber", "Renumbering applies to a numbered STOS or ST BASIC listing. GFA BASIC source has no line numbers, so there is nothing to change.");
        return;
      }
      if (numberedBodies.some(basicHasDynamicDestination) || numberedBodies.some(basicHasSemanticErl)) {
        await alertNotice("The program was left untouched", "It uses a computed line destination, or uses ERL in program logic. Renumbering physical lines could change its behaviour, so no change has been made.");
        return;
      }
      const expansions = new Map();
      for (let index = first; index <= last; index += 1) {
        if (assemblerLines[index]) continue;
        const tangled = tangledBasicLine(lines[index], nextBasicLineNumber(lines, index));
        if (tangled) expansions.set(index, tangled.statements);
      }
      const rawRebuiltLines = rebuildBasic(lines, expansions, { startAt: 10, step: 10 });
      const rebuiltAssemblerLines = basicInlineAssemblerLines(rawRebuiltLines.join("\n"));
      const rebuiltLines = rawRebuiltLines
        .map((line, index) => rebuiltAssemblerLines[index] ? line : normaliseBasicControlSpacing(line));
      const rebuilt = rebuiltLines.join("\n");
      if (rebuiltLines.some(line => Number(line.match(/^\s*(\d+)/)?.[1] || 0) > 65535)) {
        await alertNotice("Too long to renumber", "Renumbering in steps of 10 would take this program past 65535, the highest line number a numbered ST listing can hold.");
        return;
      }
      const tokens = sourceTokens(rebuilt, language, inlineAssemblyLanguage).filter(item => item.type === "keyword").reverse();
      let normalised = rebuilt;
      tokens.forEach(item => { normalised = `${normalised.slice(0, item.start)}${item.text.toUpperCase()}${normalised.slice(item.end)}`; });
      let verification = null;
      if (validateBasic) {
        try { verification = await validateBasic(normalised, textarea.value); }
        catch (error) { await alertNotice("The transformation was not applied", error.message || String(error), { danger: true }); return; }
      }
      const newStart = rebuiltPosition(selectionStart, lines, expansions, rebuiltLines);
      const newEnd = rebuiltPosition(selectionEnd, lines, expansions, rebuiltLines);
      refactorPlan = {
        mode: "refactor",
        before: textarea.value.split("\n"),
        preview: normalised.split("\n"),
        verification,
        after: { value: normalised, selectionStart: newStart, selectionEnd: newEnd, scrollTop, scrollLeft },
      };
      renderFolds();
    };
    const condense = async () => {
      if (language !== "basic" || textarea.readOnly || !packBasic) return;
      const lines = textarea.value.split("\n");
      const parsed = lines.map((line, index) => {
        const match = line.match(/^\s*(\d+)(?:\s+(.*))?$/);
        return match ? { index, number: Number(match[1]), body: match[2] || "", line } : null;
      });
      if (parsed.some((row, index) => lines[index].trim() && !row)) {
        await alertNotice("Condense needs a numbered listing", "Correct the unnumbered source lines first: condensing a partly numbered program cannot be done safely.");
        return;
      }
      const numbered = parsed.filter(Boolean);
      const assemblerLines = basicInlineAssemblerLines(textarea.value);
      if (new Set(numbered.map(row => row.number)).size !== numbered.length) {
        await alertNotice("Duplicate line numbers", "Condense cannot operate safely while BASIC line numbers are duplicated. Correct them first.");
        return;
      }
      if (numbered.some(row => basicHasDynamicDestination(row.body)) || numbered.some(row => basicHasSemanticErl(row.body))) {
        await alertNotice("Left for manual review", "This program uses a computed line destination, or uses ERL in program logic. Removing physical line numbers could change its behaviour, so no change has been made.");
        return;
      }
      const range = currentPhysicalLines();
      const noSelection = textarea.selectionStart === textarea.selectionEnd;
      const first = noSelection ? 0 : range.first;
      const last = noSelection ? lines.length - 1 : range.last;
      const targets = new Set(numbered.flatMap(row => basicDestinations(row.body).map(item => item.target)));
      const runs = [];
      const pieces = [];
      let index = 0;
      while (index < lines.length) {
        const row = parsed[index];
        if (index < first || index > last || !row || assemblerLines[index]) {
          pieces.push({ kind: "fixed", entries: [{ index, line: lines[index] }] });
          index += 1;
          continue;
        }
        if (!row.body.trim() && !targets.has(row.number)) { index += 1; continue; }
        const entries = [];
        while (index <= last) {
          const candidate = parsed[index];
          if (!candidate || assemblerLines[index]) break;
          if (!candidate.body.trim() && !targets.has(candidate.number)) { index += 1; continue; }
          if (entries.length && (targets.has(candidate.number) || basicCondenseBoundaryBefore(candidate.body))) break;
          entries.push(candidate);
          index += 1;
          if (basicCondenseBoundaryAfter(candidate.body)) break;
        }
        if (!entries.length) continue;
        const runIndex = runs.length;
        runs.push(entries.map(entry => entry.body));
        pieces.push({ kind: "run", runIndex, entries });
      }
      let packed;
      try { packed = await packBasic(runs); }
      catch (error) { await alertNotice("The transformation was not applied", error.message || String(error), { danger: true }); return; }
      if (!Array.isArray(packed) || packed.length !== runs.length) {
        await alertNotice("Condense did not complete", "The BASIC line packer returned an incomplete result, so the program has been left as it was.");
        return;
      }
      const output = [];
      const sourceMap = new Map();
      pieces.forEach(piece => {
        if (piece.kind === "fixed") {
          const outIndex = output.length;
          output.push(piece.entries[0].line);
          sourceMap.set(piece.entries[0].index, { outIndex, baseColumn: 0, sourceBodyStart: 0 });
          return;
        }
        let cursor = 0;
        for (const count of packed[piece.runIndex]) {
          const entries = piece.entries.slice(cursor, cursor + Number(count));
          if (!entries.length) continue;
          const numberPrefix = `${entries[0].number} `;
          const outIndex = output.length;
          output.push(`${numberPrefix}${entries.map(entry => entry.body).join(":")}`);
          let bodyOffset = 0;
          entries.forEach(entry => {
            const sourceBodyStart = entry.line.indexOf(entry.body);
            sourceMap.set(entry.index, { outIndex, baseColumn: numberPrefix.length + bodyOffset, sourceBodyStart });
            bodyOffset += entry.body.length + 1;
          });
          cursor += Number(count);
        }
      });
      const value = output.join("\n");
      if (value === textarea.value) {
        await alertNotice("Nothing to condense", "No physical lines in that selection can be condensed safely.");
        return;
      }
      let verification = null;
      if (validateBasic) {
        try { verification = await validateBasic(value, textarea.value); }
        catch (error) { await alertNotice("The transformation was not applied", error.message || String(error), { danger: true }); return; }
      }
      const mapPosition = position => {
        let mapping = sourceMap.get(position.line);
        if (!mapping) {
          const nearest = [...sourceMap.entries()].sort((left, right) => Math.abs(left[0] - position.line) - Math.abs(right[0] - position.line))[0];
          mapping = nearest?.[1] || { outIndex: 0, baseColumn: 0, sourceBodyStart: 0 };
        }
        const lineOffset = output.slice(0, mapping.outIndex).reduce((total, line) => total + line.length + 1, 0);
        const column = mapping.baseColumn + Math.max(0, position.column - mapping.sourceBodyStart);
        return lineOffset + Math.min(column, output[mapping.outIndex]?.length || 0);
      };
      const selectionStart = sourcePosition(textarea.selectionStart);
      const selectionEnd = sourcePosition(textarea.selectionEnd);
      refactorPlan = {
        mode: "condense",
        before: textarea.value.split("\n"),
        preview: output,
        verification,
        after: {
          value,
          selectionStart: mapPosition(selectionStart),
          selectionEnd: mapPosition(selectionEnd),
          scrollTop: textarea.scrollTop,
          scrollLeft: textarea.scrollLeft,
        },
      };
      renderFolds();
    };
    const toggleComment = () => {
      if (language !== "basic" || textarea.readOnly) return;
      showOriginalView();
      const start = textarea.value.lastIndexOf("\n", Math.max(0, textarea.selectionStart - 1)) + 1;
      const followingBreak = textarea.value.indexOf("\n", textarea.selectionEnd);
      const end = followingBreak < 0 ? textarea.value.length : followingBreak;
      const selectedLines = textarea.value.slice(start, end).split("\n");
      const nonEmpty = selectedLines.filter(line => line.trim());
      // A numbered listing comments with REM after the line number; GFA
      // BASIC source comments with an apostrophe at the start of the line.
      const remove = nonEmpty.length > 0 && nonEmpty.every(line => /^\s*\d+\s+REM(?:\s|$)/i.test(line) || /^\s*'/.test(line));
      const replacement = selectedLines.map(line => {
        if (!line.trim()) return line;
        if (remove) return /^\s*\d+\s+REM/i.test(line) ? line.replace(/^(\s*\d+\s+)REM\s?/i, "$1") : line.replace(/^(\s*)'\s?/, "$1");
        return /^\s*\d+\s/.test(line) ? line.replace(/^(\s*\d+\s+)/, "$1REM ") : line.replace(/^(\s*)/, "$1' ");
      }).join("\n");
      textarea.setRangeText(replacement, start, end, "select");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      textarea.focus();
      historyEntry(remove ? "Removed comments" : "Added comments", `${selectedLines.length} line${selectedLines.length === 1 ? "" : "s"}`);
    };
    const updateMenus = () => {
      root.querySelector('[data-editor-action="help-problems"] span')?.replaceChildren(document.createTextNode(`Problems (${state.issues.length})`));
      root.querySelector('[data-editor-action="help-symbols"] span')?.replaceChildren(document.createTextNode(`Document symbols (${state.symbols.length})`));
    };
    const render = () => {
      dismissHoverHelp(textarea.ownerDocument);
      state = { tokens: sourceTokens(textarea.value, language, inlineAssemblyLanguage), issues: diagnostics(textarea.value, language, dialect), symbols: symbols(textarea.value, language), blocks: foldBlocks(textarea.value, language) };
      const html = highlightedHtml(textarea.value, state.tokens);
      visual.querySelector("pre").innerHTML = html;
      hit.querySelector("pre").innerHTML = html;
      hit.querySelectorAll(".code-help-token").forEach(element => {
        const tokenLanguage = element.dataset.helpLanguage || language;
        const tokenStart = Number(element.dataset.tokenStart);
        const tokenEnd = Number(element.dataset.tokenEnd);
        const contextualHelp = sourceContextHelp(textarea.value, tokenLanguage, tokenStart, tokenEnd, element.dataset.helpKey, targetProfile);
        attachTooltip(root, tokenLanguage, element, element.dataset.helpKey, contextualHelp);
        element.addEventListener("pointerdown", event => {
          event.preventDefault();
          textarea.focus();
          textarea.setSelectionRange(tokenStart, tokenEnd);
          textarea.dispatchEvent(new Event("click", { bubbles: true }));
        });
      });
      syncScroll();
      updateMenus();
      renderStructureGuides();
      renderFolds();
    };
    const schedule = () => { clearTimeout(timer); timer = setTimeout(render, 80); };
    textarea.addEventListener("input", schedule);
    textarea.addEventListener("scroll", syncScroll, { passive: true });
    const updateCursorContext = () => { updateMenus(); renderStructureGuides(); };
    textarea.addEventListener("selectionchange", updateCursorContext);
    textarea.addEventListener("select", updateCursorContext);
    textarea.addEventListener("click", updateCursorContext);
    textarea.addEventListener("keyup", updateCursorContext);
    textarea.addEventListener("keydown", event => {
      if (event.key === "F1") { event.preventDefault(); helpAtCursor(); }
      else if (event.key === " " && (event.ctrlKey || event.metaKey)) { event.preventDefault(); showCompletions(); }
    });
    render();
    return { overview, helpAtCursor, showProblems, showSymbols, showCompletions, showCustom, findReferences, renameSymbol, showOutline, showHistory, compareWith, verifyRoundTrip, reference, goToLine, normaliseCommands, toggleComment, lineOperation, formatCode, condense, refactor, undo, redo, expandAll, collapseAll, toggleAll, toggleStructureGuides, setStructureGuideSize, showOriginalView, closePanel, refresh: render, recordHistory: historyEntry, state: () => state, history: () => pendingHistory };
  }

  function enhanceDisassembly({ root, report }) {
    if (!root) return null;
    const language = report.architecture || "68000";
    const panel = document.createElement("section");
    panel.className = "code-intelligence-drawer";
    panel.hidden = true;
    root.insertBefore(panel, root.querySelector(".editor-status"));
    const labelElements = [...root.querySelectorAll(".disassembly-label")];
    const labels = labelElements.map(element => ({ name: element.querySelector("span:last-child")?.textContent.replace(/:$/, "") || "Label", offset: Number(element.nextElementSibling?.dataset.offset || 0) }));
    const foldedLabels = new Set();
    const foldBlocks = labelElements.map((element, index) => {
      const rows = [];
      let sibling = element.nextElementSibling;
      while (sibling && !sibling.classList.contains("disassembly-label")) {
        if (sibling.classList.contains("disassembly-source-line")) rows.push(sibling);
        sibling = sibling.nextElementSibling;
      }
      return { id: String(index), element, rows, label: labels[index].name };
    }).filter(block => block.rows.length > 0);
    const renderFolds = () => {
      dismissHoverHelp(root.ownerDocument);
      const canFold = foldBlocks.length > 0;
      const foldAll = root.querySelector('[data-disassembly-action="fold-toggle-all"]');
      if (foldAll) {
        foldAll.disabled = !canFold;
        foldAll.querySelector("span").textContent = foldedLabels.size ? "Expand all labelled blocks" : "Collapse all labelled blocks";
      }
      foldBlocks.forEach(block => {
        const collapsed = foldedLabels.has(block.id);
        const cell = block.element.querySelector(".disassembly-fold-cell");
        cell.innerHTML = `<button type="button" class="code-fold-toggle" aria-expanded="${collapsed ? "false" : "true"}" title="${collapsed ? "Expand" : "Collapse"} ${esc(block.label)}">${collapsed ? "+" : "−"}</button>`;
        cell.querySelector("button").onclick = () => {
          if (collapsed) foldedLabels.delete(block.id);
          else foldedLabels.add(block.id);
          renderFolds();
        };
        block.element.classList.toggle("fold-collapsed", collapsed);
        block.rows.forEach(row => { row.hidden = collapsed; });
      });
    };
    const expandAll = () => { foldedLabels.clear(); renderFolds(); };
    const collapseAll = () => { foldBlocks.forEach(block => foldedLabels.add(block.id)); renderFolds(); };
    const toggleAll = () => foldedLabels.size ? expandAll() : collapseAll();
    const commands = new Set();
    const commandHelp = new Map();
    root.querySelectorAll(".disassembly-instruction").forEach((element, index) => {
      const row = report.rows[index] || { mnemonic: element.textContent.split(/\s+/)[0], operand: element.textContent.replace(/^\S+\s*/, "") };
      const mnemonic = normaliseHelpKey(row.mnemonic) || "DATA";
      const contextualHelp = disassemblyInstructionHelp(row, language);
      commands.add(mnemonic);
      if (!commandHelp.has(mnemonic)) commandHelp.set(mnemonic, contextualHelp);
      element.classList.add("code-help-token", "code-token-keyword");
      element.dataset.helpKey = mnemonic;
      element.setAttribute("aria-label", element.getAttribute("title") || element.textContent);
      element.removeAttribute("title");
      attachTooltip(root, language, element, mnemonic, contextualHelp);
    });
    root.querySelectorAll(".disassembly-comment").forEach(element => {
      const text = element.textContent;
      const pattern = new RegExp(`(?<![A-Za-z0-9_])(${Object.keys(SYSTEM_CALL_HELP).concat(Object.keys(SYSTEM_VARIABLE_HELP)).map(name => name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})(?![A-Za-z0-9_])`, "gi");
      let cursor = 0;
      const chunks = [];
      for (const match of text.matchAll(pattern)) {
        chunks.push(esc(text.slice(cursor, match.index)), `<span class="code-help-token code-token-api" data-help-key="${match[1].toUpperCase()}">${esc(match[1])}</span>`);
        commands.add(match[1].toUpperCase());
        cursor = match.index + match[1].length;
      }
      if (!chunks.length) return;
      chunks.push(esc(text.slice(cursor)));
      element.innerHTML = chunks.join("");
      element.removeAttribute("title");
      element.querySelectorAll("[data-help-key]").forEach(tokenElement => attachTooltip(root, language, tokenElement, tokenElement.dataset.helpKey));
    });
    renderFolds();
    const show = (title, body) => {
      panel.hidden = false;
      panel.innerHTML = `<header><div><small>CODE-AWARE HELP</small><h3>${esc(title)}</h3></div><button type="button" class="code-drawer-close" aria-label="Close code help">×</button></header><div class="code-drawer-body">${body}</div>`;
      panel.querySelector(".code-drawer-close").onclick = () => { panel.hidden = true; };
      panel.querySelectorAll("[data-code-help]").forEach(button => button.onclick = () => show(button.dataset.codeHelp, helpMarkup(commandHelp.get(button.dataset.codeHelp) || lookup(language, button.dataset.codeHelp))));
      panel.querySelectorAll("[data-disassembly-offset]").forEach(button => button.onclick = () => root.querySelector(`.disassembly-source-line[data-offset="${button.dataset.disassemblyOffset}"]`)?.scrollIntoView({ block: "center" }));
    };
    const overview = () => show(`${languageName(language)} overview`, `<div class="code-overview"><p>This view contains <strong>${report.rows.length.toLocaleString()} decoded instructions or data records</strong>, <strong>${labels.length.toLocaleString()} labels</strong> and <strong>${report.strings.length.toLocaleString()} readable strings</strong>.</p><p>Hover a highlighted mnemonic, TOS call or system variable for syntax, processor requirements and calling conventions. Disassembly remains read-only because data can resemble valid instructions.</p><h4>Recognised operations</h4><div class="code-command-chips">${[...commands].sort().map(key => `<button type="button" data-code-help="${key}">${key}</button>`).join("")}</div></div>`);
    const reference = () => show(`${languageName(language)} reference`, `<div class="code-reference-list">${[...new Set([...commands, ...Object.keys(INLINE_ASSEMBLER_HELP), ...Object.keys(ASM_HELP), ...Object.keys(SYSTEM_CALL_HELP)])].sort().map(key => `<button type="button" data-code-help="${key}">${key}</button>`).join("")}</div>`);
    const showSymbols = () => show("Disassembly symbols", labels.length ? `<div class="code-symbol-list">${labels.map(item => `<button type="button" data-disassembly-offset="${item.offset}"><b>label</b><span>${esc(item.name)}</span></button>`).join("")}</div>` : '<p class="code-empty-message">No labels were discovered in this range.</p>');
    return { overview, reference, showSymbols, showCustom: show, expandAll, collapseAll, toggleAll, helpAtCursor: overview, showProblems: () => show("Disassembly cautions", '<p class="code-empty-message">No writable source diagnostics apply. Treat unknown opcodes, unreachable regions and embedded data as cautions rather than automatic errors.</p>') };
  }

  return { enhance, enhanceDisassembly, lookup, contextHelp: sourceContextHelp, diagnostics, describeAddress, processorFor, configuredPlatform, M68K_TARGETS, MACHINE_PROCESSORS };
})();
