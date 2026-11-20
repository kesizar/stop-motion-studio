"""Copper halftone ribbons for the studio header and standby preview."""

import math

from PIL import Image, ImageColor, ImageDraw


HEADER_BACKGROUND = "#151618"
VIEWER_BACKGROUND = "#101114"

_APRICOT = (255, 173, 113)
_COPPER = (188, 108, 77)
_PAPER = (248, 221, 189)


def _smoothstep(start, end, value):
    fraction = min(1.0, max(0.0, (value - start) / (end - start)))
    return fraction * fraction * (3.0 - 2.0 * fraction)


def _header_bands(x, phase):
    # The bands bend in opposite directions and continue beyond the right edge.
    drift = 0.045 * math.sin(phase + x * 3.5)
    center = 0.50 + 0.38 * math.sin(5.8 * x - 1.1) + drift
    second = 0.82 - 0.53 * math.sin(5.4 * x - 1.6) - drift
    fade = _smoothstep(0.10, 0.65, x)
    return (center, 0.17 + 0.10 * x, fade), (second, 0.11 + 0.07 * x, fade * 0.58)


def _viewer_bands(x, phase):
    # A legible center remains between the two light, slow-moving edges.
    upper = 0.21 + 0.13 * math.sin(x * 7.2 - 0.8) + 0.03 * math.sin(phase + x)
    lower = 0.81 + 0.12 * math.cos(x * 7.6 + 0.6) + 0.035 * math.sin(phase - x * 2)
    right = _smoothstep(0.45, 0.98, x)
    left = 1.0 - _smoothstep(0.04, 0.57, x)
    return (upper, 0.13, right * 0.52), (lower, 0.17, left * 0.52)


def _dot_colors(background, opacity, ink):
    colors = []
    for strength in range(101):
        alpha = opacity * (strength / 100) ** 0.67
        colors.append(tuple(round(base + (tone - base) * alpha) for base, tone in zip(background, ink)))
    return colors


def render_halftone(size: tuple[int, int], *, variant: str = "header", phase: float = 0.0) -> Image.Image:
    """Render a responsive RGB texture. Phase is measured in radians."""
    width, height = size
    if width <= 0 or height <= 0:
        raise ValueError("Halftone texture dimensions must be positive.")
    if variant == "header":
        background = ImageColor.getrgb(HEADER_BACKGROUND)
        bands = _header_bands
        spacing = 7.0
        opacity = 0.85
    elif variant == "viewer":
        background = ImageColor.getrgb(VIEWER_BACKGROUND)
        bands = _viewer_bands
        spacing = 9.0
        opacity = 0.52
    else:
        raise ValueError(f"Unknown halftone variant: {variant}")

    scale = 2
    art = Image.new("RGB", (width * scale, height * scale), background)
    draw = ImageDraw.Draw(art)
    apricot, copper, paper = (_dot_colors(background, opacity, ink) for ink in (_APRICOT, _COPPER, _PAPER))
    columns = math.ceil(width / spacing) + 1
    staggered = []
    for offset in (0.15, -0.35):
        positions = []
        for column in range(columns):
            x = (column + offset) * spacing
            (center, spread, weight), (echo_center, echo_spread, echo_weight) = bands(x / width, phase)
            if max(weight, echo_weight) >= 0.035:
                positions.append((column, x, center, 1 / spread, weight, echo_center, 1 / echo_spread, echo_weight))
        staggered.append(positions)

    for row in range(math.ceil(height / spacing)):
        y = (row + 0.5) * spacing
        normalized = y / height
        for column, x, center, inverse, weight, echo_center, echo_inverse, echo_weight in staggered[row % 2]:
            offset = (normalized - center) * inverse
            echo_offset = (normalized - echo_center) * echo_inverse
            main = weight * math.exp(-offset * offset)
            echo = echo_weight * math.exp(-echo_offset * echo_offset)
            strength = max(main, echo)
            if strength < 0.035:
                continue
            if main > 0.78 and (column + 3 * row) % 7 == 0:
                colors = paper
            else:
                colors = apricot if main > echo else copper
            radius = spacing * min(0.41, 0.09 + strength * 0.32)
            draw.ellipse(
                ((x - radius) * scale, (y - radius) * scale,
                 (x + radius) * scale, (y + radius) * scale),
                fill=colors[round(strength * 100)],
            )
    return art.resize(size, Image.Resampling.BILINEAR)
