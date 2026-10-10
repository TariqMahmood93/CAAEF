# Patch — RQ2 / D early-warning result

**Status: DRAFT for the author's review. Nothing in `paper/main.tex` has been changed.**
The claim being withdrawn is the one Task 4 found to be an artefact: that $D$'s AUROC of
$0.312$ shows the score is "below chance" / "anti-informative". With the pre-violation
horizon matched between classes the AUROC is $0.496$ (H=2) and $0.432$ (H=3); the
original $0.312$ was substantially driven by the asymmetry between how violating and
compliant runs were truncated. The negative conclusion (no usable early warning on this
corpus) **survives unchanged**; only the strength of the mechanism attributed to it
weakens. See `RESULTS.md` §Task 4 for the full workings and the `action_index` falsifier
test that pins the artefact.

Patches below are expressed as *current* / *proposed replacement* per location, so the
author can accept, revise, or reject each independently. Numbers in the proposed text
come from `results/task4_next_action.json` (committed `ca52fbc`).

---

## Patch 1 — Abstract (currently line 47)

### Current

> The anomaly score we propose for early warning does not work: its AUROC is $0.312$,
> below chance, and split-conformal calibration overshoots its target false-alarm rate by
> a factor of about $2.8$.

### Proposed replacement

> The anomaly score we propose for early warning does not work: at the raw run-level it
> appears anti-predictive (AUROC $0.312$), but this is substantially a truncation artefact
> --- violating runs are truncated at their first violation and compliant ones are not, so
> the run-level maximum is taken over systematically fewer draws in the positive class.
> With the pre-violation horizon matched between classes the AUROC is uninformative
> ($0.496$ at H=2, $0.432$ at H=3); re-scoring the proposed action instead of the prefix
> gives a modest prefix-level improvement (AUROC $0.603$) that is still far too weak for a
> guard, catching nothing at a $5\%$ false-alarm budget. Split-conformal calibration
> overshoots its target false-alarm rate by a factor of about $2.8$ on the original score.

---

## Patch 2 — Table 2 (`tab:rq2`, currently lines 411–432)

### Current

```latex
\begin{table}[t]
\caption{RQ2: the distance score $D$ does not give early warning. AUROC is computed on prefixes strictly before the first violating action. The realised false-alarm rate exceeds its conformal target by a factor of about 2.8, indicating that exchangeability does not hold across scenarios.}
\label{tab:rq2}
\vskip 0.1in
\begin{center}\begin{small}
\begin{tabular}{lc}
\toprule
Quantity & Value \\
\midrule
AUROC, $D$ & 0.312 \\
AUROC, action count & 0.218 \\
AUROC, keyword rule & 0.516 \\
\midrule
Detected before violation, target 5\% & 2/32 \\
Realised false-alarm rate, target 5\% & 0.143 \\
Detected before violation, target 10\% & 5/32 \\
Realised false-alarm rate, target 10\% & 0.270 \\
\bottomrule
\end{tabular}
\end{small}\end{center}
\vskip -0.1in
\end{table}
```

### Proposed replacement

```latex
\begin{table}[t]
\caption{RQ2: early warning on this corpus. AUROC columns are run-level, computed on prefixes strictly before the first violating action. The unmatched column takes the maximum over all eligible prefixes --- so over systematically more draws for compliant runs than for violating ones, which are truncated at the first violation. Matching the horizon to $H$ pre-violation actions removes that confound: the \texttt{action\_index} score lies above chance ($0.172$) when unmatched and lands at exactly $0.500$ when matched, which is how we calibrated the matching. At matched horizon, $D$ carries no usable signal. A next-action scorer built from typed features of the proposed action and the preceding context gives a modest prefix-level AUROC of $0.603$ (position features ablated: $0.604$) but does not convert into usable detection: at a $5\%$ false-alarm budget it fires in $0$ of $17$ violating runs at $H=2$ and $0$ of $10$ at $H=3$. Only $10$--$17$ violating runs survive to the matched horizon; the AUROCs' intervals contain chance in every case.}
\label{tab:rq2}
\vskip 0.1in
\begin{center}\begin{small}
\begin{tabular}{lccc}
\toprule
Score & unmatched & matched H=2 & matched H=3 \\
\midrule
\texttt{action\_index} (falsifier) & 0.172 & 0.500 & 0.500 \\
\midrule
$D$ (prefix distance) & 0.293 & 0.496 & 0.432 \\
next-action & 0.396 & 0.381 & 0.512 \\
keyword rule & 0.495 & 0.500 & 0.500 \\
\bottomrule
\end{tabular}

\vspace{0.5em}

\begin{tabular}{lccc}
\toprule
Operating point ($D$) & detection & realised FAR & target FAR \\
\midrule
matched H=2, 5\% target & 0/17 & 0.054 & 0.05 \\
matched H=2, 10\% target & 2/17 & 0.120 & 0.10 \\
matched H=3, 5\% target & 0/10 & 0.103 & 0.05 \\
matched H=3, 10\% target & 0/10 & 0.161 & 0.10 \\
\bottomrule
\end{tabular}
\end{small}\end{center}
\vskip -0.1in
\end{table}
```

**Rationale for the schema change**: the single-column table hid the artefact. Showing
unmatched and matched side by side makes the falsifier (`action_index`) do its job
visibly — a score that cannot be anti-predictive scores $0.172$ unmatched, and the fact
that matching returns it to exactly $0.500$ is what certifies the matching. The paper's
original lower-rows numbers (detection $2/32$ and $5/32$, FAR $0.143$ and $0.270$) are
unmatched-horizon values and inherit the same confound; the proposed table reports the
operating-point values at the matched horizons instead. If you want the unmatched values
kept as a separate panel for continuity with the original table, say so and I'll add
them.

