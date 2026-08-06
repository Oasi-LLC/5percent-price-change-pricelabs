"""Pluggable persistence for adjustment ledger and distributed run locks."""

import base64
import json
import logging
import os
import time
import uuid
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = PROJECT_ROOT / "data" / "adjustment_runs"
LEDGER_FILE = LEDGER_DIR / "ledger.json"

LEDGER_VERSION = 1
LEDGER_RETENTION_DAYS = 14
RUN_LOCK_MAX_AGE_SECONDS = 3 * 60 * 60
GITHUB_SAVE_MAX_RETRIES = 5
DEFAULT_GITHUB_REPO = "Oasi-LLC/5percent-price-change-pricelabs"
DEFAULT_GITHUB_PATH = "data/adjustment_runs/manifest.json"
LEGACY_GITHUB_LEDGER_PATH = "data/adjustment_runs/ledger.json"
GITHUB_RECORDS_DIR = "data/adjustment_runs/records"
GITHUB_CONTENTS_API_LIMIT_BYTES = 1_000_000
DEFAULT_GITHUB_REF = "automation-state"


class LedgerResponseError(RuntimeError):
    """GitHub ledger API returned an empty or non-JSON response."""


class LedgerPayloadError(RuntimeError):
    """Ledger file content is missing, corrupt, or too large for GitHub Contents API."""


def _decode_github_json(response: requests.Response, context: str) -> Dict[str, Any]:
    text = (response.text or "").strip()
    if not text:
        raise LedgerResponseError(
            f"Empty response body from GitHub ({context}), "
            f"status={response.status_code}"
        )
    try:
        return response.json()
    except json.JSONDecodeError as e:
        preview = text[:200]
        raise LedgerResponseError(
            f"Invalid JSON from GitHub ({context}), "
            f"status={response.status_code}: {e}; body={preview!r}"
        ) from e


def empty_payload() -> Dict[str, Any]:
    return {"version": LEDGER_VERSION, "format": "sharded_v1", "lock": None, "records": []}


def empty_manifest() -> Dict[str, Any]:
    return {"version": LEDGER_VERSION, "format": "sharded_v1", "lock": None}


def _safe_listing_filename(listing_id: str) -> str:
    return listing_id.replace("/", "_")


def listing_shard_path(listing_id: str) -> str:
    return f"{GITHUB_RECORDS_DIR}/{_safe_listing_filename(listing_id)}.json"


def _decode_github_file_content(data: Dict[str, Any], path: str) -> Any:
    size = int(data.get("size") or 0)
    content_b64 = (data.get("content") or "").strip()
    if not content_b64:
        if size > GITHUB_CONTENTS_API_LIMIT_BYTES:
            raise LedgerPayloadError(
                f"GitHub file '{path}' is {size:,} bytes; the Contents API JSON "
                f"response omits file bodies over "
                f"{GITHUB_CONTENTS_API_LIMIT_BYTES // 1_000_000} MB."
            )
        raise LedgerPayloadError(
            f"GitHub file '{path}' has no readable content (reported size={size:,} bytes)."
        )
    try:
        decoded = base64.b64decode(content_b64).decode("utf-8")
        return json.loads(decoded)
    except json.JSONDecodeError as e:
        raise LedgerPayloadError(
            f"Could not parse JSON in GitHub file '{path}': {e}"
        ) from e


def prune_records(records: List[Dict]) -> List[Dict]:
    cutoff = date.today() - timedelta(days=LEDGER_RETENTION_DAYS)
    kept = []
    for item in records:
        if item.get("record_type") == "anchor":
            kept.append(item)
            continue
        run_day = item.get("run_day", "")
        try:
            if datetime.strptime(run_day, "%Y-%m-%d").date() >= cutoff:
                kept.append(item)
        except ValueError:
            continue
    return kept


