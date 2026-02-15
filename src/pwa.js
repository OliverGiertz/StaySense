(function () {
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/service-worker.js").catch(() => {});
    });
  }

  const isIos = /iphone|ipad|ipod/i.test(window.navigator.userAgent);
  const isStandalone =
    window.matchMedia("(display-mode: standalone)").matches || Boolean(window.navigator.standalone);
  const hintEl = document.getElementById("ios-install-hint");
  if (hintEl && isIos && !isStandalone) {
    hintEl.textContent = "Tipp: Über Teilen > Zum Home-Bildschirm hinzufügen für App-Modus auf iOS.";
    hintEl.classList.remove("hidden");
  }
})();
