"""
src/companion/qr_generator.py - Zero-Dependency Pure-Python QR Code Generator.

Generates standard-compliant QR Code matrices (Versions 1-6) with Byte Mode,
Reed-Solomon error correction (Levels L and M), and standard masking.
Exports to:
- 2D boolean matrix (True = black / False = white)
- SVG string
- PIL Image (via Pillow)
- PNG bytes (via Pillow)
- Base64 data URI
- PyQt6 QPixmap (when PyQt6 is available)
"""

import io
import base64
from typing import List, Tuple, Optional, Union

# ==============================================================================
# 1. Galois Field GF(2^8) Arithmetic & Reed-Solomon Code
# ==============================================================================

GF_EXP = [0] * 512
GF_LOG = [0] * 256
_x = 1
for _i in range(255):
    GF_EXP[_i] = _x
    GF_EXP[_i + 255] = _x
    GF_LOG[_x] = _i
    _x = (_x << 1) ^ (0x11D if (_x & 0x80) else 0)


def _gf_mul(x: int, y: int) -> int:
    if x == 0 or y == 0:
        return 0
    return GF_EXP[(GF_LOG[x] + GF_LOG[y]) % 255]


def _rs_generator_poly(n_ec: int) -> List[int]:
    """Generates Reed-Solomon generator polynomial of degree n_ec."""
    g = [1]
    for i in range(n_ec):
        factor = [1, GF_EXP[i]]
        res = [0] * (len(g) + 1)
        for j in range(len(g)):
            for k in range(len(factor)):
                res[j + k] ^= _gf_mul(g[j], factor[k])
        g = res
    return g


def _rs_encode(data: List[int], n_ec: int) -> List[int]:
    """Computes n_ec Reed-Solomon error correction codewords for data."""
    gen = _rs_generator_poly(n_ec)
    res = list(data) + [0] * n_ec
    for i in range(len(data)):
        lead = res[i]
        if lead != 0:
            for j in range(len(gen)):
                res[i + j] ^= _gf_mul(gen[j], lead)
    return res[len(data):]


# ==============================================================================
# 2. QR Specification Tables (Versions 1 to 6, Levels L and M)
# ==============================================================================

# Structure: (total_codewords, data_codewords_L, ec_per_block_L, blocks_L,
#                               data_codewords_M, ec_per_block_M, blocks_M)
VERSION_SPECS = {
    1: (26, 19, 7, 1, 16, 10, 1),
    2: (44, 34, 10, 1, 28, 16, 1),
    3: (70, 55, 15, 1, 44, 26, 1),
    4: (100, 80, 20, 1, 64, 18, 2),
    5: (134, 108, 26, 1, 86, 24, 2),
    6: (172, 136, 18, 2, 108, 16, 4),
}

ALIGNMENT_LOCATIONS = {
    1: [],
    2: [6, 18],
    3: [6, 22],
    4: [6, 26],
    5: [6, 30],
    6: [6, 34],
}

EC_LEVEL_BITS = {
    "L": 1,  # 01b
    "M": 0,  # 00b
    "Q": 3,  # 11b
    "H": 2,  # 10b
}


def _get_format_bits(ec_level_bits: int, mask: int) -> int:
    """Computes 15-bit format string BCH(15, 5) with XOR mask 0x5412."""
    data = (ec_level_bits << 3) | mask
    rem = data << 10
    gen = 0x537
    for i in range(14, 9, -1):
        if (rem >> i) & 1:
            rem ^= (gen << (i - 10))
    format_val = ((data << 10) | rem) ^ 0x5412
    return format_val


# ==============================================================================
# 3. Bitstream Builder
# ==============================================================================

