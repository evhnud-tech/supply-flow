document.querySelectorAll('form').forEach((form) => {
  form.addEventListener('submit', () => {
    const button = form.querySelector('button[type="submit"]');
    if (!button) {
      return;
    }
    if (button.disabled) {
      return;
    }
    button.disabled = true;
    button.textContent = button.dataset.loadingText || 'Saving...';
  });
});

const customSelects = [];

function closeCustomSelects(except = null) {
  customSelects.forEach((instance) => {
    if (instance === except) {
      return;
    }
    instance.close();
  });
}

function createCustomSelect(select) {
  const wrapper = document.createElement('div');
  wrapper.className = 'custom-select';

  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'custom-select__button';

  const menu = document.createElement('div');
  menu.className = 'custom-select__menu';

  const updateButtonLabel = () => {
    const selectedOption = select.options[select.selectedIndex];
    button.textContent = selectedOption ? selectedOption.textContent : '';
  };

  const open = () => {
    wrapper.classList.add('is-open');
    button.setAttribute('aria-expanded', 'true');
    closeCustomSelects(instance);
  };

  const close = () => {
    wrapper.classList.remove('is-open');
    button.setAttribute('aria-expanded', 'false');
  };

  const instance = { close };
  instance.wrapper = wrapper;
  customSelects.push(instance);

  select.classList.add('custom-select__native');
  select.setAttribute('aria-hidden', 'true');
  select.tabIndex = -1;
  select.hidden = true;
  select.style.display = 'none';

  button.setAttribute('aria-haspopup', 'listbox');
  button.setAttribute('aria-expanded', 'false');

  Array.from(select.options).forEach((option, index) => {
    const optionButton = document.createElement('button');
    optionButton.type = 'button';
    optionButton.className = 'custom-select__option';
    optionButton.textContent = option.textContent;
    optionButton.dataset.value = option.value;
    optionButton.setAttribute('role', 'option');
    optionButton.setAttribute('aria-selected', String(index === select.selectedIndex));

    if (index === select.selectedIndex) {
      optionButton.classList.add('is-selected');
    }

    optionButton.addEventListener('click', (event) => {
      event.stopPropagation();
      select.value = option.value;
      select.dispatchEvent(new Event('change', { bubbles: true }));
      updateButtonLabel();
      close();
    });

    menu.appendChild(optionButton);
  });

  button.addEventListener('click', (event) => {
    event.stopPropagation();
    if (wrapper.classList.contains('is-open')) {
      close();
      return;
    }

    open();
  });

  select.addEventListener('change', () => {
    updateButtonLabel();
    Array.from(menu.querySelectorAll('.custom-select__option')).forEach((optionButton) => {
      const isSelected = optionButton.dataset.value === select.value;
      optionButton.classList.toggle('is-selected', isSelected);
      optionButton.setAttribute('aria-selected', String(isSelected));
    });
  });

  wrapper.appendChild(button);
  wrapper.appendChild(menu);
  select.insertAdjacentElement('afterend', wrapper);
  updateButtonLabel();

  return instance;
}

document.querySelectorAll('select').forEach((select) => {
  if (select.closest('.custom-select')) {
    return;
  }
  createCustomSelect(select);
});

document.addEventListener('click', (event) => {
  if (!event.target.closest('.custom-select')) {
    closeCustomSelects();
  }
});

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    closeCustomSelects();
  }
});
