# AAE report template
The report is a LaTeX document, `report/report.tex`, that inputs files from `report/generated/`.
You write both yourself: copy the skeleton below once during setup, and rewrite the generated
files from `report/session.json` and `report/experiments/NNN/{meta.json,change.patch}` after
every experiment. Then compile in `report/` with `latexmk -pdf -interaction=nonstopmode report.tex`
(or run `pdflatex` twice). This edition of AAE contains no report generator program; the
example below shows exactly what each generated file looks like for a session with three
experiments, so follow its structure and macros.

Rules for the generated files:

- Escape LaTeX special characters in all text from `meta.json` (`\ & % $ # _ { } ~ ^`);
  text in backticks becomes `\texttt{...}`, text in `$...$` is passed through as math.
- `metric` defaults to the geometric mean of `measurements`. Compare every experiment with
  the baseline (experiment 001) and with the best value accepted before it, respecting
  `direction` (`lower` or `higher`).
- `trajectory.tex` plots `generated/traj_*.dat`: one data file per series (best so far as a
  step line, baseline, kept with the patch number as label, discarded); each file has a header
  line and one row per point.
- `experiments.tex` has one page per experiment, kept, discarded and crashed alike. The code
  change is read from `generated/diffs/NNN.diff` (the experiment's `change.patch` without the
  commit header); shorten very long diffs so that the page stays one page.
- `accepted.tex` lists the kept changes in acceptance order with their patch files.

## Skeleton: `report/report.tex`

```latex
% AAE experiment report. Static skeleton; build_report.py writes generated/*.tex next to it.
\documentclass[11pt,a4paper]{article}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{libertinus}
\usepackage[libertinus]{newtxmath}
\usepackage[a4paper,margin=2.2cm,top=2.3cm,bottom=2.4cm]{geometry}
\usepackage{microtype}
\usepackage{amsmath}
\usepackage{booktabs,tabularx,array}
\usepackage{xcolor}
\usepackage{pgfplots}
\pgfplotsset{compat=1.18}
\usepackage[most]{tcolorbox}
\usepackage{enumitem}
\usepackage{fancyhdr}
\usepackage{listings}
\usepackage[hidelinks]{hyperref}

\emergencystretch=1.5em
\setlist{itemsep=2pt,topsep=3pt,parsep=0pt}
\setlength{\parindent}{0pt}
\setlength{\parskip}{4pt}

% colours
\definecolor{ink}{HTML}{1F2937}
\definecolor{accent}{HTML}{1D4ED8}
\definecolor{safe}{HTML}{047857}
\definecolor{unsafe}{HTML}{B91C1C}
\definecolor{neutral}{HTML}{6B7280}
\definecolor{soft}{HTML}{F3F4F6}

\input{generated/session.tex}

\pagestyle{fancy}
\fancyhf{}
\renewcommand{\headrulewidth}{0.3pt}
\fancyhead[L]{\small\color{ink!70}\ReportTitle}
\fancyhead[R]{\small\color{ink!70}\nouppercase{\leftmark}}
\fancyfoot[C]{\small\thepage}
\renewcommand{\sectionmark}[1]{\markboth{#1}{}}

\makeatletter
\renewcommand\section{\@startsection{section}{1}{0pt}{-1ex}{1.2ex}{\Large\bfseries\color{accent}}}
\renewcommand\subsection{\@startsection{subsection}{2}{0pt}{-1ex}{0.6ex}{\large\bfseries\color{ink}}}
\makeatother

% status badges
\newcommand{\badge}[2]{\tcbox[on line,colback=#1!10,colframe=#1!70,boxrule=0.4pt,arc=2pt,left=3pt,right=3pt,top=1pt,bottom=1pt]{\scriptsize\bfseries\color{#1!80!black}#2}}
\newcommand{\keep}{\badge{safe}{KEEP}}
\newcommand{\discard}{\badge{neutral}{DISCARD}}
\newcommand{\crash}{\badge{unsafe}{CRASH}}
\newcommand{\baseline}{\badge{accent}{BASELINE}}

% boxes
\newtcolorbox{hypbox}{enhanced,colback=soft,colframe=ink!25,boxrule=0.4pt,arc=2pt,left=6pt,right=6pt,top=4pt,bottom=4pt}
\newtcolorbox{verdictbox}[1]{enhanced,colback=#1!4,colframe=#1!60,boxrule=0.5pt,arc=2pt,left=6pt,right=6pt,top=4pt,bottom=4pt}
\newtcolorbox{summarybox}{enhanced,colback=soft,colframe=ink!30,boxrule=0.5pt,arc=2pt,left=8pt,right=8pt}

% diffs
\lstdefinelanguage{diff}{
  morecomment=[f][\color{safe!85!black}]{+},
  morecomment=[f][\color{unsafe}]{-},
  morecomment=[f][\color{accent}]{@@},
}
\lstset{language=diff,basicstyle=\ttfamily\scriptsize,columns=fixed,
  breaklines=true,breakatwhitespace=false,postbreak=\mbox{\textcolor{neutral}{$\hookrightarrow$}\space},
  tabsize=4,showstringspaces=false,keepspaces=true,
  frame=single,rulecolor=\color{ink!20},backgroundcolor=\color{soft!60},
  xleftmargin=3pt,xrightmargin=3pt,framexleftmargin=3pt,framexrightmargin=3pt}

\hypersetup{pdftitle={\ReportTitle},pdfauthor={}}

\begin{document}

%======================================================================
\thispagestyle{empty}
\begin{center}
{\color{accent}\rule{\linewidth}{1.2pt}}\par\vspace{6pt}
{\LARGE\bfseries \ReportTitle}\par\vspace{5pt}
{\large \ReportSubtitle}\par\vspace{4pt}
{\color{accent}\rule{\linewidth}{1.2pt}}
\end{center}
{\renewcommand{\thefootnote}{}\footnotetext{\raggedright\hspace{-1.8em}This report was created using the Agentic Algorithm Engineering skill: \url{https://github.com/CHSZLab/AgenticAlgorithmEngineering}}}

\input{generated/summary.tex}

%======================================================================
\clearpage
\section{Trajectory}\label{sec:trajectory}
\input{generated/trajectory.tex}

%======================================================================
\clearpage
\section{Accepted changes}\label{sec:accepted}
\input{generated/accepted.tex}

%======================================================================
\input{generated/experiments.tex}

\end{document}
```

