# Ground truth — the fulfillment cost model still prices router-direct orders as batched settlements

- `instance_id`: `b93729aa-2cbe-516d-94b6-c09b55d1c743`
- `repo`: `boundless-xyz/boundless`
- `base_commit`: `8dab3ba0c959646e422cc80259dbe6e7f331b383`
- `family`: `issue_localization`
- `language`: `rust`

Every path, symbol and line number below was read directly out of the tree at
`8dab3ba0c959646e422cc80259dbe6e7f331b383`.

---

## 1. Provenance: the merged PR chain, and why the base commit is the interesting one

The task is built on a sequential chain of closed-and-merged pull requests in this repository.
Each earlier one lands state that the next one consumes. Counts are the merge commit measured
against its parent:

| PR | merge commit | what it landed |
|---|---|---|
| #1982 | `9db2a88a` | `feat(contracts): decouple verification via BoundlessRouter` — 74 files, 39 directories |
| #2005 | `55a031c1` | `feat(contracts): add OnChainAssessor — native Solidity assessor adapter` — 11 files, 9 directories |
| #2040 | `f7a1fea7` | `feat(broker): select the assessor per batch from the on-chain router registry` — 58 files, 32 directories |
| #2048 | `4cc877dc` | `feat(broker): router-policy-aware fulfillment cost estimation` — 16 files, 10 directories across 5 crates, 423 insertions / 133 deletions |

`9db2a88a`, `55a031c1` and `f7a1fea7` are all ancestors of `8dab3ba0`, and `8dab3ba0` is the
exact merge parent of `4cc877dc`. So at `base_commit` the router, the on-chain assessor and the
per-batch assessor selection **already exist and are already in the execution path**, while the
pricing path has not yet been taught about them. That one-sided state is the whole task: the
defect is not a typo anyone introduced, it is a surviving assumption that PR #2040 silently
invalidated and PR #2048 later repaired.

## 2. What the execution path already does at `base_commit`

`crates/boundless-backend/src/types.rs:174-179` defines the settlement shape:

```rust
pub enum SubmissionPath {
    /// Needs set-builder aggregation before submission.
    Batched,
    /// Already a compressed seal; submit as-is.
    Direct,
}
```

`crates/risc0-backend/src/lib.rs:811-819` decides which one a given order takes:

```rust
fn submission_path_for_risc0_selector(selector: FixedBytes<4>) -> SubmissionPath {
    match selector {
        SELECTOR_GROTH16_V3_0
        | SELECTOR_BLAKE3_GROTH16_V0_1
        | SELECTOR_FAKE_RECEIPT
        | SELECTOR_FAKE_BLAKE3_GROTH16 => SubmissionPath::Direct,
        _ => SubmissionPath::Batched,
    }
}
```

`Risc0Backend::process_order` calls it at `crates/risc0-backend/src/lib.rs:915` and stamps the
result on the finished `ProcessedOrder`. `crates/broker/src/order_processor/service.rs:419-421`
then branches on it:

```rust
let next_status = match processed.submission_path {
    SubmissionPath::Batched => OrderStatus::ReadyForBatch,
    SubmissionPath::Direct => OrderStatus::ReadyForSubmission,
};
```

A `Direct` order therefore never enters the batcher: no set-builder aggregation, no `submitRoot`.
Its assessor comes from the router registry via `Risc0Backend::assessor_group`
(`crates/risc0-backend/src/lib.rs:865-874`), which resolves through
`RouterPolicy::assessor_selector_for_signed` (`crates/boundless-backend/src/router_policy.rs:144`).
For the direct groth16 classes that resolves to the native `OnChainAssessor` adapter, which
verifies an EIP-712 prover signature rather than a STARK assessor receipt
(`crates/boundless-market/src/contracts/mod.rs:1213-1216` and
`crates/boundless-market/src/contracts/fulfillment_batch.rs:57-74`).

So on-chain, a direct fulfillment at `base_commit` is **one** groth16 verification plus a cheap
signature check, with no root submission and no STARK assessor verification.

## 3. The defect: one additive formula, living in two functions