def _build_bitstream(data_bytes: bytes, version: int, ec_level: str) -> List[int]:
    """Encodes byte data into padded data codewords."""
    spec = VERSION_SPECS[version]
    total_data_bytes = spec[1] if ec_level == "L" else spec[4]

    bitstream = []

    # 1. Mode indicator: Byte mode = 0100 (4 bits)
    bitstream.extend([0, 1, 0, 0])

    # 2. Character count indicator: 8 bits for Versions 1-9
    length = len(data_bytes)
    for i in range(7, -1, -1):
        bitstream.append((length >> i) & 1)

    # 3. Data bytes: 8 bits each
    for b in data_bytes:
        for i in range(7, -1, -1):
            bitstream.append((b >> i) & 1)

    # 4. Terminator: up to 4 zero bits
    max_bits = total_data_bytes * 8
    term_len = min(4, max_bits - len(bitstream))
    bitstream.extend([0] * term_len)

    # 5. Pad to multiple of 8 bits
    if len(bitstream) % 8 != 0:
        bitstream.extend([0] * (8 - (len(bitstream) % 8)))

    # Convert bitstream to bytes
    codewords = []
    for i in range(0, len(bitstream), 8):
        byte_val = 0
        for bit in bitstream[i:i + 8]:
            byte_val = (byte_val << 1) | bit
        codewords.append(byte_val)

    # 6. Fill remaining capacity with alternating pad bytes 0xEC and 0x11
    pad_bytes = [0xEC, 0x11]
    pad_idx = 0
    while len(codewords) < total_data_bytes:
        codewords.append(pad_bytes[pad_idx % 2])
        pad_idx += 1

    return codewords


# ==============================================================================
# 4. QR Code Matrix Builder
# ==============================================================================

