"""Keyboard, keywords and screen-reading for omse-ai.

Every table here is read out of the 48K ROM itself, not transcribed:
  0x0205 MAIN-KEYS   the 40 keys in matrix order: index = (4-bit)*8 + (7-row)
  0x022C E-UNSHIFT   E mode + letter          (READ BIN LPRINT DATA TAN ...)
  0x0246 EXT-SHIFT   E mode + SS/CS + letter  (~ BRIGHT PAPER \\ ATN { } ...)
  0x026A SYM-CODES   SS + letter, in K, L or C mode (STOP * ? STEP >= TO THEN ...)
  0x0284 E-DIGITS    E mode + SS + digit      (FORMAT DEF FN FN LINE OPEN# ...)
  0x0095 TKN-TABLE   keyword spellings, tokens 0xA5 (RND) to 0xFF (COPY)
K mode + letter gives token letter + 0xA5 (A = NEW 0xE6 ... Z = COPY 0xFF).
"""

# Matrix: (half-row, bit).  Row 0 is port 0xFEFE (CS Z X C V) ... row 7 is
# 0x7FFE (SPACE SS M N B).
ROWS = [
    ['CS', 'Z', 'X', 'C', 'V'],
    ['A', 'S', 'D', 'F', 'G'],
    ['Q', 'W', 'E', 'R', 'T'],
    ['1', '2', '3', '4', '5'],
    ['0', '9', '8', '7', '6'],
    ['P', 'O', 'I', 'U', 'Y'],
    ['ENTER', 'L', 'K', 'J', 'H'],
    ['SPACE', 'SS', 'M', 'N', 'B'],
]

ALIASES = {
    'SYM': 'SS', 'SYMBOL': 'SS', 'SYMSHIFT': 'SS', 'CAPS': 'CS', 'SHIFT': 'CS',
    'CAPSSHIFT': 'CS', 'RETURN': 'ENTER', 'ENT': 'ENTER', 'SPC': 'SPACE', ' ': 'SPACE',
    'BREAK': None,  # handled in chord()
}

# Chords that have names on the real keyboard
NAMED_CHORDS = {
    'BREAK': ['CS', 'SPACE'], 'DELETE': ['CS', '0'], 'EDIT': ['CS', '1'],
    'CAPSLOCK': ['CS', '2'], 'TRUEVIDEO': ['CS', '3'], 'INVVIDEO': ['CS', '4'],
    'LEFT': ['CS', '5'], 'DOWN': ['CS', '6'], 'UP': ['CS', '7'], 'RIGHT': ['CS', '8'],
    'GRAPHICS': ['CS', '9'], 'EXTEND': ['CS', 'SS'],
}

UNICODE_BLOCKS = ["⠀", "▝", "▘", "▀", "▗", "▐", "▚", "▜", "▖", "▞", "▌", "▛", "▄", "▟", "▙", "█"]
UDG_CHARS = [chr(0x24B6 + i) for i in range(21)]   # Ⓐ..Ⓤ, as speccy-basic writes UDGs


