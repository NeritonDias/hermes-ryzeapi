"""One disposable STT worker; stdout is only bounded JSON, not backend logs."""
import contextlib,json,os,sys

def transcribe(path):
    from tools.transcription_tools import transcribe_audio, transcribe_audio_local_fallback
    result = transcribe_audio(path,None,'gateway')
    if not result.get('success'): result = transcribe_audio_local_fallback(path)
    text = result.get('transcript') if result.get('success') else None
    if not isinstance(text,str) or not text.strip(): return None
    text = text.strip()
    return text[:16000]+'\n[Transcrição truncada pelo limite de segurança.]' if len(text)>16000 else text

if __name__ == '__main__':
    # Redirect the actual FDs too: native inference libraries may bypass Python streams.
    output = os.dup(1)
    with open(os.devnull,'w') as silent:
        os.dup2(silent.fileno(),1);os.dup2(silent.fileno(),2)
        with contextlib.redirect_stdout(silent),contextlib.redirect_stderr(silent):
            try: result = transcribe(sys.argv[1])
            except Exception: result = None
    with os.fdopen(output,'w') as out:
        out.write(json.dumps({'transcript':result},ensure_ascii=False))
