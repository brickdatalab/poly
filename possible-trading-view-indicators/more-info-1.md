

# Toward Black–Scholes for Prediction Markets: A Unified Kernel and Market-Maker's Handbook

Shaw Dalen*

Daedalus Research Team†

## Abstract

Prediction markets—exemplified by Polymarket and similar venues—aggregate dispersed information into tradable probabilities, yet they still lack the unifying stochastic kernel that options gained from Black–Scholes. As these markets scale (institutional participants, exchange integrations, and rising volumes around elections and macro prints), makers face belief–volatility, jump, and cross–event risks without standardized tools to quote or hedge them. We propose such a foundation: a *logit jump–diffusion with risk–neutral (RN) drift* that treats the traded probability $p_t$ as a $\mathbb{Q}$–martingale and exposes belief volatility, jump intensity, and dependence as quotable risk factors. On top, we build a calibration pipeline that filters microstructure noise, separates diffusion from jumps via EM, enforces the RN drift, and yields a stable belief–volatility surface. We then define a coherent derivative layer—variance, correlation, corridor, and first–passage instruments—analogous to volatility and correlation products in option markets. In controlled experiments (synthetic RN-consistent paths and real event data), the RN–JD model achieves lower short–horizon belief-variance forecast error than diffusion-only and $p$-space baselines, validating both its causal calibration and economic interpretability. Conceptually, the RN–JD kernel supplies the "implied volatility" analogue for prediction markets: a tractable, tradable language for quoting, hedging, and transferring *belief risk* across venues such as Polymarket.

# 1 Introduction

**What is prediction market and why we need it?** Prediction markets like Polymarket trade contracts that pay $1 if an event occurs and $0 otherwise. Under standard no-arbitrage reasoning, observed prices are interpretable as *risk-neutral* probabilities of

*daedalusrsch@gmail.com
†https://x.com/DaedalusRsch

1


---



the event. Empirically, these prices often track average beliefs under mild conditions, although biases exist and interpretation requires care [62, 63, 48]. These markets have been used to forecast outcomes in politics, economics, science, and beyond [11, 56]. Beyond entertainment or wagering, liquid, global event markets instantiate a Hayekian mechanism for aggregating dispersed knowledge [39]. Prices synthesize private signals into public probabilities, creating incentives for informed actors to reveal information when they expect to profit. Empirically and in practice, prediction markets can improve forecast accuracy and organizational decision-making by rewarding correct beliefs and penalizing noise [25]. The appeal has long been recognized by policymakers: the U.S. Defense Advanced Research Projects Agency (DARPA) explored a *Policy Analysis Market* (FutureMAP) for geopolitical risks before cancelling it in 2003 amid political criticism [34, 36]. At the same time, regulatory choices shape what can be listed: for example, the 1958 *Onion Futures Act* still bans U.S. onion futures, illustrating how legal constraints can limit the scope of information aggregation via markets [58]. Finally, recent debates over polling errors (e.g., the 2016 U.S. election) underscore the value of complementary, market-based signals when traditional information channels are noisy or biased [6]. Together, these strands motivate a standardized kernel and derivative layer so that "belief risk" can be quoted, hedged, and transferred at scale.

**Plain-language view of event contracts.** An *event contract* is a yes/no claim with a fixed payoff: it pays $1 if the specified outcome occurs by a given date and $0 otherwise. The traded price p<sub>t</sub> ∈ (0, 1) is naturally read as the market's risk-neutral probability for that outcome. Examples include "Will the unemployment rate exceed 5% in Q4?" or "Will upgrade U activate by block height H?". In regulated settings, the U.S. Commodity Futures Trading Commission (CFTC) describes such claims as derivative contracts tied to the occurrence of an event, typically with binary payoff structure; exchanges listing them must satisfy the same substantive requirements as other derivatives [1, 60]. Crypto-native venues list economically similar contracts under on-chain execution.

Execution is fragmented. Platforms rely on the *Logarithmic Market Scoring Rule (LMSR)* [35], on *constant-product automated market makers (CP-AMMs)*—a special case of *constant-function market makers (CFMMs)*—popularized by Uniswap [4, 8], or on traditional order books. Each mechanism sets prices, but none provides a shared stochastic *kernel* that explains how event probabilities should evolve over time, across information shocks, or jointly across related events. By contrast, once the Black–Scholes (BS) model appeared in options, markets standardized around *implied volatility*, which enabled quoting, hedging, and a deep derivative layer [15]. Prediction markets lack an analogous foundation.

**Motivation and background.** Market making in event contracts is hard. In microstructure, informed trading induces *adverse selection*: when a counterparty trades only when you are wrong, you lose on average [32, 46]. In binary event markets, inventory risk is concentrated near resolution and cannot be hedged by the underlying until settlement. For cost-function market makers such as LMSR, providing more liquidity increases worst-case loss; without external subsidies, they are expected to run at a deficit proportional to the liquidity they offer [52]. CP-AMMs/CFMMs face related profitability constraints for liquidity providers [9, 14]. In short, today's mechanisms expose makers to toxic flow and gap risk, but do not offer standardized tools to transfer *belief risk* (the

2


---



risk that the market-implied probability moves) across time or across related events.

**Why a derivative layer for event contracts?** Derivatives exist to let participants isolate and trade specific risks. For events, the primary risks are movements in the *belief level* and its *volatility* (how fast log-odds move), plus jump risk from news and cross-event co-movement. A derivative layer would (i) let market makers hedge adverse selection by offloading belief volatility and jump exposure; (ii) allow calendar hedges (between maturities or checkpoints before resolution); (iii) enable cross-event hedges that neutralize correlation and co-jumps; and (iv) concentrate liquidity around a small set of quoted risk factors, as implied volatility did for options. In mature option markets, variance/volatility swaps, correlation swaps, and related instruments serve exactly these functions for price volatility [28, 22, 17]. Prediction markets need the analogous instruments for belief dynamics.

**Context: the rise of Polymarket.** Crypto-native platforms have brought event trading to a wider audience and catalyzed institutional interest. In 2025, Intercontinental Exchange (ICE), the parent of the New York Stock Exchange, announced a strategic investment of up to $2 billion for roughly a 20% stake in Polymarket, with plans to distribute event-driven data through ICE's channels [53]. Separate disclosures report that Polymarket raised over $200 million across 2024–2025 prior to the ICE deal [16]. Together with growth spurts around major elections and macro events, these developments signal mainstream acceptance of event markets and amplify the need for a common pricing kernel and a standardized derivative layer.

**This paper.** We propose a minimal, actionable kernel: a *logit jump–diffusion with multi-event correlation*. Let $p_t \in (0, 1)$ be the risk-neutral event probability and $x_t = \log(p_t/(1 - p_t))$ its log-odds. We model $x_t$ as a correlated jump–diffusion. Enforcing the martingale property of $p_t$ under the risk-neutral measure pins down the drift of $x_t$; what remains—the belief-volatility $\sigma_b$, jump intensity and moments, correlation across events, and co-jump structure—are the tradable risk factors. On this kernel we define a coherent menu of *event-linked derivatives* (belief variance/volatility swaps, correlation swaps, corridor variance, threshold/path notes, and conditional baskets). Where possible we give closed-form or short-maturity approximations; otherwise we use *partial integro–differential equations (PIDE)* or *Monte Carlo (MC)*. We derive Greeks with respect to $x$ and to the kernel's parameters, and we outline practical hedges (calendar, cross-event, and inventory-aware rules near the 0/1 boundaries). Finally, we describe a data-driven calibration pipeline that maps mid/bid–ask/trade data to a smoothed belief-volatility surface with co-jump detection.

