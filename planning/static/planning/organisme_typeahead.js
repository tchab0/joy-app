/**
 * Combobox organisme : liste visible + saisie libre (mémorisée à l’enregistrement).
 */
window.organismeTypeahead = function organismeTypeahead({ options, urls, initial, initialUrl }) {
  return {
    options: Array.isArray(options) ? options : [],
    urls: urls && typeof urls === 'object' ? urls : {},
    query: initial || '',
    url: initialUrl || '',
    open: false,
    get filtered() {
      const q = (this.query || '').trim().toLowerCase();
      if (!q) return this.options;
      return this.options.filter((o) => String(o).toLowerCase().includes(q));
    },
    get isNew() {
      const q = (this.query || '').trim();
      if (!q) return false;
      return !this.options.some((o) => String(o).toLowerCase() === q.toLowerCase());
    },
    toggle() {
      this.open = !this.open;
    },
    choose(opt) {
      this.query = opt;
      if (this.urls && this.urls[opt]) {
        this.url = this.urls[opt];
      }
      this.open = false;
    },
  };
};
