"""Cancellable process group for STT. Timeout/cancel waits for real process termination."""
import asyncio,json,os,signal,sys
from pathlib import Path

def command(path):
    return [sys.executable,'-u',str(Path(__file__).with_name('stt_worker.py')),str(path)]

async def run_stt(path):
    env = dict(os.environ,PYTHONPATH=os.pathsep.join(str(p) for p in sys.path if p))
    proc = await asyncio.create_subprocess_exec(*command(path),env=env,start_new_session=True,
        stdin=asyncio.subprocess.DEVNULL,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
    try:
        # Worker normally emits <=64KiB UTF-8. Fail closed on excessive stdout.
        data = bytearray()
        while chunk := await proc.stdout.read(16384):
            data.extend(chunk)
            if len(data)>128*1024: raise ValueError('STT output limit')
        await proc.wait()
        if proc.returncode: return None
        value = json.loads(data)
        text = value.get('transcript') if isinstance(value,dict) else None
        return text[:17000] if isinstance(text,str) and text.strip() else None
    finally:
        # SIGTERM then SIGKILL cover inference and ordinary decoder descendants.
        try: os.killpg(proc.pid,signal.SIGTERM)
        except ProcessLookupError: pass
        if proc.returncode is None:
            try: await asyncio.wait_for(proc.wait(),2)
            except asyncio.TimeoutError: pass
        try: os.killpg(proc.pid,signal.SIGKILL)
        except ProcessLookupError: pass
        await proc.wait()