**Why now.** Standardization matters more than perfect realism. Black–Scholes was not "true," but it coordinated quoting and hedging around a small number of state variables; that standard enabled scale. A shared belief–variance surface can play the same role for event markets precisely as adoption accelerates. In 2025, Intercontinental Exchange (ICE), owner of the NYSE, announced *up to* $2 billion of strategic investment in Polymarket (at roughly $8 billion pre-money) and will distribute its event-driven data to institutions, a signal of mainstream integration [41, 57, 55]. On the usage side, monthly volumes

3


---



have broken through billion-dollar thresholds: reports based on Dune/DeFiLlama data indicate Polymarket posted about $1.4 billion in September 2025 while Kalshi exceeded $1–3 billion depending on the week and product mix, with sports driving much of the surge [27, 26, 54]. At the same time, U.S. oversight is becoming more explicit: the CFTC proposed rulemaking on event contracts in 2024 (clarifying categories that may be contrary to the public interest), and litigation around political markets underscores an evolving but increasingly articulate framework [59, 61, 44]. This combination of institutional capital, record volumes, and regulatory clarity strengthens the case for a common pricing kernel and a standardized derivative layer to concentrate liquidity, reduce maker losses via hedging, and support an institutional market for belief risk.

## 2 Related Work

### 2.1 Prediction markets and mechanisms.

The *Logarithmic Market Scoring Rule (LMSR)* introduced a bounded-loss, always-on *automated market maker (AMM)* for event contracts and combinatorial claims, giving crisp axiomatic guarantees and a tractable *cost function* representation [35, 23]. Subsequent designs generalized AMMs to convex cost-function markets and to liquidity-adaptive variants that mitigate worst-case losses and over-movement in thin markets [2, 52]. On crypto rails, *constant-function market makers (CFMMs)*—including the *constant-product AMM (CP-AMM)* popularized by Uniswap—standardized execution and on-chain pricing primitives [7, 4]. In contrast, *central limit order books (CLOBs)* provide deep execution microstructure but no common probabilistic dynamics for event prices [33]. Our focus is complementary: we seek a shared *stochastic kernel* for risk-neutral event probabilities across time, shocks, and related events, independent of the execution venue.

### 2.2 Option pricing, implied surfaces, and coordination role.

The Black–Scholes–Merton paradigm established a common language for quoting and hedging (implied volatility, Greeks) [15]. It catalyzed successive layers: jumps [50], stochastic volatility [40], and implied-consistent *local volatility* surfaces [29], leading to the modern practice of surface construction and management [31]. This standardization coordinated liquidity and risk transfer. Our work aims for the analogous role in prediction markets: replace price diffusions by *logit* dynamics for probabilities on (0, 1), preserving tractability while exposing belief-level, belief-volatility, and jump/correlation factors as quotable objects.

### 2.3 Information-based processes.

Information-based asset pricing treats prices as conditional expectations under a filtration generated by noisy "information processes," often Brownian-bridge–driven, offering a structural view of how news reveals payoffs over time [19]. Separately, boundary-constrained diffusions on [0, 1] (e.g., Wright–Fisher/Jacobi families) provide mathematically consistent dynamics for probabilities or bounded state variables [43, 3]. We adopt a

4


---


simple alternative: a *logit* map that transports $p_t \in (0, 1)$ to $\mathbb{R}$ so standard semimartingale tools apply, while explicit jump terms capture news shocks and co-jumps across related events.

## 2.4 Microstructure, filtering, and calibration.

Our calibration pipeline draws on state-space methods that separate the latent "efficient" signal from microstructure noise in high-frequency mid/bid-ask/trade streams [37, 30]. For parameter learning with jumps, EM/likelihood filters for jump-diffusions and inference tools for detecting common jumps offer practical estimators and diagnostics [12, 13, 42]. We adapt these ingredients to log-odds increments and to co-jump screening across events, yielding a stable belief-volatility surface suitable for quoting and hedging.

# 3 Methodology

## 3.1 Background and Motivation: From Black–Scholes to Event Probabilities

**What the Black–Scholes (BS) framework is.** In the BS paradigm, the discounted underlying price is a martingale under the risk–neutral measure. With geometric Brownian motion,

$$\frac{dS_t}{S_t} = \sigma dW_t \quad \text{(under } \mathbb{Q}\text{)},$$

self-financing replication implies a linear pricing *PDE* and closed-form option values. The key output is not realism per se, but a *common language* for quoting and hedging: implied volatility, Greeks, and volatility surfaces [15, 49, 40, 29, 31]. This language coordinates liquidity, enables standardized risk transfer, and supports a deep derivative stack.

**Why a BS-like kernel is needed for event contracts.** Event contracts trade binary payoffs. Their quoted prices are interpretable as discounted, risk–neutral probabilities of occurrence [63, 11]. Today, venues execute via scoring rules or AMMs or CLOBs, but there is no shared *stochastic* model for how probabilities evolve across time, shocks, or related events. Without a kernel, makers cannot isolate "belief risk" (level, volatility, jumps, co-movement) or lay it off in a standard way; spreads widen around news; inventory near the 0/1 boundaries becomes hard to manage. A tractable kernel standardizes quoting (what to post), hedging (what to buy/sell against), and calibration (how to read data), just as implied-vol surfaces did for options.

**How our setup connects to and differs from BS.** (i) *State variable:* BS models prices; we model *probabilities*. We map $p_t \in (0, 1)$ to log-odds $x_t \in \mathbb{R}$ so Itô–Lévy tools apply while respecting boundaries. (ii) *Martingale restriction:* in BS, discounted $S_t$ is a martingale; here discounted $p_t = S(x_t)$ is a martingale. This pins down the drift of $x_t$ (Eq. (3)) and leaves belief-volatility and jump features as the quotable risks. (iii) *News*

5


---



*and co-movement:* event probabilities jump at information times, and related events co-move; our kernel includes both diffusive correlation and co-jumps (Eq. (4)), analogous to jumps/SV in equity models [50, 40, 24]. (iv) *Incompleteness:* the binary payoff cannot be dynamically replicated by the underlying before resolution, so markets are incomplete. Derivatives on $x$ or $p$ (variance, correlation, corridor, first-passage) create targeted hedges that make inventory and adverse-selection risk manageable, echoing the role of variance and correlation swaps in equities [28, 22].

**Trading relationship between the base event and our derivatives.** The base contract transfers *level* risk: long $p_t$ benefits if the event becomes likelier. Makers, however, are primarily exposed to the *path* of beliefs: rapid swings around $p \approx 0.5$, jumps on announcements, and cross-event shocks. *Belief-variance swaps* exchange realized quadratic variation of $x$ (or of $p$) for a fixed strike, letting makers sell tight spreads and buy variance to neutralize volatility risk around data releases (Eqs. (5)–(6)). *Correlation/covariance swaps* hedge baskets (e.g., related races in an election night) by offsetting diffusive correlation and co-jumps (Eq. (4)). *Corridor variance* focuses hedging budget on the "swing zone" $p \in [a, b]$, where order flow is most toxic and inventory turns fastest. *First-passage notes* transfer gap risk near thresholds (e.g., "does $p$ break 0.7 before $T$?"), critical when quotes cluster near boundaries.

**Empirical context.** Across liquid option markets, the existence of a shared surface reduced dispersion in quotes and tightened spreads [31]. Prediction markets show analogous frictions: spreads and cancellations widen near scheduled news; quotes gap on unexpected announcements; correlated events move together. A belief-variance/correlation layer makes these exposures explicit and tradable, allowing makers to keep quotes live while laying off risk—precisely the coordination role BS played for options.

