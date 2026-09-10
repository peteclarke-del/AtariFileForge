(() => {
  "use strict";

  // GEMDOS keeps one attribute byte per directory entry. Each bit means what
  // it says, none is inverted, and the letters here follow the bit order from
  // the bottom: r read-only ($01), h hidden ($02), s system ($04), v volume
  // label ($08), d subdirectory ($10), a archive ($20). A normal file that has
  // been written since it was last backed up reads "-----a"; an ordinary
  // directory reads "----d-".
  const ATTRIBUTE_LETTERS = "rhsvda";
  const ATTRIBUTE_MASKS = Object.freeze({ r: 0x01, h: 0x02, s: 0x04, v: 0x08, d: 0x10, a: 0x20 });
  const ATTRIBUTE_MASK = 0x3F;

  const isLetterForm = text => (
    text.length === ATTRIBUTE_LETTERS.length
    && [...text].every((character, index) => character === "-" || character === ATTRIBUTE_LETTERS[index])
  );

  // Accepts the six-letter form, a number, or a hexadecimal string written
  // with a 0x, $ or & prefix. Bare digits are decimal, because that is how an
  // attribute is shown next to a listing.
  function parseAttributes(value) {
    if (typeof value === "number" && Number.isFinite(value)) return (value & ATTRIBUTE_MASK) >>> 0;
    if (value && typeof value === "object" && !Array.isArray(value)) return attributeValue(value);
    const text = String(value ?? "").trim();
    if (!text) return null;
    const lowered = text.toLowerCase();
    if (isLetterForm(lowered)) {
      let parsed = 0;
      [...lowered].forEach(character => { if (character !== "-") parsed |= ATTRIBUTE_MASKS[character]; });
      return parsed;
    }
    const hex = text.match(/^(?:0x|\$|&h?)([0-9a-f]{1,2})$/i);
    if (hex) return Number.parseInt(hex[1], 16) & ATTRIBUTE_MASK;
    const decimal = text.match(/^\d{1,3}$/);
    return decimal ? Number.parseInt(decimal[0], 10) & ATTRIBUTE_MASK : null;
  }

  function attributeFlags(value) {
    const parsed = parseAttributes(value) ?? 0;
    const flags = {};
    for (const letter of ATTRIBUTE_LETTERS) flags[letter] = (parsed & ATTRIBUTE_MASKS[letter]) !== 0;
    return flags;
  }

  // Six fixed characters, a dash for every clear bit, so a column of them
  // lines up in a listing.
  function formatAttributes(value) {
    const flags = value && typeof value === "object" && !Array.isArray(value) ? value : attributeFlags(value);
    return [...ATTRIBUTE_LETTERS].map(letter => (flags[letter] ? letter : "-")).join("");
  }

  function attributeValue(text) {
    if (text && typeof text === "object" && !Array.isArray(text)) {
      let value = 0;
      for (const letter of ATTRIBUTE_LETTERS) if (text[letter]) value |= ATTRIBUTE_MASKS[letter];
      return value;
    }
    return parseAttributes(text) ?? 0;
  }

  function attributeHex(value) {
    return `0x${attributeValue(value).toString(16).toUpperCase().padStart(2, "0")}`;
  }

  // A GEMDOS directory entry stamps a file with two words: the date counts
  // years from 1980 in bits 15-9, the month in 8-5 and the day in 4-0; the
  // time holds hours in bits 15-11, minutes in 10-5 and seconds divided by
  // two in 4-0, so a stamp is only ever accurate to two seconds.
  function parseDatestamp(value) {
    if (value && typeof value === "object" && Number.isFinite(value.date)) {
      return { date: value.date & 0xFFFF, time: (value.time || 0) & 0xFFFF };
    }
    const text = String(value ?? "").trim();
    const match = text.match(/^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?/);
    if (!match) return null;
    const year = Number(match[1]);
    const month = Number(match[2]);
    const day = Number(match[3]);
    if (year < 1980 || year > 2107 || month < 1 || month > 12 || day < 1 || day > 31) return null;
    const hours = Number(match[4] || 0);
    const minutes = Number(match[5] || 0);
    const seconds = Number(match[6] || 0);
    if (hours > 23 || minutes > 59 || seconds > 59) return null;
    return {
      date: ((year - 1980) << 9) | (month << 5) | day,
      time: (hours << 11) | (minutes << 5) | (seconds >> 1),
    };
  }

  const two = number => String(number).padStart(2, "0");

  function formatDatestamp(date, time) {
    const stamp = date && typeof date === "object" ? date : { date, time };
    const dateWord = Number(stamp.date);
    if (!Number.isFinite(dateWord)) return "";
    const timeWord = Number.isFinite(Number(stamp.time)) ? Number(stamp.time) : 0;
    const year = 1980 + ((dateWord >> 9) & 0x7F);
    const month = (dateWord >> 5) & 0x0F;
    const day = dateWord & 0x1F;
    const hours = (timeWord >> 11) & 0x1F;
    const minutes = (timeWord >> 5) & 0x3F;
    const seconds = (timeWord & 0x1F) * 2;
    return `${year}-${two(month)}-${two(day)}T${two(hours)}:${two(minutes)}:${two(seconds)}`;
  }

  window.AtariMetadata = Object.freeze({
    ATTRIBUTE_LETTERS,
    ATTRIBUTE_MASKS,
    attributeFlags,
    attributeHex,
    attributeValue,
    formatAttributes,
    parseAttributes,
    parseDatestamp,
    formatDatestamp,
    // The names app.js still imports. They now read the attribute byte, so
    // the callers that build "hsparwed" letters must move to the six-letter
    // attribute form.
  });
})();
