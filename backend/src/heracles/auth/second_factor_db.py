"""Second-factor registrations stored in the application database."""

from __future__ import annotations

from heracles.auth.second_factor import WebAuthnCredential
from heracles.ldap import dn as dnlib
from heracles.storage import Database

COMPONENT = "second_factor"

#: Append only; never edit a released migration.
MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE second_factor_totp (
        user_key TEXT PRIMARY KEY,
        secret TEXT,
        last_step INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE second_factor_recovery (
        user_key TEXT NOT NULL,
        digest TEXT NOT NULL,
        PRIMARY KEY (user_key, digest)
    );
    CREATE TABLE second_factor_webauthn (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_key TEXT NOT NULL,
        credential_id BLOB NOT NULL,
        public_key BLOB NOT NULL,
        sign_count INTEGER NOT NULL,
        label TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (user_key, credential_id)
    );
    """,
)


class SqliteSecondFactorStore:
    """:class:`~heracles.auth.second_factor.SecondFactorStore` on the application database.

    Users are keyed by their normalised DN, like the in-memory store.
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        db.migrate(COMPONENT, MIGRATIONS)

    @staticmethod
    def _k(user_dn: str) -> str:
        return dnlib.normalize(user_dn)

    # -- TOTP ----------------------------------------------------------------------------------
    def totp_secret(self, user_dn: str) -> str | None:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT secret FROM second_factor_totp WHERE user_key = ?", (self._k(user_dn),)
            ).fetchone()
        return None if row is None else row["secret"]

    def set_totp_secret(self, user_dn: str, secret: str | None) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO second_factor_totp (user_key, secret) VALUES (?, ?)"
                " ON CONFLICT (user_key) DO UPDATE SET secret = excluded.secret",
                (self._k(user_dn), secret),
            )

    def last_totp_step(self, user_dn: str) -> int:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT last_step FROM second_factor_totp WHERE user_key = ?",
                (self._k(user_dn),),
            ).fetchone()
        return 0 if row is None else int(row["last_step"])

    def set_last_totp_step(self, user_dn: str, step: int) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO second_factor_totp (user_key, last_step) VALUES (?, ?)"
                " ON CONFLICT (user_key) DO UPDATE SET last_step = excluded.last_step",
                (self._k(user_dn), step),
            )

    # -- recovery codes ------------------------------------------------------------------------
    def recovery_hashes(self, user_dn: str) -> list[str]:
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT digest FROM second_factor_recovery WHERE user_key = ? ORDER BY rowid",
                (self._k(user_dn),),
            ).fetchall()
        return [r["digest"] for r in rows]

    def set_recovery_hashes(self, user_dn: str, hashes: list[str]) -> None:
        key = self._k(user_dn)
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM second_factor_recovery WHERE user_key = ?", (key,))
            conn.executemany(
                "INSERT OR IGNORE INTO second_factor_recovery (user_key, digest) VALUES (?, ?)",
                [(key, h) for h in hashes],
            )

    def consume_recovery_hash(self, user_dn: str, digest: str) -> bool:
        with self._db.transaction() as conn:
            cur = conn.execute(
                "DELETE FROM second_factor_recovery WHERE user_key = ? AND digest = ?",
                (self._k(user_dn), digest),
            )
            return cur.rowcount == 1

    # -- WebAuthn ------------------------------------------------------------------------------
    def webauthn_credentials(self, user_dn: str) -> list[WebAuthnCredential]:
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT credential_id, public_key, sign_count, label FROM second_factor_webauthn"
                " WHERE user_key = ? ORDER BY id",
                (self._k(user_dn),),
            ).fetchall()
        return [
            WebAuthnCredential(
                bytes(r["credential_id"]), bytes(r["public_key"]), int(r["sign_count"]), r["label"]
            )
            for r in rows
        ]

    def add_webauthn_credential(self, user_dn: str, credential: WebAuthnCredential) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO second_factor_webauthn"
                " (user_key, credential_id, public_key, sign_count, label)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    self._k(user_dn),
                    credential.credential_id,
                    credential.public_key,
                    credential.sign_count,
                    credential.label,
                ),
            )

    def update_sign_count(self, user_dn: str, credential_id: bytes, sign_count: int) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE second_factor_webauthn SET sign_count = ?"
                " WHERE user_key = ? AND credential_id = ?",
                (sign_count, self._k(user_dn), credential_id),
            )

    def remove_webauthn_credential(self, user_dn: str, credential_id: bytes) -> bool:
        with self._db.transaction() as conn:
            cur = conn.execute(
                "DELETE FROM second_factor_webauthn WHERE user_key = ? AND credential_id = ?",
                (self._k(user_dn), credential_id),
            )
            return cur.rowcount == 1

    # -- reset ---------------------------------------------------------------------------------
    def clear_all(self, user_dn: str) -> None:
        key = self._k(user_dn)
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM second_factor_totp WHERE user_key = ?", (key,))
            conn.execute("DELETE FROM second_factor_recovery WHERE user_key = ?", (key,))
            conn.execute("DELETE FROM second_factor_webauthn WHERE user_key = ?", (key,))