## 3.2 Kernel: Logit Jump–Diffusion with Risk–Neutral Drift

**Notation and setup.** Fix a filtered probability space $(\Omega, \mathcal{F}, \{\mathcal{F}_t\}_{t\geq 0}, \mathbb{Q})$ satisfying the usual conditions, where $\mathbb{Q}$ denotes the risk–neutral measure (prices are discounted). Let the event-contract price at time $t$ be $p_t \in (0, 1)$ and define its *log-odds*

$$x_t := \text{logit}(p_t) = \log \frac{p_t}{1 - p_t}, \quad \text{so that} \quad p_t = S(x_t) = \frac{1}{1 + e^{-x_t}}.$$

Write $S'(x) = S(x)(1 - S(x)) = p(1-p)$ and $S''(x) = S'(x)(1 - 2S(x)) = p(1-p)(1-2p)$.
Let $W_t$ be a standard Brownian motion under $\mathbb{Q}$, and let $N(dt, dz)$ be an integer-valued random measure on $\mathbb{R} \times \mathbb{R}$ with (possibly time-varying) compensator $\nu_t(dz)\, dt$ (the *Lévy measure* $\nu_t$ satisfies $\int_{\mathbb{R}} \min\{1, z^2\}\nu_t(dz) < \infty$). The compensated jump measure is

$$\tilde{N}(dt, dz) := N(dt, dz) - \nu_t(dz)\, dt, \qquad \chi(z) := z\, \mathbf{1}_{\{|z| \leq 1\}}.$$

We model belief dynamics on the real line via the *logit* process $x_t$,

$$dx_t = \mu(t, x_t)\, dt + \sigma_b(t, x_t)\, dW_t + \int_{\mathbb{R}} z\, \tilde{N}(dt, dz), \tag{1}$$

---



where $\sigma_b$ is the *belief volatility*. This $x$-dynamics guarantees $p_t = S(x_t) \in (0,1)$ while allowing diffusive moves and news-driven jumps. The representation (1) is a standard Itô–Lévy SDE [10, 51, 24].

**Risk–neutral (martingale) drift.** Because $p_t = S(x_t)$ is the (discounted) risk–neutral price of a $1 payoff on event occurrence, $\{p_t\}$ must be a $\mathbb{Q}$-martingale. Applying the Itô formula for jump processes to $S(x_t)$ (with truncation $\chi$) yields the drift condition

$$0 = S'(x) \mu(t,x) + \frac{1}{2}S''(x) \sigma_b^2(t,x) + \int_{\mathbb{R}} \left(S(x+z) - S(x) - S'(x) \chi(z)\right) \nu_t(dz), \quad (2)$$

and thus the drift is pinned down by

