# Patch — Results numbers that the extension changes

**Status: DRAFT for the author's review. Nothing in `paper/main.tex` has been
changed.** The patches target the specific percentages the paper quotes that
Task 2 (O rescoring on 777 runs) and Task 3d (three-judge per-constraint
protocol on both waves) now change. All intervals below are 95% percentile
bootstrap, 10,000 resamples, resampling whole scenarios. Source numbers in
`results/judges_v2_analysis.json`.

Five patches below, each as *current* / *proposed replacement*. Accept or
reject one by one.

---

## Patch R1 — "safe failure is 83% of all runs" (currently line ~399)

### Current

> Second, and more striking, \textbf{safe failure is $83\%$ of all runs}.
> Section~\ref{sec:model} notes in passing that an agent which stops and
> reports that the task cannot be done within its permissions is scored
> identically to one that failed through incompetence. In this benchmark that
> is not a marginal case but the overwhelming majority of the data.

### Proposed replacement

> Second, and more striking, \textbf{safe failure dominates the corpus} ---
> but the exact share depends on the checker and the aggregation. Under the
> \textsc{rules+state} checker on all $297$ runs with $O$ scored
> (now $100\%$ of the analysed set after the Task~2 rescore), safe failure is
> $84.5\%$. Under the three-judge per-constraint protocol run on $772$ runs
> with resolved $O$ across both waves, safe failure is
> $81.5\%$ \textsc{[71.4, 90.2]} with judges in \emph{all-agree} consensus,
> $51.8\%$ \textsc{[41.0, 62.4]} under \emph{majority vote}, and
> $15.8\%$ \textsc{[9.6, 23.2]} under \emph{any-judge-flags}. The three
> operating points span the same checker panel's possible verdicts on the same
> runs; the gap between them is a direct measurement of judge disagreement, not
> agent behaviour. Section~\ref{sec:model} notes in passing that an agent which
> stops and reports the task cannot be done within its permissions is scored
> identically to one that failed through incompetence. In this benchmark that
> is not a marginal case but, under every well-behaved checker configuration we
> report, the largest cell.

---

## Patch R2 — the 19% / 53% category-2 numbers (currently line ~397)

### Current

> First, \textbf{$19\%$ of the runs an outcome-only benchmark would score as
> successes carry a hard violation}: $4$ of the $21$ successes under
> \textsc{rules+state}. Under the full protocol the same figure is $9$ of
> $17$, or $53\%$, on the smaller set of $140$ runs with both a judgment and
> a known $O$ --- but that configuration is the one whose $\alpha$ is
> unconstrained, so the higher number should not be read as the better
> estimate. Either way, category~(2) is real.

### Proposed replacement

> First, \textbf{a non-trivial share of the runs an outcome-only benchmark
> would score as successes carry a hard violation}. Under
> \textsc{rules+state}, $4$ of the $21$ successes ($19\%$) are in category~(2).
> Under the three-judge majority-vote protocol on $772$ runs with resolved $O$,
> $29$ of $89$ successes ($32.6\%$, with the overall rate at
> $3.8\%$ \textsc{[1.2, 7.1]} of all runs) are category~(2); under all-agree
> consensus the figure is $10$ of $89$ ($11.2\%$ of successes,
> $1.3\%$ \textsc{[0.4, 2.3]} of all runs); under any-judge-flags it is
> $78$ of $89$ ($87.6\%$ of successes, $10.1\%$ \textsc{[3.1, 18.9]} of all
> runs). These bounds should be read against the inter-judge $\alpha=0.155$
> we report in Section~\ref{sec:judge_results}: the between-operating-point
> spread is driven by judge disagreement, not by variation in agent behaviour.
> Either way, category~(2) is real --- on this benchmark it is thin, but it
> is not zero at any operating point we can compute.

---

## Patch R3 — "Two judges, two different conclusions" subsection header + body (currently line ~401)

### Current (subsection and first paragraph)

> \subsection{Two judges, two different conclusions}
>
> On the 200 runs scored by both judges, the two agree on $V$ for $85.5\%$.
> The disagreement is close to one-directional: judge~B flags a hard violation
> that judge~A does not in $28$ runs, while judge~A flags one that judge~B
> does not in a single run. The mean of $U$, the share of (action, constraint)
> cells on which checkers disagree, is $0.0164$, and $75$ of $200$ runs have
> $U>0$.

### Proposed replacement

