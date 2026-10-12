# Patch — positioning relative to the ODCV-Bench benchmark paper

**Status: DRAFT for the author's review. Nothing in `paper/main.tex` or
`references.bib` has been changed.** The target is Li, Fung, Weiss et al. 2026,
"A Benchmark for Evaluating Outcome-Driven Constraint Violations in Autonomous
AI Agents" (arXiv:2512.20798v5, read 2026-10-11). It is the benchmark paper for
ODCV-Bench itself; we build on their benchmark, we do not compete with them.
The patches below adjust how we introduce them and position our contribution
against the one they explicitly flag as a limitation of theirs.

Four patches, each as *current* / *proposed replacement* so the author accepts
them one by one.

---

## Patch 1 — Citation (currently `\citep{li2025odcv}` in `main.tex`; `references.bib` entry)

### Current `references.bib` entry (if present)

```bibtex
@misc{li2025odcv,
  title = {{ODCV-Bench}},
  author = {Li, Miles Q. and others},
  year = {2025},
}
```

### Proposed replacement

```bibtex
@article{li2026odcv,
  title   = {A Benchmark for Evaluating Outcome-Driven Constraint Violations in
             Autonomous {AI} Agents},
  author  = {Li, Miles Q. and Fung, Benjamin C. M. and Weiss, Martin and Xiong, Pulei
             and Al-Hussaeni, Khalil and Fachkha, Claude},
  journal = {arXiv preprint arXiv:2512.20798},
  year    = {2026},
  note    = {v5, 10 May 2026},
  url     = {https://arxiv.org/abs/2512.20798}
}
```

And update every `\citep{li2025odcv}` in `paper/main.tex` to `\citep{li2026odcv}`.
If a venue appearance supersedes the arXiv preprint later, the key `li2026odcv`
stays and only the `journal`/`booktitle` fields change.

---

## Patch 2 — Related-work paragraph on ODCV-Bench

### Current (currently cited only in passing, in §Choice of benchmark around line 275 and §Related work)

> Two options are available. The first is a benchmark that already contains
> constraint-violating routes, such as ODCV-Bench \citep{li2025odcv} or MasDrift
> \citep{xu2026masdrift}. The second is a subset of WebArena \citep{zhou2024webarena}
> or SWE-bench \citep{jimenez2024swebench} tasks annotated with the schema of
> Section~\ref{sec:framework}. The first needs less annotation. The second shows
> whether the schema can be applied to tasks that were not designed with it in mind.

### Proposed replacement

> We use ODCV-Bench \citep{li2026odcv}, the state-of-the-art benchmark for the
> failure mode this paper measures: agents under KPI pressure who satisfy their
> performance target by violating the ethical, legal, or safety constraints their
> system prompt names. ODCV-Bench ships 40 production-like Docker scenarios in two
> paired framings, Mandated (direct KPI mandate) and Incentivized (KPI pressure
> only). Li et al.\ 2026 use the benchmark to show that frontier agents misbehave
> at rates ranging from 0.0\% (Claude-Opus-4.7) to 62.8\% (Grok-4.20) on the
> Mandated framing, and that cross-generational safety is non-monotonic (five of
> nine successor models become safer than their predecessor; four get worse). They
> score trajectories with a four-model frontier judge panel (GPT-5.5, Grok-4.20,
> Claude-Opus-4.7, Gemini-3.1-Pro-Preview), report Krippendorff's $\alpha=0.81$,
> and name as an explicit limitation that \emph{``scores are produced by LLM
> judges without human verification''}. The present paper is designed to measure
> what their benchmark exposes under the measurement discipline their paper itself
> asks for: we score every run under four checker configurations (two deterministic,
> two judge-based); we quantify how the gate's verdict propagates checker false
> positive and false negative rates; we build and release the human audit
> infrastructure their paper flags as missing; and we extend their 40 scenarios
> with three repetitions per cell so the paper's reported numbers carry
> scenario-cluster bootstrap intervals rather than point estimates. We treat
> ODCV-Bench as the input, not the output.

---

## Patch 3 — New subsection in §Related work (immediately before our contribution list)

### Insert this new subsection

