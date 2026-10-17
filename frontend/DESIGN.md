# Underwriting workspace design

The workspace implements docs/SPEC.md section 5 in Operate mode. Its priority is the underwriting decision, with spatial evidence beside the parcel score. A dark forest and navy palette suits the dense desktop demo; the theme control supplies a full light palette for brighter rooms.

## Layout and type

The desktop workspace uses a 1.85:1 split between the spatial column and score panel. Each section shares a 1,540 px maximum width. Below 850 px the score follows the map; below 650 px scenario selection, property context, mitigation controls, and dialogs stack. Tabs can scroll horizontally without widening the page.

IBM Plex Sans is installed and served locally at weights 400, 500, and 600. Use 14 px body text, 10–12 px evidence labels, 14 px panel headings, and 20–24 px page headings. Monetary values and measurements use tabular numerals. Codes and JSON use monospace only where necessary.

## Tokens and states

`globals.css` owns theme tokens on `.app-shell[data-theme]`. Dark defaults are `--bg: #0b1519`, `--surface: #101f25`, `--text: #eaf1f3`, `--muted: #a1b4bd`, and `--accent: #57d3df`. Light defaults are `#edf2f3`, `#fff`, `#152c36`, `#526b77`, and `#087e8d` respectively.

Cyan identifies selected scenarios, active tabs, evidence weight, and primary actions. Green means verified or eligible, amber means conditional or awaiting review, and red marks an exception or poor score. Text accompanies status colors. Panels have thin neutral borders and restrained 4–6 px radii. Avoid decorative gradients and status glow.

Controls have visible keyboard focus and at least 40 px height. Native checkboxes retain their affordance; their surrounding label enlarges the target. Motion explains score and evidence changes. Reduced motion removes CSS animation and transitions. The fixed dark spatial canvas retains contrast in either page theme.

## Evidence presentation

Contract geometry remains distinct from the illustrative basemap. Missing BFE produces hazard context instead of a fabricated freeboard diagram. Binding receipts, mobile verification, audit exhibits, and projected mitigation changes must carry their demo status. Source precision weights and fairness outcomes must remain unknown when absent from the contract.
