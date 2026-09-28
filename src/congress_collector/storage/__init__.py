"""Raw-archive storage (Cloudflare R2, bucket `congress-raw`).

`supabase_storage.py` is kept only as the read side of the one-time
migration in `ops/migrate_raw_archive_to_r2.py` -- everything else uses
`r2_storage.py`.
"""
