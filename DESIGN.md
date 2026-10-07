---
name: "AI Storage Mover"
description: "A quiet, modern desktop workspace for choosing and moving local AI storage."
colors:
  canvas: "#f7f8fa"
  surface: "#fff"
  text: "#20232b"
  muted: "#606575"
  line: "#dce0e7"
  accent: "#5357d8"
  accent-ink: "#fff"
  tint: "#eeefff"
  hover: "#edeff4"
  warning: "#fff7e7"
  warning-ink: "#805600"
  danger: "#ad3333"
  danger-tint: "#fff0ef"
  success: "#23775c"
  focus: "#5357d8"
  dark-canvas: "#17191f"
  dark-surface: "#20232b"
  dark-text: "#f0f1f5"
  dark-muted: "#b0b5c2"
  dark-line: "#383d49"
  dark-accent: "#a7a9ff"
  dark-accent-ink: "#202147"
  dark-tint: "#2e3049"
  dark-hover: "#30343e"
  dark-warning: "#352d1e"
  dark-warning-ink: "#f4ce7c"
  dark-danger: "#ffb0ab"
  dark-danger-tint: "#372628"
  dark-success: "#89d3b8"
  dark-focus: "#a7a9ff"
typography:
  headline:
    fontFamily: "Inter, sans-serif"
    fontSize: "30px"
    fontWeight: 620
    lineHeight: 1.2
    letterSpacing: "-.03em"
  headline-compact:
    fontFamily: "Inter, sans-serif"
    fontSize: "27px"
    fontWeight: 620
    lineHeight: 1.2
    letterSpacing: "-.03em"
  title:
    fontFamily: "Inter, sans-serif"
    fontSize: "16px"
    fontWeight: 620
    lineHeight: 1.4
    letterSpacing: "-.01em"
  body:
    fontFamily: "Inter, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Inter, sans-serif"
    fontSize: "13px"
    fontWeight: 600
    lineHeight: 1.5
  button:
    fontFamily: "Inter, sans-serif"
    fontSize: "14px"
    fontWeight: 550
    lineHeight: 1.5
  path:
    fontFamily: "Inter, sans-serif"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.55
rounded:
  control: "8px"
  notice: "10px"
  list: "14px"
  marker: "50%"
spacing:
  tight: "8px"
  control: "12px"
  group: "16px"
  row: "18px"
  sidebar: "20px"
  empty: "24px"
  workspace-compact: "28px"
  workspace: "38px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-ink}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "9px 15px"
    height: "40px"
  button-primary-dark:
    backgroundColor: "{colors.dark-accent}"
    textColor: "{colors.dark-accent-ink}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "9px 15px"
    height: "40px"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "9px 15px"
    height: "40px"
  button-secondary-hover:
    backgroundColor: "{colors.hover}"
  button-secondary-dark:
    backgroundColor: "{colors.dark-surface}"
    textColor: "{colors.dark-text}"
  button-secondary-dark-hover:
    backgroundColor: "{colors.dark-hover}"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.text}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "9px 15px"
    height: "40px"
  button-quiet-hover:
    backgroundColor: "{colors.hover}"
  button-quiet-dark:
    backgroundColor: "transparent"
    textColor: "{colors.dark-text}"
  button-quiet-dark-hover:
    backgroundColor: "{colors.dark-hover}"
  button-danger:
    backgroundColor: "{colors.danger-tint}"
    textColor: "{colors.danger}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "9px 15px"
    height: "40px"
  button-danger-hover:
    backgroundColor: "{colors.hover}"
  button-danger-dark:
    backgroundColor: "{colors.dark-danger-tint}"
    textColor: "{colors.dark-danger}"
  button-danger-dark-hover:
    backgroundColor: "{colors.dark-hover}"
  text-field:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "10px 12px"
    height: "42px"
    width: "100%"
  text-field-dark:
    backgroundColor: "{colors.dark-surface}"
    textColor: "{colors.dark-text}"
  step-current:
    backgroundColor: "{colors.tint}"
    textColor: "{colors.accent}"
    rounded: "{rounded.control}"
    padding: "11px 12px"
    height: "48px"
  step-current-dark:
    backgroundColor: "{colors.dark-tint}"
    textColor: "{colors.dark-accent}"
  folder-list:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.list}"
  folder-list-dark:
    backgroundColor: "{colors.dark-surface}"
    textColor: "{colors.dark-text}"
  progress-track:
    backgroundColor: "{colors.line}"
    rounded: "{rounded.control}"
    height: "8px"
  progress-track-dark:
    backgroundColor: "{colors.dark-line}"
  notice-warning:
    backgroundColor: "{colors.warning}"
    textColor: "{colors.warning-ink}"
    rounded: "{rounded.notice}"
    padding: "15px 16px"
  notice-warning-dark:
    backgroundColor: "{colors.dark-warning}"
    textColor: "{colors.dark-warning-ink}"
  notice-danger:
    backgroundColor: "{colors.danger-tint}"
    textColor: "{colors.danger}"
    rounded: "{rounded.notice}"
    padding: "15px 16px"
  notice-danger-dark:
    backgroundColor: "{colors.dark-danger-tint}"
    textColor: "{colors.dark-danger}"
