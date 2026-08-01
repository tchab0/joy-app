/**
 * Barre de formatage markdown (style chat) pour les textareas feuille de route.
 * Actions : gras, italique, lien, liste, citation.
 */
(function () {
  function wrapSelection(ta, before, after, placeholder) {
    const start = ta.selectionStart ?? 0;
    const end = ta.selectionEnd ?? 0;
    const value = ta.value;
    const selected = value.slice(start, end) || placeholder || "";
    const next = value.slice(0, start) + before + selected + after + value.slice(end);
    ta.value = next;
    const caret = start + before.length + selected.length;
    ta.focus();
    ta.setSelectionRange(
      start + before.length,
      start + before.length + selected.length
    );
    if (!value.slice(start, end) && placeholder) {
      ta.setSelectionRange(start + before.length, caret);
    }
  }

  function prefixLines(ta, prefix) {
    const start = ta.selectionStart ?? 0;
    const end = ta.selectionEnd ?? 0;
    const value = ta.value;
    const lineStart = value.lastIndexOf("\n", Math.max(0, start - 1)) + 1;
    let lineEnd = value.indexOf("\n", end);
    if (lineEnd < 0) lineEnd = value.length;
    const block = value.slice(lineStart, lineEnd);
    const lines = block.split("\n");
    const toggled = lines.map(function (line) {
      if (!line.trim()) return line;
      if (line.indexOf(prefix) === 0) return line.slice(prefix.length);
      return prefix + line.replace(/^[-*•]\s+/, "").replace(/^>\s?/, "");
    });
    const next = value.slice(0, lineStart) + toggled.join("\n") + value.slice(lineEnd);
    ta.value = next;
    ta.focus();
    ta.setSelectionRange(lineStart, lineStart + toggled.join("\n").length);
  }

  function onAction(ta, action) {
    if (action === "bold") {
      wrapSelection(ta, "**", "**", "gras");
      return;
    }
    if (action === "italic") {
      wrapSelection(ta, "_", "_", "italique");
      return;
    }
    if (action === "link") {
      const start = ta.selectionStart ?? 0;
      const end = ta.selectionEnd ?? 0;
      const selected = ta.value.slice(start, end) || "lien";
      const url = window.prompt("URL du lien (https://…)", "https://");
      if (!url) return;
      const safe = String(url).trim();
      if (!/^https?:\/\//i.test(safe)) {
        window.alert("L’URL doit commencer par http:// ou https://");
        return;
      }
      const insert = "[" + selected + "](" + safe + ")";
      ta.value = ta.value.slice(0, start) + insert + ta.value.slice(end);
      ta.focus();
      ta.setSelectionRange(start, start + insert.length);
      return;
    }
    if (action === "list") {
      prefixLines(ta, "- ");
      return;
    }
    if (action === "quote") {
      prefixLines(ta, "> ");
    }
  }

  function bind(root) {
    const ta = root.querySelector("textarea");
    if (!ta) return;
    root.querySelectorAll("[data-md]").forEach(function (btn) {
      btn.addEventListener("mousedown", function (e) {
        e.preventDefault();
      });
      btn.addEventListener("click", function () {
        onAction(ta, btn.getAttribute("data-md"));
      });
    });
  }

  document.querySelectorAll("[data-pl-md]").forEach(bind);
})();
