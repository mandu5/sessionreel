'use strict';

const video = document.getElementById('demo');
const playButton = document.getElementById('play-demo');
const status = document.getElementById('player-status');
const chapters = [...document.querySelectorAll('[data-chapter]')];
let playIntent = 0;

function updatePlayback() {
  playButton.textContent = video.paused || video.ended ? 'Play the demo' : 'Pause the demo';
}

function updateChapter() {
  if (!Number.isFinite(video.duration) || video.duration <= 0) return;
  // Media timestamps can round just below a requested boundary (35 / 6, for example).
  const active = Math.min(chapters.length - 1, Math.floor((video.currentTime + 0.001) / video.duration * chapters.length));
  chapters.forEach((button, index) => button.setAttribute('aria-pressed', String(index === active)));
}

function enableChapters() {
  if (!Number.isFinite(video.duration) || video.duration <= 0) return;
  chapters.forEach(button => { button.disabled = false; });
  updateChapter();
}

playButton.addEventListener('click', async () => {
  const intent = ++playIntent;
  if (!video.paused && !video.ended) {
    video.pause();
    return;
  }
  try {
    if (video.ended) video.currentTime = 0;
    await video.play();
    if (intent !== playIntent) return;
    status.textContent = 'Playing the original repository demo.';
  } catch {
    if (intent !== playIntent) return;
    status.textContent = 'Playback could not start. Use the video controls or download the original MP4 below.';
  }
  updatePlayback();
});

chapters.forEach((button, index) => button.addEventListener('click', () => {
  if (!Number.isFinite(video.duration) || video.duration <= 0) return;
  // Editorial segments intentionally use video time, never source-event timestamps.
  video.currentTime = video.duration * index / chapters.length;
  updateChapter();
  status.textContent = `${button.querySelector('b').textContent}: editorial segment ${index + 1} of ${chapters.length}.`;
}));

video.addEventListener('loadedmetadata', enableChapters);
video.addEventListener('durationchange', enableChapters);
video.addEventListener('timeupdate', updateChapter);
video.addEventListener('play', updatePlayback);
video.addEventListener('pause', () => {
  updatePlayback();
  if (!video.ended) status.textContent = 'Demo paused. Play again or choose a chapter.';
});
video.addEventListener('ended', () => {
  updatePlayback();
  status.textContent = 'Demo finished. Play again or choose a chapter.';
});
video.addEventListener('error', () => {
  chapters.forEach(button => { button.disabled = true; });
  status.textContent = 'The video could not load. Download the original MP4 below.';
});
enableChapters();

document.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', async () => {
  const code = document.getElementById(button.dataset.copy);
  const message = button.closest('.command-block').querySelector('.copy-status');
  try {
    await navigator.clipboard.writeText(code.textContent);
    message.textContent = 'Copied. Run these commands in your terminal.';
  } catch {
    const range = document.createRange();
    range.selectNodeContents(code);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    message.textContent = 'Commands selected. Use your browser’s copy command.';
  }
}));
