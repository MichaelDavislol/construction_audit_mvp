const players = Array.from(document.querySelectorAll("[data-player]"));
const videos = players.map((player) => player.querySelector("video"));

document.querySelectorAll(".clip-picker").forEach((picker) => {
  const help = document.createElement("p");
  help.className = "clip-help";
  help.textContent = "Выберите фрагмент этапа";
  picker.before(help);
});

function pauseOtherVideos(currentVideo) {
  videos.forEach((video) => {
    if (video !== currentVideo && !video.paused) {
      video.pause();
    }
  });
}

players.forEach((player) => {
  const video = player.querySelector("video");
  const source = video.querySelector("source");
  const caption = player.querySelector(".clip-caption");
  const buttons = Array.from(player.querySelectorAll(".clip-button"));

  buttons.forEach((button, index) => {
    button.setAttribute("aria-pressed", index === 0 ? "true" : "false");

    button.addEventListener("click", () => {
      if (button.classList.contains("is-active")) {
        video.play().catch(() => {});
        return;
      }

      pauseOtherVideos(video);
      source.src = button.dataset.src;
      video.poster = button.dataset.poster;
      video.load();
      caption.textContent = button.dataset.label;

      buttons.forEach((candidate) => {
        const isActive = candidate === button;
        candidate.classList.toggle("is-active", isActive);
        candidate.setAttribute("aria-pressed", String(isActive));
      });

      video.play().catch(() => {});
    });
  });

  video.addEventListener("play", () => pauseOtherVideos(video));
});

const progressBar = document.querySelector(".reading-progress span");
let progressFrame = null;

function updateReadingProgress() {
  const scrollable = document.documentElement.scrollHeight - window.innerHeight;
  const progress = scrollable > 0 ? Math.min(window.scrollY / scrollable, 1) : 0;
  progressBar.style.width = `${progress * 100}%`;
  progressFrame = null;
}

window.addEventListener(
  "scroll",
  () => {
    if (progressFrame === null) {
      progressFrame = window.requestAnimationFrame(updateReadingProgress);
    }
  },
  { passive: true },
);

updateReadingProgress();
