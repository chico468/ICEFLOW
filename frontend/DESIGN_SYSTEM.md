# ICEFLOW design system

Version 2.0, the "daylight chart" system. Source of truth for tokens is `tailwind.config.js` plus the
CSS variables at the top of `src/index.css`. The map canvas cannot read CSS variables, so
`src/map/palette.ts` mirrors the same hues; change both together.

**Content rule.** The redesign changes presentation only. Every field, label, sentence, number and
panel from the original console is kept as it was. The only deliberate content changes are the ones
requested: the ICEFLOW header, the renamed tabs, and the removal of "How it works" and "Help".

## Principles

1. **The map is the product.** The chart is always full-bleed. Everything else floats over its margins
   or sits in the rail; nothing is docked beside it.
2. **Paper and ink.** A light chart: ice-white background, white instrument cards, deep ICEFLOWy text.
   It reads in a bright room and on a projector, where a dark interface washes out.
3. **Warm means something.** Orange marks the planned route; amber and red mean caution and danger. Blue
   is for actions only.
4. **One loud control per surface.** The primary action is the only solid-filled button.
5. **Colour is never alone.** Status always carries a word and, where possible, a shape.

## Structure (what replaced the old layout)

| Old | New |
|---|---|
| Top tab bar, dark navy | Masthead + left navigation rail (icon over label) |
| Full-width provenance banner under the header | One pill in the masthead; detail opens as a card |
| Planner form in a left column | Command bar across the top of the map |
| Result card stacked under the map | Floating result tray along the bottom |
| Side column of panels | Bottom shelf of instrument cards, collapsible |

After a route is planned, the command bar shrinks to a one-line summary (Edit reopens it), and the result
tray can be collapsed to its header.

## Tokens

### Colour (RGB triplets in `--c-*`)

| Token | Hex | Use |
|---|---|---|
| `ground` | #EDF2F4 | Page background, chart paper |
| `panel` / `panel-2` / `panel-3` | #FFFFFF / #F4F7F8 / #E8EFF2 | Cards / inputs / hover |
| `hair` / `hair-2` | #D3DDE2 / #AEBEC6 | Rules / input borders |
| `ink` / `ink-2` / `ink-3` | #0E2433 / #3D5666 / #587383 | Primary / secondary / tertiary text (ink-3 is about 5:1 on white) |
| `accent` / `accent-2` / `on-accent` | #0B5C8E / #084A73 / #FFFFFF | Actions, active nav, focus |
| `route` | #C2410C | The planned route |
| `ok` / `caution` / `warn` / `danger` | #1F7A4D / #A16207 / #B45309 / #B3261E | Good / simulated or caution / elevated / prohibited |
| `violet`, `teal` | #5B3FD1, #0F766E | Icebergs, stations |

Map: open water is pale glacial blue; sea-ice concentration darkens from steel to deep blue as it
thickens; land is sand-grey with a darker edge; labels are ink with a paper halo.

### Type
Section titles and headline figures use a display serif stack (Iowan Old Style, Palatino, Georgia);
everything else uses a humanist sans stack (Avenir Next, Segoe UI, system-ui). Figures use tabular lining
numerals in the same face, with no monospace. Nothing is smaller than 12 px, and nothing is upper-cased
or letter-spaced for effect. No web fonts are downloaded, so the app stays offline-capable.

### Shape and depth
Cards 12 px radius with a hairline contact shadow (`shadow-card`); floating cards 16 px with a longer
ambient shadow (`shadow-float`); controls 8 to 12 px; chips and switches fully round. Motion is 160 ms on
state changes only, and reduced-motion preferences are respected.

## Components

**MapStage.** Full-bleed map with optional `top` (command bar), `tray` (bottom result) and `shelf` (row of
cards). It measures what it covers and publishes `StageInsets` so routes are framed in the visible area and
the zoom controls and scale bar stay clear. The shelf's open state persists and defaults closed on short
windows.

**Panel.** An instrument card: white, ruled, titled in the display serif. In a shelf each card is 340 px
wide and scrolls on its own.

**Nav rail.** 88 px wide; each item is an icon over a short label; the active item is a filled accent tile.

**Provenance pill.** Amber pill in the masthead; opens a card listing simulated and real sources.
Accessible: `aria-expanded`, Escape and outside-click close.

**Form controls.** `Select`, `Slider`, `Toggle` (a switch, `role="switch"`), `Disclosure` (native
`<details>`). **Buttons:** `btn` secondary, `btn btn-accent` the single primary action, `btn-icon` for map controls.

**ComputeOverlay.** Covers the map during long calls, with the original steps and an elapsed clock.

## Known gaps

- The growler-radar scope stays dark deliberately, as an instrument window inside a light card.
- A dark "night" theme is a token swap away but needs a theme-aware map palette; not built.
- Some chart colours were retuned by search and replace; check the Insights charts by eye.
- `SimulatedNotice.tsx` (component): persistent inline notice for simulated-environment route results. Uses `caution` token with icon + text (`role="note"`), never colour alone. Text: "Planned on simulated ice and weather. Not for navigation." This is a deliberate content addition.
