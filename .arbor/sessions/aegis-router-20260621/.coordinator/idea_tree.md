# Idea Tree

**Baseline**: 0.6356 | **Trunk**: 0.6845

## ROOT: Optimize Aegis Router routing logic for adversarial dynamic networks. Maximize delivery, minimize sybil_touch_ratio, packet loss, latency, and route length; generalize across unseen seeds/scenarios; keep tests, benchmark, and metric formulas untouched; protect B_test and preserve APIs. Build a fixed dev/test benchmark for stealth Sybils, churn, congestion, and multiple graph sizes/densities before deeper optimization. [DONE]

**Insight**: Children findings: [1, pruned, score=0.6959] La sélection CVaR sur dev trouve un profil performant localement, mais son score held-out chute fortement; les cinq scénarios dev ne couvrent pas assez le régime Sybil à 15%. [Pruned: Surapprentissage dev: B_test 0.340566 très inférieur au trunk validé 0.424291.] | [2, pruned] [Pruned: Regression on the fixed dev/test benchmark: robust score dropped from 0.6356 to 0.5855 on dev and from 0.3000 to 0.2866 on test, so the latent-hazard formulation is not a net win in its current form.] | [3, pruned, score=0.6875] Une faible mémoire positive d'arêtes avec répulsion courte améliore légèrement B_dev, mais le gain ne généralise pas au held-out; la rétroaction limitée au dernier saut réduit probablement la qualité du crédit causal. [Pruned: Le gain dev ne se généralise pas: B_test 0.422692 inférieur au trunk 0.424291.] | [4, pruned, score=0.667] Le sélecteur contextuel à deux profils améliore le baseline mais ne dépasse pas le profil sécurité fixe; le coût d'apprentissage et les commutations n'apportent pas de gain robuste sur ce dev fixe. [Pruned: Dev score 0.666974 inférieur au trunk 0.684530; pas de justification pour exposer B_test ou fus...

### 1: Mechanism: CVaR tail-risk scorer over fixed scenario windows
Hypothesis: optimize the lower tail of delivery and the upper tail of Sybil exposure across the fixed dev scenarios so the router stops overfitting lucky seeds and improves worst-case robustness without changing the benchmark or metric formulas.
Observable: higher dev robust_score, lower max_sybil, and smaller score variance across seeds.
Conflicts: none - attacks the objective aggregation axis rather than local link tuning. [PRUNED] (score: 0.6959)

**Insight**: La sélection CVaR sur dev trouve un profil performant localement, mais son score held-out chute fortement; les cinq scénarios dev ne couvrent pas assez le régime Sybil à 15%.
[Pruned: Surapprentissage dev: B_test 0.340566 très inférieur au trunk validé 0.424291.]

**Result**: B_dev 0.695938 > trunk 0.684530, mais B_test 0.340566 < trunk 0.424291; profil rejeté et non promu.

### 2: Mechanism: Latent hazard filter for nodes and edges
Hypothesis: maintain a hidden risk belief per node and per directed edge inferred from delayed loss, churn, and queue signals so the router can anticipate stealth Sybil behavior before repeated failures and cut sybil_touch_ratio on unseen seeds.
Observable: fewer Sybil touches and link-loss drops on held-out seeds with similar delivery.
Conflicts: none - attacks representation and inference rather than heuristic weighting. [PRUNED]

**Insight**: [Pruned: Regression on the fixed dev/test benchmark: robust score dropped from 0.6356 to 0.5855 on dev and from 0.3000 to 0.2866 on test, so the latent-hazard formulation is not a net win in its current form.]

### 3: Mechanism: Pheromone-repulsion memory with fast decay
Hypothesis: reinforce successful edges like ant pheromones, but decay them quickly after delayed drops or Sybil hits and add a local repulsion field around recently bad nodes so the router avoids deceptive hubs under churn.
Observable: lower average hops and latency, fewer loops, and stable delivery on sparse graphs.
Conflicts: none - attacks path memory and exploration policy rather than the benchmark. [PRUNED] (score: 0.6875)

**Insight**: Une faible mémoire positive d'arêtes avec répulsion courte améliore légèrement B_dev, mais le gain ne généralise pas au held-out; la rétroaction limitée au dernier saut réduit probablement la qualité du crédit causal.
[Pruned: Le gain dev ne se généralise pas: B_test 0.422692 inférieur au trunk 0.424291.]

