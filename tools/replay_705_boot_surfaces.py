"""Model the OpenVG commands observed in the J140 boot."""

from hashlib import sha256
from math import ceil, floor
from struct import iter_unpack, pack, unpack

def require(condition, message):
    if not condition:
        raise ValueError(message)


def boot_outline(data, registers):
    """Decode J140 boot text paths, which can reuse the previous path's matrix."""
    words = unpack(f"<{len(data)//4}I", data)
    require(words[-1] == 0x14000001, "unterminated boot outline")
    pos = 0
    while pos < len(words)-1 and words[pos] >> 8 != 0x580000 and words[pos] != 0x59020008:
        op = words[pos]
        pos += 1
        if op >> 24 == 0x19:
            count, reg = ((op >> 16) & 255)+1, op & 0xffff
            require(pos+count < len(words), "incomplete outline register packet")
            registers.update((reg+4*i, v) for i, v in enumerate(words[pos:pos+count]))
            pos += count
    a, b, tx, c, d, ty = unpack("<6f", pack("<6I", *(registers[k] for k in
                                  (0x3110, 0x3114, 0x3118, 0x3120, 0x3124, 0x3128))))
    def transform(x, y):
        return a*x+b*y+tx, c*x+d*y+ty

    points = []
    contours = []
    current = None
    sizes = {0x58000002: 2, 0x58000004: 2, 0x5800000A: 4}
    while pos < len(words)-1:
        operation = words[pos]
        if operation == 0x59020008:
            require(pos+4 < len(words)-1, "truncated surface rectangle")
            x, y, w, h = unpack("<4f", data[4*(pos+1):4*(pos+5)])
            box = [transform(x,y), transform(x+w,y), transform(x+w,y+h), transform(x,y+h)]
            points.extend(box)
            contours.append(box)
            pos += 5
            continue
        if operation >> 24 == 0x19:
            pos += 2 + ((operation >> 16) & 255)
            require(pos < len(words), "trailing outline register packet exceeds path")
            continue
        if operation == 0x58000000:
            require(current is not None, "close without a starting point")
            current = contours[-1][0]
            contours[-1].append(current)
            pos += 1
            continue
        count = sizes.get(operation, 0)
        require(count and pos+count < len(words)-1, "unsupported first scene path operation")
        args = unpack(f"<{count}f", data[4*(pos+1):4*(pos+1+count)])
        pos += count+1
        if operation == 0x58000002:
            current = transform(*args)
            contours.append([current])
            # A move by itself (including the final move to zero) paints nothing.
            continue
        require(current is not None, "path segment without a starting point")
        end = transform(*args[-2:])
        points.extend((current, end))
        if count == 4:
            control = transform(*args[:2])
            curve = current, control, end

            def at(t):
                u = 1-t
                return tuple(u*u*p+2*u*t*q+t*t*r for p, q, r in zip(*curve))

            # A quadratic's extrema lie at its ends or where the derivative vanishes.
            for p, q, r in zip(*curve):
                if p-2*q+r:
                    t = (p-q)/(p-2*q+r)
                    if 0 < t < 1:
                        points.append(at(t))
            contours[-1].extend(at(t/8) for t in range(1, 8))
        contours[-1].append(end)
        current = end
    require(points, "first outline has no ink")
    x, y = zip(*points)
    clip = registers.get(0x2090, 0x01E00110)
    return [max(0, floor(min(x))), max(0, floor(min(y))),
            min(clip >> 16, ceil(max(x))), min(clip & 0xffff, ceil(max(y)))], contours


def first_outline(data):
    require(len(data) == 164*4, "unexpected first scene outline list length")
    return boot_outline(data, {})


