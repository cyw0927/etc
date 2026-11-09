"""Research agent prototype: an LLM plans and writes, deterministic tools produce every number.

Each value the agent sees is an evidence record with its source, raw-file hash and the time it became
available. The agent fixes an as-of time; tools refuse values that were not available by then.
"""
