# Historical project records

These documents preserve how the project reached its current state. They are
evidence and planning history, not first-run instructions.

| Record | Purpose | Current authority |
|---|---|---|
| [Implementation plan](../plan.md) | Original milestone graph, gates, and long execution queue | Historical roadmap; current product summary lives in the root README |
| [Progress evidence](../progress.md) | Append-only dated implementation and execution ledger | Historical observations at their recorded revisions |
| [Model completion sprint](../model-completion-sprint.md) | Frozen definition of done and bounded offline-model outcome | Completed sprint record; current model truth lives in the model card |
| [Dated technical reports](../../reports/README.md) | Reviewed metrics, hashes, and result interpretation | Claim-supporting evidence for the named run only |

Do not rewrite an old entry to make it describe the current UI or model. Add a
new current guide, ADR, or dated report and link back to the historical record.
The progress ledger contains contemporaneous wording that called the checkout
“open-source code”; its final 2026-08-30 correction explicitly withdraws that
term. No source license has been selected.

For the runnable product, use:

- [Documentation home](../README.md)
- [Current architecture](../architecture.md)
- [Model card](../model-card.md)
- [ADR-0007](../adr/0007-raft-gyro-hybrid-runtime.md)

The original CNN/IMU-recurrent training lane remains historical and
reproducible. The current web app uses the later RAFT + gyro + compact
translation-head package; the two architectures must not be presented as the
same model.
