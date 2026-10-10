# Chalk Lecture Simulation Ledger

---

### [Segment 01]: [00:00] – [00:30]

### Capital Asset Pricing Model (CAPM) & Security Market Line

---

#### Key Model Assumptions [[00:00](chalk-audio://00:00)]
The classical Capital Asset Pricing Model (CAPM) relies on two key foundational assumptions:
1. **Homogeneous Expectations:** All investors possess identical joint probability distributions regarding future asset returns.
2. **Frictionless Markets:** Investors can borrow and lend unlimited amounts at the constant risk-free rate $R_f$ without transaction costs or tax frictions.

---

#### Derivation of Systematic Risk & The Security Market Line (SML) [[00:15](chalk-audio://00:15)]

The expected return on any individual asset $i$ exhibits a linear risk-return relationship driven by its systematic risk parameter, $\beta_i$:

$$
E(R_i) = R_f + \beta_i \left[ E(R_m) - R_f \right]
$$

Where:
* $E(R_i)$ is the expected return of asset $i$.
* $R_f$ is the risk-free rate.
* $E(R_m)$ is the expected market portfolio return.
* $\beta_i$ represents the asset's standardized contribution to market risk, defined as:

$$
\beta_i = \frac{\text{Cov}(R_i, R_m)}{\text{Var}(R_m)} = \frac{\sigma_{im}}{\sigma_m^2}
$$

*Note on derivation:* The detailed optimization steps connecting individual asset weights in the market equilibrium to $\beta_i$ were skipped in this presentation segment $[Lücke]$.

```diagram
graph TD
    subgraph SML_Pricing ["Security Market Line (SML) Pricing"]
        A["Asset Position vs SML"] --> B["Above SML: Underpriced (Alpha > 0)"]
        A --> C["On SML: Fairly Priced (Alpha = 0)"]
        A --> D["Below SML: Overpriced (Alpha < 0)"]
    end
```

---

#### Interactive Discussion & Callouts

> **Question [00:20](chalk-audio://00:20):** How does the linear Security Market Line hold up if returns exhibit fat tails (non-normality) rather than quadratic utility or standard normal return distributions?
> 
> **Clarification:** The Security Market Line framework strictly depends on mean-variance tractability (achieved either through quadratic utility functions or elliptically symmetric/normally distributed asset returns). When fat tails or higher-order moments (skewness, kurtosis) are introduced, portfolio selection requires higher-moment asset pricing extensions, meaning standard $\beta_i$ alone fails to fully price tail risk.

---

<!-- CHUNK_STATE
Topic: Capital Asset Pricing Model (CAPM) & Security Market Line (SML)
Active_Variables: [E(R_i), R_f, \beta_i, E(R_m), \sigma_{im}, \sigma_m^2, \alpha]
Unresolved_Proofs: [Derivation of beta from first-order portfolio optimization conditions [Lücke]]
Primary_Speaker: Professor / Academic Lecture
-->

---