---

# Design System: AI Storage Mover

## Overview

**Creative North Star: "A quiet, modern desktop workspace"**

A quiet, modern desktop workspace for a consequential file operation. Folder paths are the primary content; concise typography, lightly outlined lists and a restrained violet accent keep selection, review and progress easy to scan. The confirmed direction replaces the rejected Windows-2000-style Tk interface with a modern interactive desktop surface.

The system follows Windows appearance by default and offers explicit light and dark choices within the current window. Both themes keep the same hierarchy and component geometry. Original copies, progress and optional cleanup remain visibly distinct, with caution expressed through clear text and semantic color. Copy names the current decision and explains actual work; idle status badges and repeated reassurance are omitted.

**Key Characteristics:**

- Folder paths and useful actions lead the interface.
- Persistent setup navigation and footer actions provide orientation.
- Direct task labels and status only while useful.
- Flat surfaces, thin borders and restrained semantic color.
- Locally bundled typography, visible keyboard focus and reduced-motion support.

This refresh records the implemented replacement world in `src/ai_storage_mover/desktop/style.css`, `index.html`, `app.js` and `gui.py`. It merges the same-task provisional direction with final code. Existing captures under `.runs/ui-preview-modern/` are synthetic UI fixtures; no approved comp or FORM seed was supplied. The frontmatter records actual CSS values; the sidecar extends them with motion, depth, responsive behavior and renderable component examples.

## Colors

The palette uses a single violet action accent, cool neutral surfaces and separate warning, danger and success colors. Frontmatter keys without a prefix describe light mode; `dark-` keys describe the corresponding dark overrides. At runtime both palettes use the same CSS custom-property names.

### Primary

- **Accent:** primary actions, current setup step, transfer fill and route arrows.
- **Accent ink:** text and icons on filled accent controls.
- **Tint:** the current navigation step's soft background.
- **Focus:** the keyboard outline; it matches the action accent in each theme.

### Neutral

- **Canvas:** sidebar, appearance selector and confirmation phrase surface.
- **Surface:** main workspace, fields and outlined list interiors.
- **Text:** primary content; also the toast surface.
- **Muted:** supporting copy, secondary path text and inactive navigation.
- **Line:** thin borders, dividers, progress track and scrollbars.
- **Hover:** the shared hover background for eligible outlined, quiet and danger buttons.

### Semantic status

- **Warning / warning ink:** the manual-backup notice and its readable text.
- **Danger / danger tint:** error feedback, irreversible-cleanup notice and destructive action.
- **Success:** completed-step checks, completed task icons and the completion heading.

**The Appearance Rule.** Follow Windows by default; keep Light and Dark available without changing the layout or the meaning of status colors.

