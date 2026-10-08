# Phase 1 runtime dependencies

Akousmata 0.8.2 treats research proposals as a core feature. Both `akousma>=0.8.3`
and `akouo-contract>=0.10.0` are ordinary runtime dependencies; installing the dev
extra is not required to create a proposal. The owner audio resolver supplies a
record's declared content hash to Earworm's checked object resolver. Explicit
external file references keep their separate host policy.

The repository carries reviewed local candidate wheels under `vendor/`, with
source fingerprints and checksums. `uv sync --locked` uses these exact wheels;
ordinary pip installs from this checkout need `--find-links vendor` while these
versions remain unpublished. This does not claim package-index availability.

CI checks the hashes, then separately builds and installs Akousmata without dev
dependencies. `scripts/check_installed_research.py` creates a synthetic proposal
and checks retry/source preservation in a disposable store. All imported owner
packages must be inside that isolated environment. No live store, publication
grant, listening model or provider is involved.
