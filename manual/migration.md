# Migrating a legacy directory

Directories written by the older management tool use a different schema (its own object
class and attribute names, an application container with another name, ACL values naming those
attributes). `heracles migrate-directory` converts an LDIF export of such a directory offline;
the server is then rebuilt from the converted file. Nothing is changed in the old directory, which
remains the way back.

## 1. Rehearse

```sh
slapcat -b dc=example,dc=org > old.ldif                    # or the server's own export
heracles migrate-directory old.ldif --dry-run              # what the conversion would do
heracles migrate-directory old.ldif --dry-run --json > report.json
```

The report lists the entries read, converted (changed) and untouched, the names renamed, the
auxiliary classes added, and everything the converter cannot explain:

* **unknown legacy names**: object classes, attributes and names stored inside values that carry
  a legacy prefix but are not in the rename table, grouped by kind with a count and sample DNs.
  They come from extensions the table does not cover; report them (with the samples, not the
  data) so the table can be extended, or remove the data if it is no longer used;
* **unreadable ACL values**: assignments or role templates that do not parse;
* values dropped because they do not fit their syntax (a boolean that is not `TRUE`/`FALSE`, ...).

The exit status is `0` when the report is clean (nothing unexplained) and `1` otherwise. Repeat
until it is clean; `--report renames.csv` writes every old → new name pair for the authors of
scripts using API v1.

## 2. Convert

```sh
heracles migrate-directory old.ldif new.ldif --report renames.csv
```

It refuses to write while errors remain (`--force` writes anyway). `new.ldif` holds password
hashes: it is created readable by its owner only.

## 3. Check before the cut-over

```sh
heracles migrate-check --ldif new.ldif
heracles migrate-check --ldif new.ldif --export-rights triples.csv expected.csv
```

* Without options, `migrate-check` runs the directory health checks on the converted tree.
* `--export-rights TRIPLES OUT` computes the rights of each `subject,object,key` row of TRIPLES
  (for example `"uid=ann,ou=people,dc=example,dc=org","ou=sales,dc=example,dc=org",user/user`)
  and writes them with the rights found. Review `OUT` against what people could do in the old
  console: it becomes the expectation of step 5.

## 4. Cut over

1. Announce a freeze of the old console; take the final export and convert it (steps 1–2).
2. On a new server, load the standard schemas, the schemas of the plugins you use and the Heracles
   schema ([Directory servers](servers.md)), then import `new.ldif` (`slapadd -l new.ldif`, or
   `ldapadd`).
3. Configure Heracles against it (`heracles init`, or the setup wizard) and start it.

## 5. Check after the cut-over

```sh
heracles migrate-check --config heracles.yaml --logins logins.csv --rights expected.csv
```

* `--logins` is a CSV of `uid,password` (or `dn,password`) for a sample of accounts, such as
  test accounts kept for the purpose; each must sign in against the new server.
* `--rights` compares the rights of every row of `expected.csv` (`subject,object,key,expected`).
* `--json` gives the result in machine-readable form. The exit status is `1` when a health check
  reports an error, a login fails or a right differs.

## Rolling back

Until the new server takes writes, rolling back is switching back to the old one. After that,
restore the pre-migration backup: the old directory's own backup, and `heracles backup` of the new
setup if you need to keep what changed since ([Backup and restore](backup.md)).
