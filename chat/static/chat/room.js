function chatRoom(cfg) {
  cfg = cfg || {};
  function loadJson(scriptId, fallback) {
    if (!scriptId) return fallback || [];
    const el = document.getElementById(scriptId);
    if (!el) return fallback || [];
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      return fallback || [];
    }
  }
  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  return {
    messages: loadJson(cfg.messagesScriptId, cfg.messages || []).map(function (m) {
      return Object.assign({
        likes: 0, mine: null, hidden: false, reply_to: null,
        author_username: '', edited_at: null,
        replies_count: 0, first_reply_id: null,
      }, m);
    }),
    members: loadJson(cfg.membersScriptId, cfg.members || []),
    readCursors: loadJson(cfg.readCursorsScriptId, cfg.readCursors || []),
    currentUserId: cfg.currentUserId,
    wsUrl: cfg.wsUrl,
    apiSendUrl: cfg.apiSendUrl || '',
    apiReactUrl: cfg.apiReactUrl || '',
    apiEditUrl: cfg.apiEditUrl || '',
    apiMembersUrl: cfg.apiMembersUrl || '',
    apiReadUrl: cfg.apiReadUrl || '',
    csrfToken: cfg.csrfToken || '',
    embedded: !!cfg.embedded,
    initialLastReadAt: cfg.initialLastReadAt || null,
    membersLoaded: false,
    body: '',
    busy: false,
    busyReact: null,
    status: 'connecting',
    displayStatus: 'connecting',
    menuOpen: false,
    pendingFiles: [],
    editingAttachments: [],
    dragOver: false,
    _dragDepth: 0,
    attZoom: null,
    attZoomStyle: '',
    emojiOpen: false,
    replyTo: null,
    editingId: null,
    editPreview: '',
    mentionOpen: false,
    mentionQuery: '',
    mentionStart: -1,
    mentionIndex: 0,
    mentionSuggestions: [],
    readDetailsId: null,
    showJumpBottom: false,
    ws: null,
    _wsReconnectTimer: null,
    _wsStatusTimer: null,
    _wsPendingStatus: null,
    _wsRetryMs: 1000,
    _vvHandler: null,
    _visHandler: null,
    _scrollHandler: null,
    _jumpRaf: null,
    _readTimer: null,
    _lastReadSentAt: 0,
    _memberByUser: null,
    emojis: [
      '😀','😂','😅','😊','🙂','😉','😍','🤩','😎','🤔',
      '😴','😮','😢','😭','😤','🙄','👍','👎','👏','🙌',
      '💪','✌️','🤝','❤️','🔥','✨','🎉','✅','❌','⭐',
      '👀','🙏','💯','🍀','☕','🍻','🎂','🎵','🎶','🎷',
      '🎺','🥁','🎹','🎸','🎤','🎻','🎼','🎧','📢','💬'
    ],
    get statusLabel() {
      // Affichage sticky (displayStatus) : « En direct » reste visible pendant
      // les micro-coupures ; « Hors ligne… » seulement après stabilisation.
      return {
        connecting: 'Connexion…',
        live: 'En direct',
        offline: 'Hors ligne — envoi possible',
        error: 'Connexion interrompue'
      }[this.displayStatus] || '';
    },
    get statusClass() {
      return { live: 'is-live', error: 'is-err', offline: 'is-err' }[this.displayStatus] || '';
    },
    setStatus(next) {
      if (!next) return;
      this.status = next;
      if (next === 'live' || next === 'connecting') {
        if (this._wsStatusTimer) {
          clearTimeout(this._wsStatusTimer);
          this._wsStatusTimer = null;
        }
        this._wsPendingStatus = null;
        this.displayStatus = next;
        return;
      }
      // Hors ligne / erreur : n’afficher qu’après 2 s stables (pas de flash).
      if (next === 'offline' || next === 'error') {
        if (next === 'offline' || !this._wsPendingStatus) {
          this._wsPendingStatus = next;
        }
        if (this._wsStatusTimer) return;
        this._wsStatusTimer = setTimeout(() => {
          this._wsStatusTimer = null;
          const pending = this._wsPendingStatus || 'offline';
          this._wsPendingStatus = null;
          if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.status = 'live';
            this.displayStatus = 'live';
            return;
          }
          if (this.status !== 'live' && this.status !== 'connecting') {
            this.displayStatus = pending;
          }
        }, 2000);
        return;
      }
      this.displayStatus = next;
    },
    memberMap() {
      if (this._memberByUser) return this._memberByUser;
      const map = {};
      (this.members || []).forEach(function (m) {
        if (m && m.username) map[String(m.username).toLowerCase()] = m;
      });
      this._memberByUser = map;
      return map;
    },
    formatBodyHtml(body) {
      if (!body) return '';
      const map = this.memberMap();
      // Échapper d’abord (pas de HTML/JS utilisateur), puis mise en forme, puis @mentions
      let s = escapeHtml(String(body));

      function decodeBasic(esc) {
        return String(esc)
          .replace(/&quot;/g, '"')
          .replace(/&gt;/g, '>')
          .replace(/&lt;/g, '<')
          .replace(/&amp;/g, '&');
      }
      function safeHref(escapedUrl) {
        const u = decodeBasic(escapedUrl).trim();
        if (!/^https?:\/\//i.test(u)) return null;
        try {
          const parsed = new URL(u);
          if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null;
        } catch (e) {
          return null;
        }
        return escapeHtml(u);
      }
      function linkHtml(href, label) {
        return '<a class="chat-msg__link" href="' + href
          + '" target="_blank" rel="noopener noreferrer">' + label + '</a>';
      }
      function mapPlain(html, fn) {
        const parts = html.split(/(<[^>]+>)/);
        let out = '';
        for (let i = 0; i < parts.length; i++) {
          const part = parts[i];
          if (!part) continue;
          out += part.charAt(0) === '<' ? part : fn(part);
        }
        return out;
      }

      // Citations : lignes « > texte » → encadré (comme l’éditeur)
      s = (function applyQuotes(escaped) {
        const lines = escaped.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n');
        const chunks = [];
        let quoteBuf = [];
        let plain = [];
        function flushQuote() {
          if (!quoteBuf.length) return;
          chunks.push(
            '<blockquote class="chat-msg__cite">' + quoteBuf.join('<br>') + '</blockquote>'
          );
          quoteBuf = [];
        }
        function flushPlain() {
          if (!plain.length) return;
          chunks.push(plain.join('\n'));
          plain = [];
        }
        for (let i = 0; i < lines.length; i++) {
          const line = lines[i];
          const m = /^(?:&gt;|＞)\s?(.*)$/.exec(line);
          if (m) {
            flushPlain();
            quoteBuf.push(m[1]);
          } else {
            flushQuote();
            plain.push(line);
          }
        }
        flushQuote();
        flushPlain();
        return chunks.join('\n');
      })(s);

      // Listes à puces : lignes « - texte » ou « * texte »
      s = this.applyListBlocks(s);

      // Liens markdown [libellé](https://…)
      s = s.replace(
        /\[([^\]]{1,200})\]\((https?:\/\/[^)\s<>]{1,2000})\)/gi,
        function (m, label, url) {
          const href = safeHref(url);
          if (!href) return m;
          return linkHtml(href, label);
        }
      );

      // Auto-liens URL brutes
      s = mapPlain(s, function (text) {
        return text.replace(/https?:\/\/[^\s<]+/gi, function (url) {
          let trailing = '';
          let core = url;
          while (/[.,;:!?)]+$/.test(core)) {
            trailing = core.slice(-1) + trailing;
            core = core.slice(0, -1);
          }
          const href = safeHref(core);
          if (!href) return url;
          return linkHtml(href, core) + trailing;
        });
      });

      // Gras **texte** ou *texte* ; italique _texte_
      s = mapPlain(s, function (text) {
        text = text.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
        text = text.replace(/\*([^*\n]+)\*/g, '<strong>$1</strong>');
        text = text.replace(
          /(^|[^a-zA-Z0-9_])_([^_\n]+)_(?![a-zA-Z0-9_])/g,
          '$1<em>$2</em>'
        );
        return text;
      });

      // Mentions @ — token déjà échappé ; noms issus des membres à échapper
      s = mapPlain(s, function (text) {
        const re = /(^|[^\w.])@([^\s@]{1,50})/g;
        let out = '';
        let last = 0;
        let m;
        while ((m = re.exec(text)) !== null) {
          const prefix = m[1] || '';
          const token = m[2];
          const start = m.index;
          out += text.slice(last, start);
          out += prefix;
          const member = map[decodeBasic(token).toLowerCase()];
          const label = member ? escapeHtml(member.name) : token;
          const title = member ? ('@' + member.username) : ('@' + decodeBasic(token));
          out += '<span class="chat-mention-tag" title="' + escapeHtml(title) + '">@'
            + label + '</span>';
          last = start + m[0].length;
        }
        out += text.slice(last);
        return out;
      });

      return s;
    },
    /* —— Éditeur WYSIWYG (contenteditable) —— */
    safeHttpUrl(url) {
      const u = String(url || '').trim();
      if (!/^https?:\/\//i.test(u)) return null;
      try {
        const parsed = new URL(u);
        if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null;
        return parsed.href;
      } catch (e) {
        return null;
      }
    },
    markdownToEditorHtml(body) {
      if (!body) return '';
      let s = escapeHtml(String(body));
      function decodeBasic(esc) {
        return String(esc)
          .replace(/&quot;/g, '"')
          .replace(/&gt;/g, '>')
          .replace(/&lt;/g, '<')
          .replace(/&amp;/g, '&');
      }
      const self = this;
      function mapPlain(html, fn) {
        const parts = html.split(/(<[^>]+>)/);
        let out = '';
        for (let i = 0; i < parts.length; i++) {
          const part = parts[i];
          if (!part) continue;
          out += part.charAt(0) === '<' ? part : fn(part);
        }
        return out;
      }
      // Citations avant le reste (texte déjà échappé → &gt;)
      s = (function applyQuotes(escaped) {
        const lines = escaped.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n');
        const chunks = [];
        let quoteBuf = [];
        let plain = [];
        function flushQuote() {
          if (!quoteBuf.length) return;
          chunks.push('<blockquote class="chat-msg__cite">' + quoteBuf.join('<br>') + '</blockquote>');
          quoteBuf = [];
        }
        function flushPlain() {
          if (!plain.length) return;
          chunks.push(plain.join('\n'));
          plain = [];
        }
        for (let i = 0; i < lines.length; i++) {
          const line = lines[i];
          const m = /^(?:&gt;|＞)\s?(.*)$/.exec(line);
          if (m) {
            flushPlain();
            quoteBuf.push(m[1]);
          } else {
            flushQuote();
            plain.push(line);
          }
        }
        flushQuote();
        flushPlain();
        return chunks.join('\n');
      })(s);
      s = self.applyListBlocks(s);
      s = s.replace(
        /\[([^\]]{1,200})\]\((https?:\/\/[^)\s<>]{1,2000})\)/gi,
        function (m, label, url) {
          const href = self.safeHttpUrl(decodeBasic(url));
          if (!href) return m;
          return '<a href="' + escapeHtml(href) + '">' + label + '</a>';
        }
      );
      s = mapPlain(s, function (text) {
        text = text.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
        text = text.replace(/\*([^*\n]+)\*/g, '<strong>$1</strong>');
        text = text.replace(
          /(^|[^a-zA-Z0-9_])_([^_\n]+)_(?![a-zA-Z0-9_])/g,
          '$1<em>$2</em>'
        );
        return text;
      });
      return s.replace(/\n/g, '<br>');
    },
    applyListBlocks(escaped) {
      const lines = String(escaped || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n');
      const chunks = [];
      let listBuf = [];
      let plain = [];
      function flushList() {
        if (!listBuf.length) return;
        chunks.push(
          '<ul class="chat-msg__list">'
            + listBuf.map(function (t) { return '<li>' + t + '</li>'; }).join('')
            + '</ul>'
        );
        listBuf = [];
      }
      function flushPlain() {
        if (!plain.length) return;
        chunks.push(plain.join('\n'));
        plain = [];
      }
      for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        if (/^<(?:blockquote|ul)\b/i.test(line)) {
          flushList();
          flushPlain();
          chunks.push(line);
          continue;
        }
        const m = /^[-*•]\s+(.*)$/.exec(line);
        if (m) {
          flushPlain();
          listBuf.push(m[1]);
        } else {
          flushList();
          plain.push(line);
        }
      }
      flushList();
      flushPlain();
      return chunks.join('\n');
    },
    serializeEditor(root) {
      if (!root) return '';
      const self = this;
      function walk(node) {
        if (node.nodeType === Node.TEXT_NODE) {
          return (node.nodeValue || '').replace(/\u00a0/g, ' ');
        }
        if (node.nodeType !== Node.ELEMENT_NODE) return '';
        const tag = node.tagName.toLowerCase();
        if (tag === 'br') return '\n';
        if (tag === 'script' || tag === 'style' || tag === 'iframe'
            || tag === 'object' || tag === 'embed' || tag === 'img') {
          return '';
        }
        let inner = '';
        for (let i = 0; i < node.childNodes.length; i++) {
          inner += walk(node.childNodes[i]);
        }
        if (tag === 'strong' || tag === 'b') {
          const t = inner.trim();
          if (!t) return inner;
          return '*' + inner.replace(/\*/g, '') + '*';
        }
        if (tag === 'em' || tag === 'i') {
          const t = inner.trim();
          if (!t) return inner;
          return '_' + inner.replace(/_/g, '') + '_';
        }
        if (tag === 'a') {
          const href = self.safeHttpUrl(node.getAttribute('href') || '');
          if (!href) return inner;
          const label = (inner || href).replace(/[\[\]]/g, '');
          return '[' + label + '](' + href + ')';
        }
        if (tag === 'blockquote') {
          const cleaned = inner.replace(/\n+$/, '');
          if (!cleaned) return '\n';
          return cleaned.split('\n').map(function (line) {
            return '> ' + line.replace(/^>\s?/, '');
          }).join('\n') + '\n';
        }
        if (tag === 'li') {
          const cleaned = inner.replace(/^\n+|\n+$/g, '').replace(/\u200B/g, '');
          if (!cleaned.trim()) return '';
          return '- ' + cleaned.replace(/^[-*•]\s+/, '') + '\n';
        }
        if (tag === 'ul' || tag === 'ol') {
          const cleaned = inner.replace(/\n+$/, '');
          return cleaned ? cleaned + '\n' : '';
        }
        if (tag === 'div' || tag === 'p' || tag === 'h1'
            || tag === 'h2' || tag === 'h3' || tag === 'tr') {
          if (!inner) return '\n';
          return inner + (/\n$/.test(inner) ? '' : '\n');
        }
        return inner;
      }
      let out = '';
      for (let i = 0; i < root.childNodes.length; i++) {
        out += walk(root.childNodes[i]);
      }
      return out.replace(/\u00a0/g, ' ').replace(/\u200B/g, '').replace(/\n+$/, '');
    },
    syncBodyFromEditor() {
      const el = this.$refs.input;
      if (!el) {
        this.body = '';
        return;
      }
      // Contenteditable laisse souvent un seul <br> quand « vide »
      const raw = el.innerHTML.replace(/<br\s*\/?>/gi, '').replace(/&nbsp;/gi, '').replace(/\u200B/g, '').trim();
      if (!raw || raw === '<div></div>' || raw === '<p></p>') {
        if (el.innerHTML && el.innerHTML !== '') el.innerHTML = '';
        this.body = '';
        return;
      }
      this.body = this.serializeEditor(el);
    },
    setEditorFromMarkdown(md) {
      const el = this.$refs.input;
      const text = md || '';
      this.body = text;
      if (!el) return;
      el.innerHTML = text ? this.markdownToEditorHtml(text) : '';
      this.autoGrow();
    },
    focusEditor(atEnd) {
      const el = this.$refs.input;
      if (!el) return;
      el.focus();
      if (atEnd) {
        try {
          const range = document.createRange();
          range.selectNodeContents(el);
          range.collapse(false);
          const sel = window.getSelection();
          sel.removeAllRanges();
          sel.addRange(range);
        } catch (_) {}
      }
    },
    getTextBeforeCaret() {
      const el = this.$refs.input;
      if (!el) return '';
      const sel = window.getSelection();
      if (!sel || !sel.rangeCount || !el.contains(sel.anchorNode)) {
        return this.serializeEditor(el);
      }
      const pre = sel.getRangeAt(0).cloneRange();
      pre.selectNodeContents(el);
      pre.setEnd(sel.getRangeAt(0).startContainer, sel.getRangeAt(0).startOffset);
      const frag = pre.cloneContents();
      const div = document.createElement('div');
      div.appendChild(frag);
      return this.serializeEditor(div);
    },
    getCaretMarkdownOffset() {
      return this.getTextBeforeCaret().length;
    },
    placeCaretInEditor(mdOffset) {
      const text = this.body || '';
      const off = Math.max(0, Math.min(mdOffset == null ? text.length : mdOffset, text.length));
      const ZW = '\u200B';
      this.setEditorFromMarkdown(text.slice(0, off) + ZW + text.slice(off));
      const el = this.$refs.input;
      if (!el) return;
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      let node;
      while ((node = walker.nextNode())) {
        const idx = node.nodeValue.indexOf(ZW);
        if (idx < 0) continue;
        node.nodeValue = node.nodeValue.slice(0, idx) + node.nodeValue.slice(idx + 1);
        try {
          const range = document.createRange();
          range.setStart(node, idx);
          range.collapse(true);
          const sel = window.getSelection();
          sel.removeAllRanges();
          sel.addRange(range);
        } catch (_) {}
        break;
      }
      this.syncBodyFromEditor();
      if (this.$refs.input) {
        try { this.$refs.input.focus(); } catch (_) {}
      }
    },
    insertTextAtCaret(text) {
      const el = this.$refs.input;
      if (!el) return;
      el.focus();
      try {
        if (!document.execCommand('insertText', false, text)) {
          const sel = window.getSelection();
          if (sel && sel.rangeCount) {
            const range = sel.getRangeAt(0);
            range.deleteContents();
            const node = document.createTextNode(text);
            range.insertNode(node);
            range.setStartAfter(node);
            range.collapse(true);
            sel.removeAllRanges();
            sel.addRange(range);
          } else {
            el.appendChild(document.createTextNode(text));
          }
        }
      } catch (_) {
        el.appendChild(document.createTextNode(text));
      }
      this.syncBodyFromEditor();
    },
    replaceMarkdownRange(start, end, insert) {
      const text = this.body || '';
      const next = text.slice(0, start) + insert + text.slice(end);
      const caretAt = start + insert.length;
      this.body = next;
      this.placeCaretInEditor(caretAt);
      this.$nextTick(() => {
        if (this.$refs.input) this.$refs.input.focus();
        this.autoGrow();
        this.measureComposer();
      });
    },
    applyRichFormat(cmd) {
      this.emojiOpen = false;
      this.closeMention();
      const el = this.$refs.input;
      if (el) el.focus();
      try {
        document.execCommand(cmd, false, null);
      } catch (_) {}
      this.syncBodyFromEditor();
      this.autoGrow();
      this.measureComposer();
    },
    onEditorPaste(ev) {
      ev.preventDefault();
      const clip = ev.clipboardData || window.clipboardData;
      const text = clip ? clip.getData('text/plain') : '';
      if (!text) return;
      try {
        document.execCommand('insertText', false, text);
      } catch (_) {
        this.insertTextAtCaret(text);
        return;
      }
      this.syncBodyFromEditor();
      this.autoGrow();
      this.measureComposer();
    },
    insertLink() {
      this.emojiOpen = false;
      this.closeMention();
      const el = this.$refs.input;
      if (el) el.focus();
      const sel = window.getSelection();
      let selected = '';
      if (sel && sel.rangeCount && el && el.contains(sel.anchorNode)) {
        selected = String(sel.toString() || '').trim();
      }
      let url = window.prompt('Adresse du lien (http:// ou https://)', 'https://');
      if (url == null) return;
      url = this.safeHttpUrl(url);
      if (!url) {
        window.alert('Le lien doit commencer par http:// ou https://');
        return;
      }
      let label = selected;
      if (!label) {
        const asked = window.prompt('Texte affiché (optionnel)', url);
        if (asked == null) return;
        label = String(asked).trim() || url;
      }
      if (selected) {
        try {
          document.execCommand('createLink', false, url);
        } catch (_) {
          this.insertTextAtCaret('[' + label + '](' + url + ')');
          this.setEditorFromMarkdown(this.body);
          return;
        }
        // Forcer http(s) uniquement : resérialise
        this.syncBodyFromEditor();
        this.setEditorFromMarkdown(this.body);
      } else {
        this.insertTextAtCaret('');
        const safeLabel = label.replace(/</g, '');
        try {
          document.execCommand(
            'insertHTML',
            false,
            '<a href="' + escapeHtml(url) + '">' + escapeHtml(safeLabel) + '</a>&nbsp;'
          );
        } catch (_) {
          this.insertTextAtCaret('[' + label + '](' + url + ')');
        }
        this.syncBodyFromEditor();
        this.setEditorFromMarkdown(this.body);
      }
      this.$nextTick(() => {
        this.focusEditor(true);
        this.autoGrow();
        this.measureComposer();
      });
    },
    isLeadingHidden(index) {
      for (let i = 0; i < index; i++) {
        const m = this.messages[i];
        if (!m.hidden || m.deleted) return false;
      }
      return true;
    },
    followingHidden(index) {
      const out = [];
      for (let i = index + 1; i < this.messages.length; i++) {
        const m = this.messages[i];
        if (m.hidden && !m.deleted) out.push(m);
        else break;
      }
      return out;
    },
    replyPreview(msg) {
      if (!msg) return '';
      if (msg.deleted) return 'Message supprimé';
      const body = (msg.body || '').trim();
      if (body) return body.length > 80 ? body.slice(0, 77) + '…' : body;
      if (msg.attachments && msg.attachments.length) {
        const n = msg.attachments.length;
        return n > 1 ? (n + ' pièces jointes') : 'Pièce jointe';
      }
      return '…';
    },
    messageActivityIso(msg) {
      if (!msg) return '';
      return msg.edited_at || msg.created_at || '';
    },
    readersFor(msg) {
      if (!msg || msg.author_id !== this.currentUserId || msg.deleted || msg.highlight) {
        return [];
      }
      const activity = this.messageActivityIso(msg);
      const activityMs = Date.parse(activity);
      if (!activityMs) return [];
      const authorId = Number(msg.author_id);
      return (this.readCursors || []).filter(function (c) {
        if (!c || c.last_read_at == null) return false;
        if (Number(c.user_id) === authorId) return false;
        const t = Date.parse(c.last_read_at);
        return !!t && t >= activityMs;
      });
    },
    readSummary(msg) {
      const readers = this.readersFor(msg);
      if (!readers.length) return '';
      if (readers.length === 1) return 'Lu par ' + readers[0].name;
      if (readers.length === 2) {
        return 'Lu par ' + readers[0].name + ' et ' + readers[1].name;
      }
      return 'Lu par ' + readers[0].name + ' et ' + (readers.length - 1) + ' autres';
    },
    readersListTitle(msg) {
      return this.readersFor(msg).map(function (r) { return r.name; }).join(', ');
    },
    toggleReadDetails(msgId) {
      this.readDetailsId = this.readDetailsId === msgId ? null : msgId;
    },
    applyReadCursor(cursor) {
      if (!cursor || cursor.user_id == null || !cursor.last_read_at) return;
      const uid = Number(cursor.user_id);
      const idx = (this.readCursors || []).findIndex(function (c) {
        return Number(c.user_id) === uid;
      });
      if (idx >= 0) {
        const prev = this.readCursors[idx];
        const prevMs = Date.parse(prev.last_read_at || '') || 0;
        const nextMs = Date.parse(cursor.last_read_at) || 0;
        if (nextMs < prevMs) return;
        this.readCursors.splice(idx, 1, Object.assign({}, prev, cursor));
      } else {
        this.readCursors = (this.readCursors || []).concat([cursor]);
      }
    },
    scheduleMarkRead() {
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
        return;
      }
      if (this._readTimer) clearTimeout(this._readTimer);
      this._readTimer = setTimeout(() => {
        this._readTimer = null;
        this.markRead();
      }, 400);
    },
    markRead() {
      const now = Date.now();
      if (now - (this._lastReadSentAt || 0) < 1500) return;
      this._lastReadSentAt = now;
      if (this.ws && this.ws.readyState === 1) {
        try {
          this.ws.send(JSON.stringify({ type: 'chat.read' }));
          return;
        } catch (_) { /* fallback HTTP */ }
      }
      if (!this.apiReadUrl) return;
      const fd = new FormData();
      fetch(this.apiReadUrl, {
        method: 'POST',
        headers: { 'X-CSRFToken': this.csrfToken },
        body: fd,
        credentials: 'same-origin',
      }).then((r) => r.json()).then((data) => {
        if (data && data.ok && data.cursor) this.applyReadCursor(data.cursor);
      }).catch(function () { /* ignore */ });
    },
    startReply(msg) {
      if (!msg || msg.deleted) return;
      this.cancelEdit();
      this.replyTo = msg;
      this.emojiOpen = false;
      this.closeMention();
      const uname = msg.author_username || '';
      if (uname && msg.author_id !== this.currentUserId) {
        const token = '@' + uname;
        const cur = (this.body || '').trimStart();
        if (!cur.toLowerCase().startsWith(token.toLowerCase())) {
          this.setEditorFromMarkdown(token + (cur ? ' ' + cur : ' '));
        }
      }
      this.$nextTick(() => {
        this.measureComposer();
        this.focusEditor(true);
        this.autoGrow();
        this.onFocus();
      });
    },
    startEdit(msg) {
      if (!msg || msg.deleted || msg.author_id !== this.currentUserId || msg.highlight) return;
      this.replyTo = null;
      this.emojiOpen = false;
      this.closeMention();
      this.editingId = msg.id;
      this.editPreview = this.replyPreview(msg);
      this.setEditorFromMarkdown(msg.body || '');
      this.clearPendingFiles();
      this.editingAttachments = (msg.attachments || []).map(function (a) {
        return {
          id: a.id,
          name: a.name || '',
          url: a.url || '',
          size: a.size || 0,
          isImage: !!a.is_image,
          key: 'ex-' + a.id,
        };
      });
      this.$nextTick(() => {
        this.measureComposer();
        this.focusEditor(true);
        this.autoGrow();
        this.onFocus();
      });
    },
    cancelEdit() {
      if (!this.editingId) return;
      this.editingId = null;
      this.editPreview = '';
      this.editingAttachments = [];
      this.clearPendingFiles();
      this.hideAttZoom();
      this.setEditorFromMarkdown('');
      this.$nextTick(() => this.measureComposer());
    },
    removeEditingAttachment(id) {
      this.editingAttachments = (this.editingAttachments || []).filter(function (a) {
        return a.id !== id;
      });
      this.hideAttZoom();
      this.$nextTick(() => this.measureComposer());
    },
    clearReply() {
      this.replyTo = null;
      this.$nextTick(() => this.measureComposer());
    },
    closeMention() {
      this.mentionOpen = false;
      this.mentionQuery = '';
      this.mentionStart = -1;
      this.mentionIndex = 0;
      this.mentionSuggestions = [];
    },
    mentionMatch(mem, query) {
      if (!mem || !mem.username) return false;
      if (Number(mem.id) === Number(this.currentUserId)) return false;
      if (!query) return true;
      function fold(s) {
        try {
          return String(s).toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
        } catch (e) {
          return String(s).toLowerCase();
        }
      }
      const q = fold(query);
      const user = fold(mem.username);
      const name = fold(mem.name || '');
      const parts = name.split(/[\s-]+/).filter(Boolean);
      if (user.startsWith(q)) return true;
      if (parts.some(function (p) { return p.startsWith(q); })) return true;
      if (q.length >= 2 && (user.includes(q) || name.includes(q))) return true;
      return false;
    },
    async loadMembers() {
      if (!this.apiMembersUrl) {
        this.membersLoaded = true;
        return;
      }
      try {
        const sep = this.apiMembersUrl.indexOf('?') >= 0 ? '&' : '?';
        const url = this.apiMembersUrl + sep + '_=' + Date.now();
        const r = await fetch(url, {
          headers: { 'Accept': 'application/json', 'Cache-Control': 'no-cache' },
          credentials: 'same-origin',
          cache: 'no-store',
        });
        if (!r.ok) throw new Error('members http ' + r.status);
        const data = await r.json();
        if (data && data.ok && Array.isArray(data.members) && data.members.length) {
          this.members = data.members;
          this._memberByUser = null;
        }
      } catch (e) { /* garde la liste embarquée */ }
      this.membersLoaded = true;
    },
    refreshMention(cursorPos) {
      const text = this.body || '';
      const pos = cursorPos != null ? cursorPos : text.length;
      const before = text.slice(0, pos);
      const m = before.match(/(^|[\s\n])@([^\s@]*)$/);
      if (!m) {
        this.closeMention();
        return;
      }
      const query = m[2] || '';
      this.mentionStart = before.length - query.length - 1;
      this.mentionQuery = query;
      const self = this;
      const scored = (this.members || []).filter(function (mem) {
        return self.mentionMatch(mem, query);
      }).map(function (mem) {
        const q = query.toLowerCase();
        const user = String(mem.username).toLowerCase();
        const name = (mem.name || '').toLowerCase();
        let score = 50;
        if (user.startsWith(q)) score = 0;
        else if (name.split(/[\s-]+/).some(function (p) { return p.startsWith(q); })) score = 1;
        return { mem: mem, score: score, label: name };
      });
      scored.sort(function (a, b) {
        if (a.score !== b.score) return a.score - b.score;
        return a.label.localeCompare(b.label, 'fr');
      });
      this.mentionSuggestions = scored.slice(0, 15).map(function (x) { return x.mem; });
      this.mentionIndex = 0;
      this.mentionOpen = true;
      this.$nextTick(() => this.measureComposer());
    },
    pickMention(mem) {
      if (!mem || !mem.username) return;
      this.syncBodyFromEditor();
      const text = this.body || '';
      const start = this.mentionStart >= 0 ? this.mentionStart : text.length;
      let end = start + 1 + (this.mentionQuery || '').length;
      const caret = this.getCaretMarkdownOffset();
      if (caret > start) end = Math.max(end, caret);
      const insert = '@' + mem.username + ' ';
      this.closeMention();
      this.replaceMarkdownRange(start, end, insert);
    },
    async startMentionPicker() {
      this.emojiOpen = false;
      if (!this.membersLoaded || !(this.members && this.members.length)) {
        await this.loadMembers();
      }
      this.syncBodyFromEditor();
      const text = this.body || '';
      let pos = this.getCaretMarkdownOffset();
      if (pos == null) pos = text.length;
      const before = text.slice(0, pos);
      const needsAt = !/(^|[\s\n])@$/.test(before) && !/(^|[\s\n])@[^\s@]*$/.test(before);
      if (needsAt) {
        this.replaceMarkdownRange(pos, pos, '@');
        pos += 1;
        this.$nextTick(() => {
          this.refreshMention(pos);
          this.autoGrow();
          this.measureComposer();
        });
        return;
      }
      this.focusEditor(false);
      this.placeCaretInEditor(pos);
      this.refreshMention(pos);
      this.autoGrow();
      this.measureComposer();
    },
    async onBodyInput() {
      this.syncBodyFromEditor();
      this.autoGrow();
      if (!this.membersLoaded) await this.loadMembers();
      const pos = this.getCaretMarkdownOffset();
      this.refreshMention(pos);
    },
    getBlockquoteAtCaret() {
      const el = this.$refs.input;
      const sel = window.getSelection();
      if (!el || !sel || !sel.anchorNode) return null;

      const findFrom = (node) => {
        if (!node) return null;
        let n = node.nodeType === 1 ? node : node.parentElement;
        while (n && n !== el) {
          if (n.tagName && n.tagName.toLowerCase() === 'blockquote') return n;
          n = n.parentElement;
        }
        return null;
      };

      let bq = findFrom(sel.anchorNode) || findFrom(sel.focusNode);
      if (bq) return bq;

      // Fréquent en mode modification : la sélection est sur la racine
      // contenteditable, pas à l’intérieur du <blockquote> enfant.
      if (sel.anchorNode === el) {
        const offset = sel.anchorOffset;
        if (offset > 0) {
          const prev = el.childNodes[offset - 1];
          if (prev && prev.nodeType === 1 && prev.tagName.toLowerCase() === 'blockquote') {
            return prev;
          }
          bq = findFrom(prev);
          if (bq) return bq;
        }
        if (offset < el.childNodes.length) {
          const next = el.childNodes[offset];
          if (next && next.nodeType === 1 && next.tagName.toLowerCase() === 'blockquote') {
            return next;
          }
          bq = findFrom(next);
          if (bq) return bq;
        }
      }
      return null;
    },
    placeCaretInNode(node, offset) {
      try {
        const sel = window.getSelection();
        const range = document.createRange();
        range.setStart(node, offset == null ? 0 : offset);
        range.collapse(true);
        sel.removeAllRanges();
        sel.addRange(range);
      } catch (_) {}
    },
    unwrapBlockquote(bq) {
      if (!bq || !bq.parentNode) return;
      const parent = bq.parentNode;
      while (bq.firstChild) {
        parent.insertBefore(bq.firstChild, bq);
      }
      parent.removeChild(bq);
    },
    /** Sort de la citation : texte avant le caret reste cité ; la suite est hors citation. */
    exitBlockquoteAtCaret() {
      const el = this.$refs.input;
      const bq = this.getBlockquoteAtCaret();
      const sel = window.getSelection();
      if (!el || !bq || !sel || !sel.rangeCount) return false;
      const range = sel.getRangeAt(0);
      const caretInside = bq === range.endContainer || bq.contains(range.endContainer);

      if (caretInside) {
        const afterRange = document.createRange();
        afterRange.selectNodeContents(bq);
        afterRange.setStart(range.endContainer, range.endOffset);
        let afterFrag = null;
        try {
          afterFrag = afterRange.extractContents();
        } catch (_) {
          afterFrag = null;
        }
        while (bq.lastChild) {
          const last = bq.lastChild;
          if (last.nodeType === Node.ELEMENT_NODE && last.tagName.toLowerCase() === 'br') {
            bq.removeChild(last);
            continue;
          }
          if (last.nodeType === Node.TEXT_NODE && !/[^\s\u200B]/.test(last.nodeValue || '')) {
            bq.removeChild(last);
            continue;
          }
          break;
        }
        const zw = document.createTextNode('\u200B');
        if (bq.nextSibling) el.insertBefore(zw, bq.nextSibling);
        else el.appendChild(zw);
        if (afterFrag) {
          const hasContent = (afterFrag.textContent || '').replace(/[\s\u200B]/g, '').length
            || (afterFrag.querySelector && afterFrag.querySelector('img,br,a'));
          if (hasContent) {
            el.insertBefore(afterFrag, zw.nextSibling);
          }
        }
        if (!bq.childNodes.length) {
          bq.parentNode && bq.parentNode.removeChild(bq);
        }
        this.placeCaretInNode(zw, 1);
        return true;
      }

      // Caret hors du blockquote (racine) : placer la suite juste après
      const zw = document.createTextNode('\u200B');
      if (bq.nextSibling) el.insertBefore(zw, bq.nextSibling);
      else el.appendChild(zw);
      this.placeCaretInNode(zw, 1);
      return true;
    },
    applyQuote() {
      this.emojiOpen = false;
      this.closeMention();
      const el = this.$refs.input;
      if (!el) return;
      el.focus();
      const bq = this.getBlockquoteAtCaret();
      try {
        if (bq) {
          // Toggle off : unwrap fiable (formatBlock('div') échoue souvent ici)
          this.unwrapBlockquote(bq);
        } else if (!document.execCommand('formatBlock', false, 'blockquote')) {
          document.execCommand('formatBlock', false, '<blockquote>');
        }
      } catch (_) {}
      this.syncBodyFromEditor();
      this.autoGrow();
      this.measureComposer();
    },
    getListItemAtCaret() {
      const el = this.$refs.input;
      const sel = window.getSelection();
      if (!el || !sel || !sel.anchorNode) return null;
      const findFrom = (node) => {
        if (!node) return null;
        let n = node.nodeType === 1 ? node : node.parentElement;
        while (n && n !== el) {
          if (n.tagName && n.tagName.toLowerCase() === 'li') return n;
          n = n.parentElement;
        }
        return null;
      };
      let li = findFrom(sel.anchorNode) || findFrom(sel.focusNode);
      if (li) return li;
      if (sel.anchorNode === el) {
        const offset = sel.anchorOffset;
        if (offset > 0) {
          const prev = el.childNodes[offset - 1];
          if (prev && prev.nodeType === 1) {
            if (prev.tagName.toLowerCase() === 'li') return prev;
            if (prev.tagName.toLowerCase() === 'ul' || prev.tagName.toLowerCase() === 'ol') {
              return prev.lastElementChild && prev.lastElementChild.tagName.toLowerCase() === 'li'
                ? prev.lastElementChild
                : findFrom(prev);
            }
            li = findFrom(prev);
            if (li) return li;
          }
        }
        if (offset < el.childNodes.length) {
          const next = el.childNodes[offset];
          if (next && next.nodeType === 1) {
            if (next.tagName.toLowerCase() === 'li') return next;
            if (next.tagName.toLowerCase() === 'ul' || next.tagName.toLowerCase() === 'ol') {
              return next.firstElementChild && next.firstElementChild.tagName.toLowerCase() === 'li'
                ? next.firstElementChild
                : findFrom(next);
            }
            li = findFrom(next);
            if (li) return li;
          }
        }
      }
      return null;
    },
    applyBulletList() {
      this.emojiOpen = false;
      this.closeMention();
      const el = this.$refs.input;
      if (!el) return;
      el.focus();
      try {
        document.execCommand('insertUnorderedList', false, null);
      } catch (_) {
        // Repli : préfixe markdown sur la sélection / ligne courante
        this.syncBodyFromEditor();
        const text = this.body || '';
        const caret = this.getCaretMarkdownOffset();
        const pos = caret == null ? text.length : caret;
        const lineStart = text.lastIndexOf('\n', Math.max(0, pos - 1)) + 1;
        let lineEnd = text.indexOf('\n', pos);
        if (lineEnd < 0) lineEnd = text.length;
        const line = text.slice(lineStart, lineEnd);
        if (/^[-*•]\s+/.test(line)) {
          this.replaceMarkdownRange(lineStart, lineEnd, line.replace(/^[-*•]\s+/, ''));
        } else {
          this.replaceMarkdownRange(lineStart, lineEnd, '- ' + line);
        }
        return;
      }
      this.syncBodyFromEditor();
      this.autoGrow();
      this.measureComposer();
    },
    insertSoftBreak() {
      // Nouvelle ligne + arrêt gras/italique/citation pour le texte qui suit
      if (this.getBlockquoteAtCaret()) {
        this.exitBlockquoteAtCaret();
      } else if (this.getListItemAtCaret()) {
        const li = this.getListItemAtCaret();
        const empty = !(li.textContent || '').replace(/[\s\u200B]/g, '');
        if (empty) {
          // Puce vide → sortir de la liste
          try { document.execCommand('insertUnorderedList', false, null); } catch (_) {}
        } else {
          try {
            if (!document.execCommand('insertParagraph')) {
              document.execCommand('insertHTML', false, '<li>\u200B</li>');
            }
          } catch (_) {
            this.insertTextAtCaret('\n- ');
          }
        }
      } else {
        try {
          if (!document.execCommand('insertLineBreak')) this.insertTextAtCaret('\n');
        } catch (_) {
          this.insertTextAtCaret('\n');
        }
      }

      try {
        if (document.queryCommandState('bold')) {
          document.execCommand('bold', false, null);
        }
        if (document.queryCommandState('italic')) {
          document.execCommand('italic', false, null);
        }
      } catch (_) {}

      this.syncBodyFromEditor();
      this.autoGrow();
      this.measureComposer();
    },
    onEditorBeforeInput(ev) {
      // Filet de sécurité : certains navigateurs créent un nouveau bloc
      // (insertParagraph) malgré preventDefault sur keydown.
      if (ev.inputType !== 'insertParagraph') return;
      if (this.mentionOpen && this.mentionSuggestions.length) {
        ev.preventDefault();
        return;
      }
      ev.preventDefault();
      this.syncBodyFromEditor();
      this.send();
    },
    onBodyKeydown(ev) {
      if (this.mentionOpen && this.mentionSuggestions.length) {
        if (ev.key === 'ArrowDown') {
          ev.preventDefault();
          this.mentionIndex = (this.mentionIndex + 1) % this.mentionSuggestions.length;
          return;
        }
        if (ev.key === 'ArrowUp') {
          ev.preventDefault();
          this.mentionIndex = (this.mentionIndex - 1 + this.mentionSuggestions.length)
            % this.mentionSuggestions.length;
          return;
        }
        if (ev.key === 'Enter' || ev.key === 'Tab') {
          ev.preventDefault();
          this.pickMention(this.mentionSuggestions[this.mentionIndex]);
          return;
        }
        if (ev.key === 'Escape') {
          ev.preventDefault();
          this.closeMention();
          return;
        }
      }
      const isEnter = ev.key === 'Enter' || ev.code === 'Enter' || ev.code === 'NumpadEnter';
      if (isEnter) {
        // Entrée = envoyer ; Maj+Entrée = nouvelle ligne et fin du formatage en cours.
        ev.preventDefault();
        if (ev.shiftKey) {
          this.insertSoftBreak();
          return;
        }
        this.syncBodyFromEditor();
        this.send();
        return;
      }
      if ((ev.key === 'b' || ev.key === 'B') && (ev.metaKey || ev.ctrlKey)) {
        ev.preventDefault();
        this.applyRichFormat('bold');
        return;
      }
      if ((ev.key === 'i' || ev.key === 'I') && (ev.metaKey || ev.ctrlKey)) {
        ev.preventDefault();
        this.applyRichFormat('italic');
      }
    },
    scrollToMessage(id, opts) {
      if (!id) return;
      const el = document.getElementById('chat-msg-' + id);
      if (!el) return;
      const o = opts || {};
      el.scrollIntoView({
        block: o.block || 'center',
        behavior: o.behavior || 'smooth',
      });
      el.classList.add('chat-msg--flash');
      setTimeout(() => el.classList.remove('chat-msg--flash'), 1200);
      // Après un saut vers une citation, le FAB « bas » aide à revenir
      this.$nextTick(() => this.queueJumpBottomUpdate());
      setTimeout(() => this.updateJumpBottom(), 400);
    },
    repliesLabel(msg) {
      const n = (msg && msg.replies_count) || 0;
      if (n <= 1) return 'Voir la réponse ↓';
      return n + ' réponses ↓';
    },
    // Cible : 1re réponse non lue parmi les messages chargés ; sinon first_reply_id.
    replyJumpTargetId(msg) {
      if (!msg) return null;
      const parentId = msg.id;
      const raw = this.initialLastReadAt;
      const lastReadMs = raw ? Date.parse(raw) : null;
      const unreadMs = raw && !lastReadMs ? null : (Number.isFinite(lastReadMs) ? lastReadMs : null);
      for (let i = 0; i < this.messages.length; i++) {
        const m = this.messages[i];
        if (!m || m.deleted || !m.reply_to || m.reply_to.id !== parentId) continue;
        if (this.isMessageUnread(m, unreadMs)) return m.id;
      }
      if (msg.first_reply_id) return msg.first_reply_id;
      for (let i = 0; i < this.messages.length; i++) {
        const m = this.messages[i];
        if (m && !m.deleted && m.reply_to && m.reply_to.id === parentId) return m.id;
      }
      return null;
    },
    scrollToReply(msg) {
      const id = this.replyJumpTargetId(msg);
      if (id) this.scrollToMessage(id);
    },
    noteReplyOnParent(message) {
      if (!message || !message.reply_to || !message.reply_to.id) return;
      const parent = this.messages.find(m => m.id === message.reply_to.id);
      if (!parent) return;
      parent.replies_count = (parent.replies_count || 0) + 1;
      if (!parent.first_reply_id) parent.first_reply_id = message.id;
    },
    ingestMessage(message) {
      if (!message || !message.id) return false;
      if (this.messages.find(m => m.id === message.id)) return false;
      this.messages.push(Object.assign({
        likes: 0, mine: null, hidden: false, reply_to: null,
        author_username: '', edited_at: null,
        replies_count: 0, first_reply_id: null,
      }, message));
      this.noteReplyOnParent(message);
      return true;
    },
    isNearBottom(threshold) {
      const el = this.$refs.thread;
      if (!el || this.embedded) return true;
      const t = threshold == null ? 120 : threshold;
      return el.scrollHeight - el.scrollTop - el.clientHeight < t;
    },
    updateJumpBottom() {
      if (this.embedded) {
        this.showJumpBottom = false;
        return;
      }
      this.showJumpBottom = !this.isNearBottom(160);
    },
    queueJumpBottomUpdate() {
      if (this.embedded) return;
      if (this._jumpRaf) return;
      this._jumpRaf = requestAnimationFrame(() => {
        this._jumpRaf = null;
        this.updateJumpBottom();
      });
    },
    bindThreadScroll() {
      if (this.embedded) return;
      const el = this.$refs.thread;
      if (!el || this._scrollHandler) return;
      this._scrollHandler = () => this.queueJumpBottomUpdate();
      el.addEventListener('scroll', this._scrollHandler, { passive: true });
    },
    jumpToBottom() {
      this.scrollBottom(true, true);
      this.showJumpBottom = false;
    },
    isMessageUnread(msg, lastReadMs) {
      if (!msg || msg.deleted) return false;
      if (Number(msg.author_id) === Number(this.currentUserId)) return false;
      if (lastReadMs == null) return true;
      if (msg.edited_at) {
        const t = Date.parse(msg.edited_at);
        return !!t && t > lastReadMs;
      }
      const t = Date.parse(msg.created_at);
      return !!t && t > lastReadMs;
    },
    findFirstUnreadId() {
      const raw = this.initialLastReadAt;
      const lastReadMs = raw ? Date.parse(raw) : null;
      if (raw && !lastReadMs) return null;
      for (let i = 0; i < this.messages.length; i++) {
        if (this.isMessageUnread(this.messages[i], Number.isFinite(lastReadMs) ? lastReadMs : null)) {
          return this.messages[i].id;
        }
      }
      return null;
    },
    scrollToInitialPosition() {
      const id = this.findFirstUnreadId();
      if (id) {
        this.scrollToMessage(id, { block: 'start', behavior: 'auto' });
        return;
      }
      this.scrollBottom(true);
    },
    _canHoverZoom() {
      try {
        return window.matchMedia('(hover: hover) and (pointer: fine)').matches;
      } catch (_) {
        return false;
      }
    },
    showAttZoom(ev, att) {
      if (!this._canHoverZoom() || !att || !att.url) return;
      this.attZoom = { url: att.url, name: att.name || '' };
      this.moveAttZoom(ev);
    },
    moveAttZoom(ev) {
      if (!this.attZoom || !ev) return;
      const pad = 16;
      const maxW = Math.min(520, window.innerWidth - pad * 2);
      const maxH = Math.min(520, window.innerHeight - pad * 2);
      let left = (ev.clientX || 0) + 18;
      let top = (ev.clientY || 0) + 18;
      if (left + maxW > window.innerWidth - pad) {
        left = Math.max(pad, (ev.clientX || 0) - maxW - 18);
      }
      if (top + maxH > window.innerHeight - pad) {
        top = Math.max(pad, window.innerHeight - maxH - pad);
      }
      this.attZoomStyle = 'left:' + left + 'px;top:' + top + 'px;--zoom-max-w:' + maxW
        + 'px;--zoom-max-h:' + maxH + 'px';
    },
    hideAttZoom() {
      this.attZoom = null;
      this.attZoomStyle = '';
    },
    _dragHasFiles(ev) {
      const types = ev && ev.dataTransfer && ev.dataTransfer.types;
      if (!types) return false;
      return Array.from(types).indexOf('Files') !== -1;
    },
    onComposerDragEnter(ev) {
      if (!this._dragHasFiles(ev)) return;
      this._dragDepth = (this._dragDepth || 0) + 1;
      this.dragOver = true;
      if (ev.dataTransfer) ev.dataTransfer.dropEffect = 'copy';
    },
    onComposerDragOver(ev) {
      if (!this._dragHasFiles(ev)) return;
      this.dragOver = true;
      if (ev.dataTransfer) ev.dataTransfer.dropEffect = 'copy';
    },
    onComposerDragLeave(ev) {
      if (!this._dragHasFiles(ev)) return;
      this._dragDepth = Math.max(0, (this._dragDepth || 0) - 1);
      if (this._dragDepth === 0) this.dragOver = false;
    },
    onComposerDrop(ev) {
      this._dragDepth = 0;
      this.dragOver = false;
      const files = ev.dataTransfer && ev.dataTransfer.files;
      if (!files || !files.length) return;
      this.addPendingFiles(Array.from(files));
    },
    _acceptedExtensions() {
      const input = this.$refs.files;
      const raw = (input && input.getAttribute('accept')) || '';
      return raw.split(',').map(function (s) {
        return s.trim().toLowerCase();
      }).filter(Boolean);
    },
    _fileIsAccepted(file) {
      if (!file) return false;
      const name = String(file.name || '').toLowerCase();
      const dot = name.lastIndexOf('.');
      const ext = dot >= 0 ? name.slice(dot) : '';
      const accepted = this._acceptedExtensions();
      if (!accepted.length) return true;
      if (ext && accepted.indexOf(ext) !== -1) return true;
      const type = String(file.type || '').toLowerCase();
      if (type && accepted.indexOf(type) !== -1) return true;
      return false;
    },
    addPendingFiles(fileList) {
      const list = Array.from(fileList || []).filter((f) => this._fileIsAccepted(f));
      if (!list.length) return;
      const maxCount = 20;
      const keptExisting = (this.editingId && this.editingAttachments)
        ? this.editingAttachments.length
        : 0;
      const existing = new Set(
        (this.pendingFiles || []).map((p) => p.name + '|' + p.size + '|' + (p.file && p.file.lastModified))
      );
      const added = [];
      let hitCap = false;
      list.forEach((file, i) => {
        const sig = file.name + '|' + file.size + '|' + file.lastModified;
        if (existing.has(sig)) return;
        if (keptExisting + (this.pendingFiles || []).length + added.length >= maxCount) {
          hitCap = true;
          return;
        }
        existing.add(sig);
        const isImage = this._isImageFile(file);
        added.push({
          key: sig + '-' + Date.now() + '-' + i,
          name: file.name,
          size: file.size,
          file,
          isImage,
          preview: isImage ? URL.createObjectURL(file) : '',
        });
      });
      if (added.length) {
        this.pendingFiles = (this.pendingFiles || []).concat(added);
      }
      if (hitCap) {
        window.alert('Maximum ' + maxCount + ' pièces jointes par message.');
      }
      this._syncFilesInput();
      this.$nextTick(() => this.measureComposer());
    },
    insertEmoji(em) {
      const el = this.$refs.input;
      this.emojiOpen = false;
      if (!el) {
        this.body = (this.body || '') + em;
        return;
      }
      el.focus();
      this.insertTextAtCaret(em);
      this.autoGrow();
      this.measureComposer();
    },
    init() {
      this.loadMembers();
      this.$nextTick(() => {
        this.bindThreadScroll();
        this.scrollToInitialPosition();
        this.updateJumpBottom();
        // Images / layout : 2e passe après paint
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            this.scrollToInitialPosition();
            this.updateJumpBottom();
          });
        });
      });
      this.connect();
      this.bindVisibility();
      if (!this.embedded) {
        this.bindViewport();
        this.$nextTick(() => this.measureComposer());
        window.addEventListener('resize', () => {
          this.measureComposer();
          this.updateJumpBottom();
        });
      }
    },
    bindVisibility() {
      this._visHandler = () => {
        if (document.visibilityState === 'visible') this.scheduleMarkRead();
      };
      document.addEventListener('visibilitychange', this._visHandler);
    },
    bindViewport() {
      if (this.embedded || !window.visualViewport) return;
      this._vvHandler = () => this.adaptToKeyboard();
      window.visualViewport.addEventListener('resize', this._vvHandler);
      window.visualViewport.addEventListener('scroll', this._vvHandler);
    },
    adaptToKeyboard() {
      if (this.embedded) return;
      const vv = window.visualViewport;
      const composer = this.$refs.composer;
      const room = this.$el;
      if (!vv || !composer) return;
      const inset = Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
      composer.style.bottom = inset + 'px';
      if (room) room.style.setProperty('--keyboard-inset', inset + 'px');
      this.measureComposer();
      if (inset > 40) this.scrollBottom(false);
    },
    measureComposer() {
      if (this.embedded) return;
      const composer = this.$refs.composer;
      const room = this.$el;
      if (!composer || !room) return;
      const h = composer.offsetHeight || 120;
      room.style.setProperty('--composer-h', h + 'px');
    },
    onFocus() {
      this.$nextTick(() => {
        this.adaptToKeyboard();
        this.scrollBottom(true);
        if (this.$refs.input) {
          this.$refs.input.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        }
      });
      if (!this.embedded) {
        setTimeout(() => { this.adaptToKeyboard(); this.scrollBottom(false); }, 350);
      }
    },
    autoGrow() {
      const el = this.$refs.input;
      if (!el) return;
      el.style.height = 'auto';
      el.style.height = Math.min(el.scrollHeight, 110) + 'px';
      this.measureComposer();
    },
    formatFileSize(bytes) {
      const n = Number(bytes) || 0;
      if (n < 1024) return n + ' o';
      if (n < 1024 * 1024) return (n / 1024).toFixed(n < 10 * 1024 ? 1 : 0) + ' Ko';
      return (n / (1024 * 1024)).toFixed(n < 10 * 1024 * 1024 ? 1 : 0) + ' Mo';
    },
    _isImageFile(file) {
      const t = (file && file.type) || '';
      return t.startsWith('image/') && t !== 'image/svg+xml';
    },
    _syncFilesInput() {
      if (!this.$refs.files) return;
      try {
        const dt = new DataTransfer();
        this.pendingFiles.forEach((item) => {
          if (item && item.file) dt.items.add(item.file);
        });
        this.$refs.files.files = dt.files;
      } catch (_) {
        /* DataTransfer non supporté : l’input garde la dernière sélection */
      }
    },
    clearPendingFiles() {
      (this.pendingFiles || []).forEach((item) => {
        if (item && item.preview) {
          try { URL.revokeObjectURL(item.preview); } catch (_) {}
        }
      });
      this.pendingFiles = [];
      if (this.$refs.files) this.$refs.files.value = '';
    },
    onFiles() {
      const list = this.$refs.files && this.$refs.files.files;
      if (!list || !list.length) return;
      this.addPendingFiles(Array.from(list));
    },
    removePendingFile(key) {
      const next = [];
      (this.pendingFiles || []).forEach((item) => {
        if (item.key === key) {
          if (item.preview) {
            try { URL.revokeObjectURL(item.preview); } catch (_) {}
          }
        } else {
          next.push(item);
        }
      });
      this.pendingFiles = next;
      this._syncFilesInput();
      this.hideAttZoom();
      this.$nextTick(() => this.measureComposer());
    },
    scheduleWsReconnect() {
      if (this._wsReconnectTimer) return;
      const wait = Math.min(this._wsRetryMs || 1000, 15000);
      this._wsRetryMs = Math.min((this._wsRetryMs || 1000) * 2, 15000);
      this._wsReconnectTimer = setTimeout(() => {
        this._wsReconnectTimer = null;
        this.connect();
      }, wait);
    },
    connect() {
      if (!this.wsUrl) {
        this.setStatus('offline');
        return;
      }
      if (this._wsReconnectTimer) {
        clearTimeout(this._wsReconnectTimer);
        this._wsReconnectTimer = null;
      }
      let sock;
      try {
        if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
          try { this.ws.close(); } catch (_) {}
        }
        sock = new WebSocket(this.wsUrl);
        this.ws = sock;
      } catch (e) {
        this.setStatus('offline');
        this.scheduleWsReconnect();
        return;
      }
      this.ws.onopen = () => {
        if (this.ws !== sock) return;
        this.setStatus('live');
        this._wsRetryMs = 1000;
        this.scheduleMarkRead();
      };
      this.ws.onclose = () => {
        if (this.ws !== sock) return;
        this.setStatus('offline');
        this.scheduleWsReconnect();
      };
      this.ws.onerror = () => {
        if (this.ws !== sock) return;
        this.setStatus('error');
      };
      this.ws.onmessage = (ev) => {
        let data;
        try { data = JSON.parse(ev.data); } catch (_) { return; }
        if (data.type === 'chat.message' && data.message) {
          if (this.ingestMessage(data.message)) {
            this.$nextTick(() => this.scrollBottom(false));
          }
          if (data.message.author_id !== this.currentUserId) {
            this.scheduleMarkRead();
          }
        } else if (data.type === 'chat.message_edit' && data.message) {
          const idx = this.messages.findIndex(m => m.id === data.message.id);
          if (idx >= 0) {
            const prev = this.messages[idx];
            this.messages.splice(idx, 1, Object.assign({}, prev, data.message, {
              likes: data.message.likes != null ? data.message.likes : prev.likes,
              mine: data.message.mine != null ? data.message.mine : prev.mine,
              hidden: data.message.hidden != null ? data.message.hidden : prev.hidden,
            }));
          }
          if (data.message.author_id !== this.currentUserId) {
            this.scheduleMarkRead();
          }
        } else if (data.type === 'chat.reaction' && data.message_id) {
          const msg = this.messages.find(m => m.id === data.message_id);
          if (msg) msg.likes = data.likes || 0;
        } else if (data.type === 'chat.read' && data.cursor) {
          this.applyReadCursor(data.cursor);
        }
      };
    },
    async toggleReaction(msg, value) {
      if (!msg || msg.deleted || !this.apiReactUrl || this.busyReact) return;
      this.busyReact = msg.id;
      const fd = new FormData();
      fd.append('message_id', msg.id);
      fd.append('value', value);
      try {
        const r = await fetch(this.apiReactUrl, {
          method: 'POST',
          headers: { 'X-CSRFToken': this.csrfToken },
          body: fd,
        });
        const data = await r.json();
        if (!data.ok) {
          alert(data.error || 'Erreur');
        } else {
          msg.likes = data.likes || 0;
          msg.mine = data.mine || null;
          msg.hidden = !!data.hidden;
        }
      } catch (e) {
        alert('Échec de la réaction');
      }
      this.busyReact = null;
    },
    formatTime(iso) {
      try {
        const d = new Date(iso);
        return d.toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
      } catch (_) { return ''; }
    },
    scrollBottom(force, smooth) {
      const el = this.$refs.thread;
      if (!el) return;
      if (this.embedded) {
        if (force) el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        return;
      }
      const nearBottom = this.isNearBottom(120);
      if (force || nearBottom) {
        if (smooth) {
          el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
        } else {
          el.scrollTop = el.scrollHeight;
        }
      }
      this.queueJumpBottomUpdate();
    },
    _resetComposer() {
      this.body = '';
      this.replyTo = null;
      this.editingId = null;
      this.editPreview = '';
      this.editingAttachments = [];
      this.emojiOpen = false;
      this.closeMention();
      this.clearPendingFiles();
      this.hideAttZoom();
      if (this.$refs.input) {
        this.$refs.input.innerHTML = '';
        this.$refs.input.style.height = 'auto';
      }
    },
    async saveEdit() {
      this.syncBodyFromEditor();
      const text = (this.body || '').trim();
      if (!this.editingId || !this.apiEditUrl) return;
      const kept = this.editingAttachments || [];
      const pending = this.pendingFiles || [];
      if (!text && !kept.length && !pending.length) return;
      const msg = this.messages.find(m => m.id === this.editingId);
      const originalIds = ((msg && msg.attachments) || []).map(a => a.id);
      const keptIds = new Set(kept.map(a => a.id));
      this.busy = true;
      const fd = new FormData();
      fd.append('message_id', this.editingId);
      fd.append('body', text);
      originalIds.forEach((id) => {
        if (!keptIds.has(id)) fd.append('remove_attachment_ids', id);
      });
      pending.forEach((item) => {
        if (item && item.file) fd.append('files', item.file, item.name || item.file.name);
      });
      try {
        const r = await fetch(this.apiEditUrl, {
          method: 'POST',
          headers: { 'X-CSRFToken': this.csrfToken },
          body: fd,
        });
        const data = await r.json();
        if (!data.ok) alert(data.error || 'Erreur');
        else {
          const idx = this.messages.findIndex(m => m.id === data.message.id);
          if (idx >= 0) {
            const prev = this.messages[idx];
            this.messages.splice(idx, 1, Object.assign({}, prev, data.message));
          }
          this._resetComposer();
          this.$nextTick(() => this.measureComposer());
        }
      } catch (e) { alert('Échec de la modification'); }
      this.busy = false;
    },
    async send() {
      this.syncBodyFromEditor();
      if (this.editingId) {
        await this.saveEdit();
        return;
      }
      const text = (this.body || '').trim();
      const pending = this.pendingFiles || [];
      if (!text && !pending.length) return;
      this.busy = true;
      this.menuOpen = false;
      this.emojiOpen = false;
      this.closeMention();
      const replyId = this.replyTo && this.replyTo.id ? this.replyTo.id : null;
      // Toujours HTTP : le message est ajouté dès la réponse (ingestMessage).
      // Le WebSocket ne sert qu’à recevoir les messages des autres en live.
      // (L’ancien envoi WS vidait le composeur sans afficher le message tant
      // que l’écho channel-layer n’arrivait pas — souvent jamais.)
      const fd = new FormData();
      fd.append('body', text);
      if (replyId) fd.append('reply_to_id', replyId);
      pending.forEach((item) => {
        if (item && item.file) fd.append('files', item.file, item.name || item.file.name);
      });
      try {
        const r = await fetch(this.apiSendUrl, {
          method: 'POST',
          headers: { 'X-CSRFToken': this.csrfToken },
          body: fd,
        });
        const data = await r.json();
        if (!data.ok) alert(data.error || 'Erreur');
        else {
          this._resetComposer();
          if (data.message) this.ingestMessage(data.message);
          this.$nextTick(() => { this.measureComposer(); this.scrollBottom(true); });
        }
      } catch (e) { alert('Échec d’envoi'); }
      this.busy = false;
    },
  };
}
