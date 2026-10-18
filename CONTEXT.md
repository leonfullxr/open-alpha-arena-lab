# Open Alpha Arena Lab

This file defines paper execution terms used in the architecture and accounting docs.

## Language

**Paper execution**: The application of model decisions and protective exits to virtual accounts under a competition's frozen rules. Fills and accounting effects represent simulated trades.

**Protective exit**: A close of an open position triggered when a trusted, fresh mark reaches its stop or take-profit condition. The exit uses an available executable quote.

**Execution quote set**: The persisted market quotes selected for a round's paper execution. New entries use the set only when it meets the competition's completeness, freshness, and cross-symbol skew limits.

**Responded job**: A job with a timely successful provider response durably recorded for paper execution. Its current attempt fence identifies the response the executor may apply.
