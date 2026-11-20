"""Replay original J140 language rows and rasterize their OpenVG paths on a local surface."""

import argparse
from hashlib import sha256
import json
from math import ceil, floor, isfinite
from pathlib import Path
from struct import iter_unpack, pack, unpack
import zlib

from tools.emulate_705 import PROFILES, SCRATCH, arm, call, machine, uc


FONT_HEADER = 0x18C00000
FONT_HASH = "f879b35945b7ce130f7a99be1795c0a9d827a722d4e89bfad4401376b1d940d9"
SMALL_FONT_HEADER = 0x18FA2588
SMALL_FONT_HASH = "19d2af9e822a9ff738e4aafa4041c6e08b7bd5745defb53bbb5a14ff64dc841d"
HEAP_START, HEAP_END = 0x20600000, 0x20900000
COORD_COUNTS = {0: 0, 2: 2, 4: 2, 10: 4}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def png(width, height, rgba):
    def chunk(kind, data):
        return pack(">I", len(data)) + kind + data + pack(">I", zlib.crc32(kind + data))

    stride = width * 4
    rows = b"".join(b"\0" + rgba[i:i + stride] for i in range(0, len(rgba), stride))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", pack(">2I5B", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def coverage(segments, coords, offset, width, height, scale=4):
    """Supersample absolute M/L/Q/Z segments with OpenVG's default even/odd fill."""
    path = []
    edges = []
    pairs = iter(zip(coords[::2], coords[1::2]))

    def point():
        x, y = next(pairs)
        return x + offset[0], height - y - offset[1]

    for op in segments:
        if op in (0, 2) and path:
            edges.extend(zip(path, path[1:] + path[:1]))
            path = []
        if op in (2, 4):
            path.append(point())
        elif op == 10:
            a, b, c = path[-1], point(), point()
            for j in range(1, 9):
                t = j / 8
                path.append(tuple((1-t)**2 * u + 2*t*(1-t)*v + t*t*w for u, v, w in zip(a, b, c)))
    if path:
        edges.extend(zip(path, path[1:] + path[:1]))
    if not edges:
        return {}
    mask = {}
    top = max(0, ceil(min(min(a[1], b[1]) for a, b in edges)*scale-.5))
    bottom = min(height*scale, ceil(max(max(a[1], b[1]) for a, b in edges)*scale-.5))
    for sy in range(top, bottom):
        y = (sy + .5) / scale
        cuts = sorted(x1 + (y-y1)*(x2-x1)/(y2-y1) for (x1, y1), (x2, y2) in edges
                      if min(y1, y2) <= y < max(y1, y2))
        require(len(cuts) % 2 == 0, "unpaired outline crossing")
        for left, right in zip(cuts[::2], cuts[1::2]):
            for sx in range(max(0, ceil(left*scale-.5)), min(width*scale, ceil(right*scale-.5))):
                pos = sy//scale*width + sx//scale
                mask[pos] = mask.get(pos, 0) + 1
    return mask


