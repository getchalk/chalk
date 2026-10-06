# Chalk Lecture Simulation Ledger

---

### ⏱️ Segment 1: [00:00] – [00:30]

## § 1. Capital Asset Pricing Model (CAPM) Derivation

Under the assumption of homogeneous expectations and frictionless capital markets, the equilibrium expected return on asset $i$ is linearly proportional to its systematic covariance risk:

$$\mathbb{E}[R_i] = R_f + \beta_i \cdot (\mathbb{E}[R_m] - R_f)$$

Where systematic risk $\beta_i$ is standardized as:

$$\beta_i = \frac{\mathrm{Cov}(R_i, R_m)}{\mathrm{Var}(R_m)} = \frac{\sigma_{im}}{\sigma_m^2}$$

> ❓ **Student Question [00:18]:** "Does mean-variance optimization still hold if asset returns exhibit fat tails?"
> 💡 **Instructor Clarification:** "No. Pure CAPM requires either normally distributed asset returns or quadratic investor utility functions. Fat tails violate quadratic optimization, requiring higher-order moment pricing."

<!-- CHUNK_STATE
Topic: Capital Asset Pricing Model & SML
Active_Variables: [R_i, R_f, R_m, beta_i, sigma_im, sigma_m^2]
Unresolved_Proofs: [Arbitrage Pricing Theory convergence]
Primary_Speaker: Instructor (Structured Lecture Cadence)
-->

---