---

## Patch 3 — RQ2 section narrative (currently line 434)

### Current

> Table~\ref{tab:rq2} reports the anomaly component, and it is a negative result. Scored
> strictly on prefixes before the first violating action, $D$ achieves an AUROC of
> $0.312$ --- \emph{below} chance. Violating runs sit closer to compliant reference
> behaviour than held-out compliant runs do. A keyword baseline is at chance ($0.516$)
> and a step-count baseline is also inverted ($0.218$). At a $5\%$ target false-alarm
> rate, $D$ fires before the violation in $2$ of $32$ violating runs.

### Proposed replacement

> Table~\ref{tab:rq2} reports the anomaly component, and it is a negative result, but
> the strength of the negative claim depends on controlling an asymmetry we had not
> isolated when the paper was first drafted. Violating runs are truncated at their first
> violation and so contribute a median of $3$ eligible prefixes; compliant runs are not
> truncated and contribute a median of $5$. Taking a run-level maximum over unequal
> numbers of draws biases the score systematically against the positive class, which
> alone is enough to make an uninformative score \emph{look} anti-predictive. We built an
> \texttt{action\_index}-only falsifier (prefix index as the score, no features)
> precisely to measure this: at the unmatched horizon it scores $0.172$ --- a score that
> cannot be anti-predictive is $0.17$ --- and matching the horizon to a fixed $H$
> pre-violation actions returns it to exactly $0.500$, as it must. We take this as
> evidence that the matching works and that the unmatched run-level AUROCs should not be
> read as mechanisms. At the matched horizon $D$'s AUROC is $0.496$ ($H=2$) and $0.432$
> ($H=3$): the right reading is that $D$ carries no usable signal here, not that it is
> actively anti-informative.

---

## Patch 4 — Secondary attempt to rescue the component (currently line 465)

### Current

> The conclusion we draw is that the problem is not in the calibration layer. A
> conformal wrapper controls the error rate of whatever score it is given; it cannot
> manufacture signal. With an AUROC of $0.312$ the underlying score is anti-informative,
> and re-calibrating it more cleverly yields a better-behaved uninformative detector.
> Fixing the early-warning component requires a different representation or longer
> trajectories, not a different quantile.

### Proposed replacement

> The conclusion we draw is that the problem is not in the calibration layer. A
> conformal wrapper controls the error rate of whatever score it is given; it cannot
> manufacture signal. With the horizon artefact controlled $D$'s AUROC lies within noise
> of chance, so the underlying score is uninformative; re-calibrating an uninformative
> score more cleverly yields a better-behaved uninformative detector. A direct repair of
> the kind the framework invites --- scoring the proposed next action rather than the
> prefix distance --- gives a modest prefix-level AUROC of $0.603$ ($0.604$ with
> position features ablated, so the discrimination comes from the typed action rather
> than from where in the run it sits) but no deployable detection: at a $5\%$
> false-alarm budget it fires in $0$ of $17$ violating runs at the matched horizon.
> Fixing the early-warning component on this corpus requires a different representation
> or longer trajectories, not a different quantile.

---

## Patch 5 — Conclusion (currently line 515)

### Current

> ...The early-warning component does not survive contact with data at this scale, and
> the conformal guarantee it relies on overshoots its target by roughly a factor of
> three; three exchangeability-robust calibration variants failed to recover it, which
> locates the fault in the score rather than in the calibration layer...

### Proposed replacement

> ...The early-warning component does not survive contact with data at this scale: $D$'s
> apparent anti-prediction at the run level turned out to be a horizon-asymmetry
> artefact, and with the horizon matched the score is uninformative; a direct repair that
> scores the proposed next action gives a modest prefix-level AUROC ($0.60$) that
> catches no violating run at a $5\%$ false-alarm budget. The conformal guarantee the
> original score relied on overshoots its target by roughly a factor of three; three
> exchangeability-robust calibration variants failed to recover it, which --- taken with
> the uninformative underlying score --- locates the fault in the score and the
> trajectory length rather than in the calibration layer...

---

## Still to decide (the parts I will not do without your call)

1. **Table 3 (`tab:conformal`, lines 443–461) stays as is**, in my reading. Its target
   is calibration-method robustness, not $D$ itself; the overshoot pattern it documents
   is a real property of the conformal wrapper that does not depend on whether $D$ is
   anti-informative or uninformative. If you prefer, we can add a one-line footnote
   stating that these multiples are reported against unmatched-horizon $D$, so they
   should not be read as evidence about the score's intrinsic quality.
2. **Where to introduce the `action_index` falsifier.** Patch 2 puts it in the table;
   Patch 3 explains it in prose. If you'd rather it live only in an appendix, I can move
   both. If you'd rather drop it entirely and just report matched-horizon numbers with
   a one-line caveat, I can do that too — I think it's load-bearing for a reviewer,
   which is why I kept it.
3. **The next-action scorer.** Patches 1, 2 and 4 report it. If you want it reserved for
   a separate paragraph with an explicit "this was done because" rather than mixed into
   the $D$ discussion, say so.
4. **Numbers to co-update elsewhere in the paper if these patches land.** `RESULTS.md`
   §Task 2 also notes `83%` → `84.5%` and `9.9%` → `10.4%` from the O-coverage work. If
   you want those paper-level updates drafted too, I'll add Patch 6 and Patch 7.

Once you give the go-ahead on any of these, I'll apply the specific ones you approve to
`paper/main.tex` on a dedicated branch so your Overleaf archive stays untouched until
you say otherwise.