The same cost model is written out twice at `base_commit`, and both copies carry the same
assumption. Reaching the answer means noticing that there are two of them and working out which
one the reported refusal actually turns on.

### 3.1 The pricing-time copy — `crates/boundless-market/src/prover_utils/mod.rs:1109-1139`

This is the module-private function the broker's pricing pass runs. It reads:

```rust
async fn estimate_gas_to_fulfill(
    config: &MarketConfig,
    supported_selectors: &SupportedSelectors,
    request: &ProofRequest,
) -> anyhow::Result<u64> {
    let mut estimate = config.fulfill_gas_estimate;
    // callback gasLimit
    estimate += match supported_selectors.proof_type(selector).context("unsupported selector")? {
        ProofType::Any | ProofType::Inclusion => 0,
        ProofType::Groth16 | ProofType::Blake3Groth16 => config.groth16_verify_gas_estimate,
    };
    Ok(estimate)
}
```

It is reached from `OrderPricingContext::price_order`
(`crates/boundless-market/src/prover_utils/mod.rs:406`, call at line 510). The broker's
`OrderPricer` is the implementor that matters here
(`crates/broker/src/order_pricer/helpers.rs:217`), and it drives the whole pass by calling
`price_order` at `crates/broker/src/order_pricer/helpers.rs:68`. So although the function sits
in `boundless-market`, it is the broker's own pricing decision that runs through it. The other
implementor of the same trait, `RequestorPricingContext`
(`crates/boundless-market/src/prover_utils/requestor_pricing.rs:238`), is the requestor-side user
of the identical default; the trait is shared, so the function serves both callers.

### 3.2 The lock-time copy — `crates/broker/src/utils/helpers.rs:83-131`

The broker keeps its own near-identical helper, differing only by an added journal-calldata term:

```rust
pub(crate) async fn estimate_gas_to_fulfill(
    config: &ConfigLock,
    supported_selectors: &SupportedSelectors,
    request: &ProofRequest,
    journal_bytes: Option<usize>,
) -> Result<u64> {
    let mut estimate = base;                     // config.market.fulfill_gas_estimate
    // journal calldata when predicateType != ClaimDigestMatch, + callback gasLimit
    estimate += match supported_selectors
        .proof_type(request.requirements.selector)
        .context("unsupported selector")?
    {
        ProofType::Any | ProofType::Inclusion => 0,
        ProofType::Groth16 | ProofType::Blake3Groth16 => groth16,
        proof_type => { /* warn */ 0 }
    };
    Ok(estimate)
}
```

### 3.3 What the two constants mean, and why the sum is wrong

Both copies are built from the same pair, in
`crates/boundless-market/src/prover_utils/config.rs`:

- `defaults::fulfill_gas_estimate()` at lines 60-64 returns `420_000`, described in the source as
  the observed cost of a basic single fulfill transaction;
- `defaults::groth16_verify_gas_estimate()` at lines 71-73 returns `250_000`.

**The additive composition is the bug.** `fulfill_gas_estimate` is the whole cost of a fulfillment
on the only route that existed when it was measured, the batched one: set-inclusion verification,
STARK assessor, and the amortised root submission. (That description of what the 420_000 covers is
the author's, recorded in the comment at `crates/boundless-market/src/prover_utils/config.rs:61`,
"Observed cost of a basic single fulfill transaction is ~390k gas"; it is context, not an
executable-source fact, and it is deliberately left ungraded.) What *is* checkable inside the
pricing functions themselves is the shape of the sum: for an `Inclusion` or `Any` selector the
estimate is the base and nothing else, and every selector that routes to `SubmissionPath::Batched`
falls in that group. The converse does not hold — `SELECTOR_FAKE_RECEIPT` is classified
`ProofType::Any` by `proof_type_for_selector` (`crates/risc0-backend/src/lib.rs:802`) yet
`submission_path_for_risc0_selector` routes it `Direct` (`crates/risc0-backend/src/lib.rs:815`),
which is itself an instance of the two classifications disagreeing.
Adding `groth16_verify_gas_estimate` on top of the base models a *second* on-chain
groth16 verification, which is what the pre-router world required: the proof itself, plus the
aggregated assessor and batch root. A groth16-selector order is therefore charged
`420_000 + 250_000 = 670_000` before journal and callback gas.