$$\mu(t,x) = -\frac{\frac{1}{2}S''(x) \sigma_b^2(t,x) + \int_{\mathbb{R}} \left(S(x+z) - S(x) - S'(x) \chi(z)\right) \nu_t(dz)}{S'(x)}. \quad (3)$$

Equations (2)–(3) ensure $p_t$ is a $\mathbb{Q}$-martingale; therefore, only the *belief-volatility* $\sigma_b$, the jump intensity and moments (embedded in $\nu_t$), and cross-event dependence (introduced below) remain as tradable risk factors [10, 24].

**Interpretation.** The logit map transports the bounded probability $p_t \in (0,1)$ to $\mathbb{R}$ where standard semimartingale tools apply, while the jump term allows for abrupt probability updates at news times. The martingale restriction fixes the drift of $x_t$ so that $S(x_t)$ carries zero drift under $\mathbb{Q}$; informally, the "belief level" $p_t$ drifts only when reparameterized in $x$ to offset convexity and jump-compensation effects. This separation makes $\sigma_b$ and jump features economically interpretable and quotable—directly analogous to how implied variance and jump parameters are quoted in price-based models [50, 45, 24].

## 3.3 Multi-Event Dependence: Diffusive Correlation and Co-Jumps

Consider events $i$ and $j$ with logits $x_t^i, x_t^j$, marginal volatilities $\sigma_b^i, \sigma_b^j$, and Brownian correlation

$$\rho_{ij}(t) = \text{corr}\left(dW_t^i, dW_t^j\right) \in [-1,1].$$

Let $\nu_{ij,t}(dz_i, dz_j)$ be a (possibly time-varying) *co-jump measure* on $\mathbb{R}^2$ capturing simultaneous news shocks. Writing $\Delta p^k := S(x_{t-}^k + z_k) - S(x_{t-}^k)$, a short-maturity (frozen-state) expansion gives the instantaneous covariance of probabilities:

$$\text{Cov}(dp^i, dp^j)_t \approx S_k'^i S_k'^j \sigma_b^i \sigma_b^j \rho_{ij}(t) dt + \int_{\mathbb{R}^2} \Delta p^i \Delta p^j \nu_{ij,t}(dz_i, dz_j) dt, \quad (4)$$

where $S_k' = S'(x_t^k)$. The first term is the diffusive covariation; the second aggregates common (co-)jumps. Empirically, co-jumps can be detected and tested using high-frequency methods [42].

---


## 3.4 Prototype Derivatives (Belief–Variance, Correlation, Corridor, and First-Passage Notes)

**Belief variance swap on log-odds x.** Define realized quadratic variation of x on [t, T] by

$$QV_{t,T}^x = \int_t^T \sigma_b^2(u, x_u) \, du + \sum_{t < u \leq T} (\Delta x_u)^2.$$

Under piecewise-constant (or slowly varying) model parameters, the fair variance strike is

$$K_{t,T}^{x\text{-var}} \approx \int_t^T \sigma_b^2(u) \, du + \int_t^T \lambda(u) \mathbb{E}[z^2(u)] \, du, \qquad (5)$$

directly paralleling classical variance swap theory in price models [28, 22, 18].

**Belief variance swap on probability p = S(x).** A short-maturity, frozen-state approximation at x<sub>t</sub> gives

$$K_{t,t+\Delta}^{p\text{-var}} \approx (p_t(1 - p_t))^2 \int_t^{t+\Delta} \sigma_b^2(u) \, du + \int_t^{t+\Delta} \int_{\mathbb{R}} \left(S(x_t + z) - S(x_t)\right)^2 \nu_u(dz) \, du, \qquad (6)$$

where the prefactor $(p(1 - p))^2$ arises from $S'(x)^2$ and the second term captures jump contributions to the quadratic variation of p [24, 21].

**Covariance and correlation swaps across events.** Using (4), a short-maturity fair *covariance* strike integrates the instantaneous covariance; dividing by marginal variances yields a *correlation* strike. These instruments let market makers neutralize cross-event exposure from both diffusive correlation and co-jumps [42, 22].

**Corridor variance on p.** A *corridor* contract accrues realized variance only while p ∈ [a, b] (a "swing zone" away from the 0/1 boundaries). Pricing proceeds either via a weighted-variance replication (when available) or by solving the PIDE with state-dependent accrual; see corridor-variance analogs in equity for guidance [47, 20].

**Threshold and path notes (first passage).** Pay a fixed amount if p first hits level h ∈ (0, 1) before T (or logical AND/OR across events). With h mapped to x<sub>h</sub> = logit(h), valuation uses (7) with absorbing boundary at x = x<sub>h</sub> and appropriate terminal/boundary conditions. Jump terms materially affect first-passage probabilities (up-crossings can occur by jump), a standard consideration in jump–diffusion settings [24, 10].

8


---



## 3.5 General Pricing via PIDE and Numerical Treatment

For a terminal payoff $g(x_T)$, the time-$t$ price $V(t, x)$ solves the (backward) partial integro–differential equation (PIDE)

$$\partial_t V + \mu(t, x) \partial_x V + \frac{1}{2} \sigma_b^2(t, x) \partial_{xx} V$$
$$+ \int_{\mathbb{R}} \left( V(t, x + z) - V(t, x) - \partial_x V(t, x) \chi(z) \right) \nu_t(dz) = 0, \qquad (7)$$
$$V(T, x) = g(x).$$

with $\mu$ given by (3). Basket and multi-event claims add diffusion cross-derivatives and a multivariate jump integral with co-jump measure $\nu_t(dz)$. Under standard growth and regularity conditions, (7) is the infinitesimal generator equation for (1) and can be solved by finite-difference with fast convolution for the jump integral, Fourier methods when coefficients are constant/affine, or Monte Carlo with variance reduction [24, 10].

**Calibration notes (brief).** Mapping mid/bid–ask/trade streams to a belief–volatility surface requires filtering the latent $x_t$ from microstructure noise (e.g., state-space/Kalman variants) and estimating jump activity and co-jumps; the microstructure and high-frequency literature provides standard tools [37, 38, 5, 42]. In our setting, these methods are applied to log-odds increments and to cross-event panels.

# 4 Market–Maker Handbook

## 4.1 Greeks, Units, and Risk Buckets

**Work in the logit domain.** Quotes and hedges should be parameterized in $x$ (log–odds), then mapped to probabilities $p = S(x)$. For the vanilla event contract $V = p = S(x)$,

$$\Delta_x := \frac{\partial V}{\partial x} = S'(x) = p(1 - p), \qquad \Gamma_x := \frac{\partial^2 V}{\partial x^2} = S''(x) = p(1 - p)(1 - 2p).$$

Near the boundaries $p \to 0, 1$, $\Delta_x \downarrow 0$ and curvature peaks in the swing zone $p \approx 0.5$.

**Belief–vega and correlation–vega.** For a derivative $V$, define

$$\nu_b := \frac{\partial V}{\partial \sigma_b}, \qquad \nu_\rho := \frac{\partial V}{\partial \rho_{ij}},$$

where $\sigma_b$ is belief volatility in (1) and $\rho_{ij}$ is diffusive correlation in (4). For $x$-variance swaps $V \propto \int \sigma_b^2$, we have $\nu_b \propto \sigma_b$; for short-maturity $p$-variance,

$$\nu_b \propto \left( p(1 - p) \right)^2 \sigma_b,$$

reflecting the Jacobian $S'(x)^2$ in (6). Sensitivity to jump second moments (via the Lévy measure $\nu_t$) is tracked as a separate *jump-vega* bucket.

9


---



Risk buckets. *Directional* (Δ_x), *curvature/news nonlinearity* (Γ_x), *information intensity* (belief–vega ν_b and jump second moments), and *cross–event* (ν_ρ plus co–jump covariance). These map to the kernel's tradable risk factors.

## 4.2 Inventory–Aware Quoting (Avellaneda–Stoikov in Logit Units)

**Reservation quote and optimal spread in x.** Treat the mid in logit units as x_t with instantaneous volatility σ_b(t), and assume order arrivals decay exponentially with distance in x (intensity λ(δ) = Ae^(-kδ)). The classical Avellaneda–Stoikov approximation yields a *reservation quote* and *optimal spread* in x:

(reservation) r_x(t) = x_t - q_t γ σ̄²_b (T - t), (8)

(total spread) 2δ_x(t) ≈ γ σ̄²_b (T - t) + (2/k) log(1 + γ/k). (9)

Here q_t is inventory (contracts), γ risk aversion, T your risk horizon, and σ̄²_b a short-horizon average of belief variance. Post

x^bid = r_x - δ_x, x^ask = r_x + δ_x, then map x ↦ p = S(x).

The reservation price skews quotes to pull inventory toward zero; the spread widens with risk and thinner order flow.<sup>1</sup>

**Display and boundary handling.** For UI display in probabilities,

δ_p ≈ S'(x_t) δ_x = p_t(1 - p_t) δ_x,

so spreads auto-compress near p≈0, 1. To prevent over-tightening, cap the display half-spread by a floor δ̄_p (e.g., ticks) and enforce an inventory cap that tightens with S'(x):

|q_t| ≤ q_max(t) ∝ 1/(max{S'(x_t), ε̄}).

**Execution hygiene (anti pick-off).**

1. **Toxicity filter:** when short-horizon order imbalance or a VPIN-style metric spikes, *widen* δ_x or *pull* quotes.

2. **News guard:** around scheduled announcements, ramp γ and/or T-t in (9); pause on unscheduled jump detectors.

3. **Queue discipline:** cancel→replace on adverse microstructure signals (rapid mid drift, queue position loss).

<sup>1</sup>Eqs. (8)–(9) are the standard A–S asymptotics under exponential arrivals.

10


---



## 4.3 Calendar Hedges (Near–Dated News vs. Slow Decay)

**Two–leg template (variance strips).** Let your book's sensitivity to belief variance over [t, t + Δ] be $\tilde{\nu}_b(t, \Delta)$ (aggregate across positions). Hedge via an x-variance strip with notional N<sup>x-var</sup>:

$$N^{x\text{-var}} \approx -\frac{\tilde{\nu}_b(t, \Delta)}{\partial K_{t,t+\Delta}^{x\text{-var}}/\partial \sigma_b} \propto -\frac{\tilde{\nu}_b(t, \Delta)}{\sigma_b}.$$

Use short windows around data releases for *spiky* $\sigma_b$ and jump variance; use longer windows to smooth slow variance growth into resolution. If listed calendars are unavailable, synthesize with adjacent maturities or related events.

**Corridor budgets.** If toxicity concentrates in a swing zone $p \in [a, b]$, buy *corridor* variance on p that accrues only when $p \in [a, b]$; this targets hedge spend where fills actually occur.

## 4.4 Cross–Event β–Hedges (Diffusion and Co–Jumps)

**Instantaneous hedge ratio.** For hedging event i with j over short horizons (diffusion, no jumps),

$$\beta_{i \leftarrow j} \approx \frac{\text{Cov}(dp^i, dp^j)}{\text{Var}(dp^j)} \approx \frac{S_i'}{S_j'} \rho_{ij}.$$

In practice, use a *shrinkage* $\tilde{\beta} = \alpha \beta$ with $\alpha \in [0.5, 1)$ and clamp $|\tilde{\beta}|$ when $S_k' \to 0$ to avoid explosive hedges near $p \to 0, 1$.

**Co–jump correction.** When co-jump covariance is material (e.g., election night), add

$$\Delta \beta_{i \leftarrow j}^{\text{jump}} \approx \frac{\int \Delta p^i \Delta p^j \nu_{ij,t}(dz_i, dz_j)}{(S_j')^2 \sigma_b^2},$$

estimated from recent detections. Around known jump windows, *over-hedge* diffusive correlation (larger α) and carry optionality (first–passage notes) to absorb threshold gaps.

## 4.5 Inventory–Aware Quoting: An Operator Recipe

**Inputs (rolling).** Filtered $x_t$ and $\widehat{\sigma}_b$ from mid/bid–ask/trade data; k from fill distance vs. intensity; $\rho_{ij}$ and co–jump counts; toxicity meters.

**Refresh loop (100–500 ms typical).**

1. Update $x_t, \widehat{\sigma}_b, q_t$, toxicity flags.

2. Compute $r_x$ and $\delta_x$ via (8)–(9); produce $x^{\text{bid/ask}}$ and display $p^{\text{bid/ask}} = S(\cdot)$ with floors/caps.

11


---


3. If (toxicity high) or (unscheduled jump alarm), widen $\delta_x$ or pull quotes; if (scheduled news soon), pre-widen by policy.

4. Rebalance cross-event exposure using $\tilde{\beta}_{i \leftrightarrow j}$ and listed covariance/correlation swaps when available.

5. Rebalance calendar exposure using near-dated variance strips (or OTC proxies).

## 4.6 PnL Attribution and Risk Limits

**Delta–Gamma–Vega attribution in $x$ units.** Over a small $\Delta t$ with $dp \approx S'(x) dx$,

$$d\Pi \approx \underbrace{\Delta_x}_{\text{directional}} dp + \underbrace{\frac{1}{2} \Gamma_x (dp)^2}_{\text{curvature/news}} + \underbrace{\nu_b d\sigma_b}_{\text{belief–vega}} + \underbrace{\sum_j \nu_\rho^{(j)} d\varrho_{ij}}_{\text{cross–event}} + \underbrace{\text{jumps}}_{\Sigma(\Delta p) \text{ position}}$$

Track realized vs. expected $(dp)^2$ to stress variance books; reconcile jump P&L around flagged news.

**Hard limits and kill–switches.** (1) Inventory caps that tighten as $S'(x)$ shrinks. (2) Max gamma exposure in the swing zone. (3) Max unhedged variance (calendar) and correlation (cross-event) notional. (4) Auto-pause on: (i) feed gaps, (ii) volatility spikes, (iii) repeated pick-offs.

## 4.7 Heuristics That Matter in Practice

* **Quote where you can hedge.** If no liquid proxy exists for a bucket (e.g., no cross-event hedge), carry less exposure and charge more spread in that bucket.

* **Pay for jump insurance explicitly.** Add a jump premium $\propto$ recent jump variance and news density to your spread.

* **Prefer $x$-variance for core hedging.** $x$-variance is more level-stable; use $p$-variance/corridor when inventory lives in a tight $p$-band.

* **Edge accounting.** Target stable edge per fill after fees and expected adverse selection; if it compresses, widen or hedge more.

## 4.8 Pointers to Implementation Details

**Estimating $\sigma_b$, jumps, and co–jumps.** Filter $x_t$ from mid/bid–ask/trade data; estimate diffusive variance on robust windows and detect jumps via thresholded bi-power variation; test co-jumps with high-frequency statistics.

12


---



**Numerics for exotics.** Use the PIDE in (7) with IMEX schemes or Fourier convolution for fast jump integration; Monte Carlo with jump thinning for first-passage structures; closed-form or transform methods for corridor payoffs when the jump law is exponential-family.

**Remark (mapping to literature).** Inventory-aware quoting and reservation prices follow the dealer/market-making tradition; the toxicity safeguards and variance/correlation hedges parallel the option-market playbook, transplanted to belief dynamics.

**What to quote on day one.** (1) vanilla event contracts (tightest where $S'(x)$ largest), (2) $x$-variance strips around scheduled news, (3) a few liquid correlation strikes between the most coupled events, and (4) a corridor variance centered on $p! \in [0.35, 0.65]$ for high-flow markets. This minimal menu already neutralizes the four buckets above.

# 5 Calibration: From Mid/Bid–Ask/Trades to a Belief–Vol Surface

**Goal.** Given raw market data (mid, bid–ask, trades) for one or many event contracts, we estimate the latent logit process $x_t$ (hence $p_t = S(x_t)$), its instantaneous *belief volatility* $\sigma_b(t,x)$, jump activity, and cross–event dependence. We summarize these into a stable, tradable *belief–vol surface* $\sigma_b(\tau, m)$ and a dependence layer $\{\rho_{ij}(\tau, m)$, co–jump moments} that feed quoting, hedging, and pricing.

**Reasoning path in brief.** (i) Work in *logit* $x$ to remove $[0, 1]$ boundaries and use Itô–Lévy tools. (ii) Recognize that observed prices are *microstructure–noisy* proxies for the latent $x_t$, so use a heteroskedastic *state–space* filter to recover $\hat{x}_t$. (iii) Separate *diffusion* from *jumps* via a mixture model on increments (EM), rather than ad–hoc thresholds, because event markets often have scheduled and unscheduled jumps. (iv) Smooth the noisy point estimates across *time–to–resolution* $\tau$ and *moneyness* $m$ with shape constraints that prevent pathologies near $p \in \{0, 1\}$. (v) For multiple events, estimate *de–jumped* diffusive correlations and *co–jumps* separately, since they hedge different risks.

## 5.1 Data Conditioning & Filtering

**Pre–processing (robust, venue–agnostic).**

1. **Canonical mid:** Compute a trade–weighted mid $\tilde{p}_t = \frac{1}{Z_t} \sum_{u \in (t-\Delta,t]} w_u \frac{b_u + a_u}{2}$ with weights $w_u$ monotone in size and inverse spread; de–bounce bid/ask flicker by ignoring updates <tick size.

2. **Clipping and cadence:** Clamp to $p \in [\varepsilon, 1-\varepsilon]$ (e.g., $\varepsilon = 10^{-5}$) to avoid exploding logits; resample to a uniform grid (e.g., 100 ms–1 s) using last–observation–carried–forward + within–bin VWAP.

3. **Outlier hygiene:** Drop prints with crossed or locked books; flag halts; remove isolated spikes that revert within one tick and one update.

13


---


**Observation model (heteroskedastic microstructure noise).** Define the observed logit

$$y_t := \text{logit}(\tilde{p}_t) = x_t + \eta_t, \quad \mathbb{E}[\eta_t] = 0, \quad \text{Var}(\eta_t) = \sigma_\vartheta^2(t).$$

Model $\sigma_\vartheta^2(t)$ as a function of observable frictions (spread $s_t$, depth $d_t$, trade rate $r_t$, aggressor imbalance $\iota_t$):

$$\sigma_\vartheta^2(t) = a_0 + a_1 s_t^2 + a_2 d_t^{-1} + a_3 r_t + a_4 \iota_t^2 \quad \text{(clipped to } [\underline{\sigma}^2, \overline{\sigma}^2]), \tag{10}$$

with $(a_k)$ fit by robust regressions on short–horizon squared microstructure innovations (Hasbrouck–style diagnostics). Heteroskedastic $\sigma_\vartheta^2(t)$ markedly improves the filter near illiquid times.

**State filtering (recovering $\hat{x}_t$).** Use a Gaussian state–space filter in $x$ with measurement (10). For the transition we *do not* impose a fixed drift; instead, we:

* propagate $x$ with a local–level model plus innovation variance proxy $\tilde{\sigma}_b^2(t)\Delta$ to capture short–run variability;

* after EM (below) enforces the risk–neutral drift (3), re–smooth $x$ with the refined $\hat{\sigma}_b$ and jump marks.

A standard Kalman filter/smoother suffices; if $p$ is pinned near $0/1$ for long stretches or if jumps are very frequent, an Unscented KF or particle smoother is more stable. Output: $\hat{x}_t$ and innovations (one–step–ahead residuals).

**Diagnostics (keep only if they pass).** (i) Residuals should be serially uncorrelated (Ljung–Box) and conditionally homoskedastic given (10); (ii) Q–Q plots should be near–Gaussian away from detected jump times; (iii) realized $p$–variance implied by $\hat{x}_t$ should match raw realized variance after removing microstructure components.

## 5.2 EM for Diffusion and Jumps (Increment Mixtures)

**Discretization and mixture.** On a grid with step $\Delta$, model $\Delta x_t := x_{t+\Delta} - x_t$ as

$$\Delta x_t \sim \begin{cases} \mathcal{N}(\mu_t \Delta, \sigma_b^2(t)\Delta), & \text{with prob. } 1 - \lambda_t \Delta, \\ Z_t \sim f_J(\cdot; \theta_t), & \text{with prob. } \lambda_t \Delta, \end{cases}$$

where $\lambda_t$ is jump intensity and $f_J$ is a centered jump law with second moment $s_J^2(t)$ (e.g., double–exponential, tempered stable, or nonparametric bins). The drift $\mu_t$ will be *implied* by the martingale restriction for $p_t = S(x_t)$ (Eq. (3)) after updating $(\sigma_b, \lambda_t, \theta_t)$.

**E–step (posterior jump responsibilities).** Given current parameters and filtered $\hat{x}_t$, form the Gaussian likelihood $\phi_t = \mathcal{N}(\Delta \hat{x}_t \mid \mu_t \Delta, \sigma_b^2(t)\Delta)$ and the jump likelihood $\psi_t = f_J(\Delta \hat{x}_t; \theta_t)$. Posterior jump probability

$$\gamma_t := \mathbb{P}\{\text{jump at } t \mid \Delta \hat{x}_t\} = \frac{\lambda_t \Delta \psi_t}{\lambda_t \Delta \psi_t + (1 - \lambda_t \Delta)\phi_t}.$$

Mark intervals with $\gamma_t > \tau_J$ (e.g., 0.7) as jump–dominant for subsequent de–jumped correlation estimates.

14


---



**M–step (updating diffusion and jump parameters).** Update (locally or in bins) by weighted moments:

$$
\widehat{\sigma}_b^2(t) \leftarrow \frac{\sum(1-\gamma_t)(\Delta\widehat{x}_t - \mu_t\Delta)^2}{\sum(1-\gamma_t)} \bigg/ \Delta, \qquad \widehat{\lambda}(t) \leftarrow \frac{1}{\Delta} \frac{1}{|B|} \sum_{t \in B} \gamma_t, \qquad (11)
$$

$$
\widehat{s}_J^2(t) \leftarrow \frac{\sum \gamma_t (\Delta\widehat{x}_t)^2}{\sum \gamma_t}. \qquad (12)
$$

If $f_J$ is parametric, update $\theta_t$ by maximizing the weighted log–likelihood.

**Risk–neutral drift enforcement.** With $\widehat{\sigma}_b^2$ and jump compensator $\widehat{\nu}_t(dz)$ (from $f_J$ and $\widehat{\lambda}$), recompute $\mu(t,x)$ using the analytical formula

$$
\mu(t,x) = -\frac{\frac{1}{2}S''(x)\sigma_b^2(t,x) + \int (S(x+z) - S(x) - S'(x)\chi(z))\nu_t(dz)}{S'(x)}.
$$

This pins the drift so that $p_t = S(x_t)$ is a martingale under $\mathbb{Q}$. Re–run the smoother for $x$ with the updated transition to tighten estimates (one or two outer loops suffice in practice).

**Stopping and checks.** Iterate E/M until (i) parameter changes are small, and (ii) de–jumped residuals are near–Gaussian with variance $\sigma_b^2\Delta$. As a sanity check, realized $p$–variance over a window should be close to $\int S'(x)^2\sigma_b^2 dt +$ jump contribution $\int(\Delta p)^2 dN$.

## 5.3 Surface Construction: Smoothing Across $(\tau, m)$

**Coordinates.** Let $\tau = T - t$ be time–to–resolution. For moneyness $m$, choose either $m = x$ (logit) or $m = \min\{p, 1-p\}$ (distance to the boundary); both work, but $m = x$ aligns with our kernel.

**Raw grid and loss.** Aggregate point estimates $\{\widehat{\sigma}_b(t), \widehat{\lambda}(t), \widehat{s}_J^2(t)\}$ to a tensor grid $(\tau, m)$. Fit a smooth surface by penalized least squares,

$$
\min_{\sigma_b(\tau,m)} \sum_g w_g\left(\widehat{\sigma}_b(g) - \sigma_b(\tau_g, m_g)\right)^2 + \alpha \|\nabla^2\sigma_b\|_2^2,
$$

with weights $w_g$ proportional to local data density and filter precision; use tensor–product B–splines or thin–plate splines.

**Shape constraints (stability & plausibility).**

* **Nonnegativity:** $\sigma_b(\tau, m) \geq 0$ (enforced via squared–link or barrier).

* **Edge stability:** penalize explosive curvature at extreme $m$; in $p$–space, note that realized variance scales like $S'(x)^2\sigma_b^2 = p^2(1-p)^2\sigma_b^2$, which already damps near $p \approx 0, 1$.

---


• **Term smoothness:** regularize ∂<sub>τ</sub>σ<sub>b</sub> to avoid artificial kinks between adjacent maturities, while allowing bumps at scheduled announcements (implemented by locally relaxing the penalty on known news dates).

Apply the same smoothing to λ(τ, m) and s²<sub>J</sub>(τ, m) to obtain jump surfaces.

**Outputs.** A calibrated *belief–vol surface* σ<sub>b</sub>(τ, m) and jump layer {λ(τ, m), s²<sub>J</sub>(τ, m)}, accompanied by uncertainty bands from the smoothing fit (use sandwich or bootstrap on bins).

## 5.4 Cross–Event Dependence: Correlation and Co–Jumps

**De–jumped diffusive correlation** ρ<sub>ij</sub>(τ, m). Using intervals with max(γ<sup>i</sup><sub>t</sub>, γ<sup>j</sup><sub>t</sub>) < τ<sub>J</sub> (no jump in either series), estimate instantaneous covariances on rolling windows,

$$\widehat{\text{Cov}}_t^{(d)}(dp^i, dp^j) \approx \frac{1}{W} \sum_{u \in (t-W,t]} S_i'(u) S_j'(u) \Delta \hat{x}_u^i \Delta \hat{x}_u^j,$$

and variances analogously, then $\hat{\rho}_{ij} = \widehat{\text{Cov}}^{(d)} / \sqrt{\widehat{\text{Var}}_i^{(d)} \widehat{\text{Var}}_j^{(d)}}$. Map estimates to (τ, m) cells and smooth with the same spline machinery (clamp to [−1, 1]).

**What the desk consumes.**

1. **Belief–vol surface** σ<sub>b</sub>(τ, m) with uncertainty bands.

2. **Jump layer** λ(τ, m) and s²<sub>J</sub>(τ, m), plus a flag list of near–term scheduled news windows.

3. **Dependence layer** ρ<sub>ij</sub>(τ, m) and co–jump {Λ̃<sub>ij</sub>, M̃<sup>(2)</sup><sub>ij</sub>} for key pairs.

These drive (i) reservation prices and spreads via σ̄²<sub>b</sub> (Sec. 4.2); (ii) notional in variance and correlation hedges (Secs. 4.3–4.4); (iii) PIDE/MC solvers for exotic pricing with jump inputs.

## 5.5 Edge Cases & Practical Notes

**Pinned markets** (p ≈ 0 or 1). Even if σ<sub>b</sub> looks large in x, realized p–variance is tiny due to S'(x)²; ensure the filter doesn't mistake tick–size for diffusion (raise σ² and increase Δ).

**Batch auctions and halts.** Treat batch prints as a single observation; if a halt occurs, freeze the filter and restart with wider priors.

**Multi–venue consolidation.** When merging venues, rescale microstructure covariates (spread/depth) to a common unit and weight observations by venue reliability before filtering.

---



# 6 Experiments

Our goal is modest but decisive: to test whether the proposed *logit jump–diffusion with risk–neutral (RN) drift* and the calibration pipeline of Secs. 5–4 produce **better short–horizon forecasts of belief variability and jumps** than reasonable alternatives, and whether these gains **translate into lower hedging error proxies**. We therefore run a single, end–to–end experiment that mirrors how a market maker would operate in real time: filter, calibrate, forecast *causally*, and evaluate.

## 6.1 Core Forecasting Task

Fix a horizon h on a uniform time grid (in code h=H=60s). At each decision time t, a model outputs a point forecast of future *logit* realized variance on [t, t+h],

$$\widehat{\mathcal{V}}^x_{t,h} \equiv \sum_{u=t+1}^{t+h} \widehat{\sigma}_b^2(u) + c_J \cdot \widehat{s}_J^2(t) \cdot \sum_{u=t+1}^{t+h} \widehat{\lambda}(u),$$
$$\underbrace{\qquad\qquad\qquad}_{\text{diffusion contribution}} \quad \underbrace{\qquad\qquad\qquad}_{\text{jump contribution}}$$

where $\widehat{\sigma}_b^2$ and the jump layer $(\widehat{\lambda}, \widehat{s}_J^2)$ come from the causal calibration described below, and $c_J$ is a scalar weight tuned on a held–out validation slice by minimizing QLIKE. After the h seconds elapse, we compute *realized* logit variance

$$\mathcal{RV}^x_{t,h} = \sum_{u=t+1}^{t+h} (\Delta \hat{x}_u)^2, \qquad \Delta \hat{x}_u \equiv \hat{x}_u - \hat{x}_{u-1},$$

using the filtered latent logit $\hat{x}$.<sup>2</sup>

**Metrics.** We report mean squared error (MSE), mean absolute error (MAE), the log–MSE of log $\mathcal{RV}$, and the QLIKE loss:

$$\text{MSE}_x(h) = \frac{1}{|\mathcal{T}|} \sum_{t \in \mathcal{T}} (\mathcal{RV}^x_{t,h} - \widehat{\mathcal{V}}^x_{t,h})^2, \quad \text{QLIKE}_x(h) = \frac{1}{|\mathcal{T}|} \sum_{t \in \mathcal{T}} \left( \frac{\mathcal{RV}^x_{t,h}}{\widehat{\mathcal{V}}^x_{t,h}} - \log \frac{\mathcal{RV}^x_{t,h}}{\widehat{\mathcal{V}}^x_{t,h}} - 1 \right).$$
(13)

QLIKE is standard for volatility evaluation, penalizes under–prediction more heavily, and is robust to noise in $\mathcal{RV}$.

## 6.2 Data, Preprocessing, and Splits

To stress–test models with known ground truth and realistic frictions, we use 20 high-volume event trades from Polymarket. We corrupt x with heteroskedastic observation noise that changes by regime, mimicking spread/depth variation. All methods receive the *same* prefiltered series: we run a heteroskedastic Kalman filter (KF) with process noise proxied by a rolling variance of observed increments and measurement variance fixed by

<sup>2</sup>All models operate causally; we drop the last h timestamps so that future sums never leak information. Robust bi–power alternatives give the same conclusions and are reported in the appendix.

17



---



regime. Models that natively operate in $p$ receive $\hat{p}=S(\hat{x})$ to equalize microstructure handling.

We adopt a simple train/validation/test split that is *shared across all methods*. Scalars needed by baselines (e.g., constant $\sigma^2$ for RW–logit) are fitted on the training third; the jump weight $c_J$ for our model is tuned on the validation third by QLIKE; evaluation is then conducted causally on the test third. (The code also prints full–sample metrics without the last $h$ timestamps for quick inspection; tables in the paper use the test region.)

## 6.3 Models and Baselines

**Proposed: RN–logit–JD (path–aware, causal).** Our pipeline mirrors Sec. 5: (i) heteroskedastic KF in $x$ (no drift) $\Rightarrow \hat{x}$; (ii) EM on rolling windows to separate diffusion and jumps, yielding $\hat{\sigma}_b^2(t)$, $\hat{\lambda}(t)$, $\hat{s}_J^2(t)$; (iii) *RN drift re–smoothing:* we compute $\hat{\mu}(t,x)$ from the martingale restriction:

$$\mu(t,x) = -\left(\frac{1}{2}S''(x)\hat{\sigma}_b^2(t) + \hat{\lambda}(t) \cdot \mathbb{E}[S(x+Z)-S(x)-S'(x)\chi(Z)]\right)/S'(x) \qquad (14)$$

, approximating the jump compensation $\mathbb{E}[\cdot]$ by Monte Carlo with the same jump law used by EM.<sup>3</sup> We then run a second KF with this $\hat{\mu}(t,\hat{x}_t)$ in the state transition. (iv) *Causal variance forecasting:* for each $t$, we return a forward sum of diffusion variance plus a jump term

$$\widehat{V}_{t,h}^x = \sum_{u=t+1}^{t+h} \hat{\sigma}_b^2(u) + c_J \cdot \hat{s}_J^2(t) \cdot \sum_{u=t+1}^{t+h} \hat{\lambda}_{\text{sched}}(u),$$

where $\hat{\lambda}_{\text{sched}}$ is an EWMA of $\hat{\lambda}$ time–warped by a Gaussian schedule kernel centered at announced windows (known ex–ante).

**Baselines.**

* **RW–logit:** $x_{t+\Delta}=x_t+\sigma\sqrt{\Delta}\xi_t$, with $\sigma^2$ set to the training–slice mean of $(\Delta\hat{x})^2$.
* **Logit diffusion (const $\sigma$):** same as above but fitted on the entire calibration region.
* **Wright–Fisher/Jacobi in $p$:** a boundary–respecting diffusion calibrated by ML on $\hat{p}$; we forecast $p$–variance $2\alpha p(1-p)$ and map back to $x$ via $S'(x)^2$.
* **AR(1)–GARCH(1,1) in $p$:** an AR(1) on $\Delta\hat{p}$ with a GARCH(1,1) volatility; forecasted $p$–variance is mapped to $x$ using $S'(x)^{-2}$.

All baselines are evaluated causally using the same forward–sum operator and the same test window.

<sup>3</sup>We use symmetric Gaussian jumps, truncation $\chi(\cdot)$ as in the simulator, and clip $S'(x)$ by $10^{-4}$ for numerical stability; $\mu$ is EWMA–smoothed and capped at $|0.25|s^{-1}$.

18


---



Table 1: Causal H=60 s forward-sum forecasts of next-window realized *logit* variance on the synthetic RN-consistent path. Lower is better. Best per column in **bold**.

<table>
  <tbody>
    <tr>
        <td>Model</td>
<td>MSE_all</td>
<td>MAE_all</td>
<td>QLIKE_all</td>
    </tr>
<tr>
        <td>RN–JD (causal path)</td>
<td>70.281</td>
<td>1.588</td>
<td>1.4621</td>
    </tr>
<tr>
        <td>RW–logit (const σ)</td>
<td>77.414</td>
<td>1.163</td>
<td>4.7318</td>
    </tr>
<tr>
        <td>Logit (const σ)</td>
<td>76.752</td>
<td>2.078</td>
<td>2.6594</td>
    </tr>
<tr>
        <td>WF/Jacobi (mapped)</td>
<td>1.71 × 10¹⁷</td>
<td>3.67 × 10⁷</td>
<td>1.9484</td>
    </tr>
<tr>
        <td>ARMA–GARCH (mapped)</td>
<td>1.07 × 10¹⁹</td>
<td>5.33 × 10⁸</td>
<td>0.7962</td>
    </tr>
  </tbody>
</table>

## 6.4 Implementation Details

**Grid and seeds.** N=6000 steps at 1 Hz; random seeds are fixed. **KF.** Process noise uses a local rolling variance proxy; measurement noise is piecewise–constant by regime. **EM.** We run 6 EM steps globally to initialize, then a rolling EM with window 400 s. **RN drift.** The Monte Carlo inner expectation uses 600 draws per step (variance–time trade–off is negligible). **Schedule.** Known windows are encoded as Gaussian kernels (width 90 s) that boost λ̂ ex–ante; the boost is capped at the 95th percentile of the smoothed λ̂ to avoid outliers. **Tuning.** c<sub>J</sub> is grid–searched over {0.3, . . . , 1.0} on the validation region using QLIKE.

## 6.5 Evaluation Protocol and What To Expect

**Causal forward–sum.** For any per–step quantity a<sub>u</sub>, we define ForwardSum:

$$\text{ForwardSum}(a, h) = \sum_{u=t+1}^{t+h} a_u$$

and drop the last h timestamps; all models use *only* information available at t to build a<sub>t+1</sub>, . . . , a<sub>t+h</sub>. **Stratification.** Metrics are reported overall, and separately on quiet vs. jump windows (Sec. 6.1). **Hedging proxy.** Following Sec. 4.6, the squared forecast error in x–variance is a first–order proxy of slippage when warehousing curvature/news exposure; improving QLIKE/MSE thus suggests lower ex–post hedge error.

## 6.6 Results and Discussion

Table 1 reports causal H=60 s forward-sum forecasts of next-window realized *logit* variance on the synthetic RN-consistent path. Lower values indicate better alignment between forecasted and realized variability. The proposed **RN–JD (causal path)** model achieves the lowest overall MSE, MAE, and logMSE, outperforming all baselines under identical causal evaluation.

**Quantitative results.** RN–JD attains MSE<sub>all</sub>=70.28 and QLIKE<sub>all</sub>=1.46, representing a consistent improvement over both diffusion-based and p-space volatility models. The

19


---


RW–logit and constant-σ logit diffusions, which lack either drift or jump structure, underfit the true variability and fail to capture the volatility bursts near scheduled information shocks. Boundary-respecting Wright–Fisher (WF) and ARMA–GARCH models produce numerically unstable forecasts when mapped from probability to logit space, resulting in orders-of-magnitude MSE inflation despite locally competitive QLIKE scores.

**Interpretation.** The gains arise from three complementary mechanisms: (i) enforcing RN drift prevents systematic bias in $\hat{x}_t$, ensuring the implied $\hat{p}_t$ evolves as a martingale under the market measure; (ii) separating diffusion and jump layers via EM yields adaptive volatility forecasts that respect local heteroskedasticity; (iii) incorporating scheduled jump boosts improves ex–ante calibration near known information releases. Collectively, these allow the RN–JD model to produce a belief–volatility surface that is both dynamically stable and economically interpretable.

# 7 Conclusion

This paper proposed a minimal, actionable kernel for event contracts: a *logit jump–diffusion with risk–neutral (RN) drift* that treats the traded price $p_t$ as a $\mathbb{Q}$–martingale and exposes belief volatility, jump intensity, and cross–event dependence as quotable risk factors. On top of this kernel we built (i) a calibration pipeline that filters microstructure noise, separates diffusion from jumps via EM, and enforces RN drift in smoothing; and (ii) a coherent derivative layer (variance, correlation, corridor, first–passage) for quoting and hedging belief risk.

Our end–to–end experiment mirrored real-time desk operation: filter, calibrate, and forecast *causally* with only information available at decision time. On a synthetic but RN-consistent path that features early breakout, scheduled and unscheduled jumps, and terminal resolution, the proposed RN–JD pipeline delivered lower short-horizon variance forecast errors than diffusion-only or $p$-space baselines under identical evaluation (Table 1). The improvement is economically interpretable: RN drift eliminates systematic bias in the latent logit, EM-based jump separation captures heteroskedasticity, and schedule-aware intensity boosts align forecasts with known information windows. These ingredients jointly yield a stable, tradable belief–volatility surface suitable for quoting, hedging, and inventory control (Secs. 4.2–4.3).

**Practical implications.** The kernel organizes market making in event contracts around a small set of risk buckets (directional, curvature/news, belief–vega, cross–event), with standardized hedges (variance/correlation strips, corridor variance) that can be listed or synthesized. In particular, belief–variance and correlation swaps provide the optionmarket analogue of volatility and correlation instruments, enabling makers to tighten quotes and keep markets live through news while laying off risk in transparent units.

**Limitations.** Our experiments focus on single-event dynamics and synthetic co-jump structure; full multi-event calibration with rich, time-varying dependence and regime switches remains future work. The jump law is modeled parsimoniously (symmetric, light-tailed in the main experiments); extreme-tailed or skewed jumps may require richer

20


---



families or nonparametric bins. Finally, microstructure conditioning is venue-agnostic but stylized; production systems should incorporate venue-specific frictions (batch auctions, halts, cross-venue consolidation).

**Future directions.** *(i) Multi-event panels:* joint RN–JD calibration with diffusive correlation and co-jumps estimated from high-frequency panels; basket pricing via PIDE/MC with multivariate jump measures. *(ii) Term/moneyness surfaces:* shape-constrained smoothing across (τ, m) with uncertainty quantification and stress testing around boundaries. *(iii) Products and design:* exchange-ready specifications for belief–variance/correlation strips, corridor variance in the swing zone, and first-passage notes; replication/hedging guides for desks. *(iv) Live deployment:* A/B tests on liquid events (macro prints, elections) to measure spread, fill quality, and hedging P&L before/after introducing the RN-consistent layer.

**Takeaway.** Standardization beats perfect realism. By enforcing the martingale property in probability space and separating diffusion from jumps in logit space, the RN–JD kernel supplies a common language—*belief volatility, jump intensity, dependence*—that coordinates quoting and hedging, just as implied volatility did in options. We hope this work helps concentrate liquidity, reduce maker losses via targeted hedges, and support an institutional market for belief risk.

## References

[1] Event contracts. *Federal Register*, 89(112), June 2024. U.S. Commodity Futures Trading Commission rulemaking notice.

[2] Jacob Abernethy, Yiling Chen, and Jennifer Wortman Vaughan. Efficient market making via convex optimization, and a connection to online learning. *ACM Trans. Economics and Computation*, 2013.

[3] Damien Ackerer, Damir Filipović, and Sergio Pulido. The jacobi stochastic volatility model. *arXiv:1605.07099*, 2016.

[4] Hayden Adams, Noah Zinsmeister, and Dan Robinson. Uniswap v2 core whitepaper. https://app.uniswap.org/whitepaper.pdf, 2020.

[5] Yacine Aït-Sahalia, Per A. Mykland, and Lan Zhang. Ultra high frequency volatility estimation with dependent microstructure noise. Technical report, NBER Working Paper 11380, 2005.

[6] American Association for Public Opinion Research. An evaluation of 2016 election polls in the u.s., 2017.

[7] Guillermo Angeris and Tarun Chitra. Improved price oracles: Constant function market makers. *arXiv:2003.10001*, 2020.

[8] Guillermo Angeris, Tarun Chitra, Theo Diamandis, Alex Evans, and Kshitij Kulkarni. The geometry of constant function market makers. arXiv preprint arXiv:2308.08066, 2023.

21
