# Verified Clinical Care Loop

A working local demo of a clinical workflow with a separate specification,
editable Python-like code, explicit proof certificates and an independent
Metamath-inspired checker. Only verified programs can run through the HTTP API.

## Run

Python 3.10 or later; no third-party packages are required.

```sh
python3 server.py
```

Open [the local app](http://127.0.0.1:8765). Use `--port 8766` to choose another port.

1. Play the patient story: pending culture, discharge, resistant result,
   deadline escalation, clinician review, family acknowledgement, treatment
   access and a corrected result.
2. Open **Protocol & proof**. Use **Generate & verify** for live AI drafting
   when an API key is configured, or load the prepared examples.
3. Load **Skip resistance review** and verify it.
   The fixed specification rejects it and displays a counterexample.
4. Try **Accept an outdated plan** or **Wait forever**. Both fail.
5. Restore **Complete care workflow**, verify it and download its actual
   Metamath proof. You can also edit the restricted program yourself.
6. View the Python verifier directly in the app.

## What is implemented

- A responsive patient workspace, timeline playback and code/proof workbench.
- Live AI drafting from the patient context and fixed specification when an
  API key is configured; each generated draft is independently verified.
- Six separately defined requirements over eight Boolean inputs.
- A parser for a small Python subset: `def care(s)`, Boolean field access,
  `not` / `and` / `or`, `if` / `elif` / `else`, and six literal action returns.
- A shared immutable program model for proof generation and interpretation.
- An actual Metamath derivation of program evaluation and specification truth
  for all 256 assignments. A complete-domain inference consumes every case.
- An independent substitution checker with typed hypotheses, simultaneous
  substitution, distinct-variable checks and exact final-goal checking.
- A certificate boundary that permits only theorems from the untrusted producer,
  preventing it from adding axioms, assumptions, or replacing the fixed goal.
- A server execution gate tied to the exact verified source.

The candidate selector contains prepared examples for repeatable failure demos.
The **Generate & verify** button calls the live model. The record adapter and
all clinical actions are simulated. No EHR is connected,
no messages are sent, and no medication is prescribed.

## Live AI drafting

Provide `OPENAI_API_KEY` through the server environment. Never put a key in
the browser or commit it. `VERIFIEDCARE_MODEL` optionally selects the model
(default `gpt-6-astra`); `OPENAI_BASE_URL` optionally configures a compatible
provider. Restart the server after changing its environment.

The generator uses the [Responses API](https://developers.openai.com/api/docs/guides/text)
with a 45-second timeout, no automatic retries, and `store: false`. Only the
synthetic demo context, fixed requirements and your drafting instructions are
sent. All returned code remains untrusted until it passes verification.

On Python installations without a configured CA bundle, install the Python
distribution's certificates or provide `SSL_CERT_FILE`. An installed `certifi`
bundle is used as a fallback; TLS certificate verification is always enabled.

## Trust and scope

The theorem covers **all 256 states of the declared Boolean abstraction**.
It does not prove arbitrary temporal properties, clinical correctness of the
requirements, record accuracy, authenticated approval, delivery, or recovery.
The `overdue` input means a timer event has arrived; the scheduler is outside the
proof. The `current` input stands for patient, culture, result and medication
version agreement, which a production adapter must establish.

The Boolean/decision semantics and finite universal-introduction rules are the
fixed trusted theory. There are no axioms asserting patient-specific success.
The specification encoding, parser, reader, record mapping and runtime remain
trusted implementation. The proof generator is not trusted.

The checker follows the companion `proof-carrying-code` project. Its readable
checking function is shown in the app with its actual line count. We do not
claim the complete trusted system is ten lines.

## Case provenance

The story is inspired by [AHRQ PSNet, Treatment Challenges After Discharge](https://psnet.ahrq.gov/web-mm/treatment-challenges-after-discharge).
David and C17 are aliases. The proposed interventions, four-hour deadline and
corrected-result scenario are synthetic additions. This app does not use a
Stanford patient export. It demonstrates workflow compliance, not an improved
clinical outcome.

## Verify

```sh
python3 -m unittest discover -s tests -v
python3 -O -m unittest discover -s tests -v
node --check static/app.js
```

A downloaded `.mm` file includes the theory and proof for standalone inspection:

```sh
python3 -m careloop.metamath path/to/downloaded-proof.mm
```

Standalone database checking validates derivation relative to the axioms in that
file. For deployment acceptance, use `careloop.engine.check_certificate(source,
theorem_only_certificate)`, which fixes the theory and independently reconstructs
the required theorem. Do not trust a database merely because it declares its own
claims as axioms.

## Layout

```text
server.py                Local HTTP server and execution gate
static/                  Browser interface
careloop/engine.py       Language, specification, runtime and proof producer
careloop/generator.py    Bounded live AI drafting; server-side credentials
careloop/theory.py       Fixed formal semantics
careloop/kernel.py       Small independent proof checker
careloop/metamath.py     Reader and certificate trust boundary
tests/                   Kernel, proof and execution regression checks
```