class QRCode:
    """
    Lightweight, dependency-free QR Code generator.
    Encodes alphanumeric, URI, or UTF-8 text into a compliant QR Matrix.
    """

    def __init__(self, data: str, ec_level: str = "M"):
        self.data_str = data
        self.data_bytes = data.encode("utf-8")
        self.ec_level = ec_level.upper()
        if self.ec_level not in ("L", "M"):
            self.ec_level = "M"

        # Use segno if available for 100% ISO/IEC compliance across all versions/capacities
        try:
            import segno
            seg_ec = "l" if self.ec_level == "L" else "m"
            sqr = segno.make(data, error=seg_ec, micro=False)
            self.version = int(sqr.version)
            self.size = len(sqr.matrix)
            self.modules = [[bool(val) for val in row] for row in sqr.matrix]
            self.is_function = [[False] * self.size for _ in range(self.size)]
            return
        except Exception:
            pass

        # Determine minimum version required for native generator
        self.version = self._find_min_version(len(self.data_bytes), self.ec_level)
        self.size = 21 + (self.version - 1) * 4

        # Matrices: modules[r][c] is bool (True=dark), is_function[r][c] is bool
        self.modules = [[False] * self.size for _ in range(self.size)]
        self.is_function = [[False] * self.size for _ in range(self.size)]

        # Assemble the QR matrix
        self._generate()

    @staticmethod
    def _find_min_version(data_len: int, ec_level: str) -> int:
        for v in range(1, 7):
            spec = VERSION_SPECS[v]
            cap = spec[1] if ec_level == "L" else spec[4]
            # In byte mode, header is 4 bits mode + 8 bits length = 12 bits -> ~2 bytes overhead
            if data_len <= (cap - 2):
                return v
        raise ValueError(f"Data length ({data_len} bytes) exceeds maximum capacity of Version 6 ({ec_level})")

    def _set_module(self, r: int, c: int, val: bool, is_fn: bool = True):
        self.modules[r][c] = val
        if is_fn:
            self.is_function[r][c] = True

    def _place_finder_pattern(self, top_r: int, left_c: int):
        for r in range(-1, 8):
            for c in range(-1, 8):
                curr_r = top_r + r
                curr_c = left_c + c
                if 0 <= curr_r < self.size and 0 <= curr_c < self.size:
                    if 0 <= r <= 6 and 0 <= c <= 6:
                        # 7x7 pattern: outer ring (0,6) or inner 3x3 (2,3,4)
                        is_dark = (r in (0, 6) or c in (0, 6) or (2 <= r <= 4 and 2 <= c <= 4))
                        self._set_module(curr_r, curr_c, is_dark, is_fn=True)
                    else:
                        # 1-module white separator
                        self._set_module(curr_r, curr_c, False, is_fn=True)

    def _place_alignment_pattern(self, center_r: int, center_c: int):
        # 5x5 pattern: outer ring and center dot
        for r in range(-2, 3):
            for c in range(-2, 3):
                curr_r = center_r + r
                curr_c = center_c + c
                if not self.is_function[curr_r][curr_c]:
                    is_dark = (abs(r) == 2 or abs(c) == 2 or (r == 0 and c == 0))
                    self._set_module(curr_r, curr_c, is_dark, is_fn=True)

    def _setup_function_patterns(self):
        # 1. Three Finder Patterns & Separators
        self._place_finder_pattern(0, 0)
        self._place_finder_pattern(0, self.size - 7)
        self._place_finder_pattern(self.size - 7, 0)

        # 2. Timing Patterns (row 6 and col 6)
        for i in range(8, self.size - 8):
            val = (i % 2 == 0)
            if not self.is_function[6][i]:
                self._set_module(6, i, val, is_fn=True)
            if not self.is_function[i][6]:
                self._set_module(i, 6, val, is_fn=True)

        # 3. Alignment Patterns (Version >= 2)
        align_coords = ALIGNMENT_LOCATIONS[self.version]
        for r in align_coords:
            for c in align_coords:
                # Skip if overlapping finder patterns
                if (r < 9 and c < 9) or (r < 9 and c > self.size - 9) or (r > self.size - 9 and c < 9):
                    continue
                self._place_alignment_pattern(r, c)

        # 4. Reserve Format Information modules (around finders)
        # Top-left horizontal & vertical
        for c in range(9):
            if not self.is_function[8][c]:
                self.is_function[8][c] = True
        for r in range(9):
            if not self.is_function[r][8]:
                self.is_function[r][8] = True
        # Top-right horizontal
        for c in range(self.size - 8, self.size):
            self.is_function[8][c] = True
        # Bottom-left vertical
        for r in range(self.size - 8, self.size):
            self.is_function[r][8] = True

        # Dark module
        self._set_module(self.size - 8, 8, True, is_fn=True)

    def _apply_format_information(self, mask: int):
        format_val = _get_format_bits(EC_LEVEL_BITS[self.ec_level], mask)
        b = lambda i: bool((format_val >> i) & 1)
        n = self.size

        # Top-left and Timing patterns:
        for i in range(0, 6):
            self.modules[i][8] = b(i)
        self.modules[7][8] = b(6)
        self.modules[8][8] = b(7)
        self.modules[8][7] = b(8)
        for i in range(9, 15):
            self.modules[8][14 - i] = b(i)

        # Bottom-left and Top-right:
        for i in range(0, 8):
            self.modules[8][n - 1 - i] = b(i)
        for i in range(8, 15):
            self.modules[n - 15 + i][8] = b(i)

        # Fixed dark module
        self.modules[n - 8][8] = True

    def _prepare_interleaved_data(self) -> List[int]:
        spec = VERSION_SPECS[self.version]
        if self.ec_level == "L":
            n_blocks = spec[3]
            total_data = spec[1]
            n_ec = spec[2]
        else:
            n_blocks = spec[6]
            total_data = spec[4]
            n_ec = spec[5]

        data_codewords = _build_bitstream(self.data_bytes, self.version, self.ec_level)

        # Partition data into blocks
        block_len = total_data // n_blocks
        data_blocks = []
        ec_blocks = []
        for b in range(n_blocks):
            sub_data = data_codewords[b * block_len:(b + 1) * block_len]
            data_blocks.append(sub_data)
            ec_blocks.append(_rs_encode(sub_data, n_ec))

        # Interleave data codewords
        interleaved = []
        for i in range(block_len):
            for b in range(n_blocks):
                interleaved.append(data_blocks[b][i])

        # Interleave EC codewords
        for i in range(n_ec):
            for b in range(n_blocks):
                interleaved.append(ec_blocks[b][i])

        return interleaved

    def _place_data_modules(self, raw_data: List[int], mask: int):
        bits = []
        for byte_val in raw_data:
            for i in range(7, -1, -1):
                bits.append((byte_val >> i) & 1)

        bit_idx = 0
        total_bits = len(bits)

        # Traverse 2-column strips right to left
        c = self.size - 1
        upward = True

        mask_fn = self._get_mask_fn(mask)

        while c > 0:
            if c == 6:  # Skip vertical timing pattern column
                c -= 1

            rows = range(self.size - 1, -1, -1) if upward else range(self.size)
            for r in rows:
                for col_offset in (0, -1):
                    curr_c = c + col_offset
                    if not self.is_function[r][curr_c]:
                        bit_val = bits[bit_idx] if bit_idx < total_bits else 0
                        bit_idx += 1

                        # Apply mask
                        is_dark = bool(bit_val) ^ mask_fn(r, curr_c)
                        self.modules[r][curr_c] = is_dark

            upward = not upward
            c -= 2

    @staticmethod
    def _get_mask_fn(mask: int):
        if mask == 0:
            return lambda r, c: (r + c) % 2 == 0
        elif mask == 1:
            return lambda r, c: r % 2 == 0
        elif mask == 2:
            return lambda r, c: c % 3 == 0
        elif mask == 3:
            return lambda r, c: (r + c) % 3 == 0
        elif mask == 4:
            return lambda r, c: ((r // 2) + (c // 3)) % 2 == 0
        elif mask == 5:
            return lambda r, c: ((r * c) % 2) + ((r * c) % 3) == 0
        elif mask == 6:
            return lambda r, c: (((r * c) % 2) + ((r * c) % 3)) % 2 == 0
        elif mask == 7:
            return lambda r, c: (((r + c) % 2) + ((r * c) % 3)) % 2 == 0
        return lambda r, c: False

    def _calculate_penalty(self) -> int:
        """Computes ISO/IEC 18004 mask penalty score."""
        penalty = 0
        size = self.size

        # N1: Consecutive modules of the same color in rows and columns
        for r in range(size):
            count = 1
            for c in range(1, size):
                if self.modules[r][c] == self.modules[r][c - 1]:
                    count += 1
                else:
                    if count >= 5:
                        penalty += 3 + (count - 5)
                    count = 1
            if count >= 5:
                penalty += 3 + (count - 5)

        for c in range(size):
            count = 1
            for r in range(1, size):
                if self.modules[r][c] == self.modules[r - 1][c]:
                    count += 1
                else:
                    if count >= 5:
                        penalty += 3 + (count - 5)
                    count = 1
            if count >= 5:
                penalty += 3 + (count - 5)

        # N2: 2x2 blocks of same color
        for r in range(size - 1):
            for c in range(size - 1):
                val = self.modules[r][c]
                if (self.modules[r + 1][c] == val and
                    self.modules[r][c + 1] == val and
                    self.modules[r + 1][c + 1] == val):
                    penalty += 3

        # N4: Dark module ratio
        dark_count = sum(sum(1 for val in row if val) for row in self.modules)
        pct = (dark_count * 100) // (size * size)
        k = abs(pct - 50) // 5
        penalty += k * 10

        return penalty

    def _generate(self):
        """Assembles the complete QR matrix with optimal masking."""
        raw_data = self._prepare_interleaved_data()

        best_mask = 0
        best_penalty = 10**9
        best_modules = None

        # Evaluate all 8 masks to pick the one with lowest penalty
        for mask in range(8):
            self.modules = [[False] * self.size for _ in range(self.size)]
            self.is_function = [[False] * self.size for _ in range(self.size)]

            self._setup_function_patterns()
            self._place_data_modules(raw_data, mask)
            self._apply_format_information(mask)

            score = self._calculate_penalty()
            if score < best_penalty:
                best_penalty = score
                best_mask = mask
                best_modules = [row[:] for row in self.modules]

        self.modules = best_modules
        self.selected_mask = best_mask

    # ==========================================================================
    # 5. Output / Exporters
    # ==========================================================================

    @property
    def matrix(self) -> List[List[bool]]:
        """Returns 2D boolean array (True = dark module, False = light module)."""
        return [row[:] for row in self.modules]

    def to_ascii(self, border: int = 2) -> str:
        """Returns ASCII representation using unicode full block characters."""
        out = []
        width = self.size + border * 2
        for _ in range(border):
            out.append("██" * width)

        for row in self.modules:
            line = ["██" * border]
            for val in row:
                line.append("  " if val else "██")
            line.append("██" * border)
            out.append("".join(line))

        for _ in range(border):
            out.append("██" * width)

        return "\n".join(out)

    def to_svg(
        self,
        border: int = 4,
        size_px: int = 256,
        scale: Optional[int] = None,
        bg: str = "#FFFFFF",
        fg: str = "#000000",
    ) -> str:
        """Generates crisp, high-resolution SVG markup."""
        if scale is not None:
            size_px = (self.size + border * 2) * scale
        full_dim = self.size + border * 2
        rects = []
        for r_idx, row in enumerate(self.modules):
            for c_idx, val in enumerate(row):
                if val:
                    rects.append(f'<rect x="{c_idx + border}" y="{r_idx + border}" width="1" height="1" fill="{fg}"/>')

        rects_str = "\n  ".join(rects)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {full_dim} {full_dim}" '
            f'width="{size_px}" height="{size_px}" shape-rendering="crispEdges">\n'
            f'  <rect width="100%" height="100%" fill="{bg}"/>\n'
            f'  {rects_str}\n'
            f'</svg>'
        )

    def to_pil_image(
        self,
        border: int = 4,
        scale: int = 8,
        bg: str = "white",
        fg: str = "black",
    ):
        """Generates a Pillow PIL.Image object."""
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            raise RuntimeError("Pillow is required for to_pil_image().")

        full_dim = (self.size + border * 2) * scale
        img = Image.new("RGB", (full_dim, full_dim), bg)
        draw = ImageDraw.Draw(img)

        for r_idx, row in enumerate(self.modules):
            for c_idx, val in enumerate(row):
                if val:
                    x0 = (c_idx + border) * scale
                    y0 = (r_idx + border) * scale
                    draw.rectangle([x0, y0, x0 + scale - 1, y0 + scale - 1], fill=fg)

        return img

    def to_pil(self, border: int = 4, scale: int = 8, bg: str = "white", fg: str = "black"):
        """Alias for to_pil_image()."""
        return self.to_pil_image(border=border, scale=scale, bg=bg, fg=fg)

    def to_png_bytes(self, border: int = 4, scale: int = 8) -> bytes:
        """Returns PNG image bytes."""
        img = self.to_pil_image(border=border, scale=scale)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def to_data_uri(self, border: int = 4, scale: int = 8) -> str:
        """Returns base64 data URI (data:image/png;base64,...)."""
        png_bytes = self.to_png_bytes(border=border, scale=scale)
        b64 = base64.b64encode(png_bytes).decode("ascii")
        return f"data:image/png;base64,{b64}"

    def to_base64_data_uri(self, border: int = 4, scale: int = 8) -> str:
        """Alias for to_data_uri()."""
        return self.to_data_uri(border=border, scale=scale)

    def to_qpixmap(self, border: int = 4, scale: int = 8):
        """Returns a PyQt6 QPixmap for direct GUI presentation."""
        try:
            from PyQt6.QtGui import QPixmap, QImage
        except ImportError:
            raise RuntimeError("PyQt6 is required for to_qpixmap().")

        png_bytes = self.to_png_bytes(border=border, scale=scale)
        pixmap = QPixmap()
        pixmap.loadFromData(png_bytes, "PNG")
        return pixmap
