// Runs in <head> before first paint so the page never flashes the wrong theme.
// An explicit choice is stored; otherwise the system setting applies.
(function () {
  var saved = null;
  try { saved = localStorage.getItem("quill-theme"); } catch (e) {}
  if (saved === "light" || saved === "dark") document.documentElement.dataset.theme = saved;
})();
