# Node 4: Two-profile bandit

## Result

- Baseline B_dev score: `0.6355613879111393`
- Current trunk B_dev score: `0.6845301005442892`
- Node 4 B_dev score: `0.6669743086973007`
- Mean delivery: `0.6048828203201181`
- Mean Sybil touch ratio: `0.12305470421882768`
- Maximum scenario Sybil touch ratio: `0.14142051638978148`
- Mean drop ratio: `0.3951171796798819`

The bandit improved over the original production baseline but did not beat the
current security-heavy trunk profile on the fixed development suite.

## Implementation

- Deterministic contextual bandit with decayed rewards, exploration bonus, and
  hysteresis.
- Context combines recent local and global drop/Sybil pressure.
- Delivery-heavy and security-heavy `EdgeLearningSolver` instances use separate
  persistent state files.
- A bounded per-edge FIFO attributes terminal outcomes to the policy that chose
  the reported edge.
- Only the responsible policy receives the outcome and updates its persistent
  edge learning.

## Validation

- `python3 -m py_compile aegis_router/solvers.py scripts/heavy_secure_search.py tests/test_two_profile_bandit.py`
- Seven focused unit tests passed before final tuning.
- B_dev only was evaluated. B_test was not run.
