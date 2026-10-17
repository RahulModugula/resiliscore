---
name: ResiliScore underwriting workspace
description: Parcel evidence and underwriting decisions in a dense adaptive workspace
colors:
  dark-bg: "#0b1519"
  dark-surface: "#101f25"
  dark-surface-raised: "#182b32"
  dark-border: "#2a4049"
  dark-text: "#eaf1f3"
  dark-muted: "#a1b4bd"
  dark-accent: "#57d3df"
  dark-accent-ink: "#06232b"
  dark-accent-soft: "#16363e"
  dark-green: "#75dca7"
  dark-green-soft: "#15362c"
  dark-amber: "#f2c56e"
  dark-amber-soft: "#3b3020"
  dark-red: "#ff958a"
  dark-red-soft: "#3b2629"
  dark-water: "#78bbef"
  light-bg: "#edf2f3"
  light-surface: "#fff"
  light-surface-raised: "#f2f6f7"
  light-border: "#cbd7dc"
  light-text: "#152c36"
  light-muted: "#526b77"
  light-accent: "#087e8d"
  light-accent-ink: "#fff"
  light-accent-soft: "#e1f2f4"
  light-green: "#18724c"
  light-green-soft: "#e5f3eb"
  light-amber: "#866000"
  light-amber-soft: "#fff3d6"
  light-red: "#b13e36"
  light-red-soft: "#fceae7"
  light-water: "#226eac"
typography:
  headline:
    fontFamily: "IBM Plex Sans, sans-serif"
    fontSize: "24px"
    fontWeight: 500
    letterSpacing: "-0.5px"
  title:
    fontFamily: "IBM Plex Sans, sans-serif"
    fontSize: "14px"
    fontWeight: 500
  body:
    fontFamily: "IBM Plex Sans, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "IBM Plex Sans, sans-serif"
    fontSize: "11px"
    fontWeight: 400
rounded:
  control: "4px"
  panel: "6px"
  dialog: "8px"
spacing:
  compact: "8px"
  control: "12px"
  panel: "20px"
  section: "24px"
  desktop-gutter: "32px"
components:
  button-primary:
    backgroundColor: "{colors.dark-accent}"
    textColor: "{colors.dark-accent-ink}"
    rounded: "{rounded.control}"
    padding: "10px 14px"
    height: "44px"
  button-secondary:
    backgroundColor: "{colors.dark-surface-raised}"
    textColor: "{colors.dark-text}"
    rounded: "{rounded.control}"
    padding: "10px 14px"
  panel:
    backgroundColor: "{colors.dark-surface}"
    textColor: "{colors.dark-text}"
    rounded: "{rounded.panel}"
    padding: "20px"
---
# ResiliScore design system

## Overview

**Creative North Star: "Property underwriting workspace"**

The institutional workspace uses dense evidence rows, restrained surfaces, and a clear decision column. Dark forest and navy neutrals support the default demo; the light theme uses white panels on a pale cool background. This is an Operate interface for comparing property evidence and completing a review.

**Key Characteristics:**

- Spatial evidence and underwriting state share one workspace.
- Thin dividers organize dense data without decorative depth.
- Status color always has a text label.

## Colors

Cyan identifies the active scenario, current tab, credibility weight, and primary action. Green means eligible or verified; amber means conditional or awaiting review; red marks an exception or poor score. The frontmatter records both theme palettes. CSS variables in `src/app/globals.css` are the implementation source.

## Typography

IBM Plex Sans is self-hosted in weights 400, 500, and 600. Body text uses the body token; evidence labels range from 10 to 12 px. Page headings use the headline token and panel headings use the title token. Measurements use tabular numerals. JSON uses monospace. Prose descriptions stop at 75ch.

## Layout

The desktop container stops at 1,540 px, with 32 px gutters and a 1.85:1 spatial-to-score grid. At 1,100 px gutters tighten to 24 px. Below 850 px the score follows the spatial column; below 650 px gutters become 16 px and scenario controls, audit sections, mitigation rows, and inspection content stack. Tabs scroll horizontally. Dialogs retain a viewport margin and scroll internally.

## Elevation & Depth

Panels use tonal separation and a one-pixel border. Dialogs and search results use the overlay shadow from the sidecar. The dialog backdrop dims the workspace. Maps keep their own dark ground in either theme.

## Shapes

Controls use restrained square corners with the control radius. Panels use the panel radius; dialogs use the dialog radius. Native checkboxes remain recognizable. Focus outlines sit outside the control.

## Components

Primary buttons use the current theme accent or the score's semantic color. Secondary buttons use raised neutral surfaces. Buttons have a minimum 40 px target, with primary actions at 44 px. Hover changes the surface or brightness; disabled actions lower opacity. Keyboard focus uses a two-pixel accent outline. Reduced motion removes CSS transitions and score animation.

Scenario buttons show selected state with an accent border and tint. Tabs use an accent underline. Evidence rows pair a label with a supplied state. Native dialogs contain protected binding and review tasks, while the separate inspection route supports phone use.

The score gauge uses the supplied 300–850 scale. The map renders contract geometry over locally cached California aerial imagery or an illustrative Louisiana basemap. Aerial attribution and the synthetic-boundary notice remain visible. The freeboard chart uses supplied elevations; missing BFE produces hazard context instead of a fabricated diagram.

## Do's and Don'ts

- Do pair status colors with text.
- Do preserve focus visibility, responsive stacking, and reduced motion.
- Do distinguish cached aerial imagery from synthetic parcel boundaries.
- Don't imply that demo verification or binding is a real insurer transaction.
- Don't invent evidence weights, fairness results, regulatory approval, or missing elevations.
