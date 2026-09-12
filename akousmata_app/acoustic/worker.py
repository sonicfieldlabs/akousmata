"""Offline CLAP encoder, run in its own environment by an admitted owner job."""
import hashlib
import json
import math
from pathlib import Path
import resource
import sys
import time


def digest(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def run(request):
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly
    import torch
    from transformers import ClapModel, ClapProcessor

    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    np.random.seed(0)
    model = ClapModel.from_pretrained(request['model'], local_files_only=True).eval()
    processor = ClapProcessor.from_pretrained(request['model'], local_files_only=True)
    results = []
    for item in request['items']:
        start = time.monotonic()
        if 'text' in item:
            inputs = processor(text=[item['text']], return_tensors='pt', padding=True, truncation=True, max_length=77)
            with torch.inference_mode():
                vector = model.get_text_features(**inputs)[0]
            receipt = dict(kind='text', token_count=int(inputs['attention_mask'].sum()), max_tokens=77, truncated=len(processor.tokenizer(item['text'])['input_ids'])>77)
        else:
            path = Path(item['path'])
            before = digest(path)
            with sf.SoundFile(path) as stream:
                rate, channels = stream.samplerate, stream.channels
                if channels > 8 or rate > 384000:
                    raise ValueError('Audio format exceeds tested bounds')
                offset = int(item.get('start_seconds', 0) * rate)
                seconds = item['seconds']
                if not 0 < seconds <= 10 or offset < 0:
                    raise ValueError('Invalid segment bounds')
                stream.seek(offset)
                samples = stream.read(int(round(seconds * rate)), dtype='float32', always_2d=True)
            if not len(samples) or not np.isfinite(samples).all():
                raise ValueError('Empty or nonfinite audio')
            mono = samples.mean(axis=1)
            g = math.gcd(rate, 48000)
            audio = np.asarray(resample_poly(mono, 48000 // g, rate // g), dtype='<f4')
            # Ten-second segments avoid stochastic long-audio cropping. Short tails
            # use the pinned processor's repeat-pad policy, recorded explicitly.
            np.random.seed(0)
            inputs = processor(audio=audio, sampling_rate=48000, return_tensors='pt', padding='repeatpad')
            with torch.inference_mode():
                vector = model.get_audio_features(**inputs)[0]
            if digest(path) != before:
                raise ValueError('Source changed during embedding')
            receipt = dict(kind='audio', source_sha256=before, start_seconds=offset / rate,
                           end_seconds=(offset + len(samples)) / rate, sample_rate_hz=48000, channels=1,
                           original_sample_rate_hz=rate, original_channels=channels,
                           view_sha256=hashlib.sha256(audio.tobytes()).hexdigest(),
                           processor_sha256=hashlib.sha256(inputs['input_features'].numpy().tobytes()).hexdigest(),
                           transformations=['arithmetic channel mean', 'polyphase resampling to 48000 Hz', 'processor repeat-pad to 10 seconds'],
                           processor_shape=list(inputs['input_features'].shape))
        vector = vector.float()
        vector = vector / vector.norm(p=2)
        values = vector.cpu().tolist()
        if len(values) != 512 or not all(math.isfinite(v) for v in values):
            raise ValueError('Invalid CLAP vector')
        results.append(dict(vector=values, receipt=receipt, elapsed_seconds=time.monotonic()-start))
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return dict(items=results, peak_memory_mib=peak/(1024**2 if sys.platform=='darwin' else 1024))


if __name__ == '__main__':
    request = json.loads(Path(sys.argv[1]).read_text())
    Path(sys.argv[2]).write_text(json.dumps(run(request), allow_nan=False))
