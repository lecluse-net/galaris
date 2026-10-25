# 0239 — Local voice detection and continuous listening

Date: 2026-10-25
Status: accepted

## Guarantee

Noise alone must not open a speech turn or interrupt playback. Capture and
barge-in must remain responsive while transcription is waiting on a provider.
Late transcripts must not start an obsolete reply or discard earlier speech.

Local classification can still mistake a noise for speech. Such a detection
pauses playback while retaining the existing response and exact unsent PCM.
An empty final transcript resumes it; only a nonempty final transcript confirms
interruption and starts a successor. This supersedes cancellation on local onset.

## Decision

The STT → agent → TTS pipeline uses a local Silero speech classifier, with one
model and resampler state per call. `pysilero-vad==3.4.0` packages the model and
native CPU implementation; calls need neither a model download nor a second
external service. Audio is continuously resampled from canonical 48 kHz mono
PCM16 to 16 kHz for classification. A 20 ms framing layer keeps segmentation
independent of transport packets. The canonical PCM and streaming STT input
remain intact. The package preserves its upstream MIT notices and model credits.

Existing onset confirmation, pre-roll and 800 ms pause tolerance remain. Onset
and minimum speech duration both use 240 ms, so an onset that interrupts a reply
is not subsequently discarded only because of a mismatched duration threshold.
Classifier tests use generated speech and deterministic noise; segmentation
tests inject a classifier rather than treating a constant PCM value as speech.

Capture and transcription run as separate owned coroutines. An ordered queue
contains both PCM and turn boundaries, so the next turn cannot contaminate an
earlier commit. PCM backlog is bounded to 30 seconds, with an additional bound
on event count. Overflow fails explicitly and closes the provider and capture.
During slow STT, a later onset still pauses output immediately. Earlier recognized
text is retained for the next current response. Generation checks also run after
waiting for previous-response cleanup. Stop cancels transcription and closes
the inbound iterator; queued progress indicators are terminated.

Input generations and response validity are tracked separately. Chat, Matrix and
Nextcloud output tracks emit paced silence while paused without consuming their
buffered PCM. The engine stops submitting frames through its existing bounded
queue. Latest-input guards prevent an earlier empty result from resuming a newer
pause. Confirmed speech clears both queues and cancels the old producer; hangup
also discards paused playback without waiting for it to drain. Transient partial
STT text cannot confirm an interruption, since the final result may still be empty.

ElevenLabs receives an internal manual commit every 20 seconds of streamed
audio, before its documented automatic commit at approximately 36 seconds.
Those segments are assembled until the local endpoint; they never independently
start an agent or tool. Empty commits keep the session open. Errors still use
the existing complete-audio fallback.
Local classification hints discard any text from segments containing no detected
speech, including hallucinated text returned by the provider during silence.
The first TTS text segment can be emitted
after 64 characters; subsequent segments retain the 160-character limit.

The native OpenAI path retains semantic VAD and provider-owned interruption,
requests high eagerness and near-field noise reduction, and continues to consume
audio directly without an auxiliary input transcript. These protocol settings
are covered by bridge tests; synthetic tests do not prove live provider latency.

## Verification and limits

Real Silero inference is exercised with silence, hum, white noise, clicks and
normal/attenuated synthetic speech across packet sizes. Pipeline tests cover
slow batch/streaming STT, ordered commits, late responses, cancellation, overflow,
empty transcripts and long provider segments. First-text/audio log timings retain
the local endpoint timestamp, including STT and queue delay.

The old onset test asserted destructive cancellation without checking the empty
transcript recovery path. It now asserts reversible pause; batch/streaming tests
exercise empty and nonempty outcomes, and actual transport-track tests verify
partial-frame retention, resumed ordering and confirmed discard.

These changes preserve deliberate pauses rather than shortening the endpoint
timer globally. Network delay, microphone acoustics, real speech recognition
accuracy and the audible benefit of native-provider settings require live-call
qualification. No deployment or real user audio is part of this decision.

Sources: [pySilero](https://github.com/rhasspy/pysilero-vad),
[ElevenLabs manual commits](https://elevenlabs.io/docs/eleven-api/guides/how-to/speech-to-text/realtime/transcripts-and-commit-strategies),
[OpenAI VAD](https://developers.openai.com/api/docs/guides/realtime-vad),
[OpenAI session input](https://developers.openai.com/api/reference/resources/realtime/client-events).
