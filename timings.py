"""Bounded process-local stage durations; never store contacts or message content."""
import math
from collections import deque

STAGES = {'buffer','identity','media_download','stt_queue','stt_execution','preparation',
          'gateway_handoff','agent_to_first_send','send_text','send_media'}

class Timings:
    def __init__(self):
        self.samples = {key:deque(maxlen=256) for key in STAGES}
        self.counts = dict.fromkeys(STAGES,0)

    def observe(self, stage, seconds):
        if stage not in STAGES or not isinstance(seconds,(int,float)) or not math.isfinite(seconds) or seconds<0: return
        self.samples[stage].append(seconds*1000)
        self.counts[stage] += 1

    def summary(self):
        result = {}
        for key, values in self.samples.items():
            if not values: continue
            ordered = sorted(values)
            result[key] = {'count':self.counts[key], 'window_samples':len(values),
                           'last_ms':round(values[-1],2), 'mean_ms':round(sum(values)/len(values),2),
                           'p50_ms':round(ordered[math.ceil(len(values)*.5)-1],2),
                           'p95_ms':round(ordered[math.ceil(len(values)*.95)-1],2)}
        return result
