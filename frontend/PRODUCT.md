# SaveMyHome frontend

SaveMyHome helps property underwriters compare a census-tract risk estimate with parcel evidence, test physical mitigations, and decide whether to bind or request human review. The frontend owns the cockpit and workflow surfaces described in docs/SPEC.md section 5, prompts 2A through 2D.

The demo starts from the shared golden scenarios and runs with the backend stopped. Users can select Louisiana flood, California wildfire, or Escondido verification scenarios, inspect parcel overlays, compare scores and premium, build an action plan, and inspect simulated workflow receipts. A live API option validates responses against the shared schema and falls back to the local demo on failure. Fonts, QR generation, and map imagery are local. California uses cached aerial imagery; Louisiana uses an illustrative basemap. Synthetic contract geometry is not surveyed to the imagery.

The core audience is an underwriter or broker presenting the evidence behind an eligibility decision. Desktop use places the parcel map and score together. Mobile use supports inspection and review without hiding the decision state.

Contracts in `../contracts/` define scenario values and response shapes. The frontend imports them through `src/data/goldenScenarios.ts`. Changes to those shared contracts require the user's authorization. `../docs/DECISIONS.md` records unresolved model choices and overrides the original blueprint where noted.

A completed demonstration must distinguish supplied evidence from simulated actions. It must pause binding during an escalated review, preserve unknown regulatory outcomes, and label every simulated verification or issued receipt. The UI does not establish that an insurer or regulator has accepted a real policy or filing. Phone inspection captures stay on their page; the review workbench runs its own capture to resolve an escalation. See `README.md` for the demo walkthrough and live API assumptions.
