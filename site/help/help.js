/* Progressive enhancement: every article and topic link also works without JS. */
(() => {
  'use strict';
  document.body.classList.add('js');
  const {locale, searchUrl, copy, copied, copyFailed, loading, searchError} = document.body.dataset;
  const input = document.getElementById('help-search');
  const results = document.getElementById('search-results');
  let catalog, request, sequence = 0, timer;
  const normalize = value => value.normalize('NFKC').toLocaleLowerCase(locale);
  const paragraph = text => {
    const element = document.createElement('p');
    element.textContent = text;
    return element;
  };
  async function loadCatalog() {
    if (catalog) return catalog;
    request ??= fetch(searchUrl).then(response => {
      if (!response.ok) throw new Error('Unavailable');
      return response.json();
    }).then(value => {
      catalog = value;
      return value;
    }).catch(error => {
      request = undefined;
      throw error;
    });
    return request;
  }
  async function search(current) {
    const query = normalize(input.value.trim());
    if (!query || current !== sequence) return;
    results.hidden = false;
    results.replaceChildren(paragraph(loading));
    try {
      const {articles, messages} = await loadCatalog();
      if (current !== sequence) return;
      const terms = query.split(/\s+/).filter(Boolean);
      const found = articles.map(article => {
        const title = normalize(article.title), text = normalize(article.text);
        return {article, matches: terms.every(term => title.includes(term) || text.includes(term)),
          score: terms.reduce((score, term) => score + (title.includes(term) ? 15 : 0) + (text.includes(term) ? 1 : 0), 0)};
      }).filter(item => item.matches).sort((a, b) => b.score - a.score);
      results.replaceChildren(paragraph(messages.results.replace('{count}', String(found.length))));
      if (!found.length) results.append(paragraph(messages.empty));
      for (const {article} of found.slice(0, 20)) {
        const link = document.createElement('a');
        link.href = article.url;
        const title = document.createElement('strong');
        title.textContent = article.title;
        // Search the full article; show the matching context as well as its title.
        const position = normalize(article.text).indexOf(terms[0]);
        const start = Math.max(0, position - 35);
        const excerpt = article.text.slice(start, start + 150);
        link.append(title, paragraph((start ? '…' : '') + excerpt + (start + 150 < article.text.length ? '…' : '')));
        results.append(link);
      }
    } catch {
      if (current === sequence) results.replaceChildren(paragraph(searchError));
    }
  }
  function clearSearch() {
    ++sequence;
    clearTimeout(timer);
    results.hidden = true;
    results.replaceChildren();
  }
  input.form.hidden = false;
  input.addEventListener('input', () => {
    clearSearch();
    const current = sequence;
    timer = setTimeout(() => void search(current), 120);
  });
  input.form.addEventListener('submit', event => {
    event.preventDefault();
    clearTimeout(timer);
    void search(++sequence);
  });
  input.form.addEventListener('reset', () => {clearSearch(); input.focus();});
  document.addEventListener('keydown', event => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault(); input.focus();
    }
    if (event.key === 'Escape') clearSearch();
  });
  for (const link of document.querySelectorAll('[data-language]')) {
    link.addEventListener('click', () => {
      // The six task sections share stable anchors across all three languages.
      if (/^#(goal|before|steps|result|troubleshooting|next)$/.test(location.hash)) link.hash = location.hash;
    });
  }
  const toggle = document.getElementById('topics-toggle');
  const nav = document.getElementById('topics-nav');
  const header = document.querySelector('.help-header');
  function closeTopics() {
    nav.classList.remove('open');
    toggle.setAttribute('aria-expanded', 'false');
  }
  new ResizeObserver(() => {
    nav.style.top = `${header.getBoundingClientRect().height}px`;
  }).observe(header);
  toggle.addEventListener('click', () => {
    const open = nav.classList.toggle('open');
    toggle.setAttribute('aria-expanded', String(open));
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && nav.classList.contains('open')) {
      closeTopics();
      toggle.focus();
    }
  });
  matchMedia('(max-width: 780px)').addEventListener('change', closeTopics);
  const dialog = document.getElementById('image-dialog');
  if (dialog.showModal) {
    dialog.querySelector('button').addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', event => {if (event.target === dialog) dialog.close();});
    for (const link of document.querySelectorAll('[data-zoom]')) link.addEventListener('click', event => {
      event.preventDefault();
      const image = dialog.querySelector('img');
      image.src = link.href;
      image.alt = link.querySelector('img').alt;
      dialog.showModal();
    });
  }
  for (const pre of document.querySelectorAll('.prose pre')) {
    const code = pre.querySelector('code');
    if (!code) continue;
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'copy-example';
    button.textContent = copy; button.setAttribute('aria-live', 'polite');
    button.addEventListener('click', async () => {
      try {await navigator.clipboard.writeText(code.textContent.trimEnd()); button.textContent = copied;}
      catch {
        const range = document.createRange(); range.selectNodeContents(code);
        const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range);
        button.textContent = copyFailed;
      }
      setTimeout(() => {button.textContent = copy;}, 2500);
    });
    pre.append(button);
  }
})();