## Example session data

`report/session.json`:

```json
{
 "title": "AAE session: example solver",
 "subtitle": "Running time of the solver on 2 inputs, branch aae/example",
 "target": "src/solver.cpp",
 "metric": "time",
 "unit": "s",
 "direction": "lower",
 "resource": "peak memory [GB]",
 "machine": "8 cores, 32 GB RAM",
 "branch": "aae/example",
 "date": "2026-11-21",
 "summary": "Two hypotheses tested: the bucket queue was kept, the cache-aligned layout was discarded."
}
```

`report/experiments/001/meta.json`:

```json
{
 "exp": 1,
 "title": "Baseline",
 "commit": "a1b2c3d",
 "hypothesis": "Baseline, unmodified code.",
 "intuition": "Reference point.",
 "prediction": "-",
 "status": "baseline",
 "metric": 2.572,
 "resource": 1.2,
 "measurements": [
  {
   "input": "rgg_n_2_20",
   "value": 4.1
  },
  {
   "input": "road_eu",
   "value": 4.7
  }
 ],
 "verdict": "Baseline established.",
 "reflection": "Profile shows 60% of the time in the priority queue."
}
```

`report/experiments/002/meta.json`:

```json
{
 "exp": 2,
 "title": "Bucket queue in refinement",
 "commit": "b2c3d4e",
 "hypothesis": "Replacing the binary heap by a bucket queue reduces time by ~15% because keys are small integers.",
 "intuition": "Most time is spent in heap operations with integer gains.",
 "prediction": "-10% to -20%; could regress if gains are spread widely.",
 "status": "keep",
 "metric": 2.181,
 "resource": 1.2,
 "measurements": [
  {
   "input": "rgg_n_2_20",
   "value": 3.483
  },
  {
   "input": "road_eu",
   "value": 3.976
  }
 ],
 "verdict": "Confirmed: -15.2% geometric mean, matching the prediction.",
 "reflection": "The queue is no longer the bottleneck; next look at memory layout.",
 "patch": "patches/0001-bucket-queue-refinement.patch"
}
```