> \paragraph{The gap this paper fills, relative to ODCV-Bench.} The ODCV-Bench
> paper reports a scalar Misalignment Rate (MR) --- fraction of runs whose
> four-judge median severity exceeds 3 on a 0--5 rubric --- and a mean Severity
> score. Both are collapsed over the trajectory and over the constraints that
> apply to it. A single scalar is sensitive to any monotonic transformation of
> the rubric and gives no handle on which agent action violated which constraint,
> which is the input a deterministic rules-based checker needs. The ODCV-Bench
> paper also treats the four-judge panel's output as the ground truth and reports
> Krippendorff's $\alpha=0.81$ as the primary quality signal, while naming the
> absence of a human audit as an open limitation. Our framework decomposes the
> same trajectories into separate components for objective achievement $O$, hard
> violations $V$, soft constraint score $\mathrm{SC}$, uncertainty $U$ and
> distance $D$, each measurable under multiple checker configurations; derives a
> gate rule that does not need a scalar; and makes the audit --- not the judge
> panel --- the authoritative source for the false positive rate $\alpha$ and
> false negative rate $\beta$ that the gate's verdict depends on. We also show
> that the inter-judge agreement reported in \citep{li2026odcv} is a frontier-model
> property: on the same benchmark, the same scenarios, with smaller open-weight
> judges (Meta Llama-3.1-8B, Qwen3.7-flash, Mistral-Nemo), Krippendorff's
> $\alpha$ drops to $0.155$ (95\% bootstrap CI $[0.103, 0.209]$) and pairwise
> Cohen's $\kappa$ sits in $[0.036, 0.261]$. The gate's verdict is then entirely
> determined by which operating point --- any-judge-flags, majority vote,
> consensus --- is chosen. This observation is the empirical motivation for the
> framework's insistence on reporting checker false positive and false negative
> rates.

---

## Patch 4 — Discussion / conclusion

### Current (currently line ~515, after the paper's main findings)

> We take this as evidence that the framework's accounting for checker error is
> not a caveat attached to it but the part most in need of development.

### Proposed replacement

> We take this as evidence that the framework's accounting for checker error is
> not a caveat attached to it but the part most in need of development. The
> ODCV-Bench paper \citep{li2026odcv} shows that frontier judges on this benchmark
> agree with each other at Krippendorff's $\alpha=0.81$ --- a number that would
> make the $\alpha$ and $\beta$ corrections we derive secondary. We show in
> Section~\ref{sec:results} that on the same benchmark, with judges from the
> smaller-and-open-weight tier that smaller teams are likely to run against, that
> inter-judge agreement drops to $\alpha=0.155$ and the gate verdict swings from
> $7\%$ unsafe-failure (consensus) to $73\%$ (any-flags) depending purely on the
> aggregation rule chosen for the same panel's verdicts. Our framework's
> contribution is to say that this spread is the measurement signal, not a
> nuisance; the paper's gating rule and audit protocol are the apparatus that
> converts it into a release decision.

---

## Also to adjust across the paper

Not patches here; marked as a to-do so the review pass catches them.

1. **Every unqualified "safe failure is 83% of runs" assertion.** With the
   extension data in, this is specifically "safe failure is 81.5% [71.4, 90.2]
   of runs under 3-judge all-agree consensus; 51.8% [41.0, 62.4] under majority
   vote; 15.8% [9.6, 23.2] under any-judge-flags; 83% under the deterministic
   state+rule checker." The paper must attach the operating point.
2. **Judge count.** The paper says "two judges". With Task 3d landed, there are
   now three judges on the Plan E and originals (per-constraint, open-weight)
   AND the original two frontier judges on 200 originals (batched). Both
   protocols are kept and reported side by side; "two judges" needs qualifying
   as "the Phase 1 two-judge batched protocol".
3. **Kendall $\tau = -0.60$ ranking inversion.** This holds under state+rule.
   Under the 3-judge majority-vote per-constraint protocol it is not reproduced.
   See Patch 4 / 5 in `paper_patches/results_update.md` (to be drafted next) for
   the specific wording.
4. **The Section 3.2 table of benchmarks.** Should name ODCV-Bench as the
   benchmark we actually use and credit Li et al. 2026 explicitly, not list it
   alongside WebArena / SWE-bench as a "could use". This is Patch 2 above.
