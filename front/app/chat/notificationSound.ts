let audioContext: AudioContext | null = null

async function resumeAudioContext(): Promise<AudioContext | null> {
  if (typeof window === 'undefined' || typeof window.AudioContext === 'undefined') return null
  if (!audioContext || audioContext.state === 'closed') audioContext = new window.AudioContext()
  if (audioContext.state === 'suspended') await audioContext.resume()
  return audioContext
}

function createTone(context: AudioContext, frequency: number, startAt: number): void {
  const oscillator = context.createOscillator()
  const gain = context.createGain()
  oscillator.type = 'sine'
  oscillator.frequency.setValueAtTime(frequency, startAt)
  gain.gain.setValueAtTime(0.0001, startAt)
  gain.gain.exponentialRampToValueAtTime(0.12, startAt + 0.012)
  gain.gain.exponentialRampToValueAtTime(0.0001, startAt + 0.11)
  oscillator.connect(gain)
  gain.connect(context.destination)
  oscillator.start(startAt)
  oscillator.stop(startAt + 0.12)
}

export async function playChatNotificationSound(): Promise<void> {
  const context = await resumeAudioContext()
  if (!context) return
  const startAt = context.currentTime
  createTone(context, 660, startAt)
  createTone(context, 880, startAt + 0.085)
}

export async function unlockChatNotificationSound(): Promise<void> {
  await resumeAudioContext()
}
