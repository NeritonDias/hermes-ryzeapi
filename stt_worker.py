"""One disposable STT worker; stdout is only bounded JSON, not backend logs."""
import contextlib,json,os,sys

class TranscriptionFailure(Exception):
    pass


def transcribe(path):
    from tools.transcription_tools import transcribe_audio, transcribe_audio_local_fallback
    from tools.transcription_tools import is_stt_enabled
    from tools.hosted_tool_policy import host_feature_refusal
    if not is_stt_enabled() or host_feature_refusal('transcription', 'Transcription'):
        raise TranscriptionFailure('disabled')
    result = transcribe_audio(path,None,'gateway')
    if not result.get('success'):
        primary_unavailable = 'no stt provider available' in str(result.get('error', '')).lower()
        result = transcribe_audio_local_fallback(path)
        if not result.get('success'):
            local_unavailable = 'no installed local stt backend' in str(result.get('error', '')).lower()
            raise TranscriptionFailure('no_provider' if primary_unavailable and local_unavailable else 'provider_failed')
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
            try: result = {'transcript': transcribe(sys.argv[1])}
            except ImportError: result = {'error':'worker_import'}
            except TranscriptionFailure as exc: result = {'error':str(exc)}
            except Exception: result = {'error':'provider_failed'}
    with os.fdopen(output,'w') as out:
        out.write(json.dumps(result,ensure_ascii=False))