class KeyTables:
    def __init__(self, rom):
        self.rom = rom
        self.MATRIX = {name: (r, b) for r, row in enumerate(ROWS) for b, name in enumerate(row)}
        # main code for each key, from MAIN-KEYS
        self.CODE = {}
        for name, (r, b) in self.MATRIX.items():
            self.CODE[name] = rom[0x0205 + (4 - b) * 8 + (7 - r)]
        letters = [chr(ord('A') + i) for i in range(26)]
        digits = [str(d) for d in range(10)]
        # token spellings
        toks, cur, a = [], '', 0x0095
        while len(toks) < 92:
            c = rom[a]
            a += 1
            cur += chr(c & 0x7F)
            if c & 0x80:
                toks.append(cur.strip())
                cur = ''
        self.TOKEN = {0xA5 + i: t for i, t in enumerate(toks[1:])}   # code -> 'PRINT'
        self.CODE_FOR = {t: c for c, t in self.TOKEN.items()}        # 'PRINT' -> code
        # ways to produce each code, by mode
        self.k_letter = {0xA5 + ord(L): L for L in letters}           # K mode: A -> NEW
        self.sym_letter = {rom[0x026A + i]: L for i, L in enumerate(letters)}
        self.e_letter = {rom[0x022C + i]: L for i, L in enumerate(letters)}
        self.e_sym_letter = {rom[0x0246 + i]: L for i, L in enumerate(letters)}
        self.e_sym_digit = {rom[0x0284 + i]: d for i, d in enumerate(digits)}
        # SS + digit, by the ROM's arithmetic in K-KLC-DGT
        self.sym_digit = {ord(c): d for c, d in zip("_!@#$%&'()", digits)}
        # G mode: 1..7 = 0x81..0x87, 8 = 0x80; with CS the inverse (0x8F - n)
        self.g_digit = {}
        for n in range(1, 8):
            self.g_digit[0x80 + n] = [str(n)]
            self.g_digit[0x8F - n] = ['CS', str(n)]
        self.g_digit[0x80] = ['8']
        self.g_digit[0x8F] = ['CS', '8']

    # -- names and chords --------------------------------------------------
    def keyname(self, n):
        k = str(n).upper().replace(' ', '') if n != ' ' else 'SPACE'
        k = ALIASES.get(k, k) or k
        if k not in self.MATRIX:
            raise KeyError(f'no Spectrum key called {n!r}')
        return k

    def chord(self, keys):
        """'SS+P' / 'CS SPACE' / ['CS','5'] / 'BREAK' / 'LEFT' -> ['SS','P']"""
        if isinstance(keys, (list, tuple)):
            return [self.keyname(k) for k in keys]
        s = str(keys)
        if s.upper() in NAMED_CHORDS:
            return list(NAMED_CHORDS[s.upper()])
        if s == ' ':
            return ['SPACE']
        parts = [p for p in s.replace('+', ' ').split(' ') if p]
        return [self.keyname(p) for p in parts]

    def main_code(self, names):
        """The code KSTATE will hold for this chord (CS+SS alone = 0x0E)."""
        others = [n for n in names if n not in ('CS', 'SS')]
        if others:
            return self.CODE[others[0]]
        if 'CS' in names and 'SS' in names:
            return 0x0E
        return None

    # -- characters ----------------------------------------------------------
    def char_code(self, ch):
        """A Unicode character as a Spectrum character code."""
        if ch == '£':
            return 0x60
        if ch == '©':
            return 0x7F
        if ch == '↑':
            return 0x5E
        if ch in UNICODE_BLOCKS:
            return 0x80 + UNICODE_BLOCKS.index(ch)
        if ch in UDG_CHARS:
            return 0x90 + UDG_CHARS.index(ch)
        o = ord(ch)
        if o >= 128:
            raise ValueError(f'no Spectrum character for {ch!r}')
        return o

    def strokes_for(self, code, zx):
        """Chords that enter `code` from the editor's current mode."""
        mode = zx.mode()
        pre = []
        if mode == 'E':
            pre, mode = ['EXTEND'], 'L'      # leave E mode (goes back to K/L)
        elif mode == 'G':
            pre, mode = ['GRAPHICS'], 'L'
        if 0x80 <= code <= 0x8F:
            return pre + ['GRAPHICS', self.g_digit[code], 'GRAPHICS']
        if 0x90 <= code <= 0xA4:
            return pre + ['GRAPHICS', chr(ord('A') + code - 0x90), 'GRAPHICS']
        if pre:
            # after leaving E/G the mode may be K or L; decide on the next call
            return pre + self._strokes_plain(code, zx, None)
        return self._strokes_plain(code, zx, mode)

    def _strokes_plain(self, code, zx, mode):
        if mode is None:
            # we don't know yet: prefer strokes that work in any of K/L/C
            mode = '?'
        ch = chr(code)
        if code == 0x20:
            return ['SPACE']
        if '0' <= ch <= '9':
            return [ch]
        if 'a' <= ch <= 'z':
            if mode == 'K':
                raise ValueError(f'cannot type letter {ch!r} in K mode (it would be a keyword)')
            if mode == 'C':
                return ['CAPSLOCK', ch.upper()]
            return [ch.upper()]
        if 'A' <= ch <= 'Z' and code < 0x80:
            if mode == 'K':
                raise ValueError(f'cannot type letter {ch!r} in K mode (it would be a keyword)')
            if mode == 'C':
                return [ch]
            return ['CS+' + ch]
        if mode == 'K' and code in self.k_letter:
            return [self.k_letter[code]]
        if code in self.sym_letter:
            return ['SS+' + self.sym_letter[code]]
        if code in self.sym_digit:
            return ['SS+' + self.sym_digit[code]]
        if code in self.e_letter:
            return ['EXTEND', self.e_letter[code]]
        if code in self.e_sym_letter:
            return ['EXTEND', 'SS+' + self.e_sym_letter[code]]
        if code in self.e_sym_digit:
            return ['EXTEND', 'SS+' + self.e_sym_digit[code]]
        if code in self.k_letter:
            raise ValueError(f'{self.TOKEN[code]} can only be typed in K mode '
                             f'(start of a statement), and the cursor is in {mode}')
        raise ValueError(f'no way to type code {code:#04x}')

    # -- tokens <-> text -----------------------------------------------------
    def detokenize(self, data):
        """Spectrum bytes -> readable text (keywords spelled out, number forms
        dropped, control codes shown as {INK 2}, {AT 3,4} ...)."""
        out = []
        i = 0
        ctl = {0x10: 'INK', 0x11: 'PAPER', 0x12: 'FLASH', 0x13: 'BRIGHT', 0x14: 'INVERSE', 0x15: 'OVER'}
        while i < len(data):
            b = data[i]
            if b == 0x0E and i + 5 < len(data) + 1:
                i += 6
                continue
            if b == 0x0D:
                out.append('\n')
            elif b == 0x06:
                out.append('\t')
            elif b in ctl and i + 1 < len(data):
                out.append('{%s %d}' % (ctl[b], data[i + 1]))
                i += 1
            elif b in (0x16, 0x17) and i + 2 < len(data):
                out.append('{%s %d,%d}' % ('AT' if b == 0x16 else 'TAB', data[i + 1], data[i + 2]))
                i += 2
            elif b >= 0xA5:
                word = self.TOKEN[b]
                if out and not out[-1].endswith((' ', '\n')):
                    out.append(' ')
                out.append(word + ' ')
            elif 0x90 <= b <= 0xA4:
                out.append(UDG_CHARS[b - 0x90])
            elif 0x80 <= b <= 0x8F:
                out.append(UNICODE_BLOCKS[b - 0x80])
            elif b == 0x60:
                out.append('£')
            elif b == 0x7F:
                out.append('©')
            elif b == 0x5E:
                out.append('↑')
            elif 0x20 <= b < 0x80:
                out.append(chr(b))
            else:
                out.append('{%02x}' % b)
            i += 1
        return ''.join(out)


