# Node 12 Report

## Idea
Local bridge-risk prior from neighbor topology before feedback learning.

## Changes
- Added an isolated `EdgeLearningSolver` bridge-risk penalty in `/tmp/aegis-arbor-node12-slim.NBHzWN`.
- The prior penalizes candidate next hops with low local redundancy and poor outgoing link quality.
- The penalty is gated off for the destination and when there is no plausible alternate unvisited neighbor.

## Implementation Choices
- Kept the mechanism deterministic and local: one-hop neighbor sets, average outgoing loss, and average stability only.
- Tried a stronger default penalty (`0.55`) and then a weaker penalty (`0.18`) after the first B_dev run showed delivery loss.
- Did not modify protected benchmark/eval files in the main checkout and did not run B_test.

## Baseline vs Result
- Current trunk B_dev: `0.6845301005442892`
- First attempt B_dev: `0.6728092784773089`
- Best adjusted B_dev: `0.6719332010858522`

## Score
`0.6719332010858522`

## Analysis
The structural prior reduced Sybil exposure compared with several earlier failure modes, but it still diverted enough useful traffic to reduce delivery and robust score. The mechanism behaves like a softer form of previous over-suppression failures: it has better targeting than global concentration penalties, but the one-hop redundancy signal is not discriminative enough on the fixed B_dev scenarios.

## Insights
Topology-only gateway suspicion is too blunt at one hop. A future variant would need to condition the structural signal on packet pressure or learned edge outcomes instead of applying it as an always-on prior.