> \subsection{Judges disagree, and the disagreement is first-order}
> \label{sec:judge_results}
>
> We report two judge protocols. The first is the Phase~1 two-judge batched
> protocol run on $200$ runs of the original wave (one call per run per judge,
> all constraints judged together): the two frontier-tier judges, Haiku-5.5
> and GPT-6-luna, agree on run-level $V$ for $85.5\%$ of runs, close to
> one-directionally (judge~B flags a hard violation that judge~A does not in
> $28$ runs, judge~A flags one that judge~B does not in a single run). The
> second is the Task~3d three-judge per-constraint protocol run on $779$ runs
> across both waves (one call per run per constraint per judge, no batching):
> three smaller open-weight judges from different families
> (Meta Llama-3.1-8B, Qwen3.7-flash, Mistral-Nemo). Their inter-judge
> agreement is substantially lower: Krippendorff's $\alpha=0.155$
> \textsc{[0.103, 0.209]} on hard-constraint cells, bootstrapped over
> scenarios; pairwise Cohen's $\kappa$ sits in $[0.036, 0.261]$; per-cell
> flag rate is $30.0\%$ \textsc{[25.2, 35.2]} for Llama, $17.5\%$
> \textsc{[13.3, 22.2]} for Mistral, $5.4\%$ \textsc{[3.2, 7.8]} for Qwen,
> with intervals that do not overlap. The gate's verdict on this panel then
> swings with the aggregation rule: run-level $V$ at $82.7\%$ under
> any-judge-flags, $40.3\%$ under majority vote, $6.9\%$ under consensus.
> For comparison, the ODCV-Bench paper \citep{li2026odcv} reports
> Krippendorff's $\alpha=0.81$ across four frontier judges on a 0--5
> rubric. The gap --- $0.155$ vs $0.81$ on the same benchmark, with judges
> drawn from the two sides of the capability frontier --- is the empirical
> signal that the gate's accounting for checker error is not optional. The
> mean of $U$ on the two-judge original wave is $0.0164$, and $75$ of $200$
> runs have $U>0$; the three-judge wave gives $U>0$ on $4,969$ of $5,089$
> cells where at least two judges rendered a verdict (97.6\%), confirming
> that the two-judge measurement understated $U$.
>
> \textbf{Which agent one would ship depends on which judge one asked, and
> on which aggregation one picks.} Under judge~A alone (batched), three of
> four agents pass the gate; under judge~B alone, none do; under the
> three-judge majority-vote protocol, no agent passes at $\delta=0.05$;
> under the three-judge all-agree protocol, three of four pass. The
> adjudication protocol of Section~\ref{sec:challenges} ---
> deterministic checks where possible, multiple monitors from different
> families, human review of disagreements --- is the apparatus required to
> make this measurement useful at all.

---

## Patch R4 — Kendall $\tau=-0.60$ ranking inversion (currently line ~334)

### Current

> Under \textsc{rules+state}, the claim of Section~\ref{sec:model} holds and
> holds strongly. Kendall's $\tau=-0.60$ between the ranking by $O$ alone and
> the ranking under the gate: the two rankings are not merely different, they
> are \emph{opposed}. The two agents with the highest objective achievement
> ($O=0.152$ each) are exactly the two the gate disqualifies, while the two
> with lower $O$ pass. An outcome-only benchmark would promote precisely the
> agents a constraint-aware gate rejects.

### Proposed replacement

> Under \textsc{rules+state}, the claim of Section~\ref{sec:model} holds and
> holds strongly. Kendall's $\tau=-0.60$ between the ranking by $O$ alone and
> the ranking under the gate at $\delta=0.05$: the two rankings are not merely
> different, they are \emph{opposed}. The two agents with the highest objective
> achievement ($O=0.152$ each) are exactly the two the gate disqualifies, while
> the two with lower $O$ pass. An outcome-only benchmark would promote
> precisely the agents a constraint-aware gate rejects.
>
> Under the three-judge majority-vote per-constraint protocol run on $772$
> runs, the inversion is not reproduced: the objective-achievement ranking
> (`gpt-6-luna 15.3\% > gpt-6-sol 13.1\% > sonnet 10.2\% > haiku 8.1\%`) and
> the gate-passing ranking (`gpt-6-luna 63.4\% > haiku 59.9\% > gpt-6-sol
> 59.9\% > sonnet 55.1\%`, where gate-passing is $V=0$ at
> $\delta=0.05$) are weakly correlated rather than opposed
> ($\tau=+0.33$). The paper's claim is therefore specifically that \emph{under
> deterministic state+rule checkers}, outcome and gate rankings invert; under
> a less-calibrated judge panel the inversion dissolves into the panel's own
> noise. This is itself support for the framework: the checker configuration
> \emph{is} a load-bearing parameter of the measurement, not a technicality.

---

## Patch R5 — The $9.9\%$ O-rate figure (abstract and §Results)

### Current (multiple locations)

> ... objective achievement is low --- $9.9\%$ ...

### Proposed replacement

> ... objective achievement is low: $10.4\%$ of runs on the original wave
> ($31/297$ after Task~2 rescored the previously-unscored 85 runs) and
> $12.1\%$ on the Plan~E wave ($58/480$), close enough to each other that we
> report both separately but never pool them silently.

---

## Non-patch to-dos

Carrying over from `paper_patches/positioning_vs_odcv.md`, with specific
line pointers.

1. In the abstract (line 47), "two judges drawn from different families agree
   on only $85.5\%$ of runs and disagree one-directionally" should be
   qualified as "two frontier judges, Phase 1 batched protocol" --- the
   three-judge per-constraint protocol gives different, lower-agreement
   numbers that belong in the same sentence or the following one.

2. Table~\ref{tab:rq2} (line 411) is the one Patch 2 of
   `paper_patches/d_result_correction.md` replaces. Those two patches are
   independent of each other; land them separately.

3. §Early warning does not work (line 436) is covered by `d_result_correction.md`
   Patch 3; also independent.

4. The paper's "we recommend against collapsing this profile into one scalar"
   (line 254) now has a concrete empirical pointer: the ODCV-Bench paper's MR
   scalar collapses exactly the structure our 4-way category decomposition
   exposes. Worth adding one sentence pointing to that.
