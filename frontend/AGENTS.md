# Frontend work

Read `../docs/SPEC.md` section 5 for prompts 2A through 2D and `../docs/DECISIONS.md` for refinements. This directory is the frontend ownership boundary.

`../contracts/parcel_score_schema.json` and `../contracts/golden_scenarios.json` are shared inputs. Get the user's authorization before editing contracts or the matching types. Import the fixtures through `src/data/goldenScenarios.ts` rather than copying their values.

Keep every demo flow usable with the backend stopped. Label simulated verification, binding receipts, and regulatory evidence as demo data. Missing evidence must remain unknown.

Use branches named `f/<topic>` and open PRs against `main`. Run `npm run lint && npm run build` from this directory before pushing, and check PR CI. Use Codex tools and `AGENTS.md` for agent instructions.
