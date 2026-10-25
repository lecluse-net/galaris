# Synthetic speech fixture

`speech.wav` is generated speech, not a recording of a person or a conversation.
It was produced with FFmpeg's `flite` filter and the `slt` voice, then converted
to 48 kHz mono signed PCM16. Its English text is deliberately generic:

> Hello. I would like to discuss my plans for tomorrow. Can you help me find a quiet place to work?

Generation command inside the development container:

```sh
ffmpeg -f lavfi -i "flite=text='Hello. I would like to discuss my plans for tomorrow. Can you help me find a quiet place to work?':voice=slt" -ar 48000 -ac 1 -c:a pcm_s16le speech.wav
```

Flite and its voice are provided by the container's FFmpeg distribution. The
fixture contains only the generated output; no upstream program or model is
redistributed here. Noise fixtures are generated deterministically in tests.