def draw_outline(cpu, base, pitch, bounds, contours, paint, over):
    """Render a stock RGB565 path with 4x4 coverage."""
    x0, y0, x1, y1 = bounds
    require(pitch in (-768, -960) and 0 <= x0 < x1 <= -pitch//2 and 0 <= y0 < y1 <= 272 and
            0x20800000 <= base+pitch*(y1-1)+2*x0 < base+pitch*y0+2*x1 <= 0x209FA000,
            "outline draws outside its target")
    opacity, *color = paint
    require(all(0 <= c <= 1 for c in paint), "invalid path paint")
    edges = [edge for path in contours for edge in zip(path, path[1:]+path[:1])]
    changed = 0
    for y in range(y0, y1):
        address = base+y*pitch+2*x0
        before = unpack(f"<{x1-x0}H", cpu.mem_read(address, 2*(x1-x0)))
        row = list(before)
        hits = [0]*(4*(x1-x0))
        for sy in range(4):
            fy = y+(sy+.5)/4
            crossings = [(ax+(fy-ay)*(bx-ax)/(by-ay), 1 if by > ay else -1)
                         for (ax, ay), (bx, by) in edges if (ay <= fy) != (by <= fy)]
            for sx in range(len(hits)):
                fx = x0+(sx+.5)/4
                hits[sx] += sum(sign for x, sign in crossings if x > fx) != 0
        for i, old in enumerate(before):
            coverage = sum(hits[4*i:4*i+4])
            if coverage:
                alpha = coverage * opacity / 16
                row[i] = sum(int(ink*m*alpha+((old>>s)&m)*(1-alpha if over else 1-coverage/16)+0.5) << s
                             for s, m, ink in zip((11, 5, 0), (31, 63, 31), color))
                changed += row[i] != old
        if tuple(row) != before:
            cpu.mem_write(address, pack(f"<{len(row)}H", *row))
    return changed