No secondary or tertiary brand palette is established. Sidecar tonal ramps are derived swatch previews, not additional colors used by the app.

## Typography

**Display and body font:** Inter variable, bundled locally as `InterVariable.woff2`, with a sans-serif fallback. The font face exposes weights from 100 to 900, so intermediate weights are intentional.

A compact type hierarchy gives folder data room while keeping the current task prominent. The hierarchy uses the frontmatter's observed roles; there is no oversized display type.

- **Headline:** the page heading, with tight tracking. Its actual weight is (620); compact windows change its size while retaining its weight and line height.
- **Title:** group headings, also at (620), with less-negative tracking than the page heading.
- **Body:** introductory and ordinary content. Introductory paragraphs are capped at (70ch).
- **Label:** explicit field labels.
- **Button:** control text with an intermediate weight (550).
- **Path:** smaller, muted folder text with a looser line height. Paths remain selectable and wrap anywhere.

Supporting metadata and navigation use observed sizes from (10px) to (13px). Progress counts, elapsed time and step numbers use tabular numerals. Descriptive row titles use weight (600); notice titles and progress percentages use (650).

Task headings name the decision directly: `Choose projects.`, `Choose destination.`, `Select data and temp.`, and `Review migration.`

**The Useful Copy Rule.** Name the current decision directly. Show paths, actual work and consequential warnings; omit idle status badges, redundant header labels, repeated empty-state instructions, technical reassurance strips and repeated reassurance.

## Layout

The native desktop window starts at (1120 × 790px) and has a minimum size of (850 × 660px). The app fills the viewport with a fixed-width sidebar and a flexible workspace; its CSS minimum height is (570px). This is a desktop layout, with no implemented mobile breakpoint.

The sidebar is (222px) wide. The workspace is positioned relatively; the independently scrolling main pane starts with (38px) top padding. A footer with a minimum height of (84px) keeps the actions visible. Main content and footer share horizontal gutters of (38px). The active-status header is positioned absolutely at (44px) from the top and (38px) from the right, and is hidden while idle. Space separates meaningful groups rather than enclosing every group in a card.

The implemented compact breakpoint is `max-width: 960px`. At that width and below, the sidebar becomes (184px), workspace gutters and the active-status header's right offset become (28px), headings use the compact headline token and list rows tighten from (17px 18px) to (15px 14px). Main top padding stays (38px). The persistent navigation remains in the sidebar.

Source-to-destination rows use two equal columns around a (24px) arrow column with (12px) gaps; compact windows reduce the arrow column to (20px) and gaps to (8px). Future temp locations use two equal columns with (18px) gaps. Their browse controls wrap beneath the fields.

Long lists scroll within their outlined containers: discovery and data lists cap at (280px), review at (235px), and retained originals at (155px). Paths wrap anywhere and flexible row content uses a zero minimum width. The spacing frontmatter contains recurring observed values rather than a fabricated uniform scale.

## Elevation & Depth

Ordinary workspace surfaces stay flat. Canvas and surface tones, one-pixel outlines and dividers carry the hierarchy in both themes. The transient toast alone uses the extracted shadow `0 6px 24px #0003`; it is documented in the sidecar, outside the frontmatter's supported schema.

**The Flat Workspace Rule.** Use tonal surfaces and thin borders for ordinary containers. Reserve the existing shadow for transient toast feedback.

Motion is short and tied to state: background-color transitions take (120ms), transfer-fill width takes (250ms), and page entry is a (180ms) upward settle from (5px) with no opacity change. The precise easing values live in the sidecar. Reduced-motion preference removes all animation and transitions.

## Shapes

Controls and the progress track use gently curved corners; notices are slightly softer, and enclosing lists use the largest radius. Circular step numbers provide compact navigation markers. The frontmatter records the actual control, notice, list and circular marker radii.

One-pixel borders define controls, lists and separators. Ordinary icons are inline SVG with (20 × 20px) bounds, consistent (1.7px) strokes, and round caps and joins. The brand mark and a few empty/success states use larger instances of the same line language.

