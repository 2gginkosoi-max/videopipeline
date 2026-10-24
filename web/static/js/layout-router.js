(function () {
  const tabs = {
    assembly: document.getElementById('tab-assembly'),
    archive: document.getElementById('tab-archive'),
    profile: document.getElementById('tab-profile'),
    slicing: document.getElementById('tab-slicing')
  };

  const navButtons = Array.from(document.querySelectorAll('[data-tab]'));
  const bottomButtons = Array.from(document.querySelectorAll('.bottom-nav__btn[data-tab]'));

  function activate(tabName) {
    if (!tabs[tabName]) return;

    Object.entries(tabs).forEach(([name, el]) => {
      if (!el) return;
      if (name === tabName) {
        el.removeAttribute('hidden');
      } else {
        el.setAttribute('hidden', '');
      }
    });

    navButtons.forEach((btn) => {
      btn.classList.toggle('is-active', btn.dataset.tab === tabName);
    });

    bottomButtons.forEach((btn) => {
      btn.classList.toggle('is-active', btn.dataset.tab === tabName);
    });

    const title = document.querySelector('.main__title');
    const subtitle = document.querySelector('.main__subtitle');

    if (tabName === 'assembly') {
      if (title) title.textContent = 'СБОРКА';
      if (subtitle) subtitle.textContent = 'Конвейер генерации ролика';
    } else if (tabName === 'archive') {
      if (title) title.textContent = 'АРХИВ';
      if (subtitle) subtitle.textContent = 'История сборок';
    } else if (tabName === 'profile') {
      if (title) title.textContent = 'ПРОФИЛЬ';
      if (subtitle) subtitle.textContent = 'Настройки и голоса';
    } else if (tabName === 'slicing') {
      if (title) title.textContent = 'НАРЕЗКА';
      if (subtitle) subtitle.textContent = 'Автоматическая нарезка видео на клипы';
    }

    try {
      // Только путь + якорь вкладки: так ссылка остаётся короткой, а мусорные
      // query-параметры (например, ?videoFile=&youtubeUrl=… после нативной
      // GET-отправки формы) не переезжают из вкладки во вкладку.
      history.replaceState(null, '', location.pathname + '#' + tabName);
    } catch (e) {}
  }

  navButtons.concat(bottomButtons).forEach((btn) => {
    btn.addEventListener('click', () => activate(btn.dataset.tab));
  });

  const initial = (location.hash || '#assembly').replace('#', '');
  if (tabs[initial]) {
    activate(initial);
  } else {
    activate('assembly');
  }
})();
