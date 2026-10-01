from akousmata_app import exports


def test_expiry_is_not_consent_or_retention_deletion(monkeypatch):
    record={'provenance':{'consent_status':'owned'},'extensions':{'earworm_listening_context':{'claims':[{
        'claim_ref':'claim:1','listening_ref':'listening:1',
        'validity':{'status':'expires','issued_at':'2026-01-01T00:00:00Z','expires_at':'2026-02-01T00:00:00Z'},
        'retention':{'status':'review_after','review_after':'2026-01-15T00:00:00Z','policy_ref':'owner-policy'}
    }]}}}
    import copy
    before=copy.deepcopy(record)
    monkeypatch.setattr(exports,'claim_clock',lambda:'2026-01-20T00:00:00Z')
    assert exports.exportable(record)[0]  # review due does not itself expire the claim
    monkeypatch.setattr(exports,'claim_clock',lambda:'2026-02-01T00:00:00Z')
    assert not exports.exportable(record)[0]
    assert record==before
    record['extensions']['earworm_listening_context']['claims'][0]['validity']={'status':'unknown','reason':'No declared validity'}
    assert not exports.exportable(record)[0]