`report/experiments/002/change.patch`:

```diff
diff --git a/src/solver.cpp b/src/solver.cpp
--- a/src/solver.cpp
+++ b/src/solver.cpp
@@ -10,3 +10,3 @@
-    BinaryHeap q;
+    BucketQueue q(max_gain);
```

`report/experiments/003/meta.json`:

```json
{
 "exp": 3,
 "title": "Cache-aligned node array",
 "commit": "c3d4e5f",
 "hypothesis": "Aligning node records to 64 bytes reduces time by ~5%.",
 "intuition": "Records straddle cache lines.",
 "prediction": "-3% to -7%.",
 "status": "discard",
 "metric": 2.203,
 "resource": 1.4,
 "measurements": [
  {
   "input": "rgg_n_2_20",
   "value": 3.51
  },
  {
   "input": "road_eu",
   "value": 4.02
  }
 ],
 "verdict": "Refuted: +1.0%, more memory.",
 "reflection": "Padding increases the working set more than it saves."
}
```

`report/experiments/003/change.patch`:

```diff
diff --git a/src/node.h b/src/node.h
--- a/src/node.h
+++ b/src/node.h
@@ -1,3 +1,3 @@
-struct Node {
+struct alignas(64) Node {
```

## Generated files for this example

`report/generated/session.tex`:

```latex
\newcommand{\ReportTitle}{AAE session: example solver}
\newcommand{\ReportSubtitle}{Running time of the solver on 2 inputs, branch aae/example}
```

`report/generated/summary.tex`:

```latex
\section*{Summary}
\begin{summarybox}
\textbf{time} (lower is better): baseline 2.572 s $\rightarrow$ best 2.181 s, an improvement by a factor of \textbf{1.179}.\par\medskip
2 hypotheses tested: 1 kept, 1 discarded, 0 crashed. Accepted changes are stored as 1 numbered patches in \texttt{patches/} (Section~\ref{sec:accepted}).
\par\medskip Two hypotheses tested: the bucket queue was kept, the cache-aligned layout was discarded.
\end{summarybox}
{\small\begin{tabularx}{\linewidth}{@{}l X@{}}
Target: & src/solver.cpp\\
Branch: & aae/example\\
Machine: & 8 cores, 32 GB RAM\\
Date: & 2026-11-21\\
\end{tabularx}}
\subsection*{Contents (one page per hypothesis)}
{\small\begin{tabularx}{\linewidth}{@{}l X l r r@{}}
\toprule Exp & Hypothesis & Status & time & Page\\\midrule
\hyperref[exp:1]{E001} & Baseline & \baseline & 2.572 & \pageref{exp:1}\\
\hyperref[exp:2]{E002} & Bucket queue in refinement & \keep & 2.181 & \pageref{exp:2}\\
\hyperref[exp:3]{E003} & Cache-aligned node array & \discard & 2.203 & \pageref{exp:3}\\
\bottomrule\end{tabularx}}
```

`report/generated/trajectory.tex`:

```latex
\begin{center}\begin{tikzpicture}
\begin{axis}[width=0.95\linewidth,height=8.5cm,axis lines=left,xlabel={experiment},ylabel={time [s]},
  tick label style={font=\small\color{ink!70}},label style={font=\small\color{ink}},
  axis line style={ink!50},major tick style={ink!50},ymajorgrids,grid style={ink!10},
  legend style={draw=none,fill=none,font=\small,at={(0.5,1.02)},anchor=south,legend columns=-1,/tikz/every even column/.append style={column sep=10pt}},clip=false,
  xmin=0.5,enlarge y limits=0.08,xtick distance=1]
\addplot[const plot mark left,accent,line width=1.2pt] table[x=x,y=y] {generated/traj_best.dat};
\addlegendentry{best so far}
\addplot[only marks,mark=square*,mark size=3pt,accent,mark options={draw=white,line width=0.6pt}] table[x=x,y=y] {generated/traj_baseline.dat};
\addlegendentry{baseline}
\addplot[only marks,mark=*,mark size=3pt,safe,mark options={draw=white,line width=0.6pt},nodes near coords,point meta=explicit symbolic,every node near coord/.append style={font=\scriptsize\bfseries\color{ink},anchor=south,yshift=1pt}] table[x=x,y=y,meta=lab] {generated/traj_keep.dat};
\addlegendentry{kept (patch number)}
\addplot[only marks,mark=o,mark size=2.6pt,neutral,line width=0.7pt] table[x=x,y=y] {generated/traj_discard.dat};
\addlegendentry{discarded}
\end{axis}\end{tikzpicture}\end{center}
{\small\color{ink!80}Every tested hypothesis is one point; the step line is the best result accepted so far. Labels P$i$ give the number of the patch in \texttt{patches/} that a kept change produced.}
\subsection*{Course of the session}
{\small\begin{tabularx}{\linewidth}{@{}l l X r r@{}}
\toprule Exp & Status & Hypothesis & time & best\\\midrule
E001 & \baseline & Baseline & 2.572 & 2.572\\
E002 & \keep & Bucket queue in refinement & 2.181 & 2.181\\
E003 & \discard & Cache-aligned node array & 2.203 & 2.181\\
\bottomrule\end{tabularx}}
```

`report/generated/traj_best.dat`:

```text
x y
1 2.572
2 2.181
3 2.181
```

`report/generated/traj_baseline.dat`:

```text
x y lab
1 2.572 -
```

`report/generated/traj_keep.dat`:

```text
x y lab
2 2.181 P1
```

`report/generated/traj_discard.dat`:

```text
x y lab
3 2.203 -
```

`report/generated/accepted.tex`:

```latex
Applying the patches in order to the baseline commit reproduces the best version:\par\smallskip\qquad\texttt{git am patches/*.patch}\par\smallskip
{\small\begin{tabularx}{\linewidth}{@{}l l X r r r@{}}
\toprule Patch & Exp & Change & time & step & total\\\midrule
\texttt{0001} & \hyperref[exp:2]{E002} & Bucket queue in refinement & 2.181 & 1.179$\times$ & 1.179$\times$\\
\bottomrule\end{tabularx}}
\par{\small\color{ink!80}\emph{step}: improvement factor over the previous best; \emph{total}: over the baseline.}
```

`report/generated/experiments.tex`:

