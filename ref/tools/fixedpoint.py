"""GTE-style fixed-point math (see ref/hardware/gte.md).

Models the formulas of RTPS, NCLIP, AVSZ3 and depth cueing closely enough to
show *why* PS1 vertices jitter: every result is an integer, the perspective
reciprocal is a 17-bit approximation, and screen coordinates clamp to 11 bits.

WHY FIXED POINT?
================
The PS1's CPU has no floating-point unit. All 3D math runs on the GTE
coprocessor using integers that *pretend* to have a fractional part. In the
"1.3.12" format a 16-bit integer is read as value / 4096, so:

    4096  -> 1.0        2048 -> 0.5        -4096 -> -1.0        1 -> 0.000244

Multiplying two such numbers gives a result scaled by 4096 * 4096, so after each
multiply the hardware shifts right by 12 (divides by 4096) to get back to
1.3.12. Every shift throws away the low bits. Every division rounds. Those tiny
losses add up to the visible "wobble" of PS1 geometry.

Run ``python -m ref.tools.fixedpoint`` for a jitter demonstration.
"""

from __future__ import annotations

import math

ONE = 0x1000  # 1.0 in 1.3.12 (4096)


# -----------------------------------------------------------------------------
# Conversions
# -----------------------------------------------------------------------------

def to_fx12(x: float) -> int:
    """Float -> 1.3.12 (int16 range).

    The clamp mirrors the 16-bit register: values outside about -8.0 .. +7.9998
    cannot be stored.
    """
    return clamp(int(round(x * ONE)), -0x8000, 0x7FFF)


def from_fx12(v: int) -> float:
    return v / ONE


def clamp(v: int, lo: int, hi: int) -> int:
    """Saturate to a range. The GTE saturates rather than wrapping on overflow
    (and sets a FLAG bit, which this model does not track)."""
    return lo if v < lo else hi if v > hi else v


# -----------------------------------------------------------------------------
# Angles and rotation matrices
# -----------------------------------------------------------------------------
#
# Sony's libgte measures angles in 4096 units per full turn (so 1024 = 90
# degrees) and looks up sine and cosine in a table, returning 1.3.12 values.

def rsin(angle: int) -> int:
    """Sine for 4096-units-per-turn angles, returned in 1.3.12 (like libgte rsin)."""
    return to_fx12(math.sin(angle * 2.0 * math.pi / 4096.0))


def rcos(angle: int) -> int:
    return to_fx12(math.cos(angle * 2.0 * math.pi / 4096.0))


def mat_mul(a: list[list[int]], b: list[list[int]]) -> list[list[int]]:
    """Multiply two 1.3.12 3x3 matrices, truncating like the hardware (>> 12).

    Each product of two 1.3.12 numbers is a 1.6.24 number; ``>> 12`` brings it
    back to 1.3.12, discarding (not rounding) the 12 lowest bits.
    """
    return [[(sum(a[i][k] * b[k][j] for k in range(3)) >> 12) for j in range(3)] for i in range(3)]


def rot_matrix_xyz(ax: int, ay: int, az: int) -> list[list[int]]:
    """Rotation matrix (1.3.12) from 4096-per-turn angles, applied X then Y then Z.

    Because each multiply truncates, the result is not perfectly orthonormal.
    Games that rebuild matrices every frame from angles avoid drift; games that
    accumulate rotations frame after frame must re-normalise.
    """
    sx, cx = rsin(ax), rcos(ax)
    sy, cy = rsin(ay), rcos(ay)
    sz, cz = rsin(az), rcos(az)
    rx = [[ONE, 0, 0], [0, cx, -sx], [0, sx, cx]]
    ry = [[cy, 0, sy], [0, ONE, 0], [-sy, 0, cy]]
    rz = [[cz, -sz, 0], [sz, cz, 0], [0, 0, ONE]]
    return mat_mul(rz, mat_mul(ry, rx))


# -----------------------------------------------------------------------------
# Perspective projection (RTPS)
# -----------------------------------------------------------------------------

