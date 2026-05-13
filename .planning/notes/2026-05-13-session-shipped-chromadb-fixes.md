---
date: "2026-05-13 09:01"
promoted: false
---

Session 2026-05-13: shipped chromadb 1.x EphemeralClient race fix (e579b024), chromadb collection leak on cache eviction via weakref.finalize (5759bd8c), and engine-wide NoneType-subscript hardening across langchain/llamaindex/chroma + broadened retry matcher + bumped retries to 4 (d9f5bf87). All on develop. 359 tests pass. Browser-harness 10-round stress test on chromadb fix returned 10/10 clean. NoneType-subscript fix awaiting Railway build for end-to-end verification.
