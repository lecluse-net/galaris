# 0241 — Android call system volume with Web Audio

Date: 2026-10-25
Status: accepted

## Guarantee

Android calls retain the Web Audio workaround for reported native WebRTC quality
and maximum-volume problems. Volume belongs to Android, without an application
slider or a saved application gain.

## Cause and decision

The previous startup opened and resumed Web Audio before requesting microphone
capture. With processed capture, Android can subsequently enter communication
mode while output remains associated with media volume. The physical buttons
then adjust a different volume from the audible output.

Chromium selects low-latency output usage from the communication mode at stream
creation and enables that mode for processed microphone input. See
[AudioManagerAndroid](https://chromium.googlesource.com/chromium/src/media/+/master/audio/android/audio_manager_android.cc).
This supports the startup-order diagnosis; it does not prove the behavior of an
individual Android device.

Acquire the microphone with echo cancellation, noise suppression and automatic
gain control before creating the call's interactive AudioContext. Keep native
remote playback muted as the Chromium WebRTC sample consumer, and send the
Web Audio source directly to its destination. Remove the media-mode toggle and
volume preferences; old saved values are ignored. Preserve explicit playback
retry and local teardown on cancellation, hangup and navigation.

Active capture allows Chromium autoplay, as documented in
[Chrome's Web Audio autoplay policy](https://developer.chrome.com/blog/web-audio-autoplay).
Keep the gesture retry for browsers that still block playback.

## Evidence and limits

The regression test fails on the previous startup order and passes after the
change. Delayed microphone permission and cancellation must not create an output.
Tests also preserve a single audible output, blocked-playback recovery, late
completion isolation and reopening. Existing component coverage sends synthetic
audio between real Chromium WebRTC peers and measures the Web Audio signal.

These tests run on Linux. They do not certify physical Android volume buttons,
perceived quality, Bluetooth profiles or browser audio-stream reuse on a phone.
A real Android call is still required to confirm those outcomes. The prior
coverage measured application gain and output samples without checking capture
before output, so it could not detect the routing mismatch; that missing order
guarantee is now covered.
