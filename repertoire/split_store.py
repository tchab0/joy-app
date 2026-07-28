"""Stockage temporaire des PDF source pour l’éditeur de découpe graphique."""

from __future__ import annotations

import hashlib
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.utils.text import slugify

_TOKEN_RE = re.compile(r"^[a-f0-9-]{36}$")
_SESSION_KEY = "repertoire_split_{piece_id}"
_MAX_UPLOAD_BYTES = 80 * 1024 * 1024  # 80 Mo
_ID_RE = re.compile(r"^[a-f0-9]{16,64}$")


@dataclass
class SplitSource:
    token: str
    page_count: int
    source_name: str

    @property
    def pdf_path(self) -> Path:
        return _dir_for(self.token) / "source.pdf"

    def thumb_path(self, page: int) -> Path:
        return _dir_for(self.token) / "thumbs" / f"{page}.jpg"

    def invalidate_thumb(self, page: int) -> None:
        thumb = self.thumb_path(page)
        if thumb.is_file():
            thumb.unlink(missing_ok=True)


@dataclass
class ServerPdfCandidate:
    """PDF déjà présent sous media/repertoire (inbox / needs_split)."""

    id: str
    name: str
    rel_path: str
    size: int
    where: str  # inbox | needs_split

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "rel_path": self.rel_path,
            "size": self.size,
            "where": self.where,
            "size_label": _human_size(self.size),
        }


def _root() -> Path:
    root = Path(settings.MEDIA_ROOT) / "repertoire" / "_split"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _dir_for(token: str) -> Path:
    if not _TOKEN_RE.match(token):
        raise ValueError("Jeton invalide.")
    return _root() / token


def _repertoire_root() -> Path:
    return (Path(settings.MEDIA_ROOT) / "repertoire").resolve()


def allowed_scan_roots() -> list[tuple[str, Path]]:
    base = _repertoire_root()
    return [
        ("inbox", base / "_inbox"),
        ("needs_split", base / "_sorted" / "_needs_split"),
    ]


def session_key(piece_id: int) -> str:
    return _SESSION_KEY.format(piece_id=piece_id)


def load_from_session(session, piece_id: int) -> SplitSource | None:
    raw = session.get(session_key(piece_id))
    if not isinstance(raw, dict):
        return None
    token = raw.get("token") or ""
    try:
        page_count = int(raw.get("page_count") or 0)
    except (TypeError, ValueError):
        return None
    source_name = (raw.get("source_name") or "").strip() or "source.pdf"
    if not _TOKEN_RE.match(token) or page_count < 1:
        return None
    src = SplitSource(token=token, page_count=page_count, source_name=source_name)
    if not src.pdf_path.is_file():
        return None
    return src


def save_to_session(session, piece_id: int, source: SplitSource) -> None:
    session[session_key(piece_id)] = {
        "token": source.token,
        "page_count": source.page_count,
        "source_name": source.source_name,
    }
    session.modified = True


def clear_session(session, piece_id: int) -> None:
    key = session_key(piece_id)
    raw = session.pop(key, None)
    session.modified = True
    if isinstance(raw, dict):
        token = raw.get("token") or ""
        if _TOKEN_RE.match(token):
            delete_token(token)


def delete_token(token: str) -> None:
    try:
        d = _dir_for(token)
    except ValueError:
        return
    if d.is_dir():
        shutil.rmtree(d, ignore_errors=True)


def _human_size(n: int) -> str:
    if n < 1024:
        return f"{n} o"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} Ko"
    return f"{n / (1024 * 1024):.1f} Mo"


def _is_pdf_file(path: Path) -> bool:
    if not path.is_file():
        return False
    suf = path.suffix.lower()
    if suf == ".pdf":
        return True
    if suf in {".docx", ".doc", ".txt", ".mp3", ".zip", ".jpg", ".jpeg", ".png"}:
        return False
    try:
        with path.open("rb") as fh:
            return fh.read(5) == b"%PDF-"
    except OSError:
        return False


def _match_tokens(piece_title: str, piece_slug: str) -> list[str]:
    tokens: set[str] = set()
    for raw in (piece_title or "", piece_slug or ""):
        s = slugify(raw) or ""
        if s:
            tokens.add(s)
            tokens.add(s.replace("-", "_"))
            tokens.add(s.replace("-", ""))
        words = [w for w in re.split(r"[\s_\-]+", (raw or "").lower()) if len(w) >= 4]
        for w in words:
            if w in {"with", "from", "love", "part"}:
                continue
            tokens.add(w)
    return [t for t in tokens if t]