class TextSurface:
    """Software model of the OpenVG calls observed in the stock settings UI."""

    def __init__(self, cpu, width, height):
        self.cpu, self.width, self.height = cpu, width, height
        self.pixels = bytearray(width * height * 4)
        self.display = (width, height, self.pixels)
        self.targets, self.dirty, self.pixel_writes = {}, [], []
        self.target = None
        self.heap, self.blocks, self.free_spans = HEAP_START, {}, []
        self.handle = 0
        self.paths, self.glyphs, self.colors, self.bound = {}, {}, {}, {}
        self.bound_handles = {}
        self.origin = (0., 0.)
        self.matrix_mode, self.matrices = 0x1404, {}
        self.images, self.image_draws = {}, []
        self.image_preview = None
        self.alpha_images, self.image_mode = set(), 0x1F00
        self.clear_color, self.clears = bytes(4), []
        self.events, self.indices = [], []
        self.handlers = {
            0x20127A28: lambda: self.alloc(self.args(1)[0]), 0x20127A4C: self.realloc,
            0x20127A78: self.free,
            0x20262C92: lambda: 1,  # The host text surface substitutes for EGL.
            0x20263BC6: self.new_handle, 0x20263898: self.new_handle,
            0x20263BE6: self.destroy_font, 0x202638B6: self.destroy_paint,
            0x2026330C: self.paint_type, 0x20263916: self.color,
            0x20263654: self.create_path, 0x2026372A: self.append_path,
            0x20263C06: self.set_glyph, 0x202636AA: self.destroy_path,
            0x202631F2: self.set_vector, 0x202632A0: self.get_vector,
            0x202631D2: self.set_int, 0x202631AE: self.set_float,
            0x202638D6: self.paint, 0x20263CA4: self.draw,
            0x202634AC: self.translate, 0x2026342E: self.identity,
            0x2026344C: self.load_matrix, 0x202634D2: self.scale,
            0x20263154: lambda: 0, 0x20263190: lambda: None, 0x2026314C: lambda: None,  # get error, finish
            0x20263976: self.create_image, 0x202639EA: self.image_data,
            0x20263A46: self.child_image, 0x20263A94: self.copy_image,
            0x20263B40: self.get_pixels,
            0x20263AC4: self.draw_image, 0x2026399C: self.destroy_image,
            0x20263B12: self.write_pixels,
            0x2026362E: self.clear,
            0x202D1748: self.diagnostic,
        }
        for addr in self.handlers:
            cpu.hook_add(uc.UC_HOOK_CODE, self.dispatch, begin=addr, end=addr)
        cpu.hook_add(uc.UC_HOOK_CODE, self.font_lookup, begin=0x201971F0, end=0x201971F0)

    def reg(self, name):
        return self.cpu.reg_read(getattr(arm, f"UC_ARM_REG_{name}"))

    def read(self, ptr, count, fmt="I"):
        return unpack(f"<{count}{fmt}", self.cpu.mem_read(ptr, count * (1 if fmt == "B" else 4)))

    def args(self, n):
        args = tuple(self.reg(f"R{i}") for i in range(min(n, 4)))
        return args + self.read(self.reg("SP"), n-4) if n > 4 else args

    def floats(self):
        return unpack("<2f", pack("<2I", self.reg("S0"), self.reg("S1")))

    def dispatch(self, cpu, addr, _size, _data):
        value = self.handlers[addr]()
        if value is not None:
            cpu.reg_write(arm.UC_ARM_REG_R0, value)
        # The J140 application can call the heap and graphics backends from A32 or Thumb.
        lr = self.reg("LR")
        require(lr & 1 or lr % 4 == 0, "misaligned A32 return at host boundary")
        cpu.reg_write(arm.UC_ARM_REG_PC, lr)

    def font_lookup(self, _cpu, _addr, _size, _data):
        self.indices.append(self.reg("R0"))

    def diagnostic(self):
        msg = bytes(self.cpu.mem_read(self.reg("R0"), 96)).split(b"\0", 1)[0]
        raise ValueError(f"original firmware diagnostic: {msg!r}")

    def alloc(self, size):
        span = (max(size, 1) + 7) & ~7
        require(size <= 0x100000, "guest allocation exceeds model")
        for i, (addr, available) in enumerate(self.free_spans):
            if available >= span:
                self.free_spans[i:i+1] = [(addr+span, available-span)] if available > span else []
                break
        else:
            addr = self.heap
            self.heap += span
            require(self.heap <= HEAP_END, "guest heap exhausted")
        self.blocks[addr] = size
        return addr

    def realloc(self):
        old, size = self.args(2)
        new = self.alloc(size)
        if old:
            self.cpu.mem_write(new, bytes(self.cpu.mem_read(old, min(self.blocks[old], size))))
            self.release(old)
        return new

    def free(self):
        addr, = self.args(1)
        if addr:
            self.release(addr)

    def release(self, addr):
        span = (max(self.blocks.pop(addr), 1) + 7) & ~7
        # Reuse guest buffers when the firmware frees them, including adjacent spans.
        merged = []
        for base, size in sorted([*self.free_spans, (addr, span)]):
            if merged and merged[-1][0]+merged[-1][1] == base:
                merged[-1] = (merged[-1][0], merged[-1][1]+size)
            else:
                merged.append((base, size))
        self.free_spans = merged

    def new_handle(self):
        self.handle += 1
        return self.handle

    def destroy_font(self):
        font, = self.args(1)
        for key in [key for key in self.glyphs if key[0] == font]:
            del self.glyphs[key]

    def destroy_paint(self):
        self.colors.pop(self.args(1)[0], None)

    def paint_type(self):
        require(self.args(3)[1:] == (0x1A00, 0x1B00), "expected solid-color paint")

    def color(self):
        handle, rgba = self.args(2)
        self.colors[handle] = rgba.to_bytes(4, "big")
        for mode, current in self.bound_handles.items():
            if current == handle:
                self.bound[mode] = self.colors[handle]

    def paint(self):
        handle, mode = self.args(2)
        self.bound_handles[mode] = handle
        self.bound[mode] = self.colors.get(handle, b"\x00\x00\x00\xff")

    def create_path(self):
        require(self.args(2) == (0, 3) and self.floats() == (1., 0.), "unsupported OpenVG path format")
        return self.new_handle()

    def append_path(self):
        handle, count, segment_ptr, coord_ptr = self.args(4)
        require(0 < count <= 512 and handle not in self.paths, "unsupported path append")
        segments = self.read(segment_ptr, count, "B")
        require(all(op in COORD_COUNTS for op in segments), "unsupported path segment")
        coords = self.read(coord_ptr, sum(COORD_COUNTS[op] for op in segments), "f")
        require(all(isfinite(x) and abs(x) < 512 for x in coords), "invalid glyph coordinates")
        self.paths[handle] = (segments, coords)

    def set_glyph(self):
        font, index, handle, hinted, origin, advance = self.args(6)
        require(hinted == 0, "unexpected hinted path")
        self.glyphs[font, index] = (self.paths[handle] if handle else ((), ()), self.read(origin, 2, "f"),
                                   self.read(advance, 2, "f"))

    def destroy_path(self):
        del self.paths[self.args(1)[0]]  # The font keeps the path data after this handle is released.

    def set_int(self):
        key, value = self.args(2)
        require((key, value) in {(0x1100, 0x1404), (0x1100, 0x1401), (0x1170, 0), (0x1104, 0x2001),
                                  (0x1105, 0x1F00), (0x1105, 0x1F01), (0x1102, 1)},
                f"unsupported OpenVG state: {key:#x}={value:#x}")
        if key == 0x1100:
            self.matrix_mode = value
        elif key == 0x1105:
            self.image_mode = value

    def set_float(self):
        require(self.args(1) == (0x1110,) and self.floats()[0] == 1., "unexpected stroke width")

    def set_vector(self):
        key, count, ptr = self.args(3)
        if (key, count) == (0x1122, 2):
            self.origin = self.read(ptr, 2, "f")
        elif (key, count) == (0x1121, 4):
            self.clear_color = bytes(round(255 * min(1., max(0., c))) for c in self.read(ptr, 4, "f"))
        else:
            raise ValueError(f"unsupported OpenVG vector: {key:#x}, {count}")

    def get_vector(self):
        key, count, ptr = self.args(3)
        require((key, count) == (0x1121, 4), f"unsupported OpenVG vector read: {key:#x}, {count}")
        self.cpu.mem_write(ptr, pack("<4f", *(c/255 for c in self.clear_color)))

    def select_target(self, index=None):
        self.target = index
        self.width, self.height, self.pixels = self.display if index is None else self.targets[index][1:]

    def note_draw(self):
        if self.target is not None:
            if self.target in self.dirty:
                self.dirty.remove(self.target)
            self.dirty.append(self.target)

    def clear(self):
        self.note_draw()
        x, y, w, h = unpack("<4i", pack("<4I", *self.args(4)))
        require(w > 0 and h > 0, f"invalid OpenVG clear: {(x, y, w, h)}")
        left, right = max(0, x), min(self.width, x + w)
        if left < right:
            line = self.clear_color * (right - left)
            for row in range(max(0, self.height - y - h), min(self.height, self.height - y)):
                self.pixels[4 * (row * self.width + left):4 * (row * self.width + right)] = line
        self.clears.append({"rect": [x, y, w, h], "rgba": self.clear_color.hex()})

    def write_pixels(self):
        ptr, stride, fmt, x, y, w, h = self.args(7)
        stride = unpack("<i", pack("<I", stride))[0]
        require(fmt == 3 and abs(stride) >= w*2 and 0 < w <= self.width-x and 0 < h <= self.height-y,
                f"unsupported VG_sRGB_565 write: {(stride, fmt, x, y, w, h)}")
        source = None
        # The original CPU reads an OpenVG render target through its RGB565 RAM address.
        for index in reversed(self.dirty):
            base, sw, sh, pixels = self.targets[index]
            source_stride = (sw*2+31) & ~31
            sy, sx_bytes = divmod(ptr-base, source_stride)
            if stride == -source_stride and 0 <= sy < sh and sy-h+1 >= 0 and sx_bytes % 2 == 0 and sx_bytes//2+w <= sw:
                if source is None:
                    source = (index, sw, sy, sx_bytes//2, pixels)
                # Modes reuse overlapping VRAM. A full-row copy starting on the
                # surface's last row identifies its tile better than recency.
                if sx_bytes == 0 and w == sw and sy == sh-1:
                    source = (index, sw, sy, 0, pixels)
                    break
        self.pixel_writes.append({"ptr": hex(ptr), "rect": [x, y, w, h], "target": self.target,
                                  "source_target": source[0] if source else None})
        self.note_draw()
        for row in range(h):
            pos = 4*((self.height-1-y-row)*self.width+x)
            if source:
                _, sw, sy, sx, pixels = source
                start = 4*((sy-row)*sw+sx)
                self.pixels[pos:pos+4*w] = pixels[start:start+4*w]
                continue
            colors = self.cpu.mem_read(ptr+row*stride, 2*w)
            if not any(colors):
                self.pixels[pos:pos+4*w] = b"\0\0\0\xff" * w
                continue
            for (value,) in iter_unpack("<H", colors):
                r, g, b = value >> 11, (value >> 5) & 63, value & 31
                self.pixels[pos:pos+4] = bytes(((r*255+15)//31, (g*255+31)//63, (b*255+15)//31, 255))
                pos += 4

    def translate(self):
        sx, sy, tx, ty = self.matrix()
        x, y = self.floats()
        self.matrices[self.matrix_mode] = (sx, sy, tx + sx*x, ty + sy*y)

    def identity(self):
        self.matrices.pop(self.matrix_mode, None)

    def matrix(self):
        return self.matrices.get(self.matrix_mode, (1., 1., 0., 0.))

    def load_matrix(self):
        sx, b, c, d, sy, f, tx, ty, i = self.read(self.args(1)[0], 9, "f")
        require((b, c, d, f, i) == (0., 0., 0., 0., 1.), "unsupported OpenVG matrix")
        self.matrices[self.matrix_mode] = (sx, sy, tx, ty)

    def scale(self):
        sx, sy, tx, ty = self.matrix()
        x, y = self.floats()
        self.matrices[self.matrix_mode] = (sx*x, sy*y, tx, ty)

    def create_image(self):
        fmt, w, h, quality = self.args(4)
        require(fmt in (0x41, 0x0B) and 0 < w <= 1024 and 0 < h <= 512 and quality == 1,
                f"unsupported OpenVG image: {(fmt, w, h, quality)}")
        handle = self.new_handle()
        self.images[handle] = [w, h, None]
        if fmt == 0x0B:
            self.alpha_images.add(handle)
        return handle

    def image_data(self):
        handle, ptr, stride, fmt, x, y, w, h = self.args(8)
        img = self.images[handle]
        if handle in self.alpha_images:
            width, height, data = img
            require(fmt == 0x0B and stride >= w and 0 <= x < width and 0 <= y < height
                    and 0 < w <= width-x and 0 < h <= height-y, "unsupported VG_A_8 upload")
            origin, _, pixels = data or (ptr, width, bytearray(width*height))
            for row in range(h):
                start = (y+row)*width+x
                pixels[start:start+w] = self.cpu.mem_read(ptr+row*stride, w)
            img[2] = (origin, width, pixels)
            return
        require((fmt, x, y) == (0x41, 0, 0) and 0 < w <= img[0] and h == img[1] and stride == img[0]*4,
                f"unsupported image data upload: {(stride, fmt, x, y, w, h, img[:2])}")
        img[2] = (ptr, w, bytes(self.cpu.mem_read(ptr, stride * h)))

    def get_pixels(self):
        handle, dx, dy, sx, sy, w, h = self.args(7)
        width, height, data = self.images[handle]
        require(handle not in self.alpha_images and 0 < w <= width-dx and 0 < h <= height-dy
                and sx+w <= self.width and sy+h <= self.height, "unsupported vgGetPixels rectangle")
        # Surface pixels are top-down RGBA. VG images use bottom-up BGRA here.
        origin, _, target = data or (self.targets[self.target][0] if self.target is not None else 0,
                                     width, bytes(width*height*4))
        target = bytearray(target)
        for row in range(h):
            pos = ((self.height-1-sy-row)*self.width+sx)*4
            rgba = self.pixels[pos:pos+w*4]
            line = bytearray(rgba)
            line[0::4], line[2::4] = rgba[2::4], rgba[0::4]
            pos = ((dy+row)*width+dx)*4
            target[pos:pos+w*4] = line
        self.images[handle][2] = (origin, width, target)

    def destroy_image(self):
        handle, = self.args(1)
        self.alpha_images.discard(handle)
        del self.images[handle]

    def child_image(self):
        handle, x, y, w, h = self.args(5)
        require(handle not in self.alpha_images, "unsupported VG_A_8 child")
        stride, height, (ptr, width, pixels) = self.images[handle]
        require(0 < w <= width-x and 0 < h <= height-y, "OpenVG child outside uploaded image")
        data = b"".join(pixels[4*(i*stride+x):4*(i*stride+x+w)] for i in range(y, y+h))
        child = self.new_handle()
        self.images[child] = [w, h, (ptr + 4*(y*stride+x), w, data)]
        return child

    def copy_image(self):
        dst, dx, dy, src, sx, sy, w, h, dither = self.args(9)
        require(src not in self.alpha_images and dst not in self.alpha_images, "unsupported VG_A_8 copy")
        ds, dh, data = self.images[dst]
        ss, sh, (ptr, sw, source) = self.images[src]
        require(dst != src and 0 < w <= min(ds-dx, sw-sx) and 0 < h <= min(dh-dy, sh-sy) and dither == 1,
                f"unsupported OpenVG copy {ds,dh,dx,dy} <- {sw,sh,sx,sy}, size={w,h} dither={dither}")
        target = data[2] if data else bytearray(ds*dh*4)
        for row in range(h):
            start, end = 4*((sy+row)*ss+sx), 4*((dy+row)*ds+dx)
            target[end:end+4*w] = source[start:start+4*w]
        self.images[dst][2] = (ptr, ds, target)

    def blend(self, pos, r, g, b, a):
        if a == 255:
            self.pixels[pos:pos+4] = bytes((r, g, b, a))
        elif a:
            old_r, old_g, old_b, old_a = self.pixels[pos:pos+4]
            old = (255-a)*old_a
            total = 255*a+old
            rgb = [(255*a*new + old*prev + total//2)//total for new, prev in
                   zip((r, g, b), (old_r, old_g, old_b))]
            self.pixels[pos:pos+4] = bytes((*rgb, (total+127)//255))

    def draw_image(self):
        self.note_draw()
        handle, = self.args(1)
        width, height, data = self.images[handle]
        ptr, w, src = data
        mask = handle in self.alpha_images
        require(self.image_mode == (0x1F01 if mask else 0x1F00), "unsupported OpenVG image mode for format")
        if mask:
            r, g, b, paint_alpha = self.bound[2]
        elif self.image_preview is not None:
            src = self.image_preview(ptr, w, width, height, src)
        sx, sy, tx, ty = self.matrix()
        require(self.matrix_mode == 0x1401 and all(isfinite(v) for v in (sx, sy, tx, ty)) and sx and sy,
                "unsupported image transform")
        x0, x1 = sorted((tx, tx+sx*w))
        y0, y1 = sorted((ty, ty+sy*height))
        for y in range(max(0, ceil(y0-.5)), min(self.height, ceil(y1-.5))):
            yy = floor((y+.5-ty)/sy)
            for x in range(max(0, ceil(x0-.5)), min(self.width, ceil(x1-.5))):
                xx = floor((x+.5-tx)/sx)
                if 0 <= xx < w and 0 <= yy < height:
                    if mask:
                        a = (src[yy*width+xx]*paint_alpha+127)//255
                    else:
                        b, g, r, a = src[4*(yy*width+xx):4*(yy*width+xx)+4]
                    self.blend(4*((self.height-1-y)*self.width+x), r, g, b, a)
        self.image_draws.append({"source": hex(ptr), "size": [w, height], "matrix": [sx, sy, tx, ty]})

    def draw(self):
        self.note_draw()
        font, count, ptr, xptr, yptr, mode, auto_hint = self.args(7)
        # The stock RTTY renderer can submit a whole 83-column row in one draw.
        require(1 <= count <= 83 and mode == 2 and yptr == 0, "unsupported glyph draw mode")
        ids = self.read(ptr, count)
        # The guest allocates count-1 adjustments; no adjustment after the last glyph is drawn.
        dx = self.read(xptr, count-1, "f") if xptr else (0.,) * (count-1)
        x, y = self.origin
        sx, sy, tx, ty = self.matrix()
        require((self.matrix_mode, sx, sy) == (0x1404, 1., 1.), "unsupported glyph transform")
        rgba = self.bound[mode]
        require(rgba[3] == 255, "expected opaque guest paint before coverage")
        glyphs = []
        for i, index in enumerate(ids):
            (segments, coords), (ox, oy), advance = self.glyphs[font, index]
            offset = x + tx - ox, y + ty - oy
            glyphs.append({"key": index, "offset": offset, "advance": advance,
                           "segments": list(segments), "coordinates": list(coords)})
            if segments:
                mask = coverage(segments, coords, offset, self.width, self.height)
                for pixel, sample_count in mask.items():
                    alpha = (sample_count * 255 + 8) // 16
                    if alpha:
                        pos = pixel * 4
                        self.blend(pos, *rgba[:3], alpha)
            x += advance[0] + (dx[i] if i < count-1 else 0.)
            y += advance[1]
        self.events.append({"translation": (tx, ty), "origin": self.origin,
                            "rgba": rgba.hex(), "auto_hint_requested": bool(auto_hint), "glyphs": glyphs})


def make_surface(main_image, font, small_font=None, *, cpu=None, initialize=True):
    if cpu is None:
        cpu = machine(main_image)
    cpu.reg_write(arm.UC_ARM_REG_C1_C0_2, 0xF00000)
    cpu.reg_write(arm.UC_ARM_REG_FPEXC, 0x40000000)
    cpu.mem_map(FONT_HEADER, (len(font) + 4 + 4095) & ~4095, uc.UC_PROT_READ)
    cpu.mem_write(FONT_HEADER, pack("<I", len(font)) + font)
    dimensions = call(cpu, 0x20195190, 18)
    width, height = unpack("<HH", cpu.mem_read(dimensions + 4, 4))
    require((width, height) == (480, 272), "unexpected stock text surface dimensions")
    surface = TextSurface(cpu, width, height)
    cpu.mem_write(0x203808A0, pack("<2I", FONT_HEADER + 4, len(font)))
    if small_font is None and initialize:
        for instance, initial_ppem in ((1, 18), (4, 10)):
            result = call(cpu, 0x20144F00, instance, 1, initial_ppem, instruction_limit=2_000_000)
            require(result == 0, "original font initialization failed")
    elif small_font is not None:
        # The small font begins in the last page of the large font's mapping.
        first = (FONT_HEADER+4+len(font)+4095) & ~4095
        last = (SMALL_FONT_HEADER+4+len(small_font)+4095) & ~4095
        cpu.mem_map(first, last-first, uc.UC_PROT_READ)
        cpu.mem_write(SMALL_FONT_HEADER, pack("<I", len(small_font)) + small_font)
        cpu.mem_write(0x203808A8, pack("<2I", SMALL_FONT_HEADER+4, len(small_font)))
        if initialize:
            call(cpu, 0x20145244, instruction_limit=5_000_000)
    return cpu, surface


def render(main_image, profile, font, system, display, language_pair=False):
    cpu, surface = make_surface(main_image, font)
    width, height = surface.width, surface.height
    cpu.mem_write(profile.language_bytes, bytes((display, system)))
    effective = call(cpu, profile.language)
    label = "表示言語" if effective else "Display Language"
    values = ("English", "Japanese") if not effective else ("英語", "日本語")
    items = [(0xA7, label, values[display], not system)]
    if language_pair:
        items.append((0xA8, "システム言語" if effective else "System Language", values[system], False))
    rows, slot = [], 0
    for row_id, expected_label, expected_value, expected_hidden in items:
        hidden = bool(call(cpu, profile.row_hidden, row_id))
        require(hidden == expected_hidden, f"unexpected visibility for row {row_id:#x}")
        if hidden:
            rows.append({"id": row_id, "hidden": True})
            continue
        cpu.mem_write(SCRATCH + slot * 128 + 12, pack("<BxH", 2, row_id))
        first = len(surface.events)
        if language_pair:
            # The stock wrapper adds the option value via the original settings table.
            call(cpu, 0x2014BA80, SCRATCH, slot, 0, effective, 0, effective, instruction_limit=2_000_000)
        else:
            call(cpu, profile.draw_row, SCRATCH, slot, effective, 0, instruction_limit=2_000_000)
        runs = ["".join(chr(g["key"]) for g in e["glyphs"]) for e in surface.events[first:]]
        require(runs == ([expected_label, expected_value] if language_pair else [expected_label]),
                f"unexpected OpenVG glyph runs for row {row_id:#x}: {runs!r}")
        rows.append({"id": row_id, "hidden": False, "slot": slot, "text_runs": runs})
        slot += 1
    if effective:
        require(surface.indices[0] == 3136, "the original cmap did not return the expected glyph for U+8868")
    alpha = surface.pixels[3::4]
    nonzero = [(i % width, i // width) for i, a in enumerate(alpha) if a]
    require(bool(nonzero) == bool(slot), "unexpected output coverage")
    bounds = ([min(x for x, _ in nonzero), min(y for _, y in nonzero),
               max(x for x, _ in nonzero) + 1, max(y for _, y in nonzero) + 1] if nonzero else None)
    row_evidence = ({"rows": rows} if language_pair else
                    {"hidden": rows[0]["hidden"], "text": label if not rows[0]["hidden"] else ""})
    return png(width, height, surface.pixels), {
        "system": system, "display": display, **row_evidence,
        "dimensions": [width, height], "font_indices": surface.indices, "bbox_xyxy": bounds,
        "nonzero_alpha_pixels": len(nonzero), "draws": surface.events,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("main", type=Path)
    parser.add_argument("font", type=Path, help="original font-0.ttf from probe_705_fonts")
    parser.add_argument("output", type=Path, help="new local output directory")
    parser.add_argument("--language-pair", action="store_true", help="draw both settings and their current values")
    args = parser.parse_args()
    image, font = args.main.read_bytes(), args.font.read_bytes()
    digest, font_digest = sha256(image).hexdigest(), sha256(font).hexdigest()
    profile = PROFILES.get(digest)
    if profile is None or profile.name != "705J140" or font_digest != FONT_HASH:
        parser.error("this text surface supports only the original J140 image and its large Japanese font")
    cases = (("japanese", 1, 1), ("english", 1, 0), ("hidden", 0, 1))
    if args.language_pair:
        cases = (("both-japanese", 1, 1), ("display-english", 1, 0),
                 ("system-english-display-japanese", 0, 1), ("both-english", 0, 0))
    results = [(name, *render(image, profile, font, system, display, args.language_pair))
               for name, system, display in cases]
    args.output.mkdir(parents=True)
    report = {"main_sha256": digest, "font_sha256": font_digest, "engine": f"Unicorn {uc.__version__}", "cases": {}}
    for name, image, evidence in results:
        (args.output / f"{name}.png").write_bytes(image)
        report["cases"][name] = {"png_sha256": sha256(image).hexdigest(), **evidence}
    (args.output / "trace.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