## Components

### Buttons

Clear, compact actions with a minimum height of (40px). Primary buttons use accent and accent-ink; outlined buttons use surface and text; quiet buttons remove the visible border and fill. Destructive buttons use danger text and border on danger-tint.

Eligible controls use the shared hover background. Primary hover retains its accent and uses brightness (1.07). All button variants retain a visible focus ring; disabled buttons reduce opacity to (0.45) and stop acting. Base padding is (9px 15px); icon-only controls are (40px) wide with (8px) padding. The frontmatter `height` values describe implemented minimum heights, not fixed clipping heights.

### Inputs / Fields

Text fields and native selects use a one-pixel outline, surface fill, control radius and (10px 12px) padding. Their minimum height is (42px). Fields have explicit labels and muted help when useful. Browse opens the native folder picker. Typing either the storage folder or projects folder immediately updates visible destination rows, preserving individually chosen destination overrides. Checkboxes retain the native shape at (18 × 18px) with the accent color.

Interactive focus is a (2px) outline using the focus token, offset by (3px). Page headings receive programmatic focus after navigation without a decorative outline.

### Navigation

Four numbered setup steps sit in the persistent sidebar. Step buttons use (48px) minimum height and (11px 12px) padding. The active step has tint and accent text, with a filled accent number. Completed steps show a success check. Future steps and navigation during an active operation are disabled. The appearance selector offers Follow Windows, Light and Dark. Follow Windows is the default; users can switch appearance within the current window, and system mode reacts to Windows preference changes.

The entire header is hidden while idle. It shows Finding folders… during an actual discovery scan, then hides when the operation finishes. Step orientation stays in the sidebar; repeated step counts and section labels are absent above the task heading. Retention guidance appears where it explains a decision or consequence; there is no repeated originals reminder in the sidebar or footer.

### Cards / Containers

Outlined lists are the recurring container. They use the list radius and a surface fill, with no shadow. Rows use a folder icon, a stronger short name, the full muted path and an explicit row action. Borders divide rows without extra card spacing. The empty project list contains one centered Choose a folder button with its folder icon inside. The icon inherits the button foreground in both themes; no detached icon or repeated title/instructions sit beside it. Review contains the actual routes, future temp locations and relevant confirmations, with no technical reassurance strip.

### Notices and cleanup confirmation

Warning notices place an inline caution icon beside a short bold lead and useful supporting copy. Irreversible cleanup uses danger colors and retains its own screen, exact phrase and checked-project acknowledgment. The phrase is selectable on a canvas-colored outlined block. Errors appear in a bounded alert above the footer; cleanup stays optional after successful migration.

### Progress

A single continuous track uses line behind an accent fill. It accompanies the current operation, measured percentage, count or transfer bytes, elapsed time and current detail. Task rows change from muted to active text to success as phases complete. A Stop safely action remains available. Component previews are static synthetic examples; actual transfer values come from the Python bridge's snapshots.

## Do's and Don'ts

### Do:

- Do use the locally bundled Inter variable font and the extracted heading weights.
- Do use the paired light and dark semantic tokens and keep Follow Windows as the default appearance.
- Do name decisions directly and show status only when it explains actual work.
- Do wrap and allow selection of full folder paths, while keeping explicit browse, change, remove and open controls.
- Do keep progress tied to backend measurements and show the current operation, counts and elapsed time.
- Do keep optional cleanup separate, with a danger notice, exact phrase and checked-project acknowledgment.
- Do preserve visible keyboard focus and disable transitions and animation for reduced motion.

### Don't:

- Don't return to stock Tk controls or the rejected Windows-2000-style visual treatment.
- Don't add terminal commands to ordinary setup.
- Don't show idle status badges, redundant header labels, repeated empty-state instructions or technical reassurance strips.
- Don't repeat reassurance in the sidebar and footer.
- Don't add decorative charts, remote fonts or ornamental shadows to the workspace.
- Don't imply that displayed screenshot or component-preview progress proves a completed migration.
