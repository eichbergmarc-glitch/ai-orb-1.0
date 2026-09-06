# Grafikassets und reproduzierbare Prompts

Alle Bilder wurden als eigenständiger „Grounded Graphic-Novel Noir“-Look gestaltet: realistischer europäischer Techno-Thriller, physisch glaubwürdige Räume und Figuren, präzise Tuschekonturen über malerischen Texturen, kontrollierte Schatten und dezentes Druckkorn. Es wurde kein bestimmtes Spiel und kein bestimmter Künstler imitiert.

## Gespeicherte Assets

### Hintergründe

- `res://assets/backgrounds/krankenstation.png`
- `res://assets/backgrounds/diagnostiklabor.png`
- `res://assets/backgrounds/sicherheitsrotunde.png`
- `res://assets/backgrounds/wartungsgalerie.png`
- `res://assets/backgrounds/quarantaene.png`
- `res://assets/backgrounds/kaltarchiv.png`
- `res://assets/backgrounds/relaiskern.png`

### Figuren

- `res://assets/characters/protagonist_female.png`
- `res://assets/characters/protagonist_male.png`
- `res://assets/characters/juna_falk.png`

## Gemeinsamer finaler Hintergrundprompt

Der folgende Block bildete die feste Grundlage. Ab dem Diagnostiklabor wurde die Aufwachkammer zusätzlich als visuelle Referenz übergeben.

```text
Use case: stylized-concept
Asset type: production game environment background for a 2D point-and-click adventure
Style/medium: highly realistic graphic-novel comic illustration, cinematic grounded European techno-thriller, physically believable architecture and materials, crisp controlled hand-inked contours over richly painted realistic textures, controlled hard-edged shadow shapes, restrained cross-hatching and subtle printed pigment grain
Composition/framing: exact 16:9 wide landscape, locked eye-level 2.5D side-on point-and-click perspective with shallow perspective, complete room visible, coherent floor plane, lower 32 percent as a spacious unobstructed walkable foreground, distinct readable silhouettes for every interactive object, no character present
Lighting/mood: motivated cinematic light, deep noir shadows but readable floor, doors and interaction objects; cold cyan for system light, restrained red for danger and amber for physical or human intervention
Constraints: no readable text, letters, numbers, logos, brands, UI, cursor, hotspot markers, speech bubbles, comic panels or watermark; no fisheye, Dutch angle, isometric view, cyberpunk neon overload, glossy spaceship aesthetic, dense fog or obstructed walk lane
```

## Finale Szenenergänzungen

Diese Abschnitte wurden jeweils mit dem gemeinsamen Block kombiniert:

### Aufwachkammer 3

```text
An underground near-future European medical research chamber during a continent-wide blackout: a sealed clinical room with a treatment bed center-left, a flickering wall terminal, a partly open medical cabinet, a diagnostic mirror and a heavy handleless security door on the right; believable cables, worn medical surfaces and emergency systems. Almost dark, with cold cyan emergency light and restrained red warning accents; scratched composite panels, brushed metal, cracked glass, worn vinyl, grime and condensation.
```

### Diagnostiklabor

```text
A semicircular underground biometric laboratory during a continent-wide blackout: curved banks of dormant medical monitors, a neural diagnostic scanner, a glass case containing a compact emergency radio, an abstract patient board and a wide observation window over a rain-dark city; cold cyan monitor spill, distant lightning and tiny amber emergency lights.
```

### Sicherheitsrotunde

```text
A broad circular security hub with clearly separated routes: maintenance passage, glass quarantine door, monumental sealed relay-core door, frost-rimmed archive door and diagnostic corridor; include a facility-map console, removable foreground floor grate and manual wall-mounted power distributor; dim cyan strips, restrained red lockdown accents and faint frost-white archive light.
```

### Wartungsgalerie B

