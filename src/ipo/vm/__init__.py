"""VM data plane (v3 Part II) — the read-API server the app fetches records + context from.

Separate deployable from the local engine: it runs on the VM, serves stores read-only, never scores.
"""