```latex
\clearpage
\section{Experiments}\label{sec:experiments}
\subsection*{E001\ \ Baseline}\label{exp:1}
\addcontentsline{toc}{subsection}{E001}
\baseline\hfill{\small\color{ink!70}commit \texttt{a1b2c3d}}\par
\begin{hypbox}\small\textbf{Hypothesis.} Baseline, unmodified code.\end{hypbox}
{\small\textbf{Intuition.} Reference point.}\par
{\small\textbf{Prediction.} -}\par
\par\smallskip{\bfseries\color{ink}Measurements}\par
{\small\begin{tabularx}{\linewidth}{@{}X r r r r@{}}
\toprule Input & baseline & previous best & this & vs.\ best\\\midrule
rgg\_n\_2\_20 & -- & -- & 4.1 & --\\
road\_eu & -- & -- & 4.7 & --\\
\midrule
\textbf{geometric mean} & \textbf{--} & \textbf{--} & \textbf{2.572} & --\\
\bottomrule\end{tabularx}}
\par{\small Peak peak memory [GB]: 1.2}
\begin{verdictbox}{accent}\small
\textbf{Verdict.} Baseline established.
\par\smallskip\textbf{Reflection.} Profile shows 60\% of the time in the priority queue.
\end{verdictbox}
\clearpage
\subsection*{E002\ \ Bucket queue in refinement}\label{exp:2}
\addcontentsline{toc}{subsection}{E002}
\keep\hfill{\small\color{ink!70}commit \texttt{b2c3d4e} \textperiodcentered\ patch \texttt{0001-bucket-queue-refinement.patch}}\par
\begin{hypbox}\small\textbf{Hypothesis.} Replacing the binary heap by a bucket queue reduces time by \textasciitilde{}15\% because keys are small integers.\end{hypbox}
{\small\textbf{Intuition.} Most time is spent in heap operations with integer gains.}\par
{\small\textbf{Prediction.} -10\% to -20\%; could regress if gains are spread widely.}\par
\par\smallskip{\bfseries\color{ink}Measurements}\par
{\small\begin{tabularx}{\linewidth}{@{}X r r r r@{}}
\toprule Input & baseline & previous best & this & vs.\ best\\\midrule
rgg\_n\_2\_20 & 4.1 & 4.1 & 3.483 & \textcolor{safe}{-15.0\,\%}\\
road\_eu & 4.7 & 4.7 & 3.976 & \textcolor{safe}{-15.4\,\%}\\
\midrule
\textbf{geometric mean} & \textbf{2.572} & \textbf{2.572} & \textbf{2.181} & \textcolor{safe}{-15.2\,\%}\\
\bottomrule\end{tabularx}}
\par{\small Peak peak memory [GB]: 1.2}
\begin{verdictbox}{safe}\small
\textbf{Verdict.} Confirmed: -15.2\% geometric mean, matching the prediction.
\par\smallskip\textbf{Reflection.} The queue is no longer the bottleneck; next look at memory layout.
\end{verdictbox}
\par\smallskip{\bfseries\color{ink}Code changes}\hfill{\small\color{ink!70}1 file, \textcolor{safe}{+1} \textcolor{unsafe}{-1}}\par
\lstinputlisting{generated/diffs/002.diff}
\clearpage
\subsection*{E003\ \ Cache-aligned node array}\label{exp:3}
\addcontentsline{toc}{subsection}{E003}
\discard\hfill{\small\color{ink!70}commit \texttt{c3d4e5f}}\par
\begin{hypbox}\small\textbf{Hypothesis.} Aligning node records to 64 bytes reduces time by \textasciitilde{}5\%.\end{hypbox}
{\small\textbf{Intuition.} Records straddle cache lines.}\par
{\small\textbf{Prediction.} -3\% to -7\%.}\par
\par\smallskip{\bfseries\color{ink}Measurements}\par
{\small\begin{tabularx}{\linewidth}{@{}X r r r r@{}}
\toprule Input & baseline & previous best & this & vs.\ best\\\midrule
rgg\_n\_2\_20 & 4.1 & 3.483 & 3.51 & \textcolor{unsafe}{+0.8\,\%}\\
road\_eu & 4.7 & 3.976 & 4.02 & \textcolor{unsafe}{+1.1\,\%}\\
\midrule
\textbf{geometric mean} & \textbf{2.572} & \textbf{2.181} & \textbf{2.203} & \textcolor{unsafe}{+1.0\,\%}\\
\bottomrule\end{tabularx}}
\par{\small Peak peak memory [GB]: 1.4}
\begin{verdictbox}{neutral}\small
\textbf{Verdict.} Refuted: +1.0\%, more memory.
\par\smallskip\textbf{Reflection.} Padding increases the working set more than it saves.
\end{verdictbox}
\par\smallskip{\bfseries\color{ink}Code changes}\hfill{\small\color{ink!70}1 file, \textcolor{safe}{+1} \textcolor{unsafe}{-1}}\par
\lstinputlisting{generated/diffs/003.diff}
```

`report/generated/diffs/002.diff`:

```diff
diff --git a/src/solver.cpp b/src/solver.cpp
--- a/src/solver.cpp
+++ b/src/solver.cpp
@@ -10,3 +10,3 @@
-    BinaryHeap q;
+    BucketQueue q(max_gain);
```

`report/generated/diffs/003.diff`:

```diff
diff --git a/src/node.h b/src/node.h
--- a/src/node.h
+++ b/src/node.h
@@ -1,3 +1,3 @@
-struct Node {
+struct alignas(64) Node {
```
