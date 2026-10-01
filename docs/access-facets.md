# Qualified library facets and access views

Unreleased K1/K7/K12 owner navigation. The existing canonical SQLite records and
listener-type index are reused through a temporary SQL view. No canonical account
is rewritten and no second record store is created.

`GET /api/facets` returns up to 200 values per subject, recipient, human-access
status, matter register, matter scale and listener type, with distinct record counts.
`GET /api/records` accepts `subject`, `recipient`, `human_access`, `register` and
`scale` together with its existing filters. Matching happens before the result
limit. Multiple facets describe membership in a record; they do not assert that
separate contexts within that record belong to one listening pass. Subject matches
explicit top-level subjects or context subject references. Registers/scales come
only from the declared matter context, never from inferred spectral ranges.

Unknown human access remains `unknown`. Missing access declarations are separately
`undeclared`. A known declaration is qualified by listener, chain, conditions,
renderings and evidence; it is not a universal audible-to-human flag. Non-acoustic
records remain navigable without imposing a frequency × timescale model.

The record detail's `access_view` preserves original capture, sampled representation,
model input, human access, listening contexts and matter context. The accessible
HTML table separates their statuses and qualifications, and an expandable original
payload provides full structured evidence. Capture range, sampled representation,
effective model input and human perceptual access do not establish one another.

All ten listener types keep textual labels in filters, cards and attributable
relationship nodes/edges. Card/detail badges add decorative glyphs hidden from
assistive technology; labels remain readable without glyphs. Community, institution,
habitat, sensor and other animal are not recategorized as human or agent.

The expandable facet controls retain current selections and refresh with library
changes. A response sequence guard prevents an older filter request replacing newer
results. Facet values remain capped at 200 and record results retain the existing
API limit; counts describe the owner library, not a public collection.

Public field allowlists remain unchanged. Owner access/context payloads and facet
inventories are not added to public projections. Publication and revocation preserve
the existing disclosure boundary. Fixtures validate canonical equality, all listener
types, compound filtering, unknown/undeclared access, non-acoustic register/scale
and public revocation. Browser checks use synthetic records and viewport emulation,
not physical human listening or a physical mobile device.