# Spellings people type that the ROM spells differently
KEYWORD_ALIASES = {'GOTO': 'GO TO', 'GOSUB': 'GO SUB', 'OPEN#': 'OPEN #', 'CLOSE#': 'CLOSE #',
                   'DEFFN': 'DEF FN', 'RANDOMISE': 'RANDOMIZE'}


def tokenize_line(text, kt):
    """Split a line of BASIC (as you'd write it: '10 PRINT AT 3,4;"Hi"') into
    Spectrum codes: keywords (UPPERCASE only) become tokens, everything else
    stays a character.  Nothing inside quotes or after REM is a keyword.
    Spaces next to keywords are dropped (the ROM draws its own)."""
    spell = {}
    for code, word in kt.TOKEN.items():
        spell[word] = code
    for alias, word in KEYWORD_ALIASES.items():
        spell[alias] = kt.CODE_FOR[word]
    words = sorted(spell, key=len, reverse=True)

    def boundary_ok(s, i, w):
        # alphabetic keywords must not be glued to letters/digits either side
        if w[0].isalpha() and i > 0 and (s[i - 1].isalnum() or s[i - 1] == '$'):
            return False
        j = i + len(w)
        if w[-1].isalpha() and j < len(s) and (s[j].isalnum() or s[j] == '$'):
            return False
        return True

    out = []
    i, n = 0, len(text)
    in_quotes = False
    rem = False
    last_was_token = False
    # the line number, if any
    while i < n and text[i] == ' ':
        i += 1
    while i < n and text[i].isdigit():
        out.append(ord(text[i]))
        i += 1
    if out:
        last_was_token = True     # swallow spaces after the line number
    while i < n:
        c = text[i]
        if rem or in_quotes:
            if c == '"' and not rem:
                in_quotes = False
            out.append(kt.char_code(c))
            i += 1
            continue
        if c == ' ':
            # drop spaces around keywords
            j = i
            while j < n and text[j] == ' ':
                j += 1
            nxt_is_kw = any(text.startswith(w, j) and boundary_ok(text, j, w) for w in words)
            if not (last_was_token or nxt_is_kw) and j < n:
                out.extend([0x20] * (j - i))
            i = j
            continue
        if c == '"':
            in_quotes = True
            out.append(0x22)
            last_was_token = False
            i += 1
            continue
        for w in words:
            if text.startswith(w, i) and boundary_ok(text, i, w):
                code = spell[w]
                out.append(code)
                i += len(w)
                last_was_token = True
                if code == kt.CODE_FOR['REM']:
                    rem = True
                    # one space after REM is the ROM's; drop it
                    if i < n and text[i] == ' ':
                        i += 1
                break
        else:
            out.append(kt.char_code(c))
            last_was_token = False
            i += 1
    return out


