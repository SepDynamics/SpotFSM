# Investor Pitch Deck Visual Assets Walkthrough

This walkthrough summarizes the current pitch-deck assets generated from the
repo-backed visual plan in [plans/INVESTOR_PITCH_VISUAL_PLAN.md](plans/INVESTOR_PITCH_VISUAL_PLAN.md).

Rendered assets live under `assets/pitch/`. Chart and explainer exports are
now saved with an explicit dark background so they render correctly in docs and
outside the final deck canvas.

## Full Slide Renders

These are self-contained slide compositions, not just supporting graphics.

- Slide 1: [problem_full.png](assets/pitch/slide1/problem_full.png)
- Slide 4: [defensible_full.png](assets/pitch/slide4/defensible_full.png)
- Slide 6: [live_evidence_full.png](assets/pitch/slide6/live_evidence_full.png)
- Slide 7: [portfolio_management_full.png](assets/pitch/slide7/portfolio_management_full.png)
- Slide 11: [the_ask_full.png](assets/pitch/slide11/the_ask_full.png)
- Slide 12: [risk_disclosures_full.png](assets/pitch/slide12/risk_disclosures_full.png)
- Generator: [generate_full_slide_renders.py](scripts/tools/generate_full_slide_renders.py)

## Rendered Slides

### Slide 2: Insight Explainer

Conceptual encoding walkthrough for the 64-candle -> 8-bit -> 512-bit manifold
idea described in the deck and architecture docs.

![Insight Explainer](assets/pitch/slide2/insight_explainer.png)

Sources:
- [plans/INVESTOR_PITCH_DECK.md](plans/INVESTOR_PITCH_DECK.md)
- [plans/ARCHITECTURE.md](plans/ARCHITECTURE.md)
- [scripts/tools/generate_slide2_explainer.py](scripts/tools/generate_slide2_explainer.py)

### Slide 3: Architecture Diagram

Graphviz system diagram matching the repo's documented service flow: OANDA ->
`sep-streamer` -> Valkey -> `sep-regime` -> `sep-backend` -> `sep-frontend`,
with order execution returning to OANDA.

![System Architecture](assets/pitch/slide3/architecture.png)

Sources:
- [README.md](README.md)
- [plans/ARCHITECTURE.md](plans/ARCHITECTURE.md)
- [assets/pitch/slide3/architecture.dot](assets/pitch/slide3/architecture.dot)

### Slide 5: Signal Mechanics

Updated to reflect the documented implementation: encoded candle bits are
assembled into a byte-stream, analyzed by the C++ manifold engine, and then
evaluated against per-pair guard thresholds before admission.

![Signal Mechanics](assets/pitch/slide5/signal_mechanics.png)

Sources:
- [plans/ARCHITECTURE.md](plans/ARCHITECTURE.md)
- [assets/pitch/slide5/signal_mechanics.dot](assets/pitch/slide5/signal_mechanics.dot)

### Slide 6: Live Evidence

Data-native charts generated directly from the live trade log in
[plans/trades.csv](plans/trades.csv). Note that the file is tab-delimited.

![Cumulative PnL](assets/pitch/slide6/cumulative_pnl.png)
![Pair PnL](assets/pitch/slide6/pair_pnl_bar.png)
![Win Rate and Volume](assets/pitch/slide6/winrate_heatstrip.png)

Sources:
- [plans/trades.csv](plans/trades.csv)
- [scripts/tools/generate_slide6_charts.py](scripts/tools/generate_slide6_charts.py)

### Slide 7: Portfolio Management

Policy cascade derived from the live portfolio policy values and deck copy.

![Portfolio Management](assets/pitch/slide7/portfolio_management.png)

Sources:
- [config/portfolio_policy.yaml](config/portfolio_policy.yaml)
- [assets/pitch/slide7/portfolio_management.dot](assets/pitch/slide7/portfolio_management.dot)

### Slide 8: Research Infrastructure

Promotion pipeline diagram showing GPU sweep -> multi-window validation ->
promoted params -> live YAML -> parity audit -> runtime. This slide communicates
curve-fitting controls; it does not claim immunity to overfitting.

![Research Pipeline](assets/pitch/slide8/research_pipeline.png)

Sources:
- [plans/INVESTOR_PITCH_DECK.md](plans/INVESTOR_PITCH_DECK.md)
- [README.md](README.md)
- [assets/pitch/slide8/research_pipeline.dot](assets/pitch/slide8/research_pipeline.dot)

### Slide 9: Roadmap

Rendered technical timeline based on the source roadmap copy, with distinct
stages for current operations, near-term infrastructure work, and medium-term
universe expansion.

![Roadmap](assets/pitch/slide9/roadmap.png)

Sources:
- [assets/pitch/slide9/roadmap.md](assets/pitch/slide9/roadmap.md)
- [scripts/tools/generate_slide9_roadmap.py](scripts/tools/generate_slide9_roadmap.py)

### Slide 10: Differentiation

Rendered editorial scorecard comparing SEP against a typical small-systematic
stack across source, bridge, resolution, exits, and audit trail.

![Differentiation](assets/pitch/slide10/scorecard.png)

Sources:
- [assets/pitch/slide10/scorecard.md](assets/pitch/slide10/scorecard.md)
- [scripts/tools/generate_slide10_scorecard.py](scripts/tools/generate_slide10_scorecard.py)

### Slide 11: The Ask

Use-of-funds / milestone flow aligned to the deck's ask and the `$100k+`
evidence-window milestone.

![The Ask](assets/pitch/slide11/the_ask.png)

Sources:
- [plans/INVESTOR_PITCH_DECK.md](plans/INVESTOR_PITCH_DECK.md)
- [assets/pitch/slide11/the_ask.dot](assets/pitch/slide11/the_ask.dot)

## Source Copy Assets

These markdown files remain the copy source for the rendered Slide 9 and Slide
10 visuals.

- [assets/pitch/slide9/roadmap.md](assets/pitch/slide9/roadmap.md)
- [assets/pitch/slide10/scorecard.md](assets/pitch/slide10/scorecard.md)

## Verification Notes

- Rendered PNG and SVG files now exist for Slides 2, 3, 5, 6, 7, 8, 9, 10, and 11.
- Slide 6 metrics match the live trade log totals in `plans/trades.csv`.
- Slide 5 and Slide 11 copy were corrected to align with the deck and
  architecture docs.
- Full-slide compositions now exist for Slides 1, 4, 6, 7, 11, and 12.
- The rendered assets follow the dark technical visual direction set in
  [plans/INVESTOR_PITCH_VISUAL_PLAN.md](plans/INVESTOR_PITCH_VISUAL_PLAN.md).
