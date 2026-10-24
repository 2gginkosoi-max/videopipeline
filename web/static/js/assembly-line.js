(function () {
  const form = document.getElementById('runForm');
  const connector = document.getElementById('stepsConnector');
  if (!form || !connector) return;

  form.addEventListener('submit', function () {
    connector.classList.add('is-active');
  });

  const logEl = document.getElementById('logBody');
  if (!logEl) return;

  const observer = new MutationObserver(function () {
    const text = logEl.textContent || '';
    if (text.includes('завершился') || text.includes('ошибка') || text.includes('Готово') || text.includes('готово')) {
      connector.classList.remove('is-active');
    }
  });

  // observer.observe(logEl, { childList: true, subtree: true, characterData: true });
})();