def screen_text(zx, udg_as=None):
    """Read the character screen: each 8x8 cell matched against the current
    font (CHARS sysvar), the UDGs and the block graphics, in either polarity."""
    mem = zx.mem
    chars = (mem[23606] | (mem[23607] << 8)) + 256
    udg = mem[23675] | (mem[23676] << 8)
    glyphs = {}
    for c in range(32, 128):
        g = bytes(mem[(chars + (c - 32) * 8 + k) & 0xFFFF] for k in range(8))
        ch = {0x60: '£', 0x7F: '©', 0x5E: '↑'}.get(c, chr(c))
        glyphs.setdefault(g, ch)
    for u in range(21):
        g = bytes(mem[(udg + u * 8 + k) & 0xFFFF] for k in range(8))
        glyphs.setdefault(g, udg_as or UDG_CHARS[u])
    for b in range(16):
        top = (0x0F if b & 1 else 0) | (0xF0 if b & 2 else 0)
        bot = (0x0F if b & 4 else 0) | (0xF0 if b & 8 else 0)
        g = bytes([top] * 4 + [bot] * 4)
        glyphs.setdefault(g, UNICODE_BLOCKS[b] if b else ' ')
    lines = []
    for row in range(24):
        s = []
        for col in range(32):
            base = 0x4000 | ((row & 0x18) << 8) | ((row & 7) << 5) | col
            g = bytes(mem[base + (k << 8)] for k in range(8))
            ch = glyphs.get(g)
            if ch is None:
                ch = glyphs.get(bytes(255 - x for x in g))
            s.append(ch if ch is not None else '·')
        lines.append(''.join(s).rstrip())
    return '\n'.join(lines)
