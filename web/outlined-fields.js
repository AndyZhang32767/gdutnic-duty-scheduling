// Keep generated forms consistent with the static outlined fields.
(() => {
  const controlSelector = 'input:not([type=checkbox], [type=radio], [type=range], [type=file], [type=hidden], [type=submit], [type=button], [type=color]), textarea, select';
  function enhance(root) {
    const labels = root.matches?.('label') ? [root] : [];
    labels.push(...root.querySelectorAll('label'));
    for (const label of labels) {
      if (label.matches('.outlined-field, .m3-outlined-label')) continue;
      const control = [...label.children].find(child => child.matches(controlSelector));
      if (!control || control.closest('.weekly-table')) continue;
      const textNodes = [...label.childNodes].filter(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim());
      if (!textNodes.length) continue;
      const caption = document.createElement('span');
      caption.className = 'm3-field-caption';
      caption.textContent = textNodes.map(node => node.textContent.trim()).join(' ');
      textNodes.forEach(node => node.remove());
      label.prepend(caption);
      label.classList.add('m3-outlined-label');
      if (control.matches('input, textarea') && !control.hasAttribute('placeholder')) {
        control.placeholder = ' ';
      }
    }
  }
  enhance(document);
  new MutationObserver(records => {
    for (const record of records) {
      for (const node of record.addedNodes) {
        if (node.nodeType === Node.ELEMENT_NODE) enhance(node);
      }
    }
  }).observe(document.body, {childList: true, subtree: true});
})();