```text
A believable underground maintenance workshop, warmer and more human than the clinical rooms: radio-shielded niche with old work radio, workbench with disassembled emergency lamp, large organized tool wall, abstract schematic sheets, yellow warning-beacon housing, burned loudspeaker shell, mechanical parts cabinet and corridor back to security; amber industrial lamps with one cold cyan spill, grease and chipped paint.
```

### Quarantäne-Observatorium

```text
A reinforced glass partition separates the playable foreground from an empty sparse isolation chamber with low bunk, pale clinical panels, condensation and a mechanical door; left medical-status display, upper-right surveillance camera and recording console, central stainless-steel material hatch and heavy manual release; transparent readable glass, cold cyan-green system light and faint humane warm light inside. No person is baked into the background.
```

### Kaltarchiv E-3

```text
A frozen offline audit archive with five frontal matte-black server racks using physical write-protect levers, mechanical clocks and sparse amber indicators; a central hardware audit drawer with three verification lamps and empty wafer slot, disconnected loudspeaker and records drawer on the left, emptied rack bay with frost scrape marks and a subtle false rear panel on the right; blue-black cold light and precise amber accents.
```

### Relaiskern ASTER-4

```text
An austere compact final control chamber: waist-high matte-black decision console with four mechanical switches, blank plates and empty audit-wafer socket; eighteen restrained circular node lights form a broken ring, seventeen dim cyan and one red; abstract city monitor and waveform on the left, physical radio dock on the right, reinforced window over a rain-soaked blacked-out Central-European city; midnight-blue light, cyan rim and one warm amber pool over the switches.
```

## Finale Figurenprompts

Alle Figuren wurden als vollständige RGBA-PNGs verlangt: echte Alpha-Transparenz mit Alpha 0 außerhalb der Figur, vollständige Hände und Füße, keine Bühne, kein Schatten und kein Hintergrund.

### Weibliche Spielfigur

```text
Selectable female protagonist, approximately 36 years old, realistic Central-European appearance, lean ordinary build, intelligent tired face, alert rather than heroic; chin-length dark auburn hair tucked behind the visible ear and a fresh precise surgical incision with three tiny graphite dots. Pale grey clinical long-sleeve shirt, graphite technical trousers, simple black belt, worn dark ankle boots and narrow red patient wristband. Full-body neutral walk-ready three-quarter side profile facing right, relaxed separated arms, hands visible and feet separated. Grounded adult European graphic-novel realism, accurate anatomy and cloth folds, precise ink contours, cool neutral key, subtle cyan rim and natural warm skin.
```

### Männliche Spielfigur

```text
Selectable male protagonist, approximately 38 years old, realistic Central-European appearance, lean ordinary build, intelligent exhausted face, short dark-brown hair and light unstyled stubble; a fresh surgical incision with three graphite dots behind the visible ear. Pale grey clinical shirt, graphite technical trousers, black belt, worn dark ankle boots and narrow red patient wristband. Exactly one full body, neutral walk-ready three-quarter side profile facing right, hands visible and feet separated. Original grounded European techno-thriller graphic-novel realism with accurate anatomy, inked contours, cinematic paint, cross-hatched shadows, cool key and cyan rim. Real PNG alpha transparency; no checkerboard, backdrop, scenery, floor, shadow, weapon, text or watermark.
```

### Dr. Juna Falk

```text
Dr. Juna Falk, a 44-year-old Central-European biomedical security researcher after hours in a freezing quarantine cell; composed, intelligent and exhausted, with a wary direct gaze, medium-brown skin, dark tightly curled hair in a practical loose bun and subtle under-eye fatigue. Worn off-white knee-length laboratory coat over a dark teal blouse, charcoal trousers, simple black shoes and blank ID holder. Exactly one full body in a neutral three-quarter side profile facing left, one hand loosely holding the opposite wrist, hands visible and feet separated. Original grounded European techno-thriller graphic-novel realism, accurate anatomy and cloth, hand-inked contours over cinematic painted realism, cool key and cyan rim. Real RGBA transparency; no checkerboard, background, gradient, scenery, floor, shadow, readable text or watermark.
```
