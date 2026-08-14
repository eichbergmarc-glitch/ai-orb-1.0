"""Create animation-ready layers from the supplied AI-Orb concept sheet.

RGB values are copied unchanged from the source. Only alpha masks are derived:
the crown, external orbital arcs, and floor reflection become independent layers
which the renderer can animate without repainting the reference design.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageFilter


SOURCE = Path(r"C:\Users\info\Downloads\ChatGPT Image 12. Aug. 2026, 11_11_12.png")
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "desktop" / "assets" / "orb" / "reference-layers"


def smoothstep(a: float, b: float, value: float) -> float:
    t = max(0.0, min(1.0, (value - a) / (b - a)))
    return t * t * (3.0 - 2.0 * t)


def energy_signal(pixel: tuple[int, int, int, int]) -> float:
    red, green, blue, _ = pixel
    high, low = max(red, green, blue), min(red, green, blue)
    chroma = high - low
    # The concept artwork is luminous and chromatic; the dark blue scene and
    # black core are rejected. White highlights remain via the high channel.
    return max(
        smoothstep(64.0, 176.0, high) * smoothstep(38.0, 126.0, chroma),
        smoothstep(186.0, 246.0, high) * smoothstep(16.0, 58.0, chroma),
    )


def save_layer(
    crop: Image.Image,
    name: str,
    alpha_values: list[int],
    blur: float = 0.65,
) -> None:
    alpha = Image.new("L", crop.size)
    alpha.putdata(alpha_values)
    if blur > 0:
        alpha = alpha.filter(ImageFilter.GaussianBlur(blur))
    result = crop.copy().convert("RGBA")
    result.putalpha(alpha)
    result.save(OUT / name, optimize=True)


def extract_main(source: Image.Image) -> None:
    # Coordinates measured on the supplied 1254 x 1254 concept sheet.
    crop = source.crop((416, 145, 856, 575)).convert("RGBA")
    width, height = crop.size
    cx, cy = 220.0, 210.0
    crown: list[int] = []
    base: list[int] = []
    inner_energy: list[int] = []
    orbits: list[int] = []
    reflection: list[int] = []

    for y in range(height):
        for x in range(width):
            pixel = crop.getpixel((x, y))
            signal = energy_signal(pixel)
            dx, dy = x - cx, y - cy
            radius = math.hypot(dx, dy)

            # Die vollstaendige sichtbare Kugel ist die feste gestalterische
            # Basis: echter dunkler Kern, exakt geflochtene Krone und exakt
            # die Farben der Vorlage. Nur die beiden Augen werden transparent,
            # damit der Live-Shader weiterhin schauen, blinzeln und Symbole
            # bilden kann.
            disk = 1.0 - smoothstep(151.0, 165.0, radius)
            left_eye = ((x - 170.0) / 27.0) ** 2 + ((y - 203.0) / 39.0) ** 2
            right_eye = ((x - 234.0) / 27.0) ** 2 + ((y - 201.0) / 39.0) ** 2
            eye_cut = max(
                1.0 - smoothstep(0.72, 1.08, left_eye),
                1.0 - smoothstep(0.72, 1.08, right_eye),
            )
            base.append(round(255 * disk * (1.0 - eye_cut)))

            # Thick braided plasma shell. Front-crossing strands belong to
            # this layer too; the dark face is deliberately excluded.
            annulus = smoothstep(101.0, 116.0, radius) * (1.0 - smoothstep(145.0, 157.0, radius))
            if y < 88 or y > 352:
                annulus = 0.0
            # The speech bubble touches the radial mask at the upper right,
            # but is not part of the Orb artwork.
            if y < 116 and x > 278:
                annulus = 0.0
            crown.append(round(255 * signal * annulus))

            # Thin cyan/violet filaments in the cavity between the dark core
            # and the braided shell.  The bright eyes stay renderer-owned so
            # they can still blink, look around and morph into symbols.
            cavity = smoothstep(52.0, 68.0, radius) * (1.0 - smoothstep(112.0, 126.0, radius))
            eye_left = left_eye < 1.0
            eye_right = right_eye < 1.0
            if eye_left or eye_right or y < 102 or y > 330:
                cavity = 0.0
            inner_energy.append(round(255 * signal * cavity * 0.92))

            # External elliptical paths, including their stars and tails.
            outside = smoothstep(143.0, 154.0, radius) * (1.0 - smoothstep(218.0, 235.0, radius))
            # Avoid the surrounding explanatory copy and speech bubble.
            if y < 70 or (y < 132 and x < 156) or (y < 116 and x > 250):
                outside = 0.0
            # The reflection belongs exclusively to the floor layer.
            if y > 326:
                outside = 0.0
            orbits.append(round(255 * signal * outside))

            # Exact multicolour floor reflection beneath the Orb.
            ex = dx / 166.0
            ey = (y - 362.0) / 38.0
            ellipse = 1.0 - smoothstep(0.54, 1.10, ex * ex + ey * ey)
            reflection.append(round(255 * signal * ellipse))

    save_layer(crop, "idle-base.png", base, blur=0.45)
    save_layer(crop, "idle-crown.png", crown)
    save_layer(crop, "idle-inner-energy.png", inner_energy, blur=0.35)
    save_layer(crop, "idle-orbits.png", orbits)
    save_layer(crop, "idle-reflection.png", reflection, blur=1.0)


def extract_state_crowns(source: Image.Image) -> None:
    """Extract only the luminous shell from every state card.

    The eyes remain renderer-owned so they can blink, track the pointer and
    morph.  The colour and plasma braid, however, are exact source pixels.
    """

    cards = {
        "idle": (34, 592, 152, 718),
        "listening": (168, 592, 286, 718),
        "thinking": (302, 592, 420, 718),
        "executing": (437, 592, 555, 718),
        "waiting": (571, 592, 689, 718),
        "success": (705, 592, 823, 718),
        "warning": (839, 592, 958, 718),
        "error": (976, 592, 1094, 718),
        "offline": (1110, 592, 1228, 718),
    }
    for state, box in cards.items():
        crop = source.crop(box).convert("RGBA")
        width, height = crop.size
        cx, cy = width * 0.5, 60.0
        alpha_values: list[int] = []
        base_values: list[int] = []
        for y in range(height):
            for x in range(width):
                radius = math.hypot(x - cx, y - cy)
                pixel = crop.getpixel((x, y))
                # Vollstaendige Zustandskugel, aber ohne das eingebrannte
                # Augen-/Symbollicht im Zentrum. Bei der echten Desktopgroesse
                # entsprechen diese Quellpixel genau den Karten der Vorlage.
                disk = 1.0 - smoothstep(55.0, 62.0, radius)
                # Der gesamte kleine Ausdrucksbereich wird ausgespart. Eine
                # reine Helligkeitsmaske liess beim gelben Ausrufezeichen den
                # Kopf und bei roten Augen farbige Saeume stehen. Unter dem
                # Loch liegt weiterhin der dunkle prozedurale Kern.
                expression_shape = math.sqrt(
                    ((x - cx) / 31.0) ** 2 + ((y - cy) / 42.0) ** 2
                )
                expression_cut = 1.0 - smoothstep(0.94, 1.12, expression_shape)
                base_values.append(round(255 * disk * (1.0 - expression_cut)))
                # Keep only the actual plasma braid.  The previous loose mask
                # also admitted the blue card border and made state changes
                # look like rectangular overlays.
                shell = smoothstep(36.0, 42.0, radius) * (1.0 - smoothstep(55.0, 60.0, radius))
                if y > 116:
                    shell = 0.0
                alpha_values.append(round(255 * energy_signal(pixel) * shell))
        save_layer(crop, f"state-base-{state}.png", base_values, blur=0.35)
        save_layer(crop, f"state-{state}.png", alpha_values, blur=0.45)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    source = Image.open(SOURCE).convert("RGBA")
    extract_main(source)
    extract_state_crowns(source)
    print(f"Reference layers written to {OUT}")


if __name__ == "__main__":
    main()
