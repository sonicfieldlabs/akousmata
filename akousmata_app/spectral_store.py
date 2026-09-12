"""Allow curation of retained 1.8 accounts without reauthoring their evidence."""
from akousma import AkousmataStore
from akousma.record_evolution import _same_json
from akousmata_app.derivatives import resolve_numeric, reconcile_derivatives


class SpectralStore(AkousmataStore):
    def put(self, record, **kwargs):
        if record.get('schema_version') == '1.8.0' and 'supported_versions' not in kwargs:
            existing = self.get(record['akousma_id'])
            if existing is None or not _same_json(self._protected_account(existing), self._protected_account(record)):
                raise ValueError('New 1.8 evidence requires explicit host admission')
            retained = existing.get('extensions', {})
            bundle = retained.get('oida.spectral')
            kwargs.update(supported_versions=['1.8.0'],
                          validate_native=lambda value: [] if _same_json(value, retained.get('akouo.agent-native')) else ['Changed native evidence'],
                          resolve_object=lambda ref: resolve_numeric(self.root, ref)[1],
                          resolve_representation=lambda ref: bundle if bundle and ref == bundle['sampled_representation'] else None)
        return super().put(record, **kwargs)

    def forget_with_receipt(self, *args, **kwargs):
        receipt = super().forget_with_receipt(*args, **kwargs)
        reconcile_derivatives(self)
        return receipt
