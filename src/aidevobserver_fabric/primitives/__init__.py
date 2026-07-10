"""Packaged, deterministic primitive implementations.

The runtime imports these modules through a fixed allowlist.  Each module is
self-contained and exposes its JSON contracts, proof fixtures, and ``run``
callable so an agent can safely materialize the exact implementation source.
"""