**Result**: B_dev 0.687493 > trunk 0.684530, mais B_test 0.422692 < trunk 0.424291; candidat rejeté sans fusion.

### 4: Mechanism: Two-profile bandit selector over edge routing policies
Hypothesis: switch between the delivery-heavy and security-heavy edge profiles using recent packet outcomes and local churn/sybil pressure so mixed scenarios can get the best of both behaviors instead of averaging them away.
Observable: higher robust_score on the fixed dev suite and lower max_sybil on the held-out stress scenario without changing any benchmark code.
Conflicts: none - attacks runtime policy selection rather than per-edge scoring. [PRUNED] (score: 0.667)

**Insight**: Le sélecteur contextuel à deux profils améliore le baseline mais ne dépasse pas le profil sécurité fixe; le coût d'apprentissage et les commutations n'apportent pas de gain robuste sur ce dev fixe.
[Pruned: Dev score 0.666974 inférieur au trunk 0.684530; pas de justification pour exposer B_test ou fusionner.]

**Result**: B_dev 0.666974, livraison 0.604883, sybil moyen 0.123055, max_sybil 0.141421; inférieur au trunk 0.684530. B_test non exécuté.

### 5: Mechanism: Path-level eligibility traces for delayed routing feedback
Hypothesis: distribute terminal delivery, drop, loop, and Sybil feedback backward across the actual packet path with decaying eligibility so earlier deceptive edges receive causal credit instead of blaming only the final hop.
Observable: higher B_dev robust_score with lower Sybil exposure and fewer repeated bad-route failures, especially on sparse scenarios.
Conflicts: pruned [3] found last-hop pheromone credit did not generalize; this counters it by assigning delayed outcomes across the full traversed path. [PRUNED] (score: 0.6816)

**Insight**: Le crédit sur chemin complet fonctionne mais attribue trop largement le signal terminal; il réduit légèrement Sybil au prix de livraison. Une attribution conditionnelle par cause serait nécessaire.
[Pruned: B_dev 0.681648 inférieur au trunk 0.684530; pas de validation B_test.]

**Result**: B_dev 0.681648, inférieur au trunk 0.684530; B_test non exécuté.

### 6: Mechanism: Adversarial domain-randomized learning curriculum
Hypothesis: train persistent edge memory across procedurally varied Sybil ratios, stealth, churn, congestion, graph sizes, and densities before evaluation so the learned state represents invariant risk signals rather than the five fixed dev regimes.
Observable: maintain or improve B_dev robust_score while reducing variance across dev scenarios and avoiding the high-pressure collapse seen in prior held-out checks.
Conflicts: pruned [1] overfit fixed dev scenario ranking; this counters it through broader training distributions while leaving the official benchmark and protected test untouched. [PRUNED] (score: 0.6744)

**Insight**: La randomisation de domaine apporte un vrai transfert et réduit fortement l'exposition Sybil par rapport à son contrôle, mais les statistiques contextuelles restent trop grossières et réduisent la livraison.
[Pruned: B_dev 0.674405 inférieur au trunk 0.684530; branche conservée comme preuve mais non fusionnée.]

**Result**: B_dev 0.674405, inférieur au trunk 0.684530; amélioration de 0.031641 face au contrôle; B_test non exécuté.

**Branch**: coordinator/n6-mechanism-adversarial-domain-ran-0a7b855f

### 7: Mechanism: Concentration-aware route diversification with local structural suspicion
Hypothesis: penalize repeated dependence on the same transit nodes and edges while using only observable local topology and outcome history to spread traffic across structurally independent routes, reducing the chance that one deceptive Sybil hub captures many packets.
Observable: lower B_dev max_sybil and route concentration without materially increasing hops, latency, or packet loss.
Conflicts: pruned [2] used a latent hazard belief and regressed; this counters via explicit route concentration and observable structural diversity rather than hidden-risk inference. [PRUNED] (score: 0.687)

**Insight**: Light route concentration penalties improved fixed B_dev but regressed held-out high-Sybil delivery; unconditional global usage penalties do not generalize. Future diversification needs a stronger local viability or congestion gate.
[Pruned: B_test regression: 0.387203 below validated trunk 0.424291 after B_dev improvement; candidate code removed from active checkout.]