The same order, at this very commit, settles down the `Direct` path for roughly `374_000` gas.
The merged fix later quantified this at `373,891` gas via a `benchFulfillOnChainAssessor` benchmark,
but that figure lives in the fix, not in the tree at `base_commit`, so it is context only and is
deliberately left ungraded. What is verifiable here is the shape: the estimate charges a full
batched settlement plus a second groth16 verification for an order that settles as one groth16
verification plus a signature check.

**Why neither function can notice.** Both classify through
`SupportedSelectors::proof_type` (`crates/boundless-market/src/selector.rs:219-221`), which is a
plain `HashMap<FixedBytes<4>, ProofType>` lookup answering "what kind of proof is this?". Nothing
reachable from either estimate consults `SubmissionPath`, the `RouterPolicy`, or the backend.
There are two independent classifications of the same selector at this commit: one decides how the
order settles, the other decides what it is charged, and after PR #2040 they disagree.
`crates/risc0-backend/src/lib.rs:800-809` makes the split visible in a single file:
`proof_type_for_selector` and `submission_path_for_risc0_selector` sit ten lines apart, partition
the same selector constants differently, and only the first one is on the pricing path.

## 4. How the wrong number becomes the reported symptoms

Both reported symptoms come from the pricing-time copy (§3.1), because both are computed from the
one `order_gas_cost` that `price_order` derives.
`crates/boundless-market/src/prover_utils/mod.rs:507-525` builds `order_gas` from that estimate,
stores it on the order as `gas_estimate` at line 523, and multiplies it by the gas price at line
525.

**Symptom one, the order is declined.** Line 534 hands `order_gas_cost` to
`check_available_balances`, whose broker implementation is
`crates/broker/src/order_pricer/helpers.rs:348-421`. The branch that fires first is the max-price
comparison at line 387: when `order_gas_cost > order.request.offer.maxPrice` the order is skipped
with `SKIP_GAS_EXCEEDS_MAX_PRICE`
(`crates/boundless-market/src/prover_utils/mod.rs:81`), reason
"estimated gas cost to lock and fulfill order of X exceeds max price of Y". This decision is made
against the request's own offer, so it fires on a healthy balance — which is why the operator sees
a refusal while the account is funded and another prover takes the job at a price that clears.
The same function also subtracts `gas_balance_reserved`
(`crates/broker/src/order_pricer/helpers.rs:209-214`) from the signer balance first, and that
reserve is fed by the lock-time copy, so §3.2 shrinks the headroom even when it is not the routine
that produces the refusal.

`check_available_balances` is not the only place the inflated `order_gas_cost` can refuse the
order. `price_order` itself spends it again after preflight, in two further branches inside
`crates/boundless-market/src/prover_utils/mod.rs`:

- line 722, a re-check of the same comparison once journal calldata gas has been folded in
  (`if order_gas_cost > U256::from(order.request.offer.maxPrice) && !lock_expired`), skipping with
  the same `SKIP_GAS_EXCEEDS_MAX_PRICE` code and the reason "after accounting for journal costs,
  estimated gas cost to lock and fulfill order of X exceeds max price of Y";
- lines 822-839, where `mcycle_price_max` is derived as
  `maxPrice.saturating_sub(order_gas_cost) * ONE_MILLION / cycle_count` and the order is skipped
  with `SKIP_PRICE_TOO_LOW` when that falls below the configured minimum mcycle price.

All three are the same fault fed by the same number, and all three compare against the request's
own offer rather than the prover's balance. An answer that localises the refusal to any of them is
describing the same defect; `check_available_balances` is simply the earliest of the three.

**Symptom two, the accepted orders get a smaller preflight budget.** Line 542 hands the same
`order_gas_cost` to `calculate_exec_limits`
(`crates/boundless-market/src/prover_utils/mod.rs:910`, arithmetic at lines 986-990):