def _path_matches(path: Path, tokens: list[str]) -> bool:
    hay = (slugify(path.stem) + " " + slugify(path.name)).replace("-", "")
    hay_u = hay.replace("_", "")
    name_l = path.name.lower()
    stem_l = path.stem.lower()
    for t in tokens:
        compact = t.replace("-", "").replace("_", "")
        if compact and compact in hay_u:
            return True
        if t in name_l or t in stem_l:
            return True
    return False


def _candidate_id(path: Path) -> str:
    rel = str(path.resolve())
    return hashlib.sha256(rel.encode("utf-8")).hexdigest()[:24]


def list_server_candidates(*, title: str, slug: str) -> list[ServerPdfCandidate]:
    """PDF serveur liés au morceau (inbox + _needs_split)."""
    tokens = _match_tokens(title, slug)
    if not tokens:
        return []
    found: list[ServerPdfCandidate] = []
    seen: set[str] = set()
    for where, root in allowed_scan_roots():
        if not root.is_dir():
            continue
        try:
            paths = list(root.rglob("*"))
        except OSError:
            continue
        for path in paths:
            if not _is_pdf_file(path):
                continue
            if not _path_matches(path, tokens):
                continue
            try:
                resolved = path.resolve()
                size = path.stat().st_size
            except OSError:
                continue
            if size < 1024 or size > _MAX_UPLOAD_BYTES:
                continue
            cid = _candidate_id(resolved)
            if cid in seen:
                continue
            seen.add(cid)
            try:
                rel = str(resolved.relative_to(_repertoire_root()))
            except ValueError:
                continue
            found.append(
                ServerPdfCandidate(
                    id=cid,
                    name=path.name,
                    rel_path=rel,
                    size=size,
                    where=where,
                )
            )
    found.sort(key=lambda c: (-c.size, c.name.lower()))
    return found


def resolve_candidate(candidate_id: str) -> Path | None:
    if not _ID_RE.match(candidate_id):
        return None
    for _where, root in allowed_scan_roots():
        if not root.is_dir():
            continue
        try:
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                try:
                    resolved = path.resolve()
                except OSError:
                    continue
                if _candidate_id(resolved) != candidate_id:
                    continue
                if not _is_pdf_file(resolved):
                    return None
                try:
                    resolved.relative_to(_repertoire_root())
                except ValueError:
                    return None
                return resolved
        except OSError:
            continue
    return None


def _finalize_source(pdf_path: Path, source_name: str) -> SplitSource:
    from repertoire.pdf_utils import pdf_page_count

    try:
        page_count = pdf_page_count(pdf_path)
    except Exception:
        delete_token(pdf_path.parent.name)
        raise ValueError("PDF illisible.") from None
    if page_count < 1:
        delete_token(pdf_path.parent.name)
        raise ValueError("PDF sans pages.")
    name = source_name.strip() or "source.pdf"
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"
    return SplitSource(
        token=pdf_path.parent.name,
        page_count=page_count,
        source_name=name[:255],
    )


def create_from_upload(file_obj, *, source_name: str = "") -> SplitSource:
    """Écrit le PDF uploadé, calcule le nombre de pages, retourne le source."""
    name = (source_name or getattr(file_obj, "name", "") or "source.pdf").strip()
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf" if name else "source.pdf"

    size = getattr(file_obj, "size", None)
    if size is not None and size > _MAX_UPLOAD_BYTES:
        raise ValueError("PDF trop volumineux (max 80 Mo).")

    token = str(uuid.uuid4())
    dest_dir = _dir_for(token)
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / "thumbs").mkdir(exist_ok=True)
    pdf_path = dest_dir / "source.pdf"

    written = 0
    with pdf_path.open("wb") as out:
        for chunk in file_obj.chunks():
            written += len(chunk)
            if written > _MAX_UPLOAD_BYTES:
                out.close()
                delete_token(token)
                raise ValueError("PDF trop volumineux (max 80 Mo).")
            out.write(chunk)

    return _finalize_source(pdf_path, name)


def create_from_server_file(path: Path) -> SplitSource:
    """Copie un PDF serveur autorisé dans le store de session."""
    resolved = path.resolve()
    try:
        resolved.relative_to(_repertoire_root())
    except ValueError as exc:
        raise ValueError("Fichier hors zone autorisée.") from exc
    if not _is_pdf_file(resolved):
        raise ValueError("Ce fichier n’est pas un PDF.")
    size = resolved.stat().st_size
    if size > _MAX_UPLOAD_BYTES:
        raise ValueError("PDF trop volumineux (max 80 Mo).")

    token = str(uuid.uuid4())
    dest_dir = _dir_for(token)
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / "thumbs").mkdir(exist_ok=True)
    pdf_path = dest_dir / "source.pdf"
    shutil.copy2(resolved, pdf_path)
    name = resolved.name
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"
    return _finalize_source(pdf_path, name)