**Result**: B_dev 0.687004 exceeded trunk 0.684530, but one merge-verification B_test scored 0.387203 below trunk 0.424291; rejected without merge.

### 8: Mechanism: Viability-shielded routing with a control-barrier action filter
Hypothesis: Filter high-risk neighbors only when at least one locally viable alternative preserves destination progress, queue headroom, and bounded projected loss, so security pressure cannot remove the last delivery-capable action as unconditional penalties did.
Observable: B_dev robust_score exceeds 0.684530 while delivery stays near trunk and max Sybil exposure falls without materially increasing hops or latency.
Conflicts: pruned [7] said unconditional concentration penalties over-diversify and pruned [6] said coarse risk penalties reduce delivery; this counters via a per-decision viability shield that leaves baseline ranking unchanged when no safe alternative exists. [PRUNED] (score: 0.6828)

**Insight**: A local viability proof prevents catastrophic over-filtering, but hard edge deletion has a narrow operating range: conservative gating nearly matches trunk without exceeding it, while broader gating collapses delivery.
[Pruned: B_dev 0.682830 did not exceed validated trunk 0.684530; B_test not authorized for a losing candidate.]

**Result**: Implemented and validated an optional directional viability shield in an isolated executor copy; B_dev scored 0.6828301562815761, below trunk by 0.001699944262713137. B_test was not run.

### 9: Mechanism: Cause-specific feedback router with competing delivery and adversary evidence channels
Hypothesis: Separate congestion, link-loss, loop, and observed-Sybil evidence before updating edge preferences, because the shared badness signal currently confuses recoverable congestion with adversarial risk and suppresses useful delivery routes.
Observable: B_dev robust_score and delivery improve together, with fewer repeated Sybil touches and no regression in congested low-Sybil scenarios.
Conflicts: pruned [5] said uniform path credit assigns terminal signals too broadly; this counters by factorizing feedback by observable failure cause before any routing penalty is applied. [PRUNED] (score: 0.667)

**Insight**: Cause-specific bounded reranking on the exact v3 profile reduced mean/max Sybil exposure to 0.119608/0.138731, but delivery fell to 0.596254; factorized penalties still over-suppress useful routes unless confidence or context can distinguish causal adversary evidence. [Pruned: B_dev 0.666965 below validated trunk 0.684530; B_test not run.]

**Result**: B_dev 0.666964541596115, below validated trunk 0.6845301005442892; B_test not run; candidate retained only in isolated executor copy.

**Branch**: /tmp/aegis-arbor-node9-cycle9-20260622

### 10: Mechanism: Empirical-Bayes confidence-gated edge evidence with reversible shrinkage
Hypothesis: Shrink sparse edge failure evidence toward a neutral prior and apply learned penalties only as posterior confidence grows, so stochastic early drops cannot permanently suppress delivery-capable routes while repeated adversarial outcomes still accumulate decisive evidence.
Observable: B_dev robust_score exceeds 0.684530 with delivery preserved near trunk and mean/max Sybil exposure no worse than trunk across the fixed five-scenario suite.
Conflicts: pruned [8] found hard filtering has a narrow operating range and pruned [9] found factorized penalties over-suppress useful routes; this counters by changing evidence calibration and confidence rather than adding stronger penalties or deleting actions. [PRUNED] (score: 0.6933)

**Insight**: Confidence-gating sparse directional evidence improved B_dev, delivery, Sybil exposure, latency, and hops, but the gain did not transfer to the held-out high-Sybil scenario; the tiny pooled prior remains sensitive to distribution shift.

**Result**: B_dev 0.6933176702330417 exceeded trunk 0.6845301005442892, but the single authorized B_test merge verification scored 0.4151347276777513 below trunk 0.42429066273896465; rejected without merge.

**Branch**: dd7c7f7a5f98877810bc79ca9448cb5e32ecf2ea at /tmp/aegis-arbor-node10-cycle10-20260622

