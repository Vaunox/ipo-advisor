"""Durable transitions archive (v3 V3-2) — the VM-side validate + append-merge of the app's history.

The app's ``verdict_transitions.json`` is the one genuinely non-reproducible thing the local machine
holds (a re-read reconstructs today's verdict but never the *sequence* of how it changed). This
package is how that history outlives the machine: the app drops the file to a private git rendezvous
(outbound only), the VM pulls it, and this code **validates then append-merges** it into a durable
archive the app can never touch.

Off the scoring path by construction — the archive is written *from* verdict transitions and is
never read back into the feature vector (proven by the import-boundary guard: ``ipo.archive`` is
unreachable from features/model/calibration/core).
"""