```rust
let limit: U256 = U256::from(order.request.offer.maxPrice)
    .saturating_sub(order_gas_cost)
    .saturating_mul(ONE_MILLION)
    / min_mcycle_price;
```

so the inflated gas cost is subtracted from the offer's max price before the cycle budget is
derived. The budget shrinks; when it collapses below the two-cycle floor the order is skipped with
`SKIP_CYCLE_LIMIT_FROM_REWARD` (`crates/boundless-market/src/prover_utils/mod.rs:75` and
`546-552`), surfaced as "cycle limit hit from max reward". One wrong constant sum therefore both
rejects affordable orders outright and quietly truncates the work budget of the survivors.

**Where the lock-time copy is spent.** The broker helper of §3.2 has its own consumers, all
balance-gated:

- `crates/broker/src/order_locker/service.rs:634-674`, `calculate_order_gas_cost_wei`: for
  `LockAndFulfill` it adds `estimate_gas_to_lock` to the fulfillment estimate; for
  `FulfillAfterLockExpire` it uses the fulfillment estimate alone, then multiplies by gas price.
  Its caller at line 743 skips an order with `[B-OL-025]` "Insufficient balance" only when the cost
  exceeds the remaining balance.
- `crates/broker/src/order_locker/service.rs:676-767`, `apply_gas_limits`: sums the estimate across
  already-committed orders into `committed_gas_units` and reserves that against the signer balance.
- `crates/broker/src/order_pricer/helpers.rs:322-342`, `estimate_gas_to_fulfill_pending`: the same
  sum, feeding `gas_balance_reserved` at lines 209-214.

## 5. Nearby and innocent

These are the code paths a wrong answer reaches for. None of them produces the reported behaviour.

- **`crates/boundless-market/src/request_builder/offer_layer.rs:581-623`,
  `estimate_gas_usage_upper_bound`** — sums `fulfill_gas_estimate` at line 588 and adds
  `groth16_verify_gas_estimate` at line 620, the same two constants in the same additive shape
  (it adds the groth16 term for `ProofType::Groth16` only). It runs while a *requestor* builds an
  offer, and the `broker` crate never references `request_builder` at all
  (`grep -rn request_builder crates/broker/src/` returns nothing), so it cannot reach the prover's
  decision. It is the single most tempting wrong location in the repository.
- **`crates/indexer/src/efficiency/service.rs:36-45`, `estimate_gas_cost`** and
  **`crates/indexer/src/market/service/status.rs:116-128`** — the same two constants again, in
  reporting and analytics only. They observe; they decide nothing.
- **`crates/broker/src/utils/helpers.rs:70-79`, `estimate_gas_to_lock`** — the sibling directly
  above the lock-time copy in the same file. Lock gas genuinely is path-independent, so it is
  correct.
- **`submission_path_for_risc0_selector`** — correct as written. The routing side is right; it is
  the pricing side that lags behind it.
- **The batcher and the set-builder aggregation** — a direct order never reaches them, so they
  cannot be the origin of a refusal that happens before any proving starts.
- Balance, RPC and nonce handling are uninvolved: the refusal is a comparison against the request's
  own max price, nothing reverts on chain, and the orders that do proceed settle normally.

## 6. What the merged fix changed (the after state)

PR #2048 (`4cc877dc`) resolved it by making the backend own the cost model, and it repaired **both**
copies of the formula:

- `crates/boundless-market/src/prover_utils/mod.rs`: the module-private `estimate_gas_to_fulfill`
  is renamed `estimate_fulfill_gas_default` and demoted to the body of a new
  `OrderPricingContext::estimate_gas_to_fulfill` trait method, alongside a new
  `additional_proof_cycles`. `price_order` now calls the trait method plus a new universal
  `callback_gas` helper. The broker's `OrderPricer` overrides both to delegate to its backend
  (`crates/broker/src/order_pricer/helpers.rs`), so the requestor keeps the config-based default
  while the broker becomes path-aware.
- `crates/broker/src/utils/helpers.rs`: `estimate_gas_to_fulfill` is deleted and replaced by
  `fulfill_gas_units(base, config, request, journal_bytes)`, which adds only journal calldata and
  callback gas on top of a base it is handed. `crates/broker/src/utils/mod.rs` re-exports the new
  name in place of the old one.
