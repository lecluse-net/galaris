import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { EditorVoiceControls, EditorVoiceContext, EditorVoiceSession } from '@/core/util'
import service from './services/personalLlmService'
import { transcriptSuffix } from './dictation'

export default function useEditorVoice(context: EditorVoiceContext): EditorVoiceSession {
  const { t, locale } = useI18n()
  const recording = ref(false), acquiring = ref(false), working = ref(false), reading = ref(false), buffering = ref(false), paused = ref(false)
  const error = ref('')
  const controls = computed<EditorVoiceControls>(() => ({
    dictating: recording.value, dictationPending: acquiring.value || working.value,
    reading: reading.value, buffering: buffering.value, paused: paused.value,
    labels: {
      dictate: t('personalVoice.dictate'), finishDictation: t('personalVoice.finishDictation'), processing: t('personalVoice.processing'),
      read: t('personalVoice.read'), reading: t('personalVoice.reading'), paused: t('personalVoice.paused'),
      pause: t('personalVoice.pauseReading'), resume: t('personalVoice.resumeReading'), stop: t('personalVoice.stopReading'),
      readingControls: t('personalVoice.readingControls'),
    },
    toggleDictation: () => {
      if (!context.editable()) return
      if (recording.value) finishRecording()
      else if (acquiring.value || working.value) stop()
      else void startRecording()
    },
    read: selectedHtml => { void read(selectedHtml) }, togglePause, stop,
  }))
  let generation = 0
  let recorder: MediaRecorder | undefined
  let stream: MediaStream | undefined
  let controller: AbortController | undefined
  let player: HTMLAudioElement | undefined
  let objectUrl: string | undefined
  let timer: ReturnType<typeof setTimeout> | undefined
  let snapshots: ReturnType<typeof setInterval> | undefined
  let releasePlayback: (() => void) | undefined

  function releaseMicrophone(): void {
    stream?.getTracks().forEach(track => track.stop()); stream = undefined
    clearTimeout(timer); timer = undefined
    clearInterval(snapshots); snapshots = undefined
  }
  function stop(): void {
    generation += 1
    controller?.abort(); controller = undefined
    if (recorder && recorder.state !== 'inactive') recorder.stop()
    recorder = undefined; releaseMicrophone()
    if (player) { player.onended = null; player.onerror = null; player.pause(); player.removeAttribute('src'); player.load() }
    player = undefined
    releasePlayback?.(); releasePlayback = undefined
    if (objectUrl) URL.revokeObjectURL(objectUrl)
    objectUrl = undefined
    recording.value = false; acquiring.value = false; working.value = false; reading.value = false; buffering.value = false; paused.value = false
  }
  async function failure(caught: unknown, fallback: string, current: number): Promise<void> {
    const data = (caught as { response?: { data?: unknown } })?.response?.data
    let detail: unknown = data
    if (data instanceof Blob) { try { detail = JSON.parse(await data.text()) } catch { detail = undefined } }
    if (current !== generation) return
    const message = (detail as { detail?: unknown })?.detail
    stop()
    error.value = typeof message === 'string' ? message : t(fallback)
  }
  async function startRecording(): Promise<void> {
    stop(); error.value = ''
    const current = generation
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      error.value = t('personalVoice.unsupported'); return
    }
    acquiring.value = true
    try {
      const acquired = await navigator.mediaDevices.getUserMedia({ audio: true })
      if (current !== generation) { acquired.getTracks().forEach(track => track.stop()); return }
      stream = acquired
      const mimeType = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus'].find(type => MediaRecorder.isTypeSupported(type))
      recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
      const activeRecorder = recorder
      const chunks: Blob[] = []
      let bytes = 0, revision = 0, transcribed = 0, running = false, previous = ''
      const request = new AbortController()
      controller = request
      // Each snapshot includes the container header and all audio so it is independently
      // decodable. Coalesce snapshots while the provider is busy; never queue stale audio.
      const transcribe = async (): Promise<void> => {
        if (running || current !== generation) return
        running = true; working.value = true
        try {
          while (current === generation && transcribed < revision) {
            const requestedRevision = revision
            const text = await service.transcribe(new Blob(chunks, { type: activeRecorder.mimeType }), locale.value, request.signal)
            if (current !== generation) return
            const addition = transcriptSuffix(previous, text)
            if (context.editable() && addition) context.insert(addition)
            if (text.trim()) previous = text.trim()
            transcribed = requestedRevision
          }
        } catch (caught) { await failure(caught, 'personalVoice.transcriptionError', current) }
        finally { running = false; if (current === generation) working.value = false }
      }
      recorder.ondataavailable = event => {
        if (current !== generation || !event.data.size) return
        chunks.push(event.data); bytes += event.data.size
        if (bytes > 20 * 1024 * 1024) { stop(); error.value = t('personalVoice.tooLarge'); return }
        revision += 1
        void transcribe()
      }
      recorder.onerror = () => { if (current === generation) { stop(); error.value = t('personalVoice.microphoneError') } }
      recorder.onstop = () => {
        if (current !== generation) return
        recorder = undefined; releaseMicrophone(); recording.value = false
        if (!running && transcribed === revision) working.value = false
      }
      recorder.start(); recording.value = true
      snapshots = setInterval(() => { if (activeRecorder.state === 'recording') activeRecorder.requestData() }, 2000)
      timer = setTimeout(finishRecording, 5 * 60 * 1000)
    } catch {
      if (current === generation) { stop(); error.value = t('personalVoice.microphoneError') }
    } finally { if (current === generation) acquiring.value = false }
  }
  function finishRecording(): void {
    if (recorder?.state === 'recording') { working.value = true; recorder.stop() }
    recording.value = false
    releaseMicrophone()
  }
  function play(current: number): void {
    void player?.play().catch((caught: unknown) => {
      if (current !== generation) return
      if (caught instanceof DOMException && caught.name === 'NotAllowedError') {
        paused.value = true; error.value = t('personalVoice.tapPlay')
      } else if (!(caught instanceof DOMException && caught.name === 'AbortError' && paused.value)) {
        void failure(caught, 'personalVoice.readError', current)
      }
    })
  }
  function togglePause(): void {
    if (!reading.value) return
    paused.value = !paused.value
    if (paused.value) player?.pause()
    else { error.value = ''; if (player?.src && !buffering.value) play(generation) }
  }
  async function read(selectedHtml?: string): Promise<void> {
    stop(); error.value = ''; reading.value = true
    const current = generation, html = selectedHtml ?? context.html()
    controller = new AbortController()
    const signal = controller.signal
    try {
      let offset = 0
      while (current === generation) {
        buffering.value = true
        const chunk = await service.speech(html, offset, signal)
        if (current !== generation) return
        buffering.value = false
        objectUrl = URL.createObjectURL(chunk.audio)
        player = context.playbackElement()
        if (!player) throw new Error('Audio player unavailable')
        player.src = objectUrl
        const activePlayer = player
        await new Promise<void>((resolve, reject) => {
          releasePlayback = resolve
          activePlayer.onended = () => resolve()
          activePlayer.onerror = () => reject(new Error('Audio playback failed'))
          if (!paused.value) play(current)
        })
        if (current !== generation) return
        URL.revokeObjectURL(objectUrl); objectUrl = undefined; releasePlayback = undefined
        if (chunk.done) break
        if (!Number.isFinite(chunk.nextOffset) || chunk.nextOffset <= offset) throw new Error('Invalid speech offset')
        offset = chunk.nextOffset
      }
    } catch (caught) { await failure(caught, 'personalVoice.readError', current) }
    finally { if (current === generation) stop() }
  }
  watch(() => context.editable(), value => { if (!value && (recording.value || acquiring.value || working.value)) stop() })
  onBeforeUnmount(stop)
  return { controls, error, stop }
}
