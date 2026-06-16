(() => {
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const nav = document.querySelector(".sidebar nav");
  const indicator = nav?.querySelector(".nav-indicator");
  const activeLink = nav?.querySelector("a.active");

  const moveNavIndicator = (link, animate = true) => {
    if (!nav || !indicator || !link) return;
    const navRect = nav.getBoundingClientRect();
    const linkRect = link.getBoundingClientRect();
    if (!animate) indicator.style.transition = "none";
    indicator.style.width = `${linkRect.width}px`;
    indicator.style.height = `${linkRect.height}px`;
    indicator.style.transform = `translate(${linkRect.left - navRect.left}px, ${linkRect.top - navRect.top}px)`;
    if (!animate) {
      indicator.getBoundingClientRect();
      indicator.style.transition = "";
    }
  };

  moveNavIndicator(activeLink, false);

  window.addEventListener("resize", () => {
    moveNavIndicator(nav?.querySelector("a.active"), false);
  });
})();

(() => {
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const video = document.querySelector(".background-video");
  if (!video || reducedMotion) return;

  const stateKey = "radar-background-video-state";
  let direction = 1;
  let lastTick = 0;
  let restored = false;

  const saveState = () => {
    if (!video.duration) return;
    localStorage.setItem(
      stateKey,
      JSON.stringify({
        time: video.currentTime,
        direction,
        updatedAt: Date.now(),
      })
    );
  };

  const restoreState = () => {
    if (restored || !video.duration) return;
    restored = true;
    try {
      const saved = JSON.parse(localStorage.getItem(stateKey) || "{}");
      if (typeof saved.time === "number" && Date.now() - saved.updatedAt < 300000) {
        video.currentTime = Math.min(Math.max(saved.time, 0), video.duration - 0.05);
      }
      direction = saved.direction === -1 ? -1 : 1;
    } catch {
      direction = 1;
    }
  };

  const playForward = () => {
    direction = 1;
    video.playbackRate = 1;
    video.play().catch(() => {});
  };

  const tickReverse = (timestamp) => {
    if (direction !== -1 || !video.duration) return;
    if (!lastTick) lastTick = timestamp;
    const delta = (timestamp - lastTick) / 1000;
    lastTick = timestamp;
    video.currentTime = Math.max(0, video.currentTime - delta);
    if (video.currentTime <= 0.04) {
      video.currentTime = 0;
      lastTick = 0;
      playForward();
      return;
    }
    window.requestAnimationFrame(tickReverse);
  };

  video.addEventListener("ended", () => {
    direction = -1;
    lastTick = 0;
    video.pause();
    video.currentTime = Math.max(0, video.duration - 0.04);
    window.requestAnimationFrame(tickReverse);
  });

  video.addEventListener("loadedmetadata", () => {
    restoreState();
    if (direction === -1) {
      video.pause();
      window.requestAnimationFrame(tickReverse);
    } else {
      playForward();
    }
  });

  window.addEventListener("pagehide", saveState);
  window.setInterval(saveState, 1000);
})();