def _reciprocal(h: int, sz: int) -> tuple[int, bool]:
    """H/SZ as an unsigned 1.16 value, saturating like the GTE divide (17-bit result).

    Perspective projection needs one division per vertex: screen_x = x * H / z.
    The GTE computes the factor n = H / SZ once and multiplies X and Y by it.
    The result has only 17 bits, and it saturates when the vertex is very close
    to the camera (H >= 2*SZ). That saturation is why geometry right in front
    of the camera "explodes" towards the screen edges in PS1 games.

    The real GTE uses a table-driven Newton-Raphson approximation; integer
    division here has the same range and saturation behaviour and is within a
    couple of LSBs, which is what matters for the visible effect.
    """
    if sz == 0 or h >= sz * 2:
        return 0x1FFFF, True
    n = ((h << 17) // sz + 1) >> 1     # (H << 16) / SZ, rounded
    return min(n, 0x1FFFF), False


def rtps(
    v: tuple[int, int, int],
    rt: list[list[int]],
    tr: tuple[int, int, int],
    h: int = 256,
    ofx: int = 160 << 16,
    ofy: int = 120 << 16,
    dqa: int = 0,
    dqb: int = 0,
) -> dict:
    """Rotate, translate and perspective-project one int16 vertex.

    Returns a dict with integer ``sx, sy`` (screen pixels), ``sz`` (depth),
    ``ir0`` (depth-cue factor, 0..0x1000) and ``overflow`` (divide saturated).
    ``ofx/ofy`` are 16.16 like the hardware; ``dqa`` is s16 (8.8), ``dqb`` s32 (8.24).
    """
    # 1. Rotate and translate into view space: view = RT * v + TR.
    #    TR is shifted up by 12 so it has the same scale as the 1.3.12 products,
    #    then the sum is shifted back down by 12.
    mac = [((tr[i] << 12) + sum(rt[i][k] * v[k] for k in range(3))) >> 12 for i in range(3)]
    ir = [clamp(m, -0x8000, 0x7FFF) for m in mac]     # IR1..3: 16-bit saturated copies
    sz = clamp(mac[2], 0, 0xFFFF)                      # depth: unsigned 16-bit
    # 2. Perspective factor n = H / SZ (1.16 fixed point).
    n, overflow = _reciprocal(h, sz)
    # 3. Screen position = centre offset + view position * n.
    #    ``>> 16`` drops the fraction completely: screen coordinates are whole
    #    pixels. This single line is the source of PS1 vertex snapping.
    #    The clamp to -1024..1023 matches the GPU's 11-bit coordinate range.
    sx = clamp((ofx + ir[0] * n) >> 16, -0x400, 0x3FF)
    sy = clamp((ofy + ir[1] * n) >> 16, -0x400, 0x3FF)
    # 4. Depth-cue (fog) factor, linear in n, so linear in 1/z, not in z.
    ir0 = clamp((dqb + dqa * n) >> 12, 0, 0x1000)
    return {"sx": sx, "sy": sy, "sz": sz, "ir0": ir0, "overflow": overflow, "view": tuple(mac)}


# -----------------------------------------------------------------------------
# Culling and sorting helpers
# -----------------------------------------------------------------------------

def nclip(p0: tuple[int, int], p1: tuple[int, int], p2: tuple[int, int]) -> int:
    """GTE NCLIP: signed doubled area of the screen triangle (winding / back-face test).

    If the triangle's corners appear clockwise on screen the result has one
    sign; anticlockwise gives the other. A closed model's back faces appear
    with the opposite winding to its front faces, so one sign test culls them.
    It runs on already-rounded integer pixels, so tiny or far-away triangles
    can flicker between "front" and "back".
    """
    (x0, y0), (x1, y1), (x2, y2) = p0, p1, p2
    return x0 * y1 + x1 * y2 + x2 * y0 - x0 * y2 - x1 * y0 - x2 * y1


def avsz3(sz1: int, sz2: int, sz3: int, zsf3: int) -> int:
    """GTE AVSZ3: ordering-table index from three depths.

    ZSF3 is a scale factor of about 1/3 * (OT length / depth range) in 1.3.12,
    so the sum of three depths becomes their (scaled) average.
    """
    return clamp((zsf3 * (sz1 + sz2 + sz3)) >> 12, 0, 0xFFFF)


def avsz4(sz0: int, sz1: int, sz2: int, sz3: int, zsf4: int) -> int:
    """GTE AVSZ4: as AVSZ3, for quads."""
    return clamp((zsf4 * (sz0 + sz1 + sz2 + sz3)) >> 12, 0, 0xFFFF)


def zsf_for(ot_len: int, z_max: int, verts: int = 3) -> int:
    """Pick ZSF3/ZSF4 so that depths 0..z_max map onto OT indices 0..ot_len-1."""
    return max(1, (ot_len * ONE) // (verts * z_max))


# -----------------------------------------------------------------------------
# Depth cueing (fog)
# -----------------------------------------------------------------------------

def depth_cue_params(h: int, z_near: int, z_far: int) -> tuple[int, int]:
    """Compute (DQA, DQB) so IR0 is 0 at z_near and 0x1000 (full fog) at z_far.

    IR0 = (DQB + DQA * n) >> 12 with n = H/SZ in 1.16 (``n = (H << 16) // SZ``).
    Solving the two endpoint equations gives the values below.
    """
    n_near = (h << 16) // z_near
    n_far = (h << 16) // z_far
    # IR0(n_near) = 0, IR0(n_far) = 0x1000  (in << 12 units: 0 and 0x1000000)
    dqa = -(0x1000 << 12) // max(1, n_near - n_far)
    dqb = -dqa * n_near
    return dqa, dqb


def depth_cue(rgb: tuple[int, int, int], far_rgb: tuple[int, int, int], ir0: int) -> tuple[int, int, int]:
    """DPCS: interpolate an 8-bit colour toward the far colour by IR0/4096.

    colour + (far - colour) * t, with t = IR0 / 4096. At t = 0 the colour is
    untouched; at t = 1 (IR0 = 4096) it IS the fog colour. Because this runs per
    vertex, the fog across a large polygon is only as smooth as its corners.
    """
    return tuple(clamp(c + (((f - c) * ir0) >> 12), 0, 255) for c, f in zip(rgb, far_rgb))


def _demo() -> None:
    print("Vertex jitter demo: a point moving smoothly along X at depth 2000.")
    print("Float projection vs GTE integer projection (H=256, 320x240 screen).\n")
    print(f"{'world x':>8} {'float sx':>10} {'gte sx':>7}")
    ident = [[ONE, 0, 0], [0, ONE, 0], [0, 0, ONE]]
    for i in range(12):
        x = i * 2  # world units
        f = 160 + x * 256 / 2000
        r = rtps((x, 0, 0), ident, (0, 0, 2000))
        print(f"{x:>8} {f:>10.3f} {r['sx']:>7}")
    print("\nThe integer column advances in whole-pixel jumps: that is PS1 wobble.")


if __name__ == "__main__":
    _demo()
