window.AtariFormats = (() => {
  // Extensions are a hint for the file picker and for drag-and-drop. The
  // backend identifies every image from its bytes, so a renamed file is
  // recognised correctly and a wrongly named one is refused with a reason.
  const imageExtensions = [
    // Floppy containers: plain sectors, Magic Shadow Archiver, FastCopy Pro
    // and Pasti.
    "st", "msa", "dim", "stx",
    // Gotek, HxC and flux captures.
    "hfe", "scp", "ipf",
    // TOS, cartridge and expansion ROMs.
    "rom", "tos",
    // Hard-disk images, partitioned or bare. ".img" and ".bin" are ambiguous
    // with a ROM dump, so only the bytes decide which one arrived.
    "img", "hd", "ahd", "acsi", "ide", "raw", "bin",
    // A good deal of Falcon and TT material was published on CD.
    "iso", "cdr"
  ];
  const imagePattern = new RegExp(`\\.(${imageExtensions.join("|")})$`, "i");
  // A floppy-sized volume, whatever container it arrived in.
  const floppyPattern = /\.(st|msa|dim|stx|hfe|scp|ipf)$/i;
  const archivePattern = /\.(zip|lzh|lha|arc)$/i;
  // Anything that may hold a GEMDOS volume, floppy or hard drive.
  const gemdosPattern = /\.(st|msa|dim|stx|hfe|scp|img|hd|ahd|acsi|ide|raw|bin|zip|lzh|lha)$/i;
  //: A CD is a read-only container, browsed rather than written to.
  const isoPattern = /\.(iso|cdr)$/i;

  return {
    accept: imageExtensions.map(extension => `.${extension}`).concat(".geo", ".zip", ".lzh", ".lha").join(","),
    // A bare hard-disk image carries no geometry of its own, so it travels
    // with a small ".geo" sidecar that records cylinders, heads and sectors.
    isDescriptor: name => /\.geo$/i.test(name),
    isArchive: name => archivePattern.test(name),
    isFloppyImage: name => floppyPattern.test(name) || archivePattern.test(name),
    isImage: name => imagePattern.test(name),
    isIsoImage: name => isoPattern.test(name),
    isImportableImage: name => imagePattern.test(name) || archivePattern.test(name),
    isPotentialGemdosImage: name => gemdosPattern.test(name),
    isRomImage: name => /\.(rom[0-3]?|tos|cart)$/i.test(name),
    stem: name => String(name).replace(/\.[^.]+$/, "")
  };
})();
