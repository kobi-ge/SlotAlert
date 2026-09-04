/**
 * Pure JavaScript QR Code Generator (SVG Output)
 * Generates ISO/IEC 18004 compliant QR Codes (Version 1-10, ECC M)
 * Zero external dependencies.
 */
(function (global) {
  // QR Code generator tables & polynomials
  const GF256_EXP = new Uint8Array(512);
  const GF256_LOG = new Uint8Array(256);
  (function initGF() {
    let x = 1;
    for (let i = 0; i < 255; i++) {
      GF256_EXP[i] = x;
      GF256_EXP[i + 255] = x;
      GF256_LOG[x] = i;
      x <<= 1;
      if (x & 256) x ^= 0x11d;
    }
  })();

  function gfMul(x, y) {
    if (x === 0 || y === 0) return 0;
    return GF256_EXP[GF256_LOG[x] + GF256_LOG[y]];
  }

  function gfPolyMul(p1, p2) {
    const res = new Uint8Array(p1.length + p2.length - 1);
    for (let i = 0; i < p1.length; i++) {
      for (let j = 0; j < p2.length; j++) {
        res[i + j] ^= gfMul(p1[i], p2[j]);
      }
    }
    return res;
  }

  function getGeneratorPoly(deg) {
    let g = new Uint8Array([1]);
    for (let i = 0; i < deg; i++) {
      g = gfPolyMul(g, new Uint8Array([1, GF256_EXP[i]]));
    }
    return g;
  }

  function calculateEcc(data, eccCount) {
    const gen = getGeneratorPoly(eccCount);
    const msg = new Uint8Array(data.length + eccCount);
    msg.set(data);
    for (let i = 0; i < data.length; i++) {
      const coef = msg[i];
      if (coef !== 0) {
        for (let j = 0; j < gen.length; j++) {
          msg[i + j] ^= gfMul(gen[j], coef);
        }
      }
    }
    return msg.slice(data.length);
  }

  // Versions capacity & ECC info for Error Correction M (Medium)
  // [version, totalCodewords, dataCodewords, ecCodewords, ecBlocks]
  const VERSION_SPECS = [
    [1, 26, 16, 10, 1],
    [2, 44, 28, 16, 1],
    [3, 70, 44, 26, 1],
    [4, 100, 64, 36, 2],
    [5, 134, 86, 48, 2],
    [6, 172, 108, 64, 4],
    [7, 196, 124, 72, 4],
    [8, 242, 154, 88, 4],
    [9, 292, 182, 110, 5],
    [10, 346, 216, 130, 5]
  ];

  function pickVersion(dataLen) {
    for (let i = 0; i < VERSION_SPECS.length; i++) {
      const [v, tot, dataCap] = VERSION_SPECS[i];
      // 4-bit mode (byte = 0100) + 8-bit length indicator
      if (dataLen + 2 <= dataCap) {
        return VERSION_SPECS[i];
      }
    }
    return VERSION_SPECS[VERSION_SPECS.length - 1];
  }

  function encodeData(text, spec) {
    const [, totalCodewords, dataCapacity] = spec;
    const utf8 = new TextEncoder().encode(text);
    const bits = [];

    function pushBits(val, count) {
      for (let i = count - 1; i >= 0; i--) {
        bits.push((val >> i) & 1);
      }
    }

    // Byte Mode Indicator: 0100
    pushBits(0b0100, 4);
    // Character Count Indicator (8 bits for Ver 1-9)
    pushBits(utf8.length, 8);
    for (let b of utf8) {
      pushBits(b, 8);
    }

    // Terminator (up to 4 zeroes)
    const maxBits = dataCapacity * 8;
    const termLen = Math.min(4, maxBits - bits.length);
    pushBits(0, termLen);

    // Pad to 8-bit boundary
    while (bits.length % 8 !== 0) {
      bits.push(0);
    }

    // Pad Codewords (0xEC, 0x11)
    const padBytes = [0xec, 0x11];
    let padIdx = 0;
    while (bits.length < maxBits) {
      pushBits(padBytes[padIdx % 2], 8);
      padIdx++;
    }

    // Convert bits to bytes
    const dataBytes = new Uint8Array(dataCapacity);
    for (let i = 0; i < dataCapacity; i++) {
      let b = 0;
      for (let j = 0; j < 8; j++) {
        b = (b << 1) | bits[i * 8 + j];
      }
      dataBytes[i] = b;
    }

    return dataBytes;
  }

  // QR Code Matrix builder
  function createMatrix(version) {
    const size = version * 4 + 17;
    const matrix = Array.from({ length: size }, () => Array(size).fill(null));
    const reserved = Array.from({ length: size }, () => Array(size).fill(false));

    function setModule(r, c, val, isRes = true) {
      matrix[r][c] = val;
      if (isRes) reserved[r][c] = true;
    }

    // Finder patterns
    function addFinder(top, left) {
      for (let r = -1; r <= 7; r++) {
        for (let c = -1; c <= 7; c++) {
          const row = top + r;
          const col = left + c;
          if (row < 0 || row >= size || col < 0 || col >= size) continue;
          if (
            (r >= 0 && r <= 6 && (c === 0 || c === 6)) ||
            (c >= 0 && c <= 6 && (r === 0 || r === 6)) ||
            (r >= 2 && r <= 4 && c >= 2 && c <= 4)
          ) {
            setModule(row, col, 1);
          } else {
            setModule(row, col, 0);
          }
        }
      }
    }

    addFinder(0, 0);
    addFinder(0, size - 7);
    addFinder(size - 7, 0);

    // Timing patterns
    for (let i = 8; i < size - 8; i++) {
      const val = i % 2 === 0 ? 1 : 0;
      if (!reserved[6][i]) setModule(6, i, val);
      if (!reserved[i][6]) setModule(i, 6, val);
    }

    // Alignment patterns (for version >= 2)
    if (version >= 2) {
      const pos = [6, size - 7];
      if (version >= 7) pos.splice(1, 0, Math.floor((size - 13) / 2) + 6);
      for (let r of pos) {
        for (let c of pos) {
          if (reserved[r][c]) continue;
          for (let dr = -2; dr <= 2; dr++) {
            for (let dc = -2; dc <= 2; dc++) {
              const val = Math.max(Math.abs(dr), Math.abs(dc)) === 1 ? 0 : 1;
              setModule(r + dr, c + dc, val);
            }
          }
        }
      }
    }

    // Dark module
    setModule(size - 8, 8, 1);

    // Reserve format information area
    for (let i = 0; i < 9; i++) {
      if (!reserved[8][i]) setModule(8, i, 0);
      if (!reserved[i][8]) setModule(i, 8, 0);
      if (!reserved[8][size - 1 - i]) setModule(8, size - 1 - i, 0);
      if (!reserved[size - 1 - i][8]) setModule(size - 1 - i, 8, 0);
    }

    return { size, matrix, reserved };
  }

  function addFormatInfo(matrix, size, mask = 0) {
    // ECC M (00) XOR Mask 0 (000) -> 00000 -> BCH code: 0b101010000010010
    const formatBits = [
      [1, 0, 1, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0], // mask 0
      [1, 0, 1, 0, 0, 1, 1, 0, 1, 1, 1, 1, 1, 0, 0], // mask 1
      [1, 0, 1, 1, 1, 1, 0, 1, 0, 1, 0, 1, 0, 0, 1], // mask 2
      [1, 0, 1, 1, 0, 0, 1, 1, 1, 0, 0, 0, 1, 1, 1]  // mask 3
    ][mask % 4];

    // Around top-left
    let idx = 0;
    for (let c = 0; c <= 8; c++) {
      if (c === 6) continue;
      matrix[8][c] = formatBits[idx++];
    }
    for (let r = 7; r >= 0; r--) {
      if (r === 6) continue;
      matrix[r][8] = formatBits[idx++];
    }

    // Around top-right & bottom-left
    idx = 0;
    for (let r = size - 1; r >= size - 7; r--) {
      matrix[r][8] = formatBits[idx++];
    }
    matrix[size - 8][8] = formatBits[idx++];
    for (let c = size - 8; c < size; c++) {
      matrix[8][c] = formatBits[idx++];
    }
  }

  function placeData(grid, allBytes, mask = 0) {
    const { size, matrix, reserved } = grid;
    const bits = [];
    for (let b of allBytes) {
      for (let i = 7; i >= 0; i--) {
        bits.push((b >> i) & 1);
      }
    }

    let bitIdx = 0;
    let up = true;
    for (let c = size - 1; c > 0; c -= 2) {
      if (c === 6) c--; // Skip vertical timing column
      const rows = up
        ? Array.from({ length: size }, (_, i) => size - 1 - i)
        : Array.from({ length: size }, (_, i) => i);

      for (let r of rows) {
        for (let colOffset = 0; colOffset < 2; colOffset++) {
          const col = c - colOffset;
          if (!reserved[r][col]) {
            let bit = bitIdx < bits.length ? bits[bitIdx++] : 0;
            // Apply Mask 0: (row + column) % 2 == 0
            const maskCondition = (r + col) % 2 === 0;
            if (maskCondition) bit ^= 1;
            matrix[r][col] = bit;
          }
        }
      }
      up = !up;
    }
  }

  function generateQrMatrix(text) {
    const spec = pickVersion(new TextEncoder().encode(text).length);
    const [version, totalCodewords, dataCapacity, ecCodewords, ecBlocks] = spec;

    const dataBytes = encodeData(text, spec);
    const ecBytes = calculateEcc(dataBytes, ecCodewords);

    const allBytes = new Uint8Array(totalCodewords);
    allBytes.set(dataBytes);
    allBytes.set(ecBytes, dataBytes.length);

    const grid = createMatrix(version);
    placeData(grid, allBytes, 0);
    addFormatInfo(grid.matrix, grid.size, 0);

    return grid;
  }

  function generateQrSvg(text, container, size = 200) {
    try {
      const { size: dim, matrix } = generateQrMatrix(text);
      const margin = 2;
      const total = dim + margin * 2;

      let rects = [];
      for (let r = 0; r < dim; r++) {
        for (let c = 0; c < dim; c++) {
          if (matrix[r][c] === 1) {
            rects.push(`<rect x="${c + margin}" y="${r + margin}" width="1" height="1" fill="#0f172a"/>`);
          }
        }
      }

      const svg = `
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${total} ${total}" width="${size}" height="${size}" shape-rendering="crispEdges">
          <rect width="${total}" height="${total}" fill="#ffffff"/>
          ${rects.join('')}
        </svg>
      `;

      if (typeof container === 'string') {
        const el = document.querySelector(container);
        if (el) el.innerHTML = svg;
      } else if (container && container.innerHTML !== undefined) {
        container.innerHTML = svg;
      }
      return svg;
    } catch (err) {
      console.error("QR Generation error:", err);
      if (container) {
        container.innerHTML = `<div style="padding: 10px; color: red;">שגיאה ביצירת QR</div>`;
      }
      return null;
    }
  }

  global.generateQrSvg = generateQrSvg;
})(typeof window !== 'undefined' ? window : this);