class BootClears:
    def __init__(self, cpu, *, slot_adjust=0):
        self.cpu = cpu
        self.slot_adjust = slot_adjust
        self.registers = {}
        self.next_register = self.remaining = 0
        self.draws = []
        self.copies = []
        self.images = []
        self.destination_format_from_source = False
        self.image_transform = False
        self.outline = None
        self.cover_words = None
        self.cover_draw = None

    def word(self, value):
        if self.cover_words is not None:
            self.cover_words.append(value)
            if len(self.cover_words) == 2:
                self.cover()
                self.cover_words = None
        elif self.remaining:
            self.registers[self.next_register] = value
            self.next_register += 4
            self.remaining -= 1
        elif value >> 28 == 0xA:
            self.next_register = value & 0xFFFF
            self.remaining = ((value >> 16) & 0xFFF) + 1
            require(self.next_register % 4 == 0 and self.remaining <= 16, "unexpected OpenVG packet")
            if self.next_register == 0x10:
                self.destination_format_from_source = self.remaining == 2
            if self.next_register == 0x80C and self.remaining == 3:
                self.image_transform = True
        elif value == 0xDA000000:
            if self.registers[0x110] & 1:
                self.copy()
            else:
                self.clear()
        elif value == 0xD8000000 and self.outline is not None and self.cover_draw is None:
            self.cover_words = []
        elif value == 0 or self.outline is not None and value == 0x08008066:
            # Observed command list synchronization; the firmware still waits for the IRQ.
            return
        else:
            raise ValueError(f"unsupported boot drawing command {value:#010x}")

    def cover(self):
        bounds, contours, coverage_ram = self.outline
        regs = self.registers
        base, pitch, fmt = (regs[x] for x in (0x10, 0x14, 0x18))
        pitch = unpack("<i", pack("<I", pitch))[0]
        x0, y0, x1, y1 = bounds
        if self.image_transform:
            self.cover_draw = self.image(base, pitch, fmt)
            self.image_transform = False
            return
        lo, hi = self.cover_words
        clip = [lo >> 16, lo & 0xFFFF, (hi >> 16)+1, (hi & 0xFFFF)+1]
        bounds = [max(x0, clip[0]), max(y0, clip[1]), min(x1, clip[2]), min(y1, clip[3])]
        paint = unpack("<4f", pack("<4I", *(regs[x] for x in (0xF0, 0xF4, 0xF8, 0xFC))))
        require(fmt == 3 and regs[0x20] == coverage_ram and regs[0x110] in (0x80121050, 0x80121051),
                f"unexpected outline format or coverage {fmt:#x} {regs[0x20]:#x} {coverage_ram:#x} {regs[0x110]:#x}")
        changed = (draw_outline(self.cpu, base, pitch, bounds, contours, paint, bool(regs[0x110]&1))
                   if bounds[0] < bounds[2] and bounds[1] < bounds[3] else 0)
        self.cover_draw = dict(address=hex(base), pitch=pitch, changed_pixels=changed)

    def image(self, base, pitch, fmt):
        regs = self.registers
        lo, hi = self.cover_words
        x0, y0, x1, y1 = lo >> 16, lo & 0xFFFF, hi >> 16, hi & 0xFFFF
        x1, y1 = min(x1+1, -pitch//2), min(y1+1, 272)
        src, stride, src_fmt = (regs[k] for k in (0x200, 0x204, 0x208))
        stride = unpack("<i", pack("<I", stride))[0]
        w, h = (regs[0x210] >> 16)+1, (regs[0x210] & 0xFFFF)+1
        vals = unpack("<6f", pack("<6I", *(regs[k] for k in (0x21C, 0x220, 0x238, 0x23C, 0x80C, 0x810))))
        sx, skew_x, skew_y, sy, tx, ty = vals
        program = regs[0x8000]
        mask = src_fmt == 0x0B and program == 0xD00201D2 and regs[0x110] == 0x80121051
        normal = program == 0x61000092 and regs[0x110] in (0x80121050, 0x80121051)
        require(fmt == 3 and pitch in (-768, -960) and
                0 <= x0 < x1 and 0 <= y0 < y1 and not skew_x and not skew_y and
                (mask or normal and src_fmt in (3, 0x41, 0x0B)),
                f"unsupported boot image operation: {program:#x} {regs[0x110]:#x} {src_fmt:#x} {vals}")
        bpp, pixel = {3: (2, "<H"), 0x41: (4, "<I"), 0x0B: (1, "<B")}[src_fmt]
        paint = unpack("<4f", pack("<4I", *(regs[k] for k in (0xF0, 0xF4, 0xF8, 0xFC)))) if mask else None
        require(paint is None or all(0 <= c <= 1 for c in paint), "invalid startup mask paint")
        if mask:
            a, r, g, b = (int(c*255+0.5) for c in paint)
        require(w*bpp <= abs(stride) and h <= 272 and
                0x20800000 <= min(src, src+(h-1)*stride) <= max(src, src+(h-1)*stride)+w*bpp <= 0x209FA000 and
                0x20800000 <= base+(y1-1)*pitch <= base+y0*pitch+2*x1 <= 0x209FA000,
                "boot image outside its surface")
        inputs = [[v for v, in iter_unpack(pixel, self.cpu.mem_read(src+y*stride, w*bpp))]
                  for y in range(h)]
        xs = [floor(sx*(x-x0)+tx) for x in range(x0, x1)]
        size, changed = 2*(x1-x0), 0
        for y in range(y0, y1):
            v = floor(sy*(y-y0)+ty)
            if not 0 <= v < h:
                continue
            address = base+y*pitch+2*x0
            old = [p for p, in iter_unpack("<H", self.cpu.mem_read(address, size))]
            row = old[:]
            for i, u in enumerate(xs):
                if not 0 <= u < w:
                    continue
                p = inputs[v][u]
                if bpp == 2:
                    row[i] = p
                else:
                    if mask:
                        alpha, p = (p*a+127)//255, r << 16 | g << 8 | b
                    elif src_fmt == 0x0B:
                        alpha, p = p, 0xFFFFFF  # Normal A8 uses white; stale paint belongs to the previous draw.
                    else:
                        alpha = p >> 24
                    channels = ((16, 11, 31), (8, 5, 63), (0, 0, 31))
                    background = old[i] if regs[0x110] & 1 else 0
                    row[i] = sum(((alpha*((p >> c) & 255)*m+(255-alpha)*((background >> s) & m)*255+32512)//65025) << s
                                 for c, s, m in channels)
            changed += sum(a != b for a, b in zip(row, old))
            if row != old:
                self.cpu.mem_write(address, pack(f"<{len(row)}H", *row))
        draw = dict(source=hex(src), target=hex(base), changed_pixels=changed, bounds=[x0,y0,x1,y1])
        self.images.append(draw)
        return draw

    def copy(self):
        regs = self.registers
        w, h = (regs[0x814] >> 16)+1, (regs[0x814] & 0xFFFF)+1
        fmt = regs[0x208 if self.destination_format_from_source else 0x018]
        require(regs[0x110] == 0x80001001 and fmt == regs[0x208] and
                fmt in (3, 0x41, 0x0B) and w <= 480 and h <= 272,
                "unsupported boot copy mode")
        bpp = {3: 2, 0x41: 4, 0x0B: 1}[fmt]
        size = w*bpp

        def rows(base, origin):
            addr, pitch = regs[base], unpack("<i", pack("<I", regs[base+4]))[0]
            x, y = regs[origin] >> 16, regs[origin] & 0xFFFF
            first, last = addr+bpp*x+pitch*y, addr+bpp*x+pitch*(y+h-1)
            lo, hi = min(first, last), max(first, last)+size
            # Startup reads both A8 masks and packed 32-bit images from the read-only DAT graphics.
            rom_source = (base == 0x200 and 0x185F0000+self.slot_adjust <= lo < hi <= 0x18BF0000+self.slot_adjust and
                          (fmt == 0x0B or fmt == 0x41 and pitch > 0 and (addr | pitch) % 4 == 0))
            ram_start = 0x20005000 if base == 0x200 else 0x20800000
            require(pitch and bpp*(x+w) <= abs(pitch) and (ram_start <= lo < hi <= 0x209FA000 or rom_source),
                    "boot copy outside its surface")
            return range(first, last+pitch, pitch)

        # Read the source before writing so overlapping rows cannot mutate it.
        data = [bytes(self.cpu.mem_read(a, size)) for a in rows(0x200, 0x81C)]
        target = rows(0x10, 0x818)
        changed = any(bytes(self.cpu.mem_read(a, size)) != row for a, row in zip(target, data))
        for a, row in zip(target, data):
            self.cpu.mem_write(a, row)
        self.copies.append(dict(source=hex(regs[0x200]), target=hex(regs[0x10]), width=w, height=h,
                                changed=changed, sha256=sha256(b"".join(data)).hexdigest()))

    def clear(self):
        regs = self.registers
        base, pitch = (regs[x] for x in (0x010, 0x014))
        fmt = regs[0x208 if self.destination_format_from_source else 0x018]
        pitch = unpack("<i", pack("<I", pitch))[0]
        size, origin, color, operation = (regs[x] for x in (0x814, 0x818, 0x80C, 0x110))
        w, h = (size >> 16) + 1, (size & 0xFFFF) + 1
        x, y = origin >> 16, origin & 0xFFFF
        require(fmt in (3, 0x41, 0x0B) and not operation & 1 and x+w <= 480 and y+h <= 272 and
                (fmt != 3 or color >> 16 in (0, color & 0xFFFF)), "unsupported boot fill mode")
        bpp, pixel = {3: (2, "<H"), 0x41: (4, "<I"), 0x0B: (1, "<B")}[fmt]
        require(pitch < 0 and bpp*(x+w) <= -pitch, "boot fill outside row")
        start = base+(y+h-1)*pitch+bpp*x
        end = base+y*pitch+bpp*(x+w)
        require(0x20800000 <= start < end <= 0x209FA000, "draw outside the boot graphics area")
        color &= (1 << (8*bpp))-1
        row = pack(pixel, color) * w
        starts = range(start, end, -pitch) if bpp*w != -pitch else (start,)
        fill = row*h if bpp*w == -pitch else row
        changed = False
        after = bytearray()
        for address in starts:
            changed |= self.cpu.mem_read(address, len(fill)) != fill
            self.cpu.mem_write(address, fill)
            after.extend(self.cpu.mem_read(address, len(fill)))
        fill = row*h
        require(after == fill, "boot graphics clear did not update the full surface")
        draw = dict(base=hex(base), start=hex(start), width=w, height=h, pitch=pitch,
                    sha256=sha256(after).hexdigest(), changed=changed)
        draw[{3: "rgb565", 0x41: "word32", 0x0B: "alpha8"}[fmt]] = hex(color)
        if x or y:
            draw["origin"] = [x, y]
        self.draws.append(draw)