### 11: Mechanism: Sibling-relative posterior evidence with local competitive shrinkage
Hypothesis: Calibrate each directional edge against the observed evidence distribution of its currently available sibling routes, so broad regime-wide failure pressure cancels out while locally exceptional adversarial edges still receive a bounded penalty.
Observable: B_dev robust_score exceeds 0.684530 while preserving delivery and reducing mean/max Sybil exposure; gains should arise without absolute global priors or action deletion.
Conflicts: pruned [10] showed fixed global empirical priors fail under distribution shift and pruned [6] showed coarse context statistics reduce delivery; this counters via decision-local relative evidence over concrete alternatives. [PRUNED] (score: 0.6732)

**Insight**: Decision-local posterior centering slightly reduced mean Sybil exposure but regressed delivery and increased max Sybil exposure; pure relative evidence discards useful absolute safety information when sibling routes share correlated risk or uneven observation coverage.
[Pruned: B_dev 0.6732324563179362 did not exceed validated trunk 0.6845301005442892; B_test was not authorized for a losing candidate.]

**Result**: B_dev 0.6732324563179362, below validated trunk 0.6845301005442892; B_test not run; candidate retained on isolated experiment branch only.

**Branch**: e803b1d99a80393018ad98f6924c9b730ebfdb77 at /tmp/aegis-arbor-node11-cycle11-20260622

### 12: Mechanism: Local bridge-risk prior from neighbor topology before feedback learning
Hypothesis: Penalizing candidate next hops that concentrate traffic through low-redundancy, high-loss neighborhoods should reduce early Sybil gateway contacts without globally suppressing useful routes.
Observable: B_dev robust_score exceeds 0.684530 while mean/max Sybil exposure falls without a material delivery regression.
Conflicts: pruned [7] used unconditional route concentration penalties and pruned [9] over-suppressed useful routes; this counters via per-decision structural gateway risk gated by local redundancy. [PRUNED] (score: 0.6719)

**Insight**: Topology-only local bridge-risk prior reduced Sybil exposure but was still too blunt: delivery fell enough that robust B_dev stayed below trunk. Future structural signals should be conditional on packet pressure or learned outcomes.
[Pruned: B_dev regression versus current trunk: 0.6719332010858522 < 0.6845301005442892. The bridge-risk prior lowered Sybil exposure but over-suppressed useful routes and reduced delivery; no B_test run.]

**Result**: Failed to beat trunk on B_dev: 0.6719332010858522 versus trunk 0.6845301005442892; no B_test run.

**Branch**: /tmp/aegis-arbor-node12-slim.NBHzWN

### 13: Mechanism: Surprise-gated adverse edge feedback with delivery-preserving relief
Hypothesis: Penalize directional edges mainly when drops or Sybil touches are surprising relative to advertised accumulated loss and recent delivery context, so ordinary congestion/noise does not permanently suppress useful routes while deceptive stealth edges still accumulate evidence.
Observable: B_dev robust_score exceeds 0.684530 with delivery preserved and mean/max Sybil exposure no worse than trunk across the fixed dev suite.
Conflicts: pruned [9] and [12] reduced Sybil by over-suppressing useful routes; this counters by changing when feedback becomes adversarial evidence instead of adding another always-on penalty. [PRUNED] (score: 0.6931)

**Insight**: Surprise-gating directional edge feedback improved B_dev while preserving delivery and lowering mean Sybil exposure, but held-out high-Sybil verification still fell below trunk; delivery relief needs a regime or pressure signal before it generalizes.

**Result**: B_dev 0.6931173548326843 exceeded trunk, but B_test verification failed at 0.42070455354319664 versus validated trunk 0.42429066273896465; no merge.

**Branch**: /tmp/aegis-arbor-node13-slim.XF4a2a

### 14: Mechanism: Local Sybil-pressure thermostat for edge evidence relief
Hypothesis: Gate delivery relief and edge-risk shrinkage by recent local Sybil pressure so the router preserves useful routes in low-pressure regimes but stops forgiving deceptive edges when Sybil contacts cluster, addressing held-out high-Sybil failures without changing benchmark code.
Observable: B_dev robust_score exceeds 0.684530 while mean/max Sybil exposure falls or stays flat and delivery does not materially regress.
Conflicts: pruned [10] and [13] showed evidence relief improves fixed dev but fails high-Sybil held-out; this counters via a local pressure signal that disables relief when adversarial contacts concentrate. [PENDING]