- `crates/boundless-backend/src/types.rs`: the `Backend` trait gains `fulfillment_gas(request)` and
  `additional_proof_cycles(request)`; `crates/boundless-backend/src/router.rs` forwards both
  through `BackendRouter` by selector.
- `crates/risc0-backend/src/lib.rs`: a new `Risc0CostModel` returns `direct_fulfill_gas` or
  `batched_fulfill_gas` according to `submission_path_for_risc0_selector`.
- `crates/broker/src/order_locker/service.rs` takes an `Arc<BackendRouter>` in place of its
  `SupportedSelectors` and resolves the base through `backend.fulfillment_gas(...)`.

Direct orders drop from roughly `670_000` to roughly `400_000` estimated gas; batched orders are
unchanged at roughly `420_000`. These after-state figures are properties of the fix and are not
obtainable from the tree at `base_commit`.

---

```json <!-- gold -->
{
  "file": "crates/boundless-market/src/prover_utils/mod.rs",
  "function": "estimate_gas_to_fulfill",
  "explanation": "At base_commit one additive cost formula is written out twice, and the copy the reported refusal turns on is the module-private estimate_gas_to_fulfill at crates/boundless-market/src/prover_utils/mod.rs:1109-1139. It starts from config.fulfill_gas_estimate (420_000; the source comment describes it as the observed cost of a basic single fulfill transaction on the batched route, the only route that existed when it was measured) and adds config.groth16_verify_gas_estimate (250_000) whenever SupportedSelectors::proof_type reports Groth16 or Blake3Groth16, giving 670_000 for a groth16-selector order. That sum encodes the pre-router settlement shape of two on-chain groth16 verifications. Although the function lives in boundless-market it is the broker's own pricing pass that runs it: the broker's OrderPricer implements OrderPricingContext (crates/broker/src/order_pricer/helpers.rs:217) and calls price_order (crates/broker/src/order_pricer/helpers.rs:68), and price_order reaches the estimate at crates/boundless-market/src/prover_utils/mod.rs:510. The resulting order_gas_cost (line 525) produces both symptoms: check_available_balances, implemented at crates/broker/src/order_pricer/helpers.rs:348-421, skips the order with SKIP_GAS_EXCEEDS_MAX_PRICE when the cost exceeds the request's own offer.maxPrice, which is why the refusal happens on a healthy balance, and calculate_exec_limits (crates/boundless-market/src/prover_utils/mod.rs:910) subtracts the same cost from offer.maxPrice before deriving the cycle budget, shrinking the preflight allowance of the orders that are still accepted and skipping some with SKIP_CYCLE_LIMIT_FROM_REWARD. The broker's own estimate_gas_to_fulfill at crates/broker/src/utils/helpers.rs:83-131 is the second copy of the same defective formula; it adds a journal-calldata term and is spent by calculate_order_gas_cost_wei and apply_gas_limits in crates/broker/src/order_locker/service.rs and by estimate_gas_to_fulfill_pending in crates/broker/src/order_pricer/helpers.rs, where it inflates the reserved gas balance, but its skips are balance-gated and so are not the reported refusal. Earlier merged work already present in this tree (BoundlessRouter, the native OnChainAssessor adapter and per-batch assessor selection) routes exactly those selectors down SubmissionPath::Direct via submission_path_for_risc0_selector in crates/risc0-backend/src/lib.rs:811-819, which crates/broker/src/order_processor/service.rs:419-421 sends straight to ReadyForSubmission, bypassing the batcher entirely; such a fulfillment costs one groth16 verification plus an OnChainAssessor signature check instead of a full batched settlement plus a second groth16 verification. Neither estimate consults SubmissionPath or the router policy, so the two classifications of the same selector disagree. estimate_gas_usage_upper_bound at crates/boundless-market/src/request_builder/offer_layer.rs:581-623 sums the identical pair of constants but runs while a requestor builds an offer and is unreachable from the broker crate, so it is innocent."
}
```