def _lock_is_stale(lock: Optional[Dict]) -> bool:
    if not lock:
        return True
    started = lock.get("started_at", "")
    try:
        started_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
        if started_dt.tzinfo:
            started_dt = started_dt.replace(tzinfo=None)
        age = (datetime.utcnow() - started_dt).total_seconds()
        return age > RUN_LOCK_MAX_AGE_SECONDS
    except (ValueError, TypeError):
        return True


class LedgerStore(ABC):
    @property
    @abstractmethod
    def backend_name(self) -> str:
        pass

    @abstractmethod
    def read(self) -> Tuple[Dict[str, Any], Optional[str]]:
        """Return (payload, version_token). version_token is used for conditional writes."""
        ...

    @abstractmethod
    def write(self, payload: Dict[str, Any], version_token: Optional[str] = None) -> None:
        ...


class FileLedgerStore(LedgerStore):
    """Local file store for Streamlit and local CLI runs."""

    def __init__(self, path: Path = LEDGER_FILE):
        self.path = path

    @property
    def backend_name(self) -> str:
        return f"file:{self.path}"

    def read(self) -> Tuple[Dict[str, Any], Optional[str]]:
        if not self.path.exists():
            return empty_payload(), None
        try:
            with open(self.path) as f:
                data = json.load(f) or {}
            if "records" not in data:
                data = empty_payload()
            if "lock" not in data:
                data["lock"] = None
            return data, "file"
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Could not read local ledger (%s); starting fresh", e)
            return empty_payload(), None

    def write(self, payload: Dict[str, Any], version_token: Optional[str] = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(payload, f, indent=2)


class GitHubLedgerStore(LedgerStore):
    """
    Sharded GitHub Contents API store for cloud agents.

    Lock + manifest live in a small manifest file; per-listing idempotency records
    live in separate shard files so the ledger can grow past GitHub's 1 MB Contents
    API read limit.
    """

    is_sharded = True

    def __init__(
        self,
        repo: str,
        path: str = DEFAULT_GITHUB_PATH,
        ref: str = DEFAULT_GITHUB_REF,
        token: Optional[str] = None,
    ):
        self.repo = repo
        self.manifest_path = path.lstrip("/")
        self.ref = ref
        self.token = token or os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
        if not self.token:
            raise ValueError(
                "GITHUB_TOKEN (or GH_TOKEN) is required for GitHub ledger backend"
            )
        self._ref_ensured = False
        self._shard_shas: Dict[str, Optional[str]] = {}

    @property
    def backend_name(self) -> str:
        return f"github:{self.repo}@{self.ref}:{self.manifest_path}"

    def _headers(self, *, raw: bool = False) -> Dict[str, str]:
        accept = (
            "application/vnd.github.raw+json"
            if raw
            else "application/vnd.github+json"
        )
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _contents_url(self, path: str) -> str:
        return f"https://api.github.com/repos/{self.repo}/contents/{path}"

    def _ensure_ref_exists(self) -> None:
        if self._ref_ensured:
            return
        ref_url = f"https://api.github.com/repos/{self.repo}/git/ref/heads/{self.ref}"
        response = requests.get(ref_url, headers=self._headers(), timeout=30)
        if response.status_code == 200:
            self._ref_ensured = True
            return
        if response.status_code != 404:
            if response.status_code == 403:
                raise PermissionError(
                    "GitHub token cannot access git refs for "
                    f"{self.repo}. Authorize the fine-grained PAT for Oasi-LLC SSO "
                    "(github.com/settings/tokens → Configure SSO), or create branch "
                    f"'{self.ref}' manually from main in the GitHub UI."
                )
            response.raise_for_status()

        repo_resp = requests.get(
            f"https://api.github.com/repos/{self.repo}",
            headers=self._headers(),
            timeout=30,
        )
        repo_resp.raise_for_status()
        default_branch = _decode_github_json(repo_resp, "repo metadata")["default_branch"]

        base_resp = requests.get(
            f"https://api.github.com/repos/{self.repo}/git/ref/heads/{default_branch}",
            headers=self._headers(),
            timeout=30,
        )
        base_resp.raise_for_status()
        base_sha = _decode_github_json(base_resp, "default branch ref")["object"]["sha"]

        create_resp = requests.post(
            f"https://api.github.com/repos/{self.repo}/git/refs",
            headers=self._headers(),
            json={"ref": f"refs/heads/{self.ref}", "sha": base_sha},
            timeout=30,
        )
        if create_resp.status_code not in (201, 422):
            if create_resp.status_code == 403:
                raise PermissionError(
                    "GitHub token cannot create branch "
                    f"'{self.ref}' on {self.repo}. Authorize the fine-grained PAT "
                    "for Oasi-LLC SSO (github.com/settings/tokens → Configure SSO), "
                    f"or create branch '{self.ref}' manually from main in the GitHub UI."
                )
            create_resp.raise_for_status()
        self._ref_ensured = True
        logger.info("Created GitHub ledger branch %s on %s", self.ref, self.repo)

    def _read_file(self, path: str) -> Tuple[Optional[Any], Optional[str]]:
        self._ensure_ref_exists()
        response = requests.get(
            self._contents_url(path),
            headers=self._headers(),
            params={"ref": self.ref},
            timeout=30,
        )
        if response.status_code == 404:
            return None, None
        response.raise_for_status()
        data = _decode_github_json(response, f"read {path}")
        sha = data.get("sha")
        size = int(data.get("size") or 0)
        content_b64 = (data.get("content") or "").strip()
        if not content_b64 and size > GITHUB_CONTENTS_API_LIMIT_BYTES:
            raw_response = requests.get(
                self._contents_url(path),
                headers=self._headers(raw=True),
                params={"ref": self.ref},
                timeout=60,
            )
            raw_response.raise_for_status()
            try:
                return json.loads(raw_response.text), sha
            except json.JSONDecodeError as e:
                raise LedgerPayloadError(
                    f"Could not parse JSON in GitHub file '{path}': {e}"
                ) from e
        return _decode_github_file_content(data, path), sha

    def _write_file(
        self,
        path: str,
        payload: Any,
        version_token: Optional[str] = None,
        message: str = "chore: update PriceLabs adjustment ledger",
    ) -> None:
        self._ensure_ref_exists()
        encoded = base64.b64encode(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        ).decode("ascii")
        body: Dict[str, Any] = {
            "message": message,
            "content": encoded,
            "branch": self.ref,
        }
        if version_token:
            body["sha"] = version_token

        last_error: Optional[Exception] = None
        for attempt in range(GITHUB_SAVE_MAX_RETRIES):
            try:
                response = requests.put(
                    self._contents_url(path),
                    headers=self._headers(),
                    json=body,
                    timeout=30,
                )
                if response.status_code == 409:
                    _, fresh_sha = self._read_file(path)
                    body["sha"] = fresh_sha
                    if fresh_sha is None:
                        body.pop("sha", None)
                    if attempt < GITHUB_SAVE_MAX_RETRIES - 1:
                        logger.warning(
                            "GitHub write conflict for %s (attempt %s); retrying",
                            path,
                            attempt + 1,
                        )
                        time.sleep(0.5 * (attempt + 1))
                        continue
                response.raise_for_status()
                return
            except requests.RequestException as e:
                last_error = e
                if attempt < GITHUB_SAVE_MAX_RETRIES - 1:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise
        if last_error:
            raise last_error

    def read_manifest_if_exists(self) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Read sharded manifest only; does not fall back to legacy monolithic ledger."""
        payload, sha = self._read_file(self.manifest_path)
        if payload is None or not isinstance(payload, dict):
            return None, sha
        if "lock" not in payload:
            payload["lock"] = None
        return payload, sha

    def read_manifest(self) -> Tuple[Dict[str, Any], Optional[str]]:
        payload, sha = self.read_manifest_if_exists()
        if payload is not None:
            return payload, sha
        try:
            legacy, legacy_sha = self._read_file(LEGACY_GITHUB_LEDGER_PATH)
        except LedgerPayloadError as e:
            raise LedgerPayloadError(
                f"{e} Run migrate_ledger_shards.py with your local ledger copy."
            ) from e
        if legacy is None:
            return empty_manifest(), None
        if isinstance(legacy, dict) and legacy.get("records"):
            raise LedgerPayloadError(
                f"Legacy ledger file '{LEGACY_GITHUB_LEDGER_PATH}' is still monolithic. "
                "Run migrate_ledger_shards.py before the next automation run."
            )
        manifest = empty_manifest()
        manifest["lock"] = legacy.get("lock") if isinstance(legacy, dict) else None
        return manifest, legacy_sha

    def write_manifest(
        self, payload: Dict[str, Any], version_token: Optional[str] = None
    ) -> None:
        manifest = {
            "version": payload.get("version", LEDGER_VERSION),
            "format": payload.get("format", "sharded_v1"),
            "lock": payload.get("lock"),
        }
        self._write_file(self.manifest_path, manifest, version_token)

    def read_listing_shard(self, listing_id: str) -> Tuple[List[Dict], Optional[str]]:
        payload, sha = self._read_file(listing_shard_path(listing_id))
        self._shard_shas[listing_id] = sha
        if payload is None:
            return [], None
        if isinstance(payload, dict):
            records = payload.get("records", [])
            return records if isinstance(records, list) else [], sha
        if isinstance(payload, list):
            return payload, sha
        return [], sha

    def write_listing_shard(
        self,
        listing_id: str,
        records: List[Dict],
        version_token: Optional[str] = None,
    ) -> None:
        payload = {
            "listing_id": listing_id,
            "records": records,
        }
        self._write_file(
            listing_shard_path(listing_id),
            payload,
            version_token or self._shard_shas.get(listing_id),
            message=f"chore: update ledger shard for listing {listing_id}",
        )

    def read(self) -> Tuple[Dict[str, Any], Optional[str]]:
        manifest, sha = self.read_manifest()
        payload = empty_payload()
        payload["version"] = manifest.get("version", LEDGER_VERSION)
        payload["format"] = manifest.get("format", "sharded_v1")
        payload["lock"] = manifest.get("lock")
        payload["records"] = []
        return payload, sha

    def write(self, payload: Dict[str, Any], version_token: Optional[str] = None) -> None:
        manifest = {
            "version": payload.get("version", LEDGER_VERSION),
            "format": payload.get("format", "sharded_v1"),
            "lock": payload.get("lock"),
        }
        self.write_manifest(manifest, version_token)
        records = payload.get("records", [])
        if not records:
            return
        by_listing: Dict[str, List[Dict]] = {}
        for item in records:
            listing_id = str(item.get("listing_id", ""))
            if listing_id:
                by_listing.setdefault(listing_id, []).append(item)
        for listing_id, listing_records in by_listing.items():
            self.write_listing_shard(listing_id, listing_records)


def resolve_ledger_backend() -> str:
    explicit = (os.getenv("ADJUSTMENT_LEDGER_BACKEND") or "auto").strip().lower()
    if explicit in ("file", "github"):
        return explicit
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    repo = os.getenv("ADJUSTMENT_LEDGER_GITHUB_REPO") or DEFAULT_GITHUB_REPO
    if token and repo:
        return "github"
    return "file"


def get_ledger_store() -> LedgerStore:
    backend = resolve_ledger_backend()
    if backend == "github":
        repo = os.getenv("ADJUSTMENT_LEDGER_GITHUB_REPO") or DEFAULT_GITHUB_REPO
        path = os.getenv("ADJUSTMENT_LEDGER_GITHUB_PATH") or DEFAULT_GITHUB_PATH
        ref = os.getenv("ADJUSTMENT_LEDGER_GITHUB_REF") or DEFAULT_GITHUB_REF
        store = GitHubLedgerStore(repo=repo, path=path, ref=ref)
        logger.info("Using GitHub adjustment ledger (%s)", store.backend_name)
        return store

    store = FileLedgerStore()
    logger.info("Using local file adjustment ledger (%s)", store.backend_name)
    return store


class LedgerRepository:
    """Read/modify/save ledger payload with optional distributed lock."""

    def __init__(self, store: Optional[LedgerStore] = None):
        self.store = store or get_ledger_store()
        self._payload = empty_payload()
        self._version_token: Optional[str] = None
        self._records: Dict[str, Dict] = {}
        self._run_id: Optional[str] = None
        self._loaded_listings: set = set()
        self._dirty_listings: set = set()
        self.reload()

    @property
    def backend_name(self) -> str:
        return self.store.backend_name

    @property
    def _is_sharded(self) -> bool:
        return getattr(self.store, "is_sharded", False)

    def _load_listing_records(self, listing_id: str) -> None:
        if not self._is_sharded or listing_id in self._loaded_listings:
            return
        records, _ = self.store.read_listing_shard(listing_id)
        for item in records:
            if item.get("key"):
                self._records[item["key"]] = item
        self._loaded_listings.add(listing_id)

    def reload(self, *, strict: bool = True, manifest_only: bool = False) -> None:
        try:
            self._payload, self._version_token = self.store.read()
        except (LedgerResponseError, LedgerPayloadError):
            if strict:
                raise
            logger.warning(
                "Could not reload ledger from %s; keeping in-memory state",
                self.backend_name,
            )
            return
        if self._is_sharded and manifest_only:
            return
        if self._is_sharded:
            self._records = {}
            self._loaded_listings = set()
            self._dirty_listings = set()
            return
        self._records = {
            item["key"]: item
            for item in self._payload.get("records", [])
            if item.get("key")
        }

    def get_record(
        self, listing_id: str, override_date: str, direction: str, run_day: str
    ) -> Optional[Dict]:
        self._load_listing_records(listing_id)
        key = f"{listing_id}|{override_date}|{direction}|{run_day}"
        return self._records.get(key)

    def get_anchor(self, listing_id: str, override_date: str) -> Optional[Dict]:
        self._load_listing_records(listing_id)
        key = f"{listing_id}|{override_date}|anchor"
        return self._records.get(key)

    def set_anchor(
        self,
        listing_id: str,
        override_date: str,
        reference_price: int,
        state: str,
    ) -> None:
        key = f"{listing_id}|{override_date}|anchor"
        self._records[key] = {
            "key": key,
            "record_type": "anchor",
            "listing_id": listing_id,
            "date": override_date,
            "reference_price": int(reference_price),
            "state": state,
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }
        if self._is_sharded:
            self._loaded_listings.add(listing_id)
            self._dirty_listings.add(listing_id)

    def record_verified(
        self,
        listing_id: str,
        override_date: str,
        direction: str,
        run_day: str,
        price_before: int,
        price_after: int,
    ) -> None:
        key = f"{listing_id}|{override_date}|{direction}|{run_day}"
        self._records[key] = {
            "key": key,
            "listing_id": listing_id,
            "date": override_date,
            "direction": direction,
            "run_day": run_day,
            "price_before": price_before,
            "price_after": price_after,
            "verified": True,
            "recorded_at": datetime.utcnow().isoformat() + "Z",
        }
        if self._is_sharded:
            self._loaded_listings.add(listing_id)
            self._dirty_listings.add(listing_id)

    def save(self) -> None:
        pruned = prune_records(list(self._records.values()))
        self._records = {item["key"]: item for item in pruned}
        self._payload["version"] = LEDGER_VERSION
        if self._is_sharded:
            self._payload["format"] = "sharded_v1"
            self._payload.pop("records", None)
            self.store.write_manifest(self._payload, self._version_token)
            by_listing: Dict[str, List[Dict]] = {}
            for item in pruned:
                listing_id = str(item.get("listing_id", ""))
                if listing_id:
                    by_listing.setdefault(listing_id, []).append(item)
            listings_to_write = self._dirty_listings | set(by_listing)
            for listing_id in listings_to_write:
                listing_records = [
                    item for item in pruned if str(item.get("listing_id")) == listing_id
                ]
                self.store.write_listing_shard(listing_id, listing_records)
            self._dirty_listings = set()
        else:
            self._payload["records"] = pruned
            self.store.write(self._payload, self._version_token)
        try:
            self.reload(manifest_only=self._is_sharded)
        except (LedgerResponseError, LedgerPayloadError) as e:
            logger.warning(
                "Ledger saved to %s but reload failed (%s); "
                "in-memory records are still valid for this run",
                self.backend_name,
                e,
            )

    def acquire_lock(self, direction: str) -> None:
        from pricelabs_tool.run_guard import AdjustmentRunInProgressError

        self._run_id = str(uuid.uuid4())
        for attempt in range(GITHUB_SAVE_MAX_RETRIES):
            self.reload(manifest_only=self._is_sharded)
            lock = self._payload.get("lock")
            if lock and not _lock_is_stale(lock):
                if lock.get("run_id") == self._run_id:
                    return
                raise AdjustmentRunInProgressError(
                    f"Another adjustment run is in progress "
                    f"(direction={lock.get('direction', 'unknown')}, "
                    f"started={lock.get('started_at', 'unknown')}, "
                    f"backend={self.backend_name}). "
                    f"Wait for it to finish before starting a new run."
                )

            self._payload["lock"] = {
                "run_id": self._run_id,
                "direction": direction,
                "started_at": datetime.utcnow().isoformat() + "Z",
                "backend": self.store.backend_name,
            }
            try:
                if self._is_sharded:
                    self.store.write_manifest(self._payload, self._version_token)
                else:
                    self.store.write(self._payload, self._version_token)
                self.reload(manifest_only=self._is_sharded)
                return
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 409:
                    if attempt < GITHUB_SAVE_MAX_RETRIES - 1:
                        time.sleep(0.5 * (attempt + 1))
                        continue
                raise

    def release_lock(self) -> None:
        if not self._run_id:
            return
        run_id = self._run_id
        try:
            for attempt in range(GITHUB_SAVE_MAX_RETRIES):
                try:
                    self.reload(strict=False, manifest_only=self._is_sharded)
                except (LedgerResponseError, LedgerPayloadError) as e:
                    logger.warning(
                        "Could not reload ledger while releasing lock (attempt %s): %s",
                        attempt + 1,
                        e,
                    )
                    if attempt < GITHUB_SAVE_MAX_RETRIES - 1:
                        time.sleep(0.5 * (attempt + 1))
                        continue
                    return

                lock = self._payload.get("lock")
                if lock and lock.get("run_id") != run_id:
                    return
                self._payload["lock"] = None
                try:
                    if self._is_sharded:
                        self.store.write_manifest(self._payload, self._version_token)
                    else:
                        self.store.write(self._payload, self._version_token)
                    self.reload(strict=False, manifest_only=self._is_sharded)
                    return
                except requests.HTTPError as e:
                    if e.response is not None and e.response.status_code == 409:
                        if attempt < GITHUB_SAVE_MAX_RETRIES - 1:
                            time.sleep(0.5 * (attempt + 1))
                            continue
                    logger.warning("Could not release ledger lock cleanly: %s", e)
                    return
                except (LedgerResponseError, LedgerPayloadError) as e:
                    logger.warning(
                        "Ledger lock cleared on %s but reload after write failed: %s",
                        self.backend_name,
                        e,
                    )
                    return
        finally:
            if self._run_id == run_id:
                self._run_id = None
